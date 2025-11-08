# config.py
import threading
import queue
from datetime import datetime

# --- Configurações Imutáveis (Constantes do Sistema) ---
INTERVALO = "1m"
COOLDOWN_MINUTOS = 1
BOLLINGER_PERIODO = 20

# Lista de todos os ativos que podem ser escolhidos
TODOS_OS_ATIVOS_DISPONIVEIS = ["btcusdt", "ethusdt", "bnbusdt", "memeusdt", "solusdt", "adausdt"]

# --- Configurações Padrão para Novos Usuários ---
# Estas são as configurações que um usuário recebe quando faz login
DEFAULT_CONFIG = {
    # --- Seção de Telegram do Usuário ---
    "TELEGRAM_TOKEN": "7492983954:AAEF7u9TIz2i8tVjWgjdE2JJhRQeUw478D0", # <-- COLOQUE SEU TOKEN AQUI
    "TELEGRAM_CHAT_ID": "-1002868221349", # <-- COLOQUE SEU ID AQUI
    
    # --- Estratégias Ativas ---
    "USAR_ESTRATEGIA_BOLLINGER_RT": True,
    "USAR_ESTRATEGIA_RSI": True,
    "USAR_ESTRATEGIA_SR": True,
    "USAR_ESTRATEGIA_T5": True,
    "USAR_ESTRATEGIA_MHI": True,
    # "USAR_ESTRATEGIA_RP": True, <-- REMOVIDO
    "USAR_ESTRATEGIA_P3V": True, # <-- Renomeado de VRV
    "USAR_ESTRATEGIA_BREAKOUT_SMA": True, # <-- NOVO
    
    # --- Parâmetros Bollinger ---
    "BOLLINGER_STD_DEV": 2.7,
    "BOLLINGER_OFFSET_PERCENT": 0.0001,
    
    # --- Parâmetros RSI ---
    "RSI_PERIODO": 14,
    "RSI_LIMITE_SUPERIOR": 70,
    "RSI_LIMITE_INFERIOR": 30,
    "RSI_USE_MACD_FILTER": False, # <-- Definido como False (desligado) por padrão
    
    # --- Parâmetros S/R ---
    "SR_PERIODO": 120,
    "SR_TOQUES_NECESSARIOS": 3, 
    "SR_TOLERANCIA_PERCENT": 0.0005,
    "SR_DISTANCIA_MIN_TOQUES": 5,

    # --- Parâmetros MHI ---
    "MHI_USE_TREND_FILTER": True,
    "MHI_TREND_PERIODO": 100,
    "CONFIANCA_MHI": 0.88,

    # --- Parâmetros T5 ---
    "CONFIANCA_T5": 0.92,
    "T5_PAVIO_MIN_RATIO": 2.0,
    
    # --- Parâmetros P3V (Verde-Vermelho-Verde) ---
    "P3V_VWMA_PERIODO": 30, # <-- Renomeado
    "CONFIANCA_P3V": 0.88,  # <-- Renomeado

    # --- Parâmetros Gerenciamento ---
    "VALOR_ENTRADA_BASE": 10.0,

    # --- Confiança (Usado pelo Bot Manager) ---
    "CONFIANCA_BOLLINGER_RT": 0.94,
    "CONFIANCA_RSI": 0.90,
    "CONFIANCA_SR": 0.96,
    "CONFIANCA_BREAKOUT_SMA": 0.80, # <-- NOVO
    
    # --- Parâmetros da Estratégia RP (REMOVIDOS) ---
    # "RP_LOOKBACK_MINUTOS": 180,
    # ... (etc)
    
    # --- Parâmetros Breakout SMA (NOVO) ---
    "BREAKOUT_SMA_CURTA": 5,
    "BREAKOUT_SMA_LONGA": 7,
    "BREAKOUT_SMA_BODY_MULT": 2.0, # (Filtro 2x Corpo)
    "BREAKOUT_SMA_AVG_PERIOD": 20,
    
    "ATIVOS": []
}

# --- Lista de Usuários (Login e Senha) ---
USUARIOS = {
    "traderbr": "ebinex",
    "rodrigo": "rodrigo",
    "123": "123"
}
