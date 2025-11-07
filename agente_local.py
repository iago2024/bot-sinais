# agente_local.py
import threading
import json
import time
import queue
import sys
import os

try:
    import requests
    from sseclient import SSEClient
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError:
    print("Erro: Bibliotecas necessárias não encontradas.")
    print("Por favor, instale as dependências com: pip install -r requirements_agente.txt")
    sys.exit(1)

# --- CONFIGURAÇÕES DO CLIENTE (VERIFIQUE ESTAS 3 SEÇÕES) ---

# 1. URL do seu servidor (o link do Ngrok ou seu domínio)
SERVIDOR_URL = "http://localhost:5000" # Mude para seu link Ngrok

# 2. Login e Senha do SEU PAINEL (o mesmo do app.py)
PAINEL_LOGIN_USER = "traderbr"
PAINEL_LOGIN_PASS = "ebinex"

# 3. Caminho para o Perfil do Chrome do cliente
# [CORRIGIDO] Este é o caminho correto no seu computador para o usuário "Administrator".
# É aqui que o seu login da Ebinex está salvo.
CHROME_PROFILE_PATH = r"C:\Users\Administrator\AppData\Local\Google\Chrome\User Data"

# 4. URLs de Trading da Ebinex
# [CORRIGIDO] O domínio foi atualizado para 'app.ebinex.com'
# (VERIFIQUE SE O RESTANTE DA URL, ex: /trade/BTC_BRL, ESTÁ CORRETO)
EBINEX_ASSET_URLS = {
    "btcusdt": "https://app.ebinex.com/trade/BTC_BRL", 
    "ethusdt": "https://app.ebinex.com/trade/ETH_BRL", 
    "bnbusdt": "https://app.ebinex.com/trade/BNB_BRL", 
    "memeusdt": "https://app.ebinex.com/trade/MEME_BRL",
    "solusdt": "https://app.ebinex.com/trade/SOL_BRL", 
    "adausdt": "https://app.ebinex.com/trade/ADA_BRL", 
}

# 5. XPaths dos Botões na Ebinex
# [CORRIGIDO] Utilizando os IDs que você encontrou: "button-bull" e "button-bear".
EBINEX_BUTTON_XPATHS = {
    "COMPRA": '//*[@id="button-bull"]', 
    "VENDA": '//*[@id="button-bear"]'  
}
# -----------------------------------------------------------------


# Fila para SINAIS DE TRADE
signal_queue = queue.Queue()
# Fila para ATUALIZAÇÕES DE CONFIG (quais ativos monitorar)
config_queue = queue.Queue()

# Dicionário global para gerenciar os navegadores
managed_drivers = {}
driver_lock = threading.Lock()

def login_ao_servidor(session):
    """Faz login no servidor de sinais (app.py) para obter o cookie de sessão."""
    login_url = f"{SERVIDOR_URL}/login"
    login_data = {
        "username": PAINEL_LOGIN_USER,
        "password": PAINEL_LOGIN_PASS
    }
    try:
        print(f"Autenticando no servidor de sinais em {SERVIDOR_URL}...")
        r = session.post(login_url, data=login_data, timeout=10)
        r.raise_for_status()
        if r.json().get("success"):
            print("Autenticado com sucesso!")
            return True
        else:
            print("Falha na autenticação: Usuário ou senha do PAINEL incorretos.")
            return False
    except requests.exceptions.ConnectionError:
        print(f"Erro: Não foi possível conectar ao servidor {SERVIDOR_URL}.")
        return False
    except Exception as e:
        print(f"Erro inesperado no login do servidor: {e}")
        return False

def conectar_ao_stream(session):
    """Ouve o stream de sinais do servidor e coloca nas filas corretas."""
    stream_url = f"{SERVIDOR_URL}/stream"
    while True:
        try:
            print("Conectando ao stream de sinais...")
            response = session.get(stream_url, stream=True, headers={"Accept": "text/event-stream"})
            response.raise_for_status()
            print("Conectado! Ouvindo eventos...")
            client = SSEClient(response)
            
            for event in client.events():
                if not event.data:
                    continue
                    
                try:
                    data = json.loads(event.data)
                    
                    # --- [BUG CORRIGIDO AQUI] ---
                    # O tipo do evento está DENTRO do JSON 'data'
                    event_type = data.get('type')
                    
                    if event_type == "signal":
                    # --- [FIM DA CORREÇÃO] ---
                        print(f"--- SINAL RECEBIDO: {data.get('direcao')} {data.get('ativo')} ---")
                        signal_queue.put(data)
                        
                    # --- [BUG CORRIGIDO AQUI] ---
                    elif event_type == "active_assets_update":
                    # --- [FIM DA CORREÇÃO] ---
                        print(f"--- ATUALIZAÇÃO DE ATIVOS: {data.get('assets')} ---")
                        config_queue.put(data)
                        
                except json.JSONDecodeError:
                    print(f"Erro: Recebido dado mal formatado: {event.data}")
                except AttributeError as e:
                    print(f"Erro de atributo: {e}. Evento: {event}")
                
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                print("Erro de autorização (401). A sessão expirou. Tentando relogar...")
                if not login_ao_servidor(session):
                    time.sleep(30)
            else:
                print(f"Erro HTTP no stream: {e}"); time.sleep(10)
        except Exception as e:
            print(f"Erro na conexão do stream: {e}. Reconectando em 10s...")
            time.sleep(10)

def criar_novo_driver(par):
    """Função helper para criar uma nova instância do Chrome para um ativo."""
    driver = None # <-- [BUG CORRIGIDO 2] Inicializa driver
    
    if par not in EBINEX_ASSET_URLS:
        print(f"Erro: Ativo '{par}' não tem URL definida em EBINEX_ASSET_URLS.")
        return None
        
    try:
        print(f"[{par}] Abrindo novo navegador...")
        options = webdriver.ChromeOptions()
        options.add_argument(f"user-data-dir={CHROME_PROFILE_PATH}")
        options.add_argument("--start-maximized")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-popup-blocking")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        
        # --- [BUG CORRIGIDO 1] ---
        # Novo método para silenciar os logs do webdriver-manager
        os.environ['WDM_LOG_LEVEL'] = '0' 
        
        # Removemos os argumentos antigos (log_level, print_first_line)
        s = Service(ChromeDriverManager().install())
        # --- [FIM DA CORREÇÃO 1] ---
        
        driver = webdriver.Chrome(service=s, options=options)
        
        print(f"[{par}] Navegando para a página de trade: {EBINEX_ASSET_URLS[par]}")
        driver.get(EBINEX_ASSET_URLS[par])
        
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, EBINEX_BUTTON_XPATHS["COMPRA"]))
        )
        print(f"[{par}] Página carregada e pronta.")
        return driver
    except Exception as e:
        print(f"[{par}] Erro ao iniciar o navegador para {par}: {e}")
        if driver: # <-- [BUG CORRIGIDO 2] Verificação segura
            driver.quit()
        return None

def gerenciador_selenium():
    """Thread principal que gerencia os navegadores e executa os trades."""
    global managed_drivers
    
    try:
        print("Buscando configuração inicial de ativos...")
        r = session.get(f"{SERVIDOR_URL}/api/get_config")
        r.raise_for_status()
        initial_assets = r.json().get("ativos", [])
        print(f"Ativos iniciais: {initial_assets}")
        config_queue.put({"assets": initial_assets}) 
    except Exception as e:
        print(f"Erro ao buscar config inicial: {e}")
        
    
    while True:
        try:
            # 1. Processa atualizações de configuração (abrir/fechar navegadores)
            while not config_queue.empty():
                config_update = config_queue.get()
                new_assets = set(config_update.get("assets", []))
                
                with driver_lock:
                    current_assets = set(managed_drivers.keys())
                    
                    to_close = current_assets - new_assets
                    for par in to_close:
                        print(f"[{par}] Ativo desativado. Fechando navegador...")
                        driver = managed_drivers.pop(par, None)
                        if driver:
                            driver.quit()
                            
                    to_open = new_assets - current_assets
                    for par in to_open:
                        driver = criar_novo_driver(par)
                        if driver:
                            managed_drivers[par] = driver
            
            # 2. Processa sinais de trade (clicar botões)
            while not signal_queue.empty():
                signal = signal_queue.get()
                ativo = signal.get("ativo", "").lower()
                direcao = signal.get("direcao", "").upper()
                
                with driver_lock:
                    driver = managed_drivers.get(ativo)
                    
                if not driver:
                    print(f"Aviso: Sinal recebido para {ativo}, mas o navegador não está pronto/aberto.")
                    continue
                
                if direcao not in EBINEX_BUTTON_XPATHS:
                    print(f"Erro: Direção '{direcao}' não tem XPath definido.")
                    continue
                    
                try:
                    button_xpath = EBINEX_BUTTON_XPATHS[direcao]
                    print(f"[{ativo}] EXECUTANDO ORDEM DE {direcao}!")
                    
                    driver.find_element(By.XPATH, button_xpath).click()
                    
                    print(f"[{ativo}] --- ORDEM EXECUTADA ---")
                    
                except Exception as e:
                    print(f"[{ativo}] ERRO AO CLICAR NO BOTÃO: {e}")
                    print(f"[{ativo}] O XPath '{button_xpath}' pode estar errado ou a página mudou.")
            
            time.sleep(0.1) 
            
        except Exception as e:
            print(f"Erro fatal no gerenciador_selenium: {e}")
            time.sleep(5)

if __name__ == "__main__":
    if "SEU_LINK" in SERVIDOR_URL:
        print("ERRO: Edite a variável 'SERVIDOR_URL' (linha 21).")
        sys.exit(1)
    if r"C:\Users\Administrator\Downloads\trader_refatorado\trader_refatorado\User Data" in CHROME_PROFILE_PATH:
        print("AVISO: O 'CHROME_PROFILE_PATH' (linha 29) ainda é o de exemplo.")
        print("Ele DEVE ser o caminho real do seu perfil (ex: C:\\Users\\Administrator\\AppData\\...)")
        time.sleep(5)
    if "trade-form-spot-buy" in EBINEX_BUTTON_XPATHS["COMPRA"]:
        print("AVISO: Os 'EBINEX_BUTTON_XPATHS' (linha 48) são EXEMPLOS.")
        print("Você PRECISA atualizá-los com os XPaths corretos da Ebinex, ou o robô irá falhar.")
        time.sleep(5)

    session = requests.Session()
    
    if not login_ao_servidor(session):
        print("Encerrando o agente.")
        sys.exit(1)

    stream_thread = threading.Thread(target=conectar_ao_stream, args=(session,), daemon=True)
    stream_thread.start()
    
    try:
        gerenciador_selenium()
    except KeyboardInterrupt:
        print("\nDesligando agente local...")
    finally:
        print("Fechando todos os navegadores...")
        with driver_lock:
            for driver in managed_drivers.values():
                driver.quit()
        print("Agente local encerrado.")