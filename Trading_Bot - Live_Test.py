# === IMPORTS ===
import pandas as pd
import time
import threading
from datetime import datetime, timezone
import requests
from flask import Flask, jsonify, render_template_string
import random  # für kleine Preisschwankungen im Simulationstest

# === TELEGRAM KONFIGURATION ===
telegram_token = '7793055320:AAFhsfKiAsK766lBL4olwGamBA8q6HCFtqk'
telegram_chat_id = '591018668'

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {'chat_id': telegram_chat_id, 'text': message, 'parse_mode': 'Markdown'}
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"Telegram Fehler: {e}")

# === BOT KONFIGURATION ===
order_size_usdt = 10
trigger_pct = 1.5
profit_target = 10.0
stop_loss = 3.0

# === SIMULATION ===
symbol = 'BTC/USDT'
price_sim = 100.0  # Startpreis für Simulation
open_trades = []
last_status_update = datetime.now(timezone.utc)

# === FLASK ===
app = Flask(__name__)

@app.route('/')
def home():
    return '✅ Trading Bot Simulation läuft!'

@app.route('/ping')
def ping():
    return jsonify({"status": "success", "message": "Bot Simulation läuft!"}), 200

@app.route('/status')
def get_status():
    current_price = get_current_price()
    trade_info = [
        {"side": t['side'], "entry_price": t['entry_price'], "entry_time": t['entry_time']}
        for t in open_trades
    ]
    return jsonify({
        "current_price": current_price,
        "open_trades": len(open_trades),
        "trade_info": trade_info
    }), 200

@app.route('/dashboard')
def dashboard():
    current_price = get_current_price()
    long_trades = len([t for t in open_trades if t['side'] == 'long'])
    short_trades = len([t for t in open_trades if t['side'] == 'short'])

    if len(open_trades) == 0:
        table_rows = "<tr><td colspan='4'>Keine offenen Trades</td></tr>"
    else:
        table_rows = ""
        for t in open_trades:
            table_rows += f"""
                <tr>
                    <td>{t['side'].upper()}</td>
                    <td>{t['entry_price']:.2f}</td>
                    <td>{t['entry_time'].strftime('%Y-%m-%d %H:%M')}</td>
                    <td>{t['amount']}</td>
                </tr>
            """

    unrealized_pnl = 0
    for t in open_trades:
        entry = t['entry_price']
        qty = t['amount']
        side = t['side']
        pnl = (current_price - entry) * qty if side == 'long' else (entry - current_price) * qty
        unrealized_pnl += pnl

    html = f"""
    <html>
    <head>
        <title>Trading Bot Simulation Dashboard</title>
        <meta http-equiv="refresh" content="10">
        <style>
            body {{ font-family: Arial; background: #f4f4f4; }}
            h1 {{ color: #333; }}
            table {{ width: 100%; border-collapse: collapse; }}
            th, td {{ padding: 10px; border: 1px solid #ccc; text-align: center; }}
            th {{ background-color: #eee; }}
        </style>
    </head>
    <body>
        <h1>📊 Trading Bot Simulation Dashboard</h1>
        <p>Aktueller Preis: <strong>{current_price:.2f} USDT</strong></p>
        <p>Offene Trades: {len(open_trades)} (Long: {long_trades} / Short: {short_trades})</p>
        <p>📈 Unrealized PnL: <strong>{unrealized_pnl:.2f} USDT</strong></p>
        <table>
            <thead>
                <tr>
                    <th>Richtung</th>
                    <th>Eintrittspreis</th>
                    <th>Zeit</th>
                    <th>Menge</th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>
    </body>
    </html>
    """
    return render_template_string(html)

# === SIMULATIONS-FUNKTIONEN ===
def get_current_price():
    global price_sim
    # kleine zufällige Schwankung simulieren
    price_sim *= 1 + random.uniform(-0.001, 0.001)
    return round(price_sim, 2)

def run_bot_simulation():
    global open_trades, last_status_update
    send_telegram_message("📢 Simulation gestartet ✅ (2h-Breakout Strategie)")

    while True:
        try:
            now = datetime.now(timezone.utc)
            current_price = get_current_price()

            # 2h-Breakout Signale (simuliert)
            lowest_2h = current_price * 0.98  # 2% Pullback simuliert
            highest_2h = current_price * 1.02
            change_up = (current_price - lowest_2h) / lowest_2h * 100
            change_down = (current_price - highest_2h) / highest_2h * 100

            # LONG SIGNAL
            if change_up >= trigger_pct:
                qty = round(order_size_usdt / current_price, 3)
                open_trades.append({'side':'long','entry_price':current_price,'entry_time':now,'amount':qty})
                send_telegram_message(f"🟢 SIM LONG @ {current_price:.2f} | Menge: {qty}")

            # SHORT SIGNAL
            if change_down <= -trigger_pct:
                qty = round(order_size_usdt / current_price, 3)
                open_trades.append({'side':'short','entry_price':current_price,'entry_time':now,'amount':qty})
                send_telegram_message(f"🔴 SIM SHORT @ {current_price:.2f} | Menge: {qty}")

            # TP / SL prüfen
            updated_trades = []
            current_price = get_current_price()
            for t in open_trades:
                pnl_pct = ((current_price - t['entry_price']) / t['entry_price'] * 100
                           if t['side']=='long'
                           else (t['entry_price'] - current_price) / t['entry_price'] * 100)
                reason = None
                if pnl_pct >= profit_target:
                    reason = f"🎯 SIM TP erreicht (+{pnl_pct:.2f}%)"
                elif pnl_pct <= -stop_loss:
                    reason = f"🛑 SIM SL ausgelöst ({pnl_pct:.2f}%)"

                if reason:
                    send_telegram_message(f"{reason}\nExit: {t['side'].upper()} @ {current_price:.2f}")
                else:
                    updated_trades.append(t)

            open_trades = updated_trades

            # Status-Update alle 15 Minuten
            if (now - last_status_update).total_seconds() >= 900:
                msg = f"📊 STATUS-UPDATE (Simulation)\nPreis: {current_price:.2f} USDT\nOpen Trades: {len(open_trades)}"
                send_telegram_message(msg)
                last_status_update = now

            time.sleep(5)  # schneller für Simulation

        except Exception as e:
            print(f"⚠️ Simulation Fehler: {e}")
            time.sleep(5)

# === SIMULATION + FLASK PARALLEL STARTEN ===
if __name__ == "__main__":
    threading.Thread(target=run_bot_simulation).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
