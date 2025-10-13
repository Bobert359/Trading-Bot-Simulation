# === IMPORTS ===
import os
import pandas as pd
import time
import threading
from datetime import datetime, timezone, timedelta
import requests
from flask import Flask, jsonify, render_template_string

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
fee_pct = 0.0004  # 0.04% pro Trade

# === SIMULATION ===
symbol = 'BTCUSDT'
open_trades = []
last_status_update = datetime.now(timezone.utc)

# === FLASK ===
app = Flask(__name__)

@app.route('/')
def home():
    return '✅ Trading Bot Echtzeit-Simulation läuft!'

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
        <title>Trading Bot Dashboard</title>
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
        <h1>📊 Trading Bot Dashboard</h1>
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

# === BINANCE DATA ===
def get_current_price():
    try:
        url = f'https://api.binance.com/api/v3/ticker/price?symbol={symbol}'
        data = requests.get(url).json()
        return float(data['price'])
    except Exception as e:
        print(f"Fehler beim Abrufen des Preises: {e}")
        return None

def get_klines(interval='30m', limit=100):
    """Holt Kerzendaten von Binance"""
    url = f'https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}'
    data = requests.get(url).json()
    df = pd.DataFrame(data, columns=[
        'open_time','open','high','low','close','volume','close_time','qav','num_trades','taker_base','taker_quote','ignore'])
    df['timestamp'] = pd.to_datetime(df['close_time'], unit='ms')
    df['open'] = df['open'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    df['close'] = df['close'].astype(float)
    df.set_index('timestamp', inplace=True)
    return df

# === BOT LOGIK ===
def run_bot_simulation():
    global open_trades, last_status_update
    send_telegram_message("📢 Echtzeit-Simulation gestartet ✅ (2h/30m Breakout-Logik)")

    while True:
        try:
            now = datetime.now(timezone.utc)

            # Hol 2h und 30m Kerzen
            df_2h = get_klines(interval='2h', limit=50)
            df_30m = get_klines(interval='30m', limit=200)

            current_price = get_current_price()
            if current_price is None:
                time.sleep(5)
                continue

            # Breakout Signale basierend auf letzter 2h Kerze
            last_2h = df_2h.iloc[-1]
            lowest_2h = df_2h['low'].min()
            highest_2h = df_2h['high'].max()
            change_up = (current_price - lowest_2h) / lowest_2h * 100
            change_down = (current_price - highest_2h) / highest_2h * 100

            signal = None
            if change_up >= trigger_pct:
                signal = 'long'
            elif change_down <= -trigger_pct:
                signal = 'short'

            if signal:
                # Entry auf Basis 30m Kerzen (Pullback-Logik)
                for idx, row in df_30m.iterrows():
                    price_30m = row['close']
                    if signal == 'long' and price_30m <= current_price:
                        qty = round(order_size_usdt / price_30m, 3)
                        open_trades.append({'side':'long','entry_price':price_30m*(1+fee_pct),
                                            'entry_time':idx,'amount':qty})
                        send_telegram_message(f"🟢 LONG ENTRY @ {price_30m:.2f} | Menge: {qty}")
                        break
                    elif signal == 'short' and price_30m >= current_price:
                        qty = round(order_size_usdt / price_30m, 3)
                        open_trades.append({'side':'short','entry_price':price_30m*(1-fee_pct),
                                            'entry_time':idx,'amount':qty})
                        send_telegram_message(f"🔴 SHORT ENTRY @ {price_30m:.2f} | Menge: {qty}")
                        break

            # TP / SL prüfen
            updated_trades = []
            for t in open_trades:
                pnl_pct = ((current_price - t['entry_price']) / t['entry_price'] * 100
                           if t['side']=='long' else (t['entry_price'] - current_price) / t['entry_price'] * 100)
                reason = None
                if pnl_pct >= profit_target: reason='TP'
                elif pnl_pct <= -stop_loss: reason='SL'
                if reason:
                    send_telegram_message(f"🎯 {reason} ausgelöst: {t['side'].upper()} @ {current_price:.2f}")
                else:
                    updated_trades.append(t)

            open_trades = updated_trades

            # Status-Update alle 15 Minuten
            if (now - last_status_update).total_seconds() >= 900:
                send_telegram_message(f"📊 STATUS: {current_price:.2f} USDT | Open Trades: {len(open_trades)}")
                last_status_update = now

            time.sleep(5)

        except Exception as e:
            print(f"⚠️ Simulation Fehler: {e}")
            time.sleep(5)

# === START BOT + FLASK ===
if __name__ == "__main__":
    threading.Thread(target=run_bot_simulation, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
