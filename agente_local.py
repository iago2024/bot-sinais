# agente_local.py — versão multi-navegador e estável 🚀
import sys
import os
import time
import json
import winsound
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from colorama import Fore, init

init(autoreset=True)

# --- CONFIGURAÇÕES PRINCIPAIS ---
BOT_URL = "https://ia-bot1.onrender.com"
BOT_USER = "traderbr"
BOT_PASS = "ebinex"
EBINEX_URL = "https://app.ebinex.com/traderoom"
DEBUG_PORT = "127.0.0.1:9222"

# Caminhos dos binários e drivers
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
CHROMEDRIVER_PATH = os.path.join(ROOT_DIR, "chromedriver.exe")
EDGE_DRIVER_PATH = os.path.join(ROOT_DIR, "msedgedriver.exe")

OPERA_BINARY = r"C:\Users\Administrator\AppData\Local\Programs\Opera GX\opera.exe"
CHROME_BINARY = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
EDGE_BINARY = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

# XPaths fixos (IDs estáveis)
XPATH_BOTAO_COMPRA = '//*[@id="button-bull"]/p'
XPATH_BOTAO_VENDA = '//*[@id="button-bear"]'


# --- FUNÇÃO DE CRIAÇÃO DO DRIVER ---
def create_driver_for(browser_choice):
    browser_choice = browser_choice.lower()
    if browser_choice in ["opera", "chrome"]:
        options = ChromeOptions()
        options.debugger_address = DEBUG_PORT
        if browser_choice == "opera":
            options.binary_location = OPERA_BINARY
        else:
            options.binary_location = CHROME_BINARY
        service = ChromeService(executable_path=CHROMEDRIVER_PATH)
        driver = webdriver.Chrome(options=options, service=service)
        return driver

    elif browser_choice == "edge":
        options = EdgeOptions()
        options.add_experimental_option("debuggerAddress", DEBUG_PORT)
        options.binary_location = EDGE_BINARY
        service = EdgeService(executable_path=EDGE_DRIVER_PATH)
        driver = webdriver.Edge(options=options, service=service)
        return driver

    else:
        raise ValueError("Navegador desconhecido: " + browser_choice)


# --- CLASSE PRINCIPAL ---
class ClickBot:
    def __init__(self, ativos, browser_choice):
        self.ativos_monitorados = ativos
        self.browser_choice = browser_choice
        print(Fore.CYAN + f"--- Iniciando Click Bot ({browser_choice.upper()}) ---")

        try:
            print(Fore.CYAN + f"Anexando ao navegador na porta {DEBUG_PORT}...")
            self.driver = create_driver_for(browser_choice)

            # Tenta encontrar ou abrir a Ebinex
            found = False
            for handle in self.driver.window_handles:
                self.driver.switch_to.window(handle)
                if "Ebinex" in self.driver.title or "Traderoom" in self.driver.title:
                    found = True
                    print(Fore.GREEN + f"✅ Ebinex já aberta (título: {self.driver.title})")
                    break

            if not found:
                print(Fore.CYAN + f"Abrindo automaticamente {EBINEX_URL} ...")
                self.driver.execute_script(f"window.open('{EBINEX_URL}', '_blank');")
                self.driver.switch_to.window(self.driver.window_handles[-1])
                time.sleep(5)
                print(Fore.GREEN + f"✅ Página aberta: {self.driver.title}")

            print(Fore.CYAN + "AVISO: Deixe esta página (Ebinex) em primeiro plano.")
        except Exception as e:
            print(Fore.RED + f"❌ ERRO ao anexar ao navegador: {e}")
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
        while True:
            cookies = self.login_to_bot()
            if not cookies:
                print(Fore.RED + "Encerrando bot de clique.")
                return

            cookie_str = "; ".join([f"{c.name}={c.value}" for c in cookies])
            headers = {"Cookie": cookie_str}

            try:
                print(Fore.CYAN + f"🔌 Conectando ao stream ({BOT_URL}/stream)...")
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
                                    print(Fore.YELLOW + f"⚪ Sinal ignorado (ativo {ativo} não está na lista monitorada).")
                        except Exception as e:
                            print(Fore.RED + f"Erro ao processar SSE: {e}")

            except Exception as e:
                print(Fore.RED + f"--- Conexão perdida ({e}). Tentando reconectar em 5s... ---")
                time.sleep(5)

    # --- EXECUTA CLIQUES ---
    def execute_trade(self, direcao, ativo):
        try:
            wait = WebDriverWait(self.driver, 15)
            if direcao == "COMPRA":
                print(Fore.CYAN + f"...Procurando botão de COMPRA ({ativo})...")
                botao = wait.until(EC.element_to_be_clickable((By.XPATH, XPATH_BOTAO_COMPRA)))
                print(Fore.GREEN + "✅ Botão de COMPRA encontrado, clicando...")
                botao.click()
                # time.sleep(0.5)
                # botao.click()
                print(Fore.GREEN + f"🚀 CLIQUE DE COMPRA ({ativo}) EXECUTADO!")

            elif direcao == "VENDA":
                print(Fore.CYAN + f"...Procurando botão de VENDA ({ativo})...")
                botao = wait.until(EC.element_to_be_clickable((By.XPATH, XPATH_BOTAO_VENDA)))
                print(Fore.GREEN + "✅ Botão de VENDA encontrado, clicando...")
                botao.click()
                # time.sleep(0.5)
                # botao.click()
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
if __name__ == "__main__":
    print(Fore.CYAN + "\n=== Escolha os ativos para monitorar ===")
    print("1️⃣  BTCUSDT")
    print("2️⃣  ETHUSDT")
    print("3️⃣  MEMEUSDT")
    print("4️⃣  ADAUSDT")
    print("5️⃣  SOLUSDT")
    print("6️⃣  BNBUSDT")
    print("7️⃣  Todos os ativos")
    escolha = input("Digite os números separados por vírgula (ex: 1,3,6): ").strip()

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

    # Lê argumento de navegador (passado pelo .bat)
    browser_choice = "opera"
    if len(sys.argv) > 1:
        browser_choice = sys.argv[1].lower()

    print(Fore.GREEN + f"\nAtivos monitorados: {ativos}")
    print(Fore.CYAN + f"Navegador escolhido: {browser_choice.upper()}")
    bot = ClickBot(ativos, browser_choice)
    bot.listen_to_signals()
