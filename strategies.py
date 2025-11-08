# strategies.py
import pandas as pd
import ta
import traceback
import numpy as np
from datetime import datetime

# Este arquivo não importa NADA do config.py
# Ele é uma biblioteca "pura" que opera em instâncias de BotManager.

def verificar_filtro_macd_rsi(df_com_rt, direcao_sinal):
    """
    Função FILTRO (APENAS PARA RSI): Verifica o MACD.
    Retorna True se o sinal for PERMITIDO, False se for BLOQUEADO.
    """
    try:
        macd = ta.trend.MACD(df_com_rt['close'])
        macd_line = macd.macd().iloc[-1]
        signal_line = macd.macd_signal().iloc[-1]
        hist = macd.macd_diff().iloc[-1]
        hist_prev = macd.macd_diff().iloc[-2]
        hist_2prev = macd.macd_diff().iloc[-3]

        if direcao_sinal == "COMPRA":
            tendencia_alta = (macd_line > signal_line)
            histograma_crescente = (hist > hist_prev) and (hist_prev > hist_2prev)
            cruzou_macd = (macd_line > signal_line and macd.macd().iloc[-2] < macd.macd_signal().iloc[-2]) 
            if (tendencia_alta and histograma_crescente) or cruzou_macd:
                return True # Permitido (MACD confirma alta)
            else:
                return False # Bloqueado

        elif direcao_sinal == "VENDA":
            tendencia_baixa = (macd_line < signal_line)
            histograma_decrescente = (hist < hist_prev) and (hist_prev < hist_2prev)
            cruzou_macd = (macd_line < signal_line and macd.macd().iloc[-2] > macd.macd_signal().iloc[-2]) 
            if (tendencia_baixa and histograma_decrescente) or cruzou_macd:
                return True # Permitido (MACD confirma baixa)
            else:
                return False # Bloqueado
                
        return False
    except Exception:
        return False # Bloqueia em caso de erro

# Assinatura atualizada para aceitar o flag de tempo do bot_manager
def verificar_rsi_reentry_realtime(bot, par, k, df_historico, is_last_10_seconds):
    """
    Verifica RSI. Arma o sinal se a lógica for válida.
    O bot_manager envia na janela de 10s.
    """
    config = bot.config
    rsi_p = config.get('RSI_PERIODO', 14)
    rsi_ls = config.get('RSI_LIMITE_SUPERIOR', 70)
    rsi_li = config.get('RSI_LIMITE_INFERIOR', 30)
    confianca_rsi = config.get('CONFIANCA_RSI', 0.85)
    usar_filtro_macd_rsi = config.get('RSI_USE_MACD_FILTER', False) 

    if df_historico is None or len(df_historico) < rsi_p + 3:
        return None

    try:
        preco_atual = float(k['c'])
        preco_abertura = float(k['o'])
        vela_verde = preco_atual > preco_abertura
        vela_vermelha = preco_atual < preco_abertura

        df_temp = df_historico.copy()
        ts_atual = pd.to_datetime(k['T'], unit='ms')
        vela_atual_rt_dados = {
            'open': preco_abertura, 'high': float(k['h']), 'low': float(k['l']),
            'close': preco_atual, 'volume': float(k['v'])
        }
        vela_atual_series = pd.DataFrame([vela_atual_rt_dados], index=[ts_atual])
        df_com_rt = pd.concat([df_temp, vela_atual_series])

        rsi_series = ta.momentum.RSIIndicator(df_com_rt['close'], window=rsi_p).rsi()
        if len(rsi_series) < 3: return None
        rsi_atual = rsi_series.iloc[-1]
        rsi_anterior_fechada = rsi_series.iloc[-2]

        with bot.rsi_lock:
            if par not in bot.rsi_estado_anterior:
                bot.rsi_estado_anterior[par] = {
                    'rsi_anterior_fechada': rsi_anterior_fechada,
                    'timestamp': datetime.now()
                }
            
            rsi_fechada_armazenada = bot.rsi_estado_anterior[par]['rsi_anterior_fechada']

            if rsi_anterior_fechada != rsi_fechada_armazenada:
                bot.rsi_estado_anterior[par]['rsi_anterior_fechada'] = rsi_anterior_fechada
                rsi_fechada_armazenada = rsi_anterior_fechada

            sinal_armado = False
            direcao_sinal = None
            motivo_sinal = ""
            confianca_final = confianca_rsi

            # --- COMPRA ---
            if (rsi_fechada_armazenada < rsi_li and rsi_atual > rsi_li):
                if vela_verde:
                    direcao_sinal = "COMPRA"
                    motivo_sinal = "RSI cruzou sobrevenda"
            
            # --- VENDA ---
            elif (rsi_fechada_armazenada > rsi_ls and rsi_atual < rsi_ls):
                if vela_vermelha:
                    direcao_sinal = "VENDA"
                    motivo_sinal = "RSI cruzou sobrecompra"

            if direcao_sinal:
                if usar_filtro_macd_rsi:
                    if verificar_filtro_macd_rsi(df_com_rt, direcao_sinal):
                        sinal_armado = True
                        motivo_sinal += " + MACD OK"
                        confianca_final = round(confianca_rsi + 0.06, 2)
                    else:
                        sinal_armado = False 
                else:
                    sinal_armado = True 
            
            if sinal_armado:
                bot.rsi_potencial_sinal[par] = {
                    'direcao': direcao_sinal,
                    'confianca': confianca_final,
                    'motivo': motivo_sinal
                }
            else:
                bot.rsi_potencial_sinal.pop(par, None)
                
        return None
    except Exception as e:
        print(f"[{bot.username}] Erro em verificar_rsi_reentry_realtime {par}: {e}")
        return None

def verificar_toque_bollinger_realtime(par, k, df_historico, config):
    std_dev_configurado = config.get('BOLLINGER_STD_DEV', 2.7)
    bollinger_periodo = config.get('BOLLINGER_PERIODO', 20)
    offset_percent = config.get('BOLLINGER_OFFSET_PERCENT', 0.0001)
    
    if df_historico is None or len(df_historico) < 101:
        return None
    try:
        low_price, high_price = float(k['l']), float(k['h'])
        
        bollinger = ta.volatility.BollingerBands(df_historico['close'], window=bollinger_periodo, window_dev=std_dev_configurado)
        bb_upper = bollinger.bollinger_hband().iloc[-1]
        bb_lower = bollinger.bollinger_lband().iloc[-1]
        ma_100 = ta.trend.sma_indicator(df_historico['close'], window=100).iloc[-1]

        direcao_sinal = None
        if low_price <= (bb_lower * (1 - offset_percent)) and ma_100 < bb_lower:
            direcao_sinal = "COMPRA"
        if high_price >= (bb_upper * (1 + offset_percent)) and ma_100 > bb_upper:
            direcao_sinal = "VENDA"
            
        return direcao_sinal
    except Exception:
        return None

def verificar_sr_realtime(bot, par, k, df_historico):
    config = bot.config
    periodo = config.get('SR_PERIODO', 120)
    toques_necessarios = config.get('SR_TOQUES_NECESSARIOS', 3)
    tolerancia = config.get('SR_TOLERANCIA_PERCENT', 0.0005)
    distancia_min = config.get('SR_DISTANCIA_MIN_TOQUES', 15)
    
    if df_historico is None or len(df_historico) < periodo:
        return None

    try:
        df_periodo = df_historico.iloc[-periodo:]
        resistencia_atual = df_periodo['high'].max()
        suporte_atual = df_periodo['low'].min()
        
        preco_high_rt = float(k['h'])
        preco_low_rt = float(k['l'])
        ts_vela_atual = int(k['T']) // 60000 

        direcao_sinal = None

        with bot.sr_lock:
            if par not in bot.sr_niveis:
                bot.sr_niveis[par] = {'res': (resistencia_atual, []), 'sup': (suporte_atual, [])}
                return None
            
            if abs(bot.sr_niveis[par]['res'][0] - resistencia_atual) > (resistencia_atual * tolerancia):
                bot.sr_niveis[par]['res'] = (resistencia_atual, [])
            if abs(bot.sr_niveis[par]['sup'][0] - suporte_atual) > (suporte_atual * tolerancia):
                bot.sr_niveis[par]['sup'] = (suporte_atual, [])

            nivel_res, toques_res = bot.sr_niveis[par]['res']
            zona_res_inferior = nivel_res * (1.0 - tolerancia)
            zona_res_superior = nivel_res * (1.0 + tolerancia)
            
            if zona_res_inferior <= preco_high_rt <= zona_res_superior:
                if not toques_res or (ts_vela_atual - toques_res[-1]) > distancia_min:
                    toques_res.append(ts_vela_atual)
                    if len(toques_res) == toques_necessarios:
                        toques_res.clear()
                        direcao_sinal = "VENDA"

            nivel_sup, toques_sup = bot.sr_niveis[par]['sup']
            zona_sup_inferior = nivel_sup * (1.0 - tolerancia)
            zona_sup_superior = nivel_sup * (1.0 + tolerancia)

            if zona_sup_inferior <= preco_low_rt <= zona_sup_superior:
                if not toques_sup or (ts_vela_atual - toques_sup[-1]) > distancia_min:
                    toques_sup.append(ts_vela_atual)
                    if len(toques_sup) == toques_necessarios:
                        toques_sup.clear()
                        direcao_sinal = "COMPRA"
        
        return direcao_sinal
    except Exception as e:
        print(f"[{bot.username}] Erro em verificar_sr_realtime {par}: {e}")
        return None

def verificar_mhi(par, df_historico, config):
    if not config.get('USAR_ESTRATEGIA_MHI', False):
        return None
    try:
        if df_historico is None or len(df_historico) < 5: return None 
        bloco_5m = df_historico.iloc[-5:]
        bullish_candles = (bloco_5m['close'] > bloco_5m['open']).sum()
        bearish_candles = (bloco_5m['close'] < bloco_5m['open']).sum()
        
        direcao_dominante = None
        if bearish_candles >= 3: direcao_dominante = "COMPRA"
        elif bullish_candles >= 3: direcao_dominante = "VENDA"
        else: return None
        
        usar_filtro = config.get('MHI_USE_TREND_FILTER', True)
        trend_periodo = config.get('MHI_TREND_PERIODO', 100)
        
        if usar_filtro:
            if len(df_historico) < trend_periodo: return None
            sma_trend = ta.trend.sma_indicator(df_historico['close'], window=trend_periodo).iloc[-1]
            preco_atual = df_historico['close'].iloc[-1]
            if direcao_dominante == "COMPRA" and preco_atual < sma_trend: return None
            if direcao_dominante == "VENDA" and preco_atual > sma_trend: return None
            
        return direcao_dominante
    except Exception as e:
        print(f"Erro em verificar_mhi {par}: {e}\n{traceback.format_exc()}")
        return None

def verificar_t5(par, df_historico, config):
    if not config.get('USAR_ESTRATEGIA_T5', False):
        return None
    try:
        if df_historico is None or len(df_historico) < 5: return None

        pavio_min_ratio = config.get('T5_PAVIO_MIN_RATIO', 2.0)
        
        bloco_5m = df_historico.iloc[-5:]
        vela_43 = bloco_5m.iloc[-2]
        vela_44 = bloco_5m.iloc[-1]
        
        corpo_43 = abs(vela_43['close'] - vela_43['open'])
        sombra_superior_43 = vela_43['high'] - max(vela_43['open'], vela_43['close'])
        sombra_inferior_43 = min(vela_43['open'], vela_43['close']) - vela_43['low']
        
        tem_padrao_43 = False
        direcao_padrao_43 = None
        
        if sombra_inferior_43 >= corpo_43 * pavio_min_ratio and sombra_superior_43 < corpo_43 * 0.5:
            tem_padrao_43 = True; direcao_padrao_43 = "COMPRA"
        elif sombra_superior_43 >= corpo_43 * pavio_min_ratio and sombra_inferior_43 < corpo_43 * 0.5:
            tem_padrao_43 = True; direcao_padrao_43 = "VENDA"
        
        if not tem_padrao_43: return None
        
        vela_43_verde = vela_43['close'] > vela_43['open']
        vela_43_vermelha = vela_43['close'] < vela_43['open']
        vela_44_verde = vela_44['close'] > vela_44['open']
        vela_44_vermelha = vela_44['close'] < vela_44['open']
        
        direcao_t5 = None
        if direcao_padrao_43 == "COMPRA":
            if (vela_43_verde and vela_44_vermelha) or (vela_43_vermelha and vela_44_vermelha):
                direcao_t5 = "COMPRA"
        elif direcao_padrao_43 == "VENDA":
            if (vela_43_verde and vela_44_verde) or (vela_43_vermelha and vela_44_verde):
                direcao_t5 = "VENDA"
                
        return direcao_t5
    except Exception as e:
        print(f"Erro em verificar_t5 {par}: {e}\n{traceback.format_exc()}")
        return None

# --- [ESTRATÉGIA P3V (Verde-Vermelho-Verde) - LÓGICA CORRIGIDA] ---

def calcular_vwma(df, periodo=30):
    """ Calcula a Volume Weighted Moving Average (VWMA) """
    cv = df['close'] * df['volume']
    vwma = cv.rolling(window=periodo).sum() / df['volume'].rolling(window=periodo).sum()
    return vwma

def verificar_p3v_realtime(bot, par, k, df_historico, is_pre_alert_window, is_last_10_seconds):
    """
    Estratégia P3V: Padrão G-R-G (Compra) ou R-G-R (Venda) com filtro VWMA.
    Modifica 'bot.p3v_potencial_sinal'.
    """
    config = bot.config
    periodo_vwma = config.get("P3V_VWMA_PERIODO", 30) 
    
    # *** CORREÇÃO DO BUG (image_321fe1.png / image_66629c.png) ***
    if df_historico is None or len(df_historico) < (periodo_vwma + 2):
        return None

    try:
        # 1. Pegar Velas Fechadas (CORRIGIDO)
        vela_1 = df_historico.iloc[-2] # Vela -2 (Penúltima)
        vela_2 = df_historico.iloc[-1] # Vela -1 (Última fechada)
        
        # 2. Pegar Dados da Vela Atual (Realtime)
        preco_open = float(k['o'])
        preco_close = float(k['c'])
        
        # 3. Calcular Cores (CORRIGIDO)
        vela_1_verde = vela_1['close'] > vela_1['open']
        vela_1_vermelha = vela_1['close'] < vela_1['open']
        
        vela_2_verde = vela_2['close'] > vela_2['open']
        vela_2_vermelha = vela_2['close'] < vela_2['open']
        
        vela_3_rt_verde = preco_close > preco_open
        vela_3_rt_vermelha = preco_close < preco_open

        # 4. Calcular VWMA 
        df_temp = df_historico.copy()
        ts_atual = pd.to_datetime(k['T'], unit='ms')
        vela_atual_rt_dados = {
            'open': preco_open, 'high': float(k['h']), 'low': float(k['l']),
            'close': preco_close, 'volume': float(k['v'])
        }
        vela_atual_series = pd.DataFrame([vela_atual_rt_dados], index=[ts_atual])
        df_com_rt = pd.concat([df_temp, vela_atual_series])

        vwma_series = calcular_vwma(df_com_rt, periodo=periodo_vwma)
        if vwma_series.isnull().all() or len(vwma_series) < 2:
            return None
        vwma_atual = vwma_series.iloc[-1]
        
        # 5. Checar Padrões e Filtros (CORRIGIDO)
        direcao_sinal = None
        
        # Padrão de COMPRA: Verde (-2), Vermelha (-1), Verde (RT)
        if vela_1_verde and vela_2_vermelha and vela_3_rt_verde:
            # Filtro: As 3 velas devem estar ACIMA da VWMA
            if (vela_1['low'] > vwma_atual and
                vela_2['low'] > vwma_atual and
                preco_open > vwma_atual and 
                preco_close > vwma_atual):  
                direcao_sinal = "COMPRA"
                
        # Padrão de VENDA: Vermelha (-2), Verde (-1), Vermelha (RT)
        elif vela_1_vermelha and vela_2_verde and vela_3_rt_vermelha:
            # Filtro: As 3 velas devem estar ABAIXO da VWMA
            if (vela_1['high'] < vwma_atual and
                vela_2['high'] < vwma_atual and
                preco_open < vwma_atual and 
                preco_close < vwma_atual):  
                direcao_sinal = "VENDA"
        
        # 6. Armar o Sinal (para o bot_manager pegar na janela de 20s ou 10s)
        if direcao_sinal:
            with bot.p3v_lock: 
                bot.p3v_potencial_sinal[par] = { 
                    "direcao": direcao_sinal,
                    "timestamp": datetime.now()
                }
        else:
            # Se o padrão não for atendido (ex: vela RT reverteu), cancela o sinal
            with bot.p3v_lock: 
                bot.p3v_potencial_sinal.pop(par, None)
                # Também remove o pré-alerta do site se ele existir
                with bot.pre_alerta_lock:
                    if bot.pre_alerta_ativo.pop(par, None):
                        bot.publish_remove_pre_alert(par)

    except Exception as e:
        print(f"[{bot.username}] Erro em verificar_p3v_realtime {par}: {e}\n{traceback.format_exc()}")
        with bot.p3v_lock: 
            bot.p3v_potencial_sinal.pop(par, None) 
        return None

# --- [ESTRATÉGIA BREAKOUT SMA (Vela 2x) - LÓGICA CORRIGIDA] ---

# --- [ESTRATÉGIA BREAKOUT SMA (Vela 2x) - LÓGICA CORRIGIDA] ---

def verificar_breakout_sma(bot, par, k, df_historico, is_pre_alert_window, is_last_12_seconds):
    """
    Estratégia Breakout SMA: Apenas VENDA.
    Checa se a vela ABRIU ACIMA e FECHOU ABAIXO (ROMPEU).
    USA FILTRO DE TAMANHO MÍNIMO PERCENTUAL.
    """
    config = bot.config
    sma_curta_p = config.get("BREAKOUT_SMA_CURTA", 5)
    sma_longa_p = config.get("BREAKOUT_SMA_LONGA", 7)
    
    # --- LÓGICA DE TAMANHO MÍNIMO ---
    # Define um tamanho mínimo de corpo em % do preço. 
    # Ex: 0.0005 = 0.05% do preço do ativo.
    # Esquece 'avg_period' e 'body_mult' das versões anteriores.
    min_body_percent = config.get("BREAKOUT_SMA_MIN_BODY_PERCENT", 0.0005) # 0.05%
    # --- FIM DA LÓGICA ---
    
    # O mínimo de histórico que precisamos é para a SMA mais longa
    if df_historico is None or len(df_historico) < (sma_longa_p + 2):
        return None

    try:
        # 1. Dados da Vela Atual (Realtime T-0)
        preco_open_rt = float(k['o'])
        preco_close_rt = float(k['c'])
        corpo_vela_rt = abs(preco_close_rt - preco_open_rt)
        
        vela_rt_vermelha = preco_close_rt < preco_open_rt

        # 2. Dados Históricos
        df_temp = df_historico.copy()
        
        # 2a. Calcular SMAs da vela ATUAL (T-0)
        ts_atual = pd.to_datetime(k['T'], unit='ms')
        vela_atual_rt_dados = {
            'open': preco_open_rt, 'high': float(k['h']), 'low': float(k['l']),
            'close': preco_close_rt, 'volume': float(k['v'])
        }
        vela_atual_series = pd.DataFrame([vela_atual_rt_dados], index=[ts_atual])
        df_com_rt = pd.concat([df_temp, vela_atual_series])
        
        sma_curta_rt = ta.trend.sma_indicator(df_com_rt['close'], window=sma_curta_p).iloc[-1]
        sma_longa_rt = ta.trend.sma_indicator(df_com_rt['close'], window=sma_longa_p).iloc[-1]
        
        # --- LÓGICA DE TAMANHO MÍNIMO ---
        # 2b. Calcular o tamanho mínimo exigido em preço
        # Comparamos o corpo da vela com o 'tamanho mínimo'
        tamanho_minimo_exigido = preco_close_rt * min_body_percent
        # --- FIM DA LÓGICA ---

        # 3. Checar Padrões e Filtros
        direcao_sinal = None
        
        # Padrão de VENDA: 
        # 1. Vela RT é Vermelha
        # 2. Vela RT tem corpo > (preço * min_body_percent) <-- CONDIÇÃO MODIFICADA
        # 3. Vela RT ABRIU (open) ACIMA de pelo menos uma das médias
        # 4. Vela RT FECHOU (close) ABAIXO de AMBAS as médias
        
        if (vela_rt_vermelha and 
            (corpo_vela_rt > tamanho_minimo_exigido) and  # <-- CONDIÇÃO MODIFICADA
            (preco_open_rt > sma_curta_rt or preco_open_rt > sma_longa_rt) and
            (preco_close_rt < sma_curta_rt and preco_close_rt < sma_longa_rt)):
            
            direcao_sinal = "VENDA"
        
        # 4. Armar o Sinal (para o bot_manager pegar na janela de 20s ou 12s)
        if direcao_sinal:
            with bot.breakout_lock: 
                bot.breakout_potencial_sinal[par] = { 
                    "direcao": direcao_sinal,
                    "timestamp": datetime.now()
                }
        else:
            # Se o padrão não for atendido (ex: vela RT reverteu ou ficou pequena), cancela o sinal
            with bot.breakout_lock: 
                bot.breakout_potencial_sinal.pop(par, None)
                # Também remove o pré-alerta do site se ele existir
                with bot.pre_alerta_lock:
                    if bot.pre_alerta_ativo.pop(par, None):
                        bot.publish_remove_pre_alert(par)

    except Exception as e:
        print(f"[{bot.username}] Erro em verificar_breakout_sma {par}: {e}\n{traceback.format_exc()}")
        with bot.breakout_lock: 
            bot.breakout_potencial_sinal.pop(par, None) 
        return None
