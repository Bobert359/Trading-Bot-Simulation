# paper_bot_live.py
# Paper-Trading Bot: 2h Breakout + 30m Pullback entry, paper orders on live Binance data,
# Flask dashboard with chart + open trades + live capital. Pyramiding allowed.
#
# Usage: python paper_bot_live.py
# Requirements: pip install ccxt flask pandas numpy

import time
import threading
from datetime import datetime, timezone
import json
import math
import os

import ccxt
import pandas as pd
import numpy as np
from flask import Flask, jsonify, render_template_string, request

# -------------------------
# === CONFIGURATION ===
# -------------------------
order_size_usdt = 10.0         # fixed per-trade size (paper trading)
start_capital = 100.0          # starting capital
fee_pct = 0.0004               # 0.04% per trade (as in your backtest)
trigger_pct = 1.5              # breakout threshold (%) — will be overwritten by params if needed
profit_target = 10.0           # TP (%) from entry (in percent)
stop_loss = 3.0                # SL (%) from entry
max_open_per_side = 12         # pyramiding limit per side
symbol = "BTC/USDT"            # market symbol used
fetch_limit_2h = 200           # number of 2h candles to fetch (must be > lookback usage)
fetch_limit_30m = 400          # enough 30m candles
loop_sleep = 60                # seconds between main loop iterations
chart_history_points = 200     # how many recent price pts to show on chart

# Paper mode (always True here). If you later want real orders, add logic using exchange.private API.
paper_mode = True

# -------------------------
# === GLOBAL STATE ===
# -------------------------
capital = start_capital
open_trades = []        # list of trade dicts
closed_trades = []      # historical closed trades
price_history = []      # (timestamp_ms, price)
last_status_update = datetime.now(timezone.utc)

# -------------------------
# === EXCHANGE SETUP ===
# -------------------------
# Using Binance public market data via ccxt (no keys needed)
exchange = ccxt.binance({
    'enableRateLimit': True,
    # 'options': {'defaultType': 'future'} if you want futures; default is spot
})
# ensure symbol normalized for ccxt
ccxt_symbol = symbol.replace('/', '/')

# -------------------------
# === FLASK DASHBOARD ===
# -------------------------
app = Flask(__name__)

DASH_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Paper Bot Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    body { font-family: Arial, sans-serif; background: #f7f7f7; margin: 20px; }
    h1 { color: #333; }
    .row { display:flex; gap: 20px; }
    .card { background: white; padding: 12px; border-radius: 6px; box-shadow: 0 2px 6px rgba(0,0,0,0.08); flex:1; }
    table { width:100%; border-collapse: collapse; }
    th, td { padding:8px; border-bottom:1px solid #eee; text-align:left; font-size:13px; }
    .muted { color:#666; font-size:12px; }
  </style>
</head>
<body>
  <h1>📊 Paper-Trading Bot (2h Breakout + 30m Pullback)</h1>
  <div class="row">
    <div class="card">
      <h3>Kapital</h3>
      <p>Start: <strong>{{start_capital}} USDT</strong></p>
      <p>Live Kapital: <strong id="live_capital">...</strong> USDT</p>
      <p class="muted">Order size: {{order_size_usdt}} USDT — Fee: {{fee_pct*100}}%</p>
    </div>
    <div class="card">
      <h3>Offene Trades</h3>
      <div id="open_trades_container">Laden...</div>
    </div>
    <div class="card">
      <h3>Statistik</h3>
      <p id="stats">Lade...</p>
    </div>
  </div>

  <div class="card" style="margin-top:16px;">
    <canvas id="priceChart" height="120"></canvas>
  </div>

<script>
async function fetchData(){
  const res = await fetch('/api/state');
  const data = await res.json();
  return data;
}

let chart;
async function updateUI(){
  const data = await fetchData();
  document.getElementById('live_capital').textContent = data.capital.toFixed(2);
  // Open trades
  const ot = data.open_trades;
  if(ot.length===0){
    document.getElementById('open_trades_container').innerHTML = '<p>Keine offenen Trades</p>';
  } else {
    let html = '<table><thead><tr><th>Side</th><th>Entry</th><th>Qty</th><th>Size(USDT)</th><th>Open PnL</th></tr></thead><tbody>';
    for(const t of ot){
      html += `<tr><td>${t.side.toUpperCase()}</td><td>${t.entry_price.toFixed(2)}</td><td>${t.amount.toFixed(6)}</td><td>${t.order_size.toFixed(2)}</td><td>${t.unrealized_pnl.toFixed(2)}</td></tr>`;
    }
    html += '</tbody></table>';
    document.getElementById('open_trades_container').innerHTML = html;
  }
  // Stats
  document.getElementById('stats').innerHTML = `Closed Trades: ${data.closed_count} &nbsp;|&nbsp; Winrate: ${data.win_rate.toFixed(2)}% &nbsp;|&nbsp; Max DD: ${data.max_dd.toFixed(2)}%`;

  // Chart
  const chdata = data.chart;
  const labels = chdata.map(p=> new Date(p[0]).toLocaleTimeString());
  const prices = chdata.map(p=> p[1]);
  const markers = data.markers || [];
  const markerDataset = markers.map(m=>({x: new Date(m.ts).toLocaleTimeString(), y:m.price, label: m.label, side:m.side}));

  if(!chart){
    const ctx = document.getElementById('priceChart').getContext('2d');
    chart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: 'Price',
          data: prices,
          borderColor: 'rgb(20,120,200)',
          tension: 0.1,
          pointRadius: 0
        }]
      },
      options: {
        plugins:{
          legend:{display:false}
        },
        scales:{
          x:{ display:true },
          y:{ display:true }
        }
      }
    });
  } else {
    chart.data.labels = labels;
    chart.data.datasets[0].data = prices;
    chart.update();
  }

  // draw markers (simple) — we append marker info below chart
  let markhtml = '<div style="margin-top:8px;"><strong>Markers:</strong><ul>';
  for(const m of markers) markhtml += `<li>[${m.side.toUpperCase()}] ${m.label} @ ${m.price.toFixed(2)} (${new Date(m.ts).toLocaleString()})</li>`;
  markhtml += '</ul></div>';
  document.getElementById('open_trades_container').insertAdjacentHTML('beforeend', markhtml);
}

updateUI();
setInterval(updateUI, 10000);
</script>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(DASH_HTML,
                                  start_capital=start_capital,
                                  order_size_usdt=order_size_usdt,
                                  fee_pct=fee_pct)

@app.route('/api/state')
def api_state():
    # Return capital, open trades, closed stats, chart history and markers
    global capital, open_trades, closed_trades, price_history

    # prepare open trades with unrealized pnl
    latest_price = price_history[-1][1] if price_history else None
    ot = []
    for t in open_trades:
        # unrealized pnl in USDT: for long (price - entry)*qty, for short (entry - price)*qty
        if latest_price is None:
            unreal = 0.0
        else:
            unreal = (latest_price - t['entry_price']) * t['amount'] if t['side']=='long' else (t['entry_price'] - latest_price) * t['amount']
        copyt = dict(t)
        copyt['unrealized_pnl'] = unreal
        ot.append(copyt)

    # stats
    closed = closed_trades
    closed_count = len(closed)
    wins = sum(1 for t in closed if t.get('pnl_usdt',0) > 0)
    win_rate = (wins/closed_count*100) if closed_count>0 else 0.0
    # max drawdown we track locally (not persisted); just compute from capital history isn't implemented — placeholder
    max_dd = 0.0

    # chart: send last N points
    chart_data = price_history[-chart_history_points:] if price_history else []
    # markers: map entries/exits from closed_trades and open_trades
    markers = []
    for t in closed_trades:
        if t.get('entry_time'):
            markers.append({'ts': int(t['entry_time'].timestamp()*1000), 'price': t['entry_price'], 'label':'entry', 'side': t['side']})
        if t.get('exit_time'):
            markers.append({'ts': int(t['exit_time'].timestamp()*1000), 'price': t['exit_price'], 'label':'exit', 'side': t['side']})
    for t in open_trades:
        markers.append({'ts': int(t['entry_time'].timestamp()*1000), 'price': t['entry_price'], 'label':'open', 'side': t['side']})

    return jsonify({
        'capital': capital,
        'open_trades': ot,
        'closed_count': closed_count,
        'win_rate': win_rate,
        'max_dd': max_dd,
        'chart': chart_data,
        'markers': markers
    })

# -------------------------
# === STRATEGY / TRADING LOGIC ===
# -------------------------

def fetch_ohlcv_ccxt(timeframe='2h', limit=200):
    """
    Fetch OHLCV for the symbol using ccxt. Returns DataFrame indexed by timestamp (datetime UTC).
    """
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    except Exception as e:
        print("fetch_ohlcv error:", e)
        return pd.DataFrame(columns=['timestamp','open','high','low','close','volume']).set_index('timestamp')
    df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    df.set_index('timestamp', inplace=True)
    return df

def try_enter_from_2h_breakout(df_2h, df_30m, t_trigger_pct, t_fee):
    """
    Scan df_2h for the latest completed candle and decide whether to open a trade
    using the same logic as in your backtest:
      - compute change_up / change_down vs historical lowest/highest (excluding current)
      - if breakout signal, scan 30m window (previous 2h candle -> current 2h candle) for pullback entry
    Returns list of newly created trade dicts (not yet appended to open_trades).
    """
    new_trades = []
    # need at least two 2h candles: previous (for window start) and current
    if len(df_2h) < 2:
        return new_trades

    # Use latest 2h close as "current" analogous to backtest loop index i
    current_idx = df_2h.index[-1]
    current_price_2h = float(df_2h['close'].iloc[-1])

    # historical low/high excluding current candle ([: -1] slice)
    lowest_2h = float(df_2h['low'][:-1].min())
    highest_2h = float(df_2h['high'][:-1].max())

    change_up = (current_price_2h - lowest_2h) / lowest_2h * 100 if lowest_2h > 0 else 0
    change_down = (current_price_2h - highest_2h) / highest_2h * 100 if highest_2h > 0 else 0

    signal = None
    if change_up >= t_trigger_pct:
        signal = 'long'
    elif change_down <= -t_trigger_pct:
        signal = 'short'

    if not signal:
        return new_trades

    # window for 30m candles is between previous 2h candle and current 2h candle
    start_time = df_2h.index[-2]
    end_time = df_2h.index[-1]
    df30_window = df_30m[(df_30m.index > start_time) & (df_30m.index <= end_time)]
    if df30_window.empty:
        return new_trades

    # find the first 30m candle that meets pullback requirement (same condition as backtest)
    for ts, row in df30_window.iterrows():
        price_30m = float(row['close'])
        if signal == 'long' and price_30m <= current_price_2h:
            # entry price adjusted by fee like in backtest
            entry_price = price_30m * (1 + t_fee)
            qty = order_size_usdt / entry_price
            trade = {
                'side': 'long',
                'entry_price': entry_price,
                'entry_time': ts.to_pydatetime(),
                'amount': qty,
                'order_size': order_size_usdt,
                'status': 'open'
            }
            new_trades.append(trade)
            break
        elif signal == 'short' and price_30m >= current_price_2h:
            entry_price = price_30m * (1 - t_fee)
            qty = order_size_usdt / entry_price
            trade = {
                'side': 'short',
                'entry_price': entry_price,
                'entry_time': ts.to_pydatetime(),
                'amount': qty,
                'order_size': order_size_usdt,
                'status': 'open'
            }
            new_trades.append(trade)
            break

    return new_trades

def evaluate_and_close_trades(df_2h, t_fee, t_tp, t_sl):
    """
    Evaluate open trades vs current 2h close (matching backtest evaluation),
    close trades hitting TP/SL and update capital.
    """
    global open_trades, closed_trades, capital

    if len(df_2h) == 0:
        return

    current_price_2h = float(df_2h['close'].iloc[-1])

    to_close = []
    for t in open_trades:
        # PnL percent relative to entry_price
        if t['side'] == 'long':
            pnl_pct = (current_price_2h - t['entry_price']) / t['entry_price'] * 100
        else:
            pnl_pct = (t['entry_price'] - current_price_2h) / t['entry_price'] * 100

        reason = None
        if pnl_pct >= t_tp:
            reason = 'TP'
        elif pnl_pct <= -t_sl:
            reason = 'SL'

        if reason:
            # exit price adjusted by fee like backtest
            exit_price = current_price_2h * (1 - t_fee if t['side']=='long' else 1 + t_fee)
            # pnl in USDT
            if t['side'] == 'long':
                pnl_usdt = (exit_price - t['entry_price']) * t['order_size'] / t['entry_price']
            else:
                pnl_usdt = (t['entry_price'] - exit_price) * t['order_size'] / t['entry_price']

            # record
            t_closed = dict(t)
            t_closed.update({
                'exit_price': exit_price,
                'exit_time': df_2h.index[-1].to_pydatetime(),
                'close_reason': reason,
                'pnl_usdt': pnl_usdt
            })
            closed_trades.append(t_closed)
            # adjust capital
            capital += pnl_usdt
            to_close.append(t)

    # remove closed trades from open_trades
    for t in to_close:
        open_trades.remove(t)

# -------------------------
# === MAIN PAPER-TRADING LOOP ===
# -------------------------
def run_live_paper_bot():
    global open_trades, closed_trades, price_history, capital, last_status_update

    print("Starting live paper bot loop (using Binance public data) — strategy = backtest exact")
    while True:
        try:
            # fetch recent candles
            df_2h = fetch_ohlcv_ccxt('2h', limit=fetch_limit_2h)
            df_30m = fetch_ohlcv_ccxt('30m', limit=fetch_limit_30m)

            # update price history (use latest spot close from 30m or ticker)
            # also fetch live ticker for more granular price if preferred
            try:
                ticker = exchange.fetch_ticker(symbol)
                latest_price = float(ticker['last'])
                ts_ms = int(time.time()*1000)
            except Exception:
                # fallback if ticker fails
                if not df_30m.empty:
                    latest_price = float(df_30m['close'].iloc[-1])
                    ts_ms = int(df_30m.index[-1].timestamp()*1000)
                else:
                    time.sleep(loop_sleep)
                    continue

            price_history.append([ts_ms, latest_price])
            # cap history length
            if len(price_history) > 1000:
                price_history = price_history[-1000:]

            # 1) Check for new entries from 2h breakout -> 30m pullback (strategy EXACT)
            new_candidates = try_enter_from_2h_breakout(df_2h, df_30m, trigger_pct, fee_pct)

            # apply pyramiding limits: allow multiple opens but limited per side
            for c in new_candidates:
                side = c['side']
                open_side_count = sum(1 for t in open_trades if t['side']==side)
                if open_side_count < max_open_per_side:
                    open_trades.append(c)
                    print(f"[{datetime.now(timezone.utc).isoformat()}] OPEN {c['side'].upper()} entry {c['entry_price']:.2f} qty {c['amount']:.6f}")
                else:
                    print(f"Pyramiding limit reached for {side}, skipping entry.")

            # 2) Evaluate and close trades using current 2h close (matching backtest)
            evaluate_and_close_trades(df_2h, fee_pct, profit_target, stop_loss)

            # log periodic status
            now = datetime.now(timezone.utc)
            if (now - last_status_update).total_seconds() >= 15*60:
                print(f"[STATUS {now.isoformat()}] Capital: {capital:.2f} | Open trades: {len(open_trades)} | Closed trades: {len(closed_trades)}")
                last_status_update = now

            time.sleep(loop_sleep)

        except Exception as e:
            print("ERROR in main loop:", e)
            time.sleep(5)

# -------------------------
# === START BOT + DASHBOARD ===
# -------------------------
if __name__ == '__main__':
    # start bot loop in background thread
    thread = threading.Thread(target=run_live_paper_bot, daemon=True)
    thread.start()

    # start flask app (bind to 0.0.0.0 for Render)
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
