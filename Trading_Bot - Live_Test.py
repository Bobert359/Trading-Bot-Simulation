# === IMPORTS ===
import ccxt
import pandas as pd
import time
import threading
from datetime import datetime, timezone
import requests
from flask import Flask, jsonify, render_template_string

# === TELEGRAM ===
telegram_token = 'DEIN_TELEGRAM_TOKEN'
telegram_chat_id = 'DEINE_CHAT_ID'

def send_telegram_message(message):
    try:
        url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
        payload = {'chat_id': telegram_chat_id, 'text': message, 'parse_mode': 'Markdown'}
        requests.post(url, data=payload)
    except Exception as e:
        print(f"Telegram Fehler: {e}")

# === KONFIGURATION ===
symbol = "BTC/USDT"
order_size_usdt = 10
start_capital = 100
fee_pct = 0.0004  # 0.04 %
trigger_pct = 1.5
profit_target = 10.0
stop_loss = 3.0

capital = start_capital
open_trades = []

# === BINANCE ===
exchange = ccxt.binance({
    "enableRateLimit": True,
})

# === FLASK ===
app = Flask(__name__)

@app.route('/')
def home():
    return '✅ Paper-Trading-Bot läuft (2h-Pullback-Strategie)'

@app.route('/status')
def status():
    total_open = len(open_trades)
    unrealized = 0
    current_price = get_current_price()
    for t in open_trades:
        pnl = (current_price - t['entry_price']) * t['amount'] if t['side'] == 'long' else (t['entry_price'] - current_price) * t['amount']
        unrealized += pnl
    return jsonify({
        "symbol": symbol,
        "capital": capital,
        "open_trades": total_open,
        "unrealized_pnl": unrealized,
        "current_price": current_price,
    })

# === HELFER ===
def get_current_price():
    ticker = exchange.fetch_ticker(symbol)
    return ticker['last']

def get_ohlcv(timeframe='2h', limit=100):
    data = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(data, columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    return df

# === PAPER-TRADING-LOGIK ===
def run_paper_trader():
    global open_trades, capital
    send_telegram_message("📢 Paper-Trading gestartet ✅ (2h Pullback Strategie)")

    while True:
        try:
            df_2h = get_ohlcv('2h', 200)
            df_30m = get_ohlcv('30m', 200)
            current_price = df_2h['close'].iloc[-1]

            lowest_2h = df_2h['low'].min()
            highest_2h = df_2h['high'].max()
            change_up = (current_price - lowest_2h) / lowest_2h * 100
            change_down = (current_price - highest_2h) / highest_2h * 100

            # === ENTRY SIGNALS ===
            if change_up >= trigger_pct:
                qty = order_size_usdt / current_price
                open_trades.append({
                    'id': len(open_trades)+1,
                    'side': 'long',
                    'entry_price': current_price * (1 + fee_pct),
                    'entry_time': datetime.now(timezone.utc),
                    'amount': qty,
                    'status': 'open'
                })
                send_telegram_message(f"🟢 LONG eröffnet @ {current_price:.2f} | Menge: {qty:.4f}")

            elif change_down <= -trigger_pct:
                qty = order_size_usdt / current_price
                open_trades.append({
                    'id': len(open_trades)+1,
                    'side': 'short',
                    'entry_price': current_price * (1 - fee_pct),
                    'entry_time': datetime.now(timezone.utc),
                    'amount': qty,
                    'status': 'open'
                })
                send_telegram_message(f"🔴 SHORT eröffnet @ {current_price:.2f} | Menge: {qty:.4f}")

            # === EXIT MANAGEMENT (TP/SL) ===
            updated_trades = []
            for t in open_trades:
                side = t['side']
                entry = t['entry_price']
                qty = t['amount']

                pnl_pct = ((current_price - entry) / entry * 100) if side == 'long' else ((entry - current_price) / entry * 100)
                reason = None

                if pnl_pct >= profit_target:
                    reason = "🎯 Take Profit"
                elif pnl_pct <= -stop_loss:
                    reason = "🛑 Stop Loss"

                if reason:
                    exit_price = current_price * (1 - fee_pct if side == 'long' else 1 + fee_pct)
                    pnl_usdt = ((exit_price - entry) * qty if side == 'long' else (entry - exit_price) * qty)
                    capital += pnl_usdt
                    send_telegram_message(f"{reason} | {side.upper()} @ {exit_price:.2f} | PnL: {pnl_usdt:.2f} USDT | Kapital: {capital:.2f}")
                else:
                    updated_trades.append(t)

            open_trades = updated_trades
            time.sleep(120)  # alle 2 Minuten prüfen

        except Exception as e:
            print(f"⚠️ Fehler: {e}")
            time.sleep(60)

# === START ===
if __name__ == "__main__":
    threading.Thread(target=run_paper_trader).start()
    app.run(host='0.0.0.0', port=5000)
