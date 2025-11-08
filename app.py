# app.py
import threading
import json
import copy
from datetime import datetime, timedelta
import time as time_sleep
import queue
import requests 
import os
import signal
from flask import Flask, Response, render_template, request, jsonify, redirect, url_for, session
from bot_manager import BotManager 
from config import DEFAULT_CONFIG, USUARIOS, TODOS_OS_ATIVOS_DISPONIVEIS

app = Flask(__name__)
app.secret_key = 'sua-chave-secreta-muito-forte-e-aleatoria-aqui'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7) 

USER_BOTS = {}
APP_LOCK = threading.Lock() 

@app.route("/")
def index():
    if 'username' in session: return redirect(url_for('dashboard'))
    return render_template("login.html")

@app.route("/login", methods=["POST"])
def login():
    u = request.form.get("username", "").strip()
    p = request.form.get("password", "").strip()
    if u in USUARIOS and USUARIOS[u] == p:
        session['username'] = u; session['config'] = copy.deepcopy(DEFAULT_CONFIG); session.permanent = True
        with APP_LOCK:
            if u not in USER_BOTS: USER_BOTS[u] = BotManager(u, session['config'])
            else: USER_BOTS[u].update_config(session['config'])
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route("/dashboard")
def dashboard():
    if 'username' not in session: return redirect(url_for('index'))
    return render_template("index.html", username=session.get('username'))

@app.route("/logout", methods=["POST"])
def logout():
    u = session.pop('username', None); session.pop('config', None)
    if u:
        with APP_LOCK:
            bot = USER_BOTS.pop(u, None)
            if bot: bot.shutdown()
    return jsonify({"success": True})

@app.route("/stream")
def stream():
    if 'username' not in session: return Response("Não autorizado", status=401)
    u = session['username']
    with APP_LOCK: bot = USER_BOTS.get(u)
    if not bot:
        session['config'] = copy.deepcopy(DEFAULT_CONFIG)
        with APP_LOCK: bot = BotManager(u, session['config']); USER_BOTS[u] = bot
    q = bot.get_event_queue()
    def event_stream():
        try:
            while True:
                data = q.get(); 
                if data is None: break
                yield f"data: {json.dumps(data, default=str)}\n\n"
        except GeneratorExit: pass
    return Response(event_stream(), mimetype="text/event-stream")

def get_ucb():
    if 'username' not in session: return None, None, None
    u = session['username']; c = session.get('config')
    with APP_LOCK: b = USER_BOTS.get(u)
    if not c: c = copy.deepcopy(DEFAULT_CONFIG); session['config'] = c
    if not b:
        with APP_LOCK:
            if u not in USER_BOTS: b = BotManager(u, c); USER_BOTS[u] = b
            else: b = USER_BOTS[u]
    return u, c, b

def save_c(c): session['config'] = c; session.modified = True

@app.route("/api/get_config")
def get_config_api():
    u, c, b = get_ucb()
    if not u: return jsonify({"status": "error"}), 401
    # Adicionado Breakout SMA, Removido MACD Global
    return jsonify({
        "bollinger": c.get("USAR_ESTRATEGIA_BOLLINGER_RT", True),
        "rsi": c.get("USAR_ESTRATEGIA_RSI", True),
        "sr": c.get("USAR_ESTRATEGIA_SR", True),
        "t5": c.get("USAR_ESTRATEGIA_T5", True),
        "mhi": c.get("USAR_ESTRATEGIA_MHI", True),
        "p3v": c.get("USAR_ESTRATEGIA_P3V", True),
        "breakout_sma": c.get("USAR_ESTRATEGIA_BREAKOUT_SMA", True), # <-- NOVO
        # "usar_macd": c.get("USAR_FILTRO_MACD", False), # <-- REMOVIDO
        "rsi_use_macd": c.get("RSI_USE_MACD_FILTER", False), # <-- Padrão False
        "bollinger_std": c.get("BOLLINGER_STD_DEV", 2.7),
        "rsi_periodo": c.get("RSI_PERIODO", 14),
        "rsi_limite_sup": c.get("RSI_LIMITE_SUPERIOR", 70),
        "rsi_limite_inf": c.get("RSI_LIMITE_INFERIOR", 30),
        "valor_entrada_base": c.get("VALOR_ENTRADA_BASE", 10.0),
        "sr_periodo": c.get("SR_PERIODO", 120),
        "sr_toques": c.get("SR_TOQUES_NECESSARIOS", 3),
        "sr_tolerancia": c.get("SR_TOLERANCIA_PERCENT", 0.0005),
        "t5_pavio_min": c.get("T5_PAVIO_MIN_RATIO", 2.0),
        "mhi_use_trend": c.get("MHI_USE_TREND_FILTER", True),
        "mhi_trend_periodo": c.get("MHI_TREND_PERIODO", 100),
        "p3v_vwma_periodo": c.get("P3V_VWMA_PERIODO", 30),
        # --- Parâmetros Breakout SMA (NOVO) ---
        "breakout_sma_curta": c.get("BREAKOUT_SMA_CURTA", 5),
        "breakout_sma_longa": c.get("BREAKOUT_SMA_LONGA", 7),
        "breakout_sma_body_mult": c.get("BREAKOUT_SMA_BODY_MULT", 2.0),
        "breakout_sma_avg_period": c.get("BREAKOUT_SMA_AVG_PERIOD", 20),
        # --- Fim ---
        "ativos": c.get("ATIVOS", []),
        "telegram_token": c.get("TELEGRAM_TOKEN", ""),
        "telegram_chat_id": c.get("TELEGRAM_CHAT_ID", "")
    })

@app.route("/api/update_strategy", methods=["POST"])
def update_strategy_api():
    u, c, b = get_ucb()
    if not u: return jsonify({"status": "error"}), 401
    d = request.json or {}; s = d.get("strategy", ""); e = d.get("enabled", False)
    if s == "bollinger": c["USAR_ESTRATEGIA_BOLLINGER_RT"] = e
    elif s == "rsi": c["USAR_ESTRATEGIA_RSI"] = e
    elif s == "sr": c["USAR_ESTRATEGIA_SR"] = e
    elif s == "t5": c["USAR_ESTRATEGIA_T5"] = e
    elif s == "mhi": c["USAR_ESTRATEGIA_MHI"] = e
    elif s == "p3v": c["USAR_ESTRATEGIA_P3V"] = e
    elif s == "breakout_sma": c["USAR_ESTRATEGIA_BREAKOUT_SMA"] = e # <-- NOVO
    
    save_c(c); b.update_config(c)
    return jsonify({"status": "success"})

@app.route("/api/update_settings", methods=["POST"])
def update_settings_api():
    u, c, b = get_ucb()
    if not u: return jsonify({"status": "error"}), 401
    d = request.json or {}
    if d.get("bollinger_std") is not None: c["BOLLINGER_STD_DEV"] = float(d["bollinger_std"])
    if d.get("rsi_periodo") is not None: c["RSI_PERIODO"] = int(d["rsi_periodo"])
    if d.get("rsi_limite_sup") is not None: c["RSI_LIMITE_SUPERIOR"] = int(d["rsi_limite_sup"])
    if d.get("rsi_limite_inf") is not None: c["RSI_LIMITE_INFERIOR"] = int(d["rsi_limite_inf"])
    if d.get("valor_entrada_base") is not None: c["VALOR_ENTRADA_BASE"] = float(d["valor_entrada_base"])
    if d.get("sr_periodo") is not None: c["SR_PERIODO"] = int(d["sr_periodo"])
    if d.get("sr_toques") is not None: c["SR_TOQUES_NECESSARIOS"] = int(d["sr_toques"])
    if d.get("sr_tolerancia") is not None: c["SR_TOLERANCIA_PERCENT"] = float(d["sr_tolerancia"]) / 100.0
    if d.get("t5_pavio_min") is not None: c["T5_PAVIO_MIN_RATIO"] = float(d["t5_pavio_min"])
    if d.get("mhi_use_trend") is not None: c["MHI_USE_TREND_FILTER"] = bool(d["mhi_use_trend"])
    if d.get("mhi_trend_periodo") is not None: c["MHI_TREND_PERIODO"] = int(d["mhi_trend_periodo"])
    if d.get("p3v_vwma_periodo") is not None: c["P3V_VWMA_PERIODO"] = int(d["p3v_vwma_periodo"]) 
    # if d.get("usar_macd") is not None: c["USAR_FILTRO_MACD"] = bool(d["usar_macd"]) # <-- REMOVIDO
    if d.get("rsi_use_macd") is not None: c["RSI_USE_MACD_FILTER"] = bool(d["rsi_use_macd"])
    
    # --- Parâmetros Breakout SMA (NOVO) ---
    if d.get("breakout_sma_curta") is not None: c["BREAKOUT_SMA_CURTA"] = int(d["breakout_sma_curta"])
    if d.get("breakout_sma_longa") is not None: c["BREAKOUT_SMA_LONGA"] = int(d["breakout_sma_longa"])
    if d.get("breakout_sma_body_mult") is not None: c["BREAKOUT_SMA_BODY_MULT"] = float(d["breakout_sma_body_mult"])
    if d.get("breakout_sma_avg_period") is not None: c["BREAKOUT_SMA_AVG_PERIOD"] = int(d["breakout_sma_avg_period"])
    # --- Fim ---

    save_c(c); b.update_config(c)
    return jsonify({"status": "success"})

@app.route("/api/update_telegram", methods=["POST"])
def update_telegram_api():
    u, c, b = get_ucb()
    if not u: return jsonify({"status": "error"}), 401
    d = request.json or {}
    c["TELEGRAM_TOKEN"] = d.get("telegram_token", "").strip()
    c["TELEGRAM_CHAT_ID"] = d.get("telegram_chat_id", "").strip() 
    save_c(c); b.update_config(c)
    return jsonify({"status": "success"})

@app.route("/api/update_asset", methods=["POST"])
def update_asset_api():
    u, c, b = get_ucb()
    if not u: return jsonify({"status": "error"}), 401
    d = request.json or {}; a = d.get("asset", ""); m = d.get("monitor", False)
    if a not in TODOS_OS_ATIVOS_DISPONIVEIS: return jsonify({"status": "error"}), 400
    if m and a not in c["ATIVOS"]: c["ATIVOS"].append(a); b.start_asset_monitor(a)
    elif not m and a in c["ATIVOS"]: c["ATIVOS"].remove(a); b.stop_asset_monitor(a)
    save_c(c); b.update_config(c)
    return jsonify({"status": "success"})

@app.route("/api/get_history")
def get_history_api():
    u, c, b = get_ucb()
    if not u: return jsonify({"status": "error"}), 401
    h, s = b.get_history_and_stats()
    return jsonify({'history': h, 'stats': s})

@app.route("/api/manual_check_mhi_t5", methods=["POST"])
def manual_check_mhi_t5_api():
    u, c, b = get_ucb()
    if not u: return jsonify({"status": "error"}), 401
    return jsonify(b.trigger_manual_mhi_t5(TODOS_OS_ATIVOS_DISPONIVEIS))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port)
