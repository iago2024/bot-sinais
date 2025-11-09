# bot_manager.py
import threading
import json
import pandas as pd
import requests
from datetime import datetime, timedelta, time
import time as time_sleep
import ta
import traceback
import numpy as np
from websocket import WebSocketApp
import queue

import strategies

class BotManager:
    
    def __init__(self, username, config):
        self.username = username
        self.config = config
        self.robo_ativo = True
        self.event_queue = queue.Queue()
        
        self.historico = {}
        self.websockets = {}
        self.cooldown_ativo = {}
        self.sinais_ativos = {}
        self.sinais_pendentes_para_envio = {}
        
        # --- Dicionários de Sinais Armados (Pré-Alertas) ---
        self.rsi_potencial_sinal = {}
        self.rsi_estado_anterior = {} 
        self.p3v_potencial_sinal = {} 
        self.breakout_potencial_sinal = {}
        self.pre_alerta_ativo = {} 
        
        self.sr_niveis = {}
        self.mhi_manual_search_assets = set()
        
        self.vitorias_diretas = 0
        self.vitorias_1_protecao = 0
        self.vitorias_2_protecoes = 0
        self.derrotas_do_dia = 0
        self.historico_resultados = []
        self.estatisticas_estrategia = {}

        # --- Locks ---
        self.historico_lock = threading.Lock()
        self.sinais_lock = threading.Lock()
        self.ws_lock = threading.Lock()
        self.cooldown_lock = threading.Lock()
        self.stats_lock = threading.Lock()
        self.mhi_lock = threading.Lock()
        self.propostas_lock = threading.Lock()
        # Locks dos Sinais Armados
        self.rsi_lock = threading.Lock()
        self.sr_lock = threading.Lock()
        self.p3v_lock = threading.Lock() 
        self.breakout_lock = threading.Lock()
        self.pre_alerta_lock = threading.Lock() # <-- CORREÇÃO: ESTA LINHA ESTAVA FALTANDO

        
        print(f"[{self.username}] Instância do BotManager criada.")
        self.iniciar_workers()
        self.iniciar_ativos_da_config()
        self.publish_active_assets_update()

    def iniciar_workers(self):
        print(f"[{self.username}] Iniciando workers...")
        threading.Thread(target=self.processar_fila_de_envio, daemon=True).start()
        threading.Thread(target=self.processar_fila_de_resultados, daemon=True).start()
        threading.Thread(target=self.news_worker, daemon=True).start()
        threading.Thread(target=self.limpar_sinais_antigos, daemon=True).start()

    def iniciar_ativos_da_config(self):
        ativos_para_iniciar = self.config.get("ATIVOS", [])
        print(f"[{self.username}] Iniciando {len(ativos_para_iniciar)} ativos da config: {ativos_para_iniciar}")
        for par in ativos_para_iniciar:
            self.start_asset_monitor(par)

    def shutdown(self):
        print(f"[{self.username}] Desligando todos os monitores...")
        self.robo_ativo = False
        with self.ws_lock:
            pares = list(self.websockets.keys())
            for par in pares:
                ws = self.websockets.pop(par, None)
                if ws:
                    ws.close()
        print(f"[{self.username}] Bot desligado.")

    def update_config(self, new_config):
        old_token = self.config.get("TELEGRAM_TOKEN")
        old_chat_id = self.config.get("TELEGRAM_CHAT_ID")
        old_assets = set(self.config.get("ATIVOS", []))
        
        self.config = new_config
        print(f"[{self.username}] Configuração atualizada.")

        new_token = self.config.get("TELEGRAM_TOKEN")
        new_chat_id = self.config.get("TELEGRAM_CHAT_ID")
        new_assets = set(self.config.get("ATIVOS", []))

        if old_assets != new_assets:
            print(f"[{self.username}] Lista de ativos mudou. Enviando atualização para o agente local.")
            self.publish_active_assets_update()

        if (new_token != old_token or new_chat_id != old_chat_id) and (new_token and new_chat_id):
            print(f"[{self.username}] Novos dados de Telegram salvos. Enviando mensagem de teste...")
            threading.Thread(target=self._send_connection_test_message, daemon=True).start()

    def _send_connection_test_message(self):
        time_sleep.sleep(1) 
        success = self._enviar_mensagem_telegram(
            "Olá! 👋\n\nSua conta Quantum Trade foi conectada com sucesso a este chat."
        )
        if success:
            print(f"[{self.username}] Mensagem de teste do Telegram enviada com sucesso.")
            self.event_queue.put({"type": "telegram_connect_success"})
        else:
            print(f"[{self.username}] Falha ao enviar mensagem de teste do Telegram.")
            self.event_queue.put({"type": "telegram_connect_fail"})
    
    def get_event_queue(self):
        return self.event_queue

    def get_history_and_stats(self):
        with self.stats_lock:
            return list(reversed(self.historico_resultados)), self.estatisticas_estrategia.copy()

    def trigger_manual_mhi_t5(self, todos_os_ativos):
        if not self.config.get("USAR_ESTRATEGIA_MHI", False) and not self.config.get("USAR_ESTRATEGIA_T5", False):
            return {"status": "disabled", "message": "Estratégias MHI e T5 estão desativadas."}
        with self.mhi_lock:
            for par in todos_os_ativos:
                self.mhi_manual_search_assets.add(par)
        print(f"[{self.username}] Busca manual MHI+T5 ativada.")
        return {"status": "searching", "message": "Busca ativada! Aguardando janela..."}

    def start_asset_monitor(self, par):
        with self.ws_lock:
            if par in self.websockets:
                print(f"[{self.username}] Ativo {par} já está sendo monitorado.")
                return False
        
        print(f"[{self.username}] Iniciando monitoramento para {par}...")
        try:
            p3v_vwma_periodo = self.config.get("P3V_VWMA_PERIODO", 30) 
            breakout_avg = self.config.get("BREAKOUT_SMA_AVG_PERIOD", 20)
            
            limite_necessario = max(500, self.config.get('RSI_PERIODO', 14) * 3, 
                                    self.config.get('SR_PERIODO', 120), 
                                    p3v_vwma_periodo + 10, breakout_avg + 10) 
            limite_final = min(1000, limite_necessario)
            
            url_1m = f"https://api.binance.com/api/v3/klines?symbol={par.upper()}&interval=1m&limit={limite_final}"
            data_1m = requests.get(url_1m, timeout=10).json()
            df_1m = pd.DataFrame(data_1m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'ct', 'qav', 'nt', 'tbbav', 'tbqav', 'i'])
            df_1m['timestamp'] = pd.to_datetime(df_1m['timestamp'], unit='ms')
            df_1m.set_index('timestamp', inplace=True)
            df_1m = df_1m[['open', 'high', 'low', 'close', 'volume']].astype(float)
            
            with self.historico_lock:
                self.historico[par] = df_1m
            print(f"[{self.username}] Histórico de {par} carregado ({len(df_1m)} velas).")
            
        except Exception as e:
            print(f"[{self.username}] ERRO ao baixar histórico para {par}: {e}")
            return False

        thread = threading.Thread(target=self.run_websocket_client, args=(par,), daemon=True)
        thread.start()
        return True

    def stop_asset_monitor(self, par):
        print(f"[{self.username}] Parando monitoramento de {par}...")
        with self.ws_lock:
            ws = self.websockets.pop(par, None)
            if ws:
                ws.close() 
        
        with self.historico_lock: self.historico.pop(par, None)
        with self.sr_lock: self.sr_niveis.pop(par, None)
        with self.rsi_lock:
            self.rsi_estado_anterior.pop(par, None)
            self.rsi_potencial_sinal.pop(par, None)
        with self.mhi_lock: self.mhi_manual_search_assets.discard(par)
        with self.p3v_lock: self.p3v_potencial_sinal.pop(par, None)
        with self.breakout_lock: self.breakout_potencial_sinal.pop(par, None)
        with self.pre_alerta_lock: self.pre_alerta_ativo.pop(par, None)

    def run_websocket_client(self, par):
        
        def on_message(ws, message):
            sinal_enviado = False 
            try:
                msg = json.loads(message)
                k = msg.get('k')
                if not k: return
                
                event_time_ms = msg.get('E', 0)
                kline_close_time = k.get('T', 0)
                time_remaining_ms = kline_close_time - event_time_ms
                
                # --- JANELAS DE TEMPO PARA PRÉ-ALERTA E SINAL ---
                is_pre_alert_window = (20000 < time_remaining_ms <= 22000) 
                is_breakout_confirm_window = (12000 < time_remaining_ms <= 14000)
                is_p3v_rsi_confirm_window = (10000 < time_remaining_ms <= 12000) 

                if k.get('x'): # Se a vela fechou
                    ts = pd.to_datetime(k['T'], unit='ms')
                    candle_data = {"open": float(k["o"]), "high": float(k["h"]), "low": float(k["l"]), "close": float(k["c"]), "volume": float(k["v"])}
                    candle = pd.DataFrame([candle_data], index=[ts])
                    
                    with self.historico_lock:
                        df_old = self.historico.get(par)
                        
                        p3v_vwma_periodo = self.config.get("P3V_VWMA_PERIODO", 30) 
                        breakout_avg = self.config.get("BREAKOUT_SMA_AVG_PERIOD", 20)
                        
                        velas_a_manter = max(500, self.config.get('RSI_PERIODO', 14) + 100, 
                                             self.config.get('SR_PERIODO', 120) + 100, 
                                             p3v_vwma_periodo + 10, breakout_avg + 10) 
                        
                        if df_old is not None and not df_old.empty:
                            df_concatenado = pd.concat([df_old, candle])
                            self.historico[par] = df_concatenado.iloc[-velas_a_manter:]
                        else:
                            self.historico[par] = candle
                    
                    # Limpa todos os sinais "armados" e pré-alertas quando uma vela fecha
                    with self.rsi_lock: self.rsi_potencial_sinal.pop(par, None)
                    with self.p3v_lock: self.p3v_potencial_sinal.pop(par, None)
                    with self.breakout_lock: self.breakout_potencial_sinal.pop(par, None)
                    with self.pre_alerta_lock:
                        if self.pre_alerta_ativo.pop(par, None):
                            self.publish_remove_pre_alert(par) # Remove o alerta do site
                    
                    self.verificar_resultados(par, k)
                
                with self.cooldown_lock:
                    cooldown_presente = par in self.cooldown_ativo and datetime.now() < self.cooldown_ativo[par]
                    if par in self.cooldown_ativo and datetime.now() >= self.cooldown_ativo[par]:
                        del self.cooldown_ativo[par]
                
                with self.sinais_lock:
                    sinal_ativo_presente = par in self.sinais_ativos

                with self.mhi_lock:
                    mhi_manual_search_active = par in self.mhi_manual_search_assets
                
                # --- LÓGICA MHI/T5 (Busca Manual) ---
                mhi_ativo_config = self.config.get("USAR_ESTRATEGIA_MHI", False)
                t5_ativo_config = self.config.get("USAR_ESTRATEGIA_T5", False)

                if mhi_manual_search_active and (mhi_ativo_config or t5_ativo_config) and not cooldown_presente and not sinal_ativo_presente:
                    ts_close = pd.to_datetime(k.get('T', 0), unit='ms') 
                    if ts_close.minute % 5 == 4:
                        time_remaining_ms_mhi = (k.get('T', 0) + 1) - event_time_ms
                        if 20000 <= time_remaining_ms_mhi < 22000:
                            
                            with self.historico_lock: df_ref = self.historico.get(par) 
                            if df_ref is None or len(df_ref) < 4:
                                with self.mhi_lock: self.mhi_manual_search_assets.discard(par)
                                self.publish_mhi_analysis_complete()
                                return

                            current_candle_data = {"open": float(k["o"]), "high": float(k["h"]), "low": float(k["l"]), "close": float(k["c"]), "volume": float(k["v"])}
                            current_candle_df = pd.DataFrame([current_candle_data], index=[ts_close])
                            df_com_rt = pd.concat([df_ref, current_candle_df])

                            direcao_mhi = strategies.verificar_mhi(par, df_com_rt, self.config)
                            direcao_t5 = strategies.verificar_t5(par, df_com_rt, self.config)

                            with self.mhi_lock: self.mhi_manual_search_assets.discard(par)
                            self.publish_mhi_analysis_complete()

                            direcao_final, origem_final, confianca_final = None, "", 0.0
                            conf_mhi = self.config.get('CONFIANCA_MHI', 0.75)
                            conf_t5 = self.config.get('CONFIANCA_T5', 0.75)

                            if direcao_mhi and direcao_t5:
                                if direcao_mhi == direcao_t5:
                                    direcao_final, origem_final = direcao_mhi, "MHI + T5"
                                    confianca_final = max(conf_mhi, conf_t5) + 0.05
                                else:
                                    if conf_mhi >= conf_t5:
                                        direcao_final, origem_final, confianca_final = direcao_mhi, "MHI (Discordante)", conf_mhi
                                    else:
                                        direcao_final, origem_final, confianca_final = direcao_t5, "T5 (Discordante)", conf_t5
                            elif direcao_mhi:
                                direcao_final, origem_final, confianca_final = direcao_mhi, "MHI", conf_mhi
                            elif direcao_t5:
                                direcao_final, origem_final, confianca_final = direcao_t5, "T5", conf_t5

                            if direcao_final:
                                sinal_info = {'direcao': direcao_final, 'origem': origem_final, 'confianca': min(confianca_final, 0.99), 'horario_alvo': ts_close}
                                if self.enviar_sinal(par, sinal_info):
                                    sinal_enviado = True; return
                
                if sinal_enviado: return

                with self.historico_lock: df_ref = self.historico.get(par)
                if df_ref is None: return

                # --- SINAIS DE TOQUE (Envio Imediato) ---
                if self.config.get("USAR_ESTRATEGIA_BOLLINGER_RT", False) and not cooldown_presente and not sinal_ativo_presente:
                    direcao_bb = strategies.verificar_toque_bollinger_realtime(par, k, df_ref, self.config)
                    if direcao_bb:
                        sinal_info = {'direcao': direcao_bb, 'origem': "BOLLINGER-RT", 'confianca': self.config.get('CONFIANCA_BOLLINGER_RT', 0.8), 'horario_alvo': datetime.now()}
                        if self.enviar_sinal(par, sinal_info): 
                            sinal_enviado = True; return

                if self.config.get("USAR_ESTRATEGIA_SR", False) and not cooldown_presente and not sinal_ativo_presente:
                    direcao_sr = strategies.verificar_sr_realtime(self, par, k, df_ref)
                    if direcao_sr:
                        sinal_info = {'direcao': direcao_sr, 'origem': "SUP/RES-RT", 'confianca': self.config.get('CONFIANCA_SR', 0.9), 'horario_alvo': datetime.now()} 
                        if self.enviar_sinal(par, sinal_info): 
                            sinal_enviado = True; return
                            
                # --- SINAIS DE TEMPO (Armar / Desarmar) ---
                # Estas funções rodam a todo momento, armando e desarmando os sinais
                
                if self.config.get("USAR_ESTRATEGIA_RSI", False):
                    strategies.verificar_rsi_reentry_realtime(self, par, k, df_ref, is_p3v_rsi_confirm_window)
                
                if self.config.get("USAR_ESTRATEGIA_P3V", False):
                    strategies.verificar_p3v_realtime(self, par, k, df_ref, is_pre_alert_window, is_p3v_rsi_confirm_window)

                if self.config.get("USAR_ESTRATEGIA_BREAKOUT_SMA", False):
                    strategies.verificar_breakout_sma(self, par, k, df_ref, is_pre_alert_window, is_breakout_confirm_window)
                
                
                # --- LÓGICA DE PRÉ-ALERTA (20s) ---
                if is_pre_alert_window and not sinal_ativo_presente and not cooldown_presente:
                    sinal_pre_alerta = None
                    origem_pre_alerta = ""
                    
                    # Checa Breakout primeiro (Prioridade 1 de alerta)
                    with self.breakout_lock:
                        if par in self.breakout_potencial_sinal:
                            sinal_pre_alerta = self.breakout_potencial_sinal[par]
                            origem_pre_alerta = "BREAKOUT-SMA"
                    
                    # Se não tiver Breakout, checa P3V (Prioridade 2 de alerta)
                    if not sinal_pre_alerta:
                        with self.p3v_lock:
                            if par in self.p3v_potencial_sinal:
                                sinal_pre_alerta = self.p3v_potencial_sinal[par]
                                origem_pre_alerta = "PADRAO-P3V"
                    
                    if sinal_pre_alerta:
                        with self.pre_alerta_lock:
                            if par not in self.pre_alerta_ativo:
                                self.pre_alerta_ativo[par] = True
                                self.publish_pre_alert(par, sinal_pre_alerta['direcao'], origem_pre_alerta)
                
                # --- LÓGICA DE ENVIO FINAL (SINAIS DE 12s e 10s) ---
                
                # 1. Checar Breakout (Janela de 12s)
                if is_breakout_confirm_window and not sinal_ativo_presente and not cooldown_presente:
                    sinal_final_armado = None
                    with self.breakout_lock: 
                        sinal_final_armado = self.breakout_potencial_sinal.get(par) # .get() para não remover
                    
                    if sinal_final_armado:
                        print(f"[{self.username}] ENVIANDO SINAL BREAKOUT: {par}")
                        sinal_info = {
                            'direcao': sinal_final_armado['direcao'], 
                            'origem': "BREAKOUT-SMA", 
                            'confianca': self.config.get('CONFIANCA_BREAKOUT_SMA', 0.80), 
                            'horario_alvo': datetime.now()
                        }
                        if self.enviar_sinal(par, sinal_info):
                            with self.breakout_lock: self.breakout_potencial_sinal.pop(par, None) # Limpa só se enviar
                            sinal_enviado = True; return

                # 2. Checar P3V e RSI (Janela de 10s)
                if is_p3v_rsi_confirm_window and not sinal_ativo_presente and not cooldown_presente:
                    sinal_final_armado = None
                    origem_final = ""
                    confianca_final = 0.85
                    
                    # 2a. Checar P3V (Prioridade 1)
                    with self.p3v_lock:
                        sinal_final_armado = self.p3v_potencial_sinal.get(par) # .get() para não remover
                        if sinal_final_armado:
                            origem_final = "PADRAO-P3V"
                            confianca_final = self.config.get('CONFIANCA_P3V', 0.88)
                    
                    # 2b. Checar RSI (Prioridade 2)
                    if not sinal_final_armado:
                        with self.rsi_lock: 
                            sinal_final_armado = self.rsi_potencial_sinal.get(par) # .get() para não remover
                            if sinal_final_armado:
                                origem_final = "RSI-RT"
                                confianca_final = sinal_final_armado.get('confianca', self.config.get('CONFIANCA_RSI', 0.85))

                    if sinal_final_armado:
                        print(f"[{self.username}] ENVIANDO SINAL {origem_final}: {par}")
                        sinal_info = {
                            'direcao': sinal_final_armado['direcao'], 
                            'origem': origem_final, 
                            'confianca': confianca_final, 
                            'horario_alvo': datetime.now()
                        }
                        if self.enviar_sinal(par, sinal_info):
                            # Limpa o sinal que foi enviado
                            if origem_final == "PADRAO-P3V":
                                with self.p3v_lock: self.p3v_potencial_sinal.pop(par, None)
                            elif origem_final == "RSI-RT":
                                with self.rsi_lock: self.rsi_potencial_sinal.pop(par, None)
                            sinal_enviado = True; return

            except Exception as e:
                print(f"[{self.username}] ERRO on_message {par}: {e}\n{traceback.format_exc()}")
        
        def on_error(ws, error):
            print(f"[{self.username}] WS ERRO {par.upper()}: {error}")

        def on_close(ws, code, msg):
            print(f"[{self.username}] WS FECHADO {par.upper()} code={code} msg={msg}")
            with self.ws_lock:
                self.websockets.pop(par, None)
            
            if self.robo_ativo and par in self.config.get("ATIVOS", []):
                print(f"[{self.username}] Perda de conexão. Tentando reconectar {par.upper()} em 5s...")
                time_sleep.sleep(5)
                self.start_asset_monitor(par)
            else:
                print(f"[{self.username}] Desligamento intencional de {par.upper()}. Não vai reconectar.")

        def on_open(ws):
            print(f"[{self.username}] WS ABERTO {par.upper()}")

        try:
            url = f"wss://stream.binance.com:9443/ws/{par}@kline_1m"
            ws_app = WebSocketApp(url, on_message=on_message, on_error=on_error, on_close=on_close, on_open=on_open)
            with self.ws_lock:
                self.websockets[par] = ws_app 
            ws_app.run_forever()
        except Exception as e:
            print(f"[{self.username}] ERRO ao iniciar WebSocket para {par.upper()}: {e}")
            with self.ws_lock:
                self.websockets.pop(par, None)
            if self.robo_ativo:
                time_sleep(10)
                self.start_asset_monitor(par)

    def verificar_resultados(self, par, candle_fechada):
        with self.sinais_lock:
            if par in self.sinais_ativos:
                sinal = self.sinais_ativos[par]
                etapa_atual = sinal.get('etapa', -1)
                def registrar_resultado(resultado_final):
                    sinal['resultado_final'] = resultado_final
                    sinal['etapa'] = 10 
                if etapa_atual in [-1, 10]: return
                if etapa_atual == 0:
                    sinal['etapa'] = 1; return
                preco_fechamento = float(candle_fechada['c'])
                preco_abertura = float(candle_fechada['o'])
                direcao = sinal.get('direcao')
                resultado_rodada = 'vitoria' if (preco_fechamento > preco_abertura and direcao == 'COMPRA') or \
                                              (preco_fechamento < preco_abertura and direcao == 'VENDA') else 'derrota'
                if preco_fechamento == preco_abertura: resultado_rodada = 'empate'
                if etapa_atual == 1:
                    if resultado_rodada == 'vitoria': registrar_resultado("WIN ✅")
                    else: sinal['etapa'] = 2
                elif etapa_atual == 2:
                    if resultado_rodada == 'vitoria': registrar_resultado("WIN NA PROTEÇÃO 1 ✅")
                    else: sinal['etapa'] = 3
                elif etapa_atual == 3:
                    if resultado_rodada == 'vitoria': registrar_resultado("WIN NA PROTEÇÃO 2 ✅")
                    else: registrar_resultado("LOSS ❌")

    def _enviar_mensagem_telegram(self, msg, markdown=False):
        token = self.config.get("TELEGRAM_TOKEN")
        chat_id = self.config.get("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            # print(f"[{self.username}] Telegram não configurado. Mensagem pulada: {msg[:30]}...")
            return False
        data = {"chat_id": chat_id, "text": msg}
        if markdown: data["parse_mode"] = "Markdown"
        try:
            response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=10)
            response_data = response.json()
            if response_data.get("ok"):
                return True
            else:
                print(f"[{self.username}] ❌ Erro ao enviar Telegram: {response_data.get('description')}")
                if "chat not found" in response_data.get('description', ''):
                    self.event_queue.put({"type": "telegram_connect_fail"})
                return False
        except Exception as e:
            print(f"[{self.username}] ❌ Exceção ao enviar Telegram: {e}")
            self.event_queue.put({"type": "telegram_connect_fail"})
            return False

    def enviar_sinal(self, par, sinal_info):
        # Proteção para garantir que não estamos em cooldown
        with self.cooldown_lock:
            if par in self.cooldown_ativo and datetime.now() < self.cooldown_ativo[par]:
                print(f"[{self.username}] Sinal para {par} bloqueado por COOLDOWN.")
                return False # Não envia o sinal
        # Proteção para garantir que não há sinal ativo
        with self.sinais_lock:
            if par in self.sinais_ativos:
                print(f"[{self.username}] Sinal para {par} bloqueado por SINAL ATIVO.")
                return False # Não envia o sinal
                
        # --- LÓGICA DO PRÉ-ALERTA ---
        # Se um sinal final for enviado, remove o pré-alerta
        with self.pre_alerta_lock:
            if self.pre_alerta_ativo.pop(par, None):
                self.publish_remove_pre_alert(par)
        # --- FIM ---

        direcao, origem, confianca = sinal_info['direcao'], sinal_info['origem'], sinal_info.get('confianca')
        horario_alvo = sinal_info['horario_alvo']
        if isinstance(horario_alvo, datetime): hora_msg = horario_alvo.strftime("%H:%M")
        else: hora_msg = datetime.now().strftime("%H:%M")
        ativo_fmt = par.replace("usdt", "/USD").upper()
        emoji = "🟢" if direcao == "COMPRA" else "🔴"
        try:
            conf_text = f"🎯 Confiança: {float(confianca):.2%}\n"
        except (ValueError, TypeError):
            conf_text = f"🎯 Confiança: {confianca}\n" if confianca is not None else ""
        msg = (f"{emoji} SINAL DE {direcao} ({origem})\n\n"
               f"📈 ATIVO: {ativo_fmt}\n⏰ ENTRADA: {hora_msg}\n📊 ORDEM: {direcao}\n{conf_text}"
               f"⏱️ INTERVALO: 1 minuto\n\n🛡️ Se necessário, usar até 2 proteções.")
        
        telegram_sucesso = self._enviar_mensagem_telegram(msg)
        
        with self.sinais_lock:
            self.sinais_ativos[par] = {"direcao": direcao, "etapa": 0, "origem": origem}
        with self.cooldown_lock:
            self.cooldown_ativo[par] = datetime.now() + timedelta(minutes=self.config.get('COOLDOWN_MINUTOS', 1))
        
        self.publish_signal_to_web(par, direcao, confianca, origem, texto=msg)
        
        if telegram_sucesso:
            print(f"[{self.username}] ✅ Sinal enviado para {par.upper()} ({origem}) - (Telegram OK)")
        else:
            print(f"[{self.username}] ✅ Sinal enviado para {par.upper()} ({origem}) - (Falha/Sem Telegram, mas site OK)")
            
        return True 

    def enviar_resultado_telegram(self, par, resultado_texto, sinal):
        if not sinal.get('resultado_contabilizado', False):
            with self.stats_lock:
                if "WIN ✅" in resultado_texto: self.vitorias_diretas += 1
                elif "WIN NA PROTEÇÃO 1 ✅" in resultado_texto: self.vitorias_1_protecao += 1
                elif "WIN NA PROTEÇÃO 2 ✅" in resultado_texto: self.vitorias_2_protecoes += 1
                elif "LOSS ❌" in resultado_texto: self.derrotas_do_dia += 1
                origem = sinal.get('origem', 'Desconhecida')
                if origem not in self.estatisticas_estrategia:
                    self.estatisticas_estrategia[origem] = {'WIN ✅': 0, 'WIN NA PROTEÇÃO 1 ✅': 0, 'WIN NA PROTEÇÃO 2 ✅': 0, 'LOSS ❌': 0}
                if resultado_texto in self.estatisticas_estrategia[origem]:
                    self.estatisticas_estrategia[origem][resultado_texto] += 1
                self.historico_resultados.append({
                    'par': par, 'origem': origem, 'resultado': resultado_texto, 
                    'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                if len(self.historico_resultados) > 200: self.historico_resultados.pop(0)
            sinal['resultado_contabilizado'] = True
        total_vitorias = self.vitorias_diretas + self.vitorias_1_protecao + self.vitorias_2_protecoes
        placar = f"({total_vitorias} x {self.derrotas_do_dia})"
        msg = f"🏁 **Resultado {placar}** | {par.replace('usdt', '/USD').upper()} | **{resultado_texto}**"
        self.publish_remove_signal(par)
        return self._enviar_mensagem_telegram(msg, markdown=True)

    def publish_signal_to_web(self, par, direcao, confianca, origem, texto=""):
        try:
            confianca_formatada = f"{(float(confianca)*100):.2f}%"
        except (ValueError, TypeError):
            confianca_formatada = confianca
        self.event_queue.put({
            "type": "signal", "ativo": par.upper(), "direcao": direcao,
            "confianca": confianca_formatada, "origem": origem,
            "horario": datetime.now().strftime("%H:%M:%S"), "texto": texto
        })
        
    # --- NOVAS FUNÇÕES DE PRÉ-ALERTA ---
    def publish_pre_alert(self, par, direcao, origem):
        print(f"[{self.username}] PUBLICANDO PRÉ-ALERTA: {par} ({origem})")
        self.event_queue.put({
            "type": "pre_alert", "ativo": par.upper(), "direcao": direcao,
            "origem": origem, "horario": datetime.now().strftime("%H:%M:%S")
        })

    def publish_remove_pre_alert(self, par):
        print(f"[{self.username}] REMOVENDO PRÉ-ALERTA: {par}")
        self.event_queue.put({ "type": "remove_pre_alert", "ativo": par.upper() })
    # --- FIM ---

    def publish_stats_to_web(self):
        with self.stats_lock:
            self.event_queue.put({
                "type": "stats", "winsDirect": self.vitorias_diretas,
                "wins1": self.vitorias_1_protecao,
                "wins2": self.vitorias_2_protecoes, "losses": self.derrotas_do_dia
            })
    
    def publish_remove_signal(self, par):
        self.event_queue.put({ "type": "remove_signal", "ativo": par.upper() })
    
    def publish_mhi_analysis_complete(self):
        self.event_queue.put({"type": "mhi_analysis_complete"})

    def publish_active_assets_update(self):
        print(f"[{self.username}] Enviando atualização de ativos para o agente: {self.config.get('ATIVOS', [])}")
        self.event_queue.put({
            "type": "active_assets_update",
            "assets": self.config.get("ATIVOS", [])
        })

    def publish_config_update_to_web(self):
        """Envia a config ATUALIZADA para o frontend (ex: após teste do Telegram)."""
        config = self.config
        config_data = {
            "bollinger": config.get("USAR_ESTRATEGIA_BOLLINGER_RT", True),
            "rsi": config.get("USAR_ESTRATEGIA_RSI", True),
            "sr": config.get("USAR_ESTRATEGIA_SR", True),
            "t5": config.get("USAR_ESTRATEGIA_T5", True),
            "mhi": config.get("USAR_ESTRATEGIA_MHI", True),
            "p3v": config.get("USAR_ESTRATEGIA_P3V", True), 
            "breakout_sma": config.get("USAR_ESTRATEGIA_BREAKOUT_SMA", True),
            "rsi_use_macd": config.get("RSI_USE_MACD_FILTER", False), 
            "bollinger_std": config.get("BOLLINGER_STD_DEV", 2.7),
            "rsi_periodo": config.get("RSI_PERIODO", 14),
            "rsi_limite_sup": config.get("RSI_LIMITE_SUPERIOR", 70),
            "rsi_limite_inf": config.get("RSI_LIMITE_INFERIOR", 30),
            "valor_entrada_base": config.get("VALOR_ENTRADA_BASE", 10.0),
            "sr_periodo": config.get("SR_PERIODO", 120),
            "sr_toques": config.get("SR_TOQUES_NECESSARIOS", 3),
            "sr_tolerancia": config.get("SR_TOLERANCIA_PERCENT", 0.0005),
            "t5_pavio_min": config.get("T5_PAVIO_MIN_RATIO", 2.0),
            "mhi_use_trend": config.get("MHI_USE_TREND_FILTER", True),
            "mhi_trend_periodo": config.get("MHI_TREND_PERIODO", 100),
            "p3v_vwma_periodo": config.get("P3V_VWMA_PERIODO", 30),
            "breakout_sma_curta": config.get("BREAKOUT_SMA_CURTA", 5),
            "breakout_sma_longa": config.get("BREAKOUT_SMA_LONGA", 7),
            "breakout_sma_body_mult": config.get("BREAKOUT_SMA_BODY_MULT", 2.0),
            "breakout_sma_avg_period": config.get("BREAKOUT_SMA_AVG_PERIOD", 20),
            "ativos": config.get("ATIVOS", []),
            "telegram_token": config.get("TELEGRAM_TOKEN", ""),
            "telegram_chat_id": config.get("TELEGRAM_CHAT_ID", "")
        }
        self.event_queue.put({
            "type": "config_update",
            "config": config_data
        })

    def processar_fila_de_envio(self):
        while self.robo_ativo:
            ativo_proc, sinal_proc = None, None
            with self.propostas_lock:
                if self.sinais_pendentes_para_envio:
                    ativo_proc, sinal_proc = next(iter(self.sinais_pendentes_para_envio.items()))
                    del self.sinais_pendentes_para_envio[ativo_proc]
            if ativo_proc:
                self.enviar_sinal(ativo_proc, sinal_proc)
            time_sleep.sleep(1)

    def processar_fila_de_resultados(self):
        while self.robo_ativo:
            with self.sinais_lock:
                for par, sinal in list(self.sinais_ativos.items()):
                    if sinal.get('etapa', -1) >= 10 and self.enviar_resultado_telegram(par, sinal['resultado_final'], sinal):
                        del self.sinais_ativos[par]
            time_sleep.sleep(10)

    def limpar_sinais_antigos(self):
        while self.robo_ativo:
            self.event_queue.put({
                "type": "limpar_antigos",
                "horario_limite": (datetime.now() - timedelta(minutes=30)).strftime("%H:%M:%S")
            })
            time_sleep.sleep(300)

    def news_worker(self):
        while self.robo_ativo:
            try:
                self.publish_stats_to_web()
            except Exception as e:
                print(f"[{self.username}] Erro no news_worker: {e}")
            time_sleep.sleep(10)
