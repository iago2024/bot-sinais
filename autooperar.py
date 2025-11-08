# agente_local.py — versão final e estável 🚀
import requests
import json
import os
import time
import winsound
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from colorama import Fore, Style, init

init(autoreset=True)

# --- CONFIGURAÇÕES ---
BOT_URL = "https://ia-bot1.onrender.com"
BOT_USER = "traderbr"
BOT_PASS = "ebinex"
EBINEX_URL = "https://app.ebinex.com/traderoom"

# XPaths fixos (usando IDs diretos)
XPATH_BOTAO_COMPRA = '//*[@id="button-bull"]/p'
XPATH_BOTAO_VENDA = '//*[@id="button-bear"]'


class ClickBot:
    def __init__(self, ativos):
        self.ativos_monitorados = ativos
        print(Fore.CYAN + "--- Iniciando Click Bot (Selenium) ---")
        print("Anexando ao Opera GX (porta 9222)...")

        try:
            driver_path = os.path.join(os.getcwd(), "chromedriver.exe")
            options = ChromeOptions()
            options.debugger_address = "127.0.0.1:9222"

            # Caminho do Opera GX
            opera_exe_path = r"C:\Users\Administrator\AppData\Local\Programs\Opera GX\opera.exe"
            options.binary_location = opera_exe_path

            service = ChromeService(executable_path=driver_path)
            self.driver = webdriver.Chrome(options=options, service=service)

            # 🔍 Verifica se a Ebinex já está aberta
            found = False
            for handle in self.driver.window_handles:
                self.driver.switch_to.window(handle)
                if "Ebinex" in self.driver.title or "Traderoom" in self.driver.title:
                    found = True
                    print(Fore.GREEN + f"✅ Ebinex já aberta (título: {self.driver.title})")
                    break

            # 🔗 Se não estiver aberta, abre nova aba visível
            if not found:
                print(Fore.CYAN + f"Abrindo automaticamente {EBINEX_URL} ...")
                self.driver.execute_script(f"window.open('{EBINEX_URL}', '_blank');")
                self.driver.switch_to.window(self.driver.window_handles[-1])
                time.sleep(5)
                print(Fore.GREEN + f"✅ Página aberta: {self.driver.title}")

            print(Fore.CYAN + "AVISO: Deixe esta página (Ebinex) em primeiro plano.")
        except Exception as e:
            print(Fore.RED + f"❌ ERRO CRÍTICO: {e}")
            exit()

        self.session = requests.Session()

    # --- LOGIN ---
    def login_to_bot(self):
        print(Fore.CYAN + f"Logando no servidor de sinais ({BOT_URL})...")
        try:
            r = self.session.post(f"{BOT_URL}/login", data={"username": BOT_USER, "password": BOT_PASS})
            if r.json().get("success"):
                print(Fore.GREEN + "✅ Login no servidor de sinais OK.")
                return self.session.cookies
            else:
                print(Fore.RED + "❌ Falha no login. Verifique BOT_USER/BOT_PASS.")
                return None
        except Exception as e:
            print(Fore.RED + f"❌ Erro ao conectar ao servidor de sinais: {e}")
            return None

    # --- STREAM SSE ---
    def listen_to_signals(self):
        """Escuta eventos SSE do servidor e executa cliques."""
        while True:
            cookies = self.login_to_bot()
            if not cookies:
                print(Fore.RED + "Encerrando bot de clique.")
                return

            cookie_str = "; ".join([f"{c.name}={c.value}" for c in cookies])
            headers = {"Cookie": cookie_str}

            try:
                print(Fore.CYAN + f"🔌 Conectando ao stream de sinais ({BOT_URL}/stream)...")
                with self.session.get(f"{BOT_URL}/stream", headers=headers, stream=True, timeout=(10, None)) as resp:
                    if resp.status_code != 200:
                        print(Fore.RED + f"❌ Erro ao conectar ao stream: {resp.status_code}")
                        time.sleep(5)
                        continue

                    print(Fore.GREEN + "✅ Conectado ao stream SSE. Aguardando sinais...")
                    for line in resp.iter_lines(decode_unicode=True):
                        if not line or not line.startswith("data:"):
                            continue
                        try:
                            data_str = line.replace("data: ", "").strip()
                            data = json.loads(data_str)
                            tipo = data.get("type")

                            if tipo == "signal":
                                ativo = data.get("ativo", "").upper()
                                direcao = data.get("direcao", "").upper()
                                origem = data.get("origem", "")
                                confianca = data.get("confianca", "")
                                hora = data.get("horario", "")

                                print(Fore.MAGENTA + f"\n🔥 [{hora}] SINAL RECEBIDO: {direcao} {ativo} ({origem}) | Confiança {confianca}")

                                if ativo in self.ativos_monitorados:
                                    winsound.Beep(1200, 200)
                                    winsound.Beep(1000, 200)
                                    self.execute_trade(direcao, ativo)
                                else:
                                    print(Fore.YELLOW + f"⚪ Sinal ignorado (ativo {ativo} não está monitorado).")

                        except Exception as e:
                            print(Fore.RED + f"Erro ao processar linha SSE: {e}")

            except Exception as e:
                print(Fore.RED + f"--- Conexão perdida ({e}). Tentando reconectar em 5s... ---")
                time.sleep(5)

    # --- EXECUTA CLIQUES ---
    def execute_trade(self, direcao, ativo):
        try:
            wait = WebDriverWait(self.driver, 10)

            if direcao == "COMPRA":
                print(Fore.CYAN + f"...Procurando botão de COMPRA ({ativo})...")
                botao = wait.until(EC.element_to_be_clickable((By.XPATH, XPATH_BOTAO_COMPRA)))
                botao.click()
                print(Fore.GREEN + f"🚀 CLIQUE DE COMPRA ({ativo}) EXECUTADO!")

            elif direcao == "VENDA":
                print(Fore.CYAN + f"...Procurando botão de VENDA ({ativo})...")
                botao = wait.until(EC.element_to_be_clickable((By.XPATH, XPATH_BOTAO_VENDA)))
                botao.click()
                print(Fore.RED + f"🚀 CLIQUE DE VENDA ({ativo}) EXECUTADO!")

            else:
                print(Fore.YELLOW + f"⚠️ Direção desconhecida: {direcao}")

        except Exception as e:
            print(Fore.RED + "\n" + "=" * 60)
            print("❌ ERRO AO CLICAR NO BOTÃO!")
            print("Verifique se os XPATHs estão corretos e se a Ebinex está ativa.")
            print(f"Erro: {e}")
            print("=" * 60)


# --- EXECUÇÃO ---
# --- EXECUÇÃO ---
if __name__ == "__main__":
    print(Fore.CYAN + "\n=== Escolha os ativos para monitorar ===")
    print("1️⃣  BTCUSDT")
    print("2️⃣  ETHUSDT")
    print("3️⃣  MEMEUSDT")
    print("4️⃣  ADAUSDT")
    print("5️⃣  SOLUSDT")
    print("6️⃣  BNBUSDT")
    print("7️⃣  Todos os ativos")

    escolha = input("Digite os números separados por vírgula (ex: 1,2,4): ").strip()

    ativos_opcoes = {
        "1": "BTCUSDT",
        "2": "ETHUSDT",
        "3": "MEMEUSDT",
        "4": "ADAUSDT",
        "5": "SOLUSDT",
        "6": "BNBUSDT"
    }

    ativos = []
    if escolha == "7":
        ativos = list(ativos_opcoes.values())
    else:
        for i in escolha.split(","):
            i = i.strip()
            if i in ativos_opcoes:
                ativos.append(ativos_opcoes[i])

    if not ativos:
        print(Fore.YELLOW + "⚠️ Nenhum ativo selecionado. Usando todos por padrão.")
        ativos = list(ativos_opcoes.values())

    print(Fore.GREEN + f"\nAtivos monitorados: {ativos}")
    bot = ClickBot(ativos)
    bot.listen_to_signals()

