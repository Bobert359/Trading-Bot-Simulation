# paper_bot_live_full.py
# Paper-Trading Bot + Dashboard (Dark Mode, Live Chart, EMA, RSI, Entries/Exits, SSE realtime)
#
# Usage: python paper_bot_live_full.py
# Requirements: pip install ccxt flask pandas numpy requests

import os
import time
import threading
import json
from datetime import datetime, timezone
from io import StringIO

import ccxt
import pandas as pd
import numpy as np
import requests
from flask import Flask, jsonify, render_template_string, Response, request, send_file

# -------------------------
# === USER CONFIG ===
# -------------------------
# Telegram (put your token & chat id here)
TELEGRAM_TOKEN = ""   # <-- set your telegram bot token or leave empty to disable telegram
TELEGRAM_CHAT_ID = "" # <-- set chat id

def send_telegram_message(text: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': text, 'parse_mode': 'Markdown'}
        requests.post(url, data=payload, timeout=5)
    except Exception as e:
        print("Telegram send error:", e)

# Trading config (paper trading)
order_size_usdt = 10.0         # fixed per-trade size (paper trading)
start_capital = 100.0          # starting capital
fee_pct = 0.0004               # 0.04% per trade (as in your backtest)
trigger_pct = 1.5              # breakout threshold (%) 
profit_target = 10.0           # TP (%) from entry (in percent)
stop_loss = 3.0                # SL (%) from entry
max_open_per_side = 12         # pyramiding limit per side
symbol = "BTC/USDT"            # market symbol used
fetch_limit_2h = 200
fetch_limit_30m = 400
loop_sleep = 60                # main loop sleep (seconds)
chart_history_points = 300

# EMAs / RSI config
ema_short = 50
ema_long = 200
rsi_period = 14

# -------------------------
# === GLOBAL STATE ===
# -------------------------
capital = start_capital
open_trades = []
closed_trades = []
price_history = []   # list of [ts_ms, price]
capital_history = [] # list of [ts_ms, capital]
last_status_update = datetime.now(timezone.utc)

# -------------------------
# === EXCHANGE SETUP ===
# -------------------------
exchange = ccxt.binance({'enableRateLimit': True})
# ensure symbol normalized
ccxt_symbol = symbol

# -------------------------
# === FLASK APP + DASH HTML ===
# -------------------------
app = Flask(__name__, static_folder=None)

DASH_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Paper Bot Dashboard — Dark</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    :root {
      --bg: #0b1220;
      --panel: #0f1724;
      --muted: #9aa6b2;
      --accent: #19a37b;
      --danger: #f05252;
      --text: #e6eef6;
    }
    body { background:var(--bg); color:var(--text); font-family: Inter, Arial; margin:16px; }
    .layout { display:grid; grid-template-columns: 360px 1fr 360px; gap: 16px; }
    .panel { background:var(--panel); padding:12px; border-radius:8px; box-shadow: 0 6px 18px rgba(0,0,0,0.6); }
    h1 { margin:0 0 8px 0; font-size:18px; }
    .muted { color:var(--muted); font-size:13px; }
    .kpi { display:flex; gap:8px; align-items:center; justify-content:space-between; }
    .small { font-size:13px; color:var(--muted); }
    table { width:100%; border-collapse: collapse; margin-top:8px; font-size:13px; }
    th, td { padding:6px; border-bottom: 1px solid rgba(255,255,255,0.03); text-align:left; color:var(--text); }
    .progress { height:10px; background:rgba(255,255,255,0.03); border-radius:6px; overflow:hidden; }
    .prog-fill { height:100%; background: linear-gradient(90deg, #19a37b, #4ad9b2); }
    .prog-fill.loss { background: linear-gradient(90deg, #f05252, #f79a9a); }
    .marker { font-size:12px; padding:4px 8px; border-radius:6px; background:rgba(255,255,255,0.03); display:inline-block; }
    .btn { background:transparent; border:1px solid rgba(255,255,255,0.06); padding:6px 8px; border-radius:6px; color:var(--text); cursor:pointer; }
    .top-row { display:flex; gap:12px; align-items:center; justify-content:space-between; margin-bottom:8px; }
    .chart-wrap { grid-column: 2 / 3; }
  </style>
</head>
<body>
  <div class="top-row">
    <h1>📊 Paper-Trading Bot — 2h Breakout + 30m Pullback (Dark)</h1>
    <div>
      <span class="small">Live Price: </span>
      <strong id="live_price">...</strong>
      <span class="small"> USDT</span>
    </div>
  </div>

  <div class="layout">
    <div class="panel">
      <h3>Kapital</h3>
      <p class="muted">Startkapital: <strong>{{start_capital}} USDT</strong></p>
      <p style="font-size:20px"><strong id="live_capital">...</strong> USDT</p>
      <p class="small">Order size: {{order_size_usdt}} USDT &nbsp; Fee: {{fee_pct*100}}%</p>
      <div style="margin-top:8px;">
        <h4 style="margin:6px 0;">Open Trades</h4>
        <div id="open_trades_panel">Loading...</div>
      </div>
      <div style="margin-top:10px;">
        <h4 style="margin:6px 0;">Recent Activity</h4>
        <div id="activity">Loading...</div>
      </div>
      <div style="margin-top:10px;">
        <button class="btn" onclick="downloadCSV()">Export Trade History CSV</button>
      </div>
    </div>

    <div class="panel chart-wrap">
      <canvas id="priceChart" height="220"></canvas>
      <div style="display:flex; gap:16px; margin-top:8px;">
        <canvas id="rsiChart" height="80" style="flex:1"></canvas>
        <canvas id="equityChart" height="80" style="width:240px"></canvas>
      </div>
      <div class="muted" style="margin-top:8px">Markers: entry=open, exit=closed. TP/SL lines shown on chart.</div>
    </div>

    <div class="panel">
      <h4>Stats</h4>
      <p id="stats">Loading...</p>
      <h4 style="margin-top:10px">Trade History</h4>
      <div style="max-height:320px; overflow:auto;">
        <table id="hist_table">
          <thead><tr><th>Side</th><th>Entry</th><th>Exit</th><th>PnL (USDT)</th></tr></thead>
          <tbody id="hist_rows"></tbody>
        </table>
      </div>
    </div>
  </div>

<script>
let priceChart, rsiChart, equityChart;

async function fetchState(){
  const res = await fetch('/api/state');
  return await res.json();
}

function formatDate(ts){
  return new Date(ts).toLocaleString();
}

function buildOpenTradesHTML(open_trades, latest_price){
  if(open_trades.length===0) return '<p class="small">Keine offenen Trades</p>';
  let html = '<table><thead><tr><th>Side</th><th>Entry</th><th>Qty</th><th>Size</th><th>OpenPnL</th><th>Progress</th></tr></thead><tbody>';
  for(const t of open_trades){
    const pnl = t.unrealized_pnl.toFixed(2);
    const pct = ((t.side==='long') ? ((latest_price - t.entry_price)/t.entry_price*100) : ((t.entry_price - latest_price)/t.entry_price*100));
    // progress: map from -SL..TP to 0..100
    const totalRange = (t.order_size>0) ? (Math.abs(pct) / ( (pct>0) ? {{profit_target}} : {{stop_loss}} )) : 0;
    // compute progress in JS below as we don't have server-side template for dynamic numbers
    html += `<tr>
      <td>${t.side.toUpperCase()}</td>
      <td>${t.entry_price.toFixed(2)}</td>
      <td>${t.amount.toFixed(6)}</td>
      <td>${t.order_size.toFixed(2)}</td>
      <td>${pnl}</td>
      <td><div class="progress"><div class="prog-fill" style="width:${Math.min(100, Math.max(0, ( ( (t.side==='long') ? ( (latest_price - t.entry_price)/t.entry_price*100 ) : ((t.entry_price - latest_price)/t.entry_price*100) ) + {{stop_loss}} ) / ({{profit_target}} + {{stop_loss}}) *100 ))}%"></div></div></td>
    </tr>`;
  }
  html += '</tbody></table>';
  return html;
}

async function updateUI(){
  const s = await fetchState();
  document.getElementById('live_price').textContent = s.latest_price.toFixed(2);
  document.getElementById('live_capital').textContent = s.capital.toFixed(2);

  // open trades
  document.getElementById('open_trades_panel').innerHTML = buildOpenTradesHTML(s.open_trades, s.latest_price);

  // recent activity
  let act = '';
  for(const a of s.activity.slice(0,8)) act += `<div class="small">${a}</div>`;
  document.getElementById('activity').innerHTML = act || '<div class="small">No activity</div>';

  // stats
  document.getElementById('stats').innerHTML = `Closed: ${s.closed_count} | Winrate: ${s.win_rate.toFixed(2)}% | Max DD: ${s.max_dd.toFixed(2)}%`;

  // history table
  const rows = document.getElementById('hist_rows');
  rows.innerHTML = '';
  for(const h of s.history.slice(0,200).reverse()){
    const exit = h.exit_time ? new Date(h.exit_time).toLocaleString() : '-';
    rows.insertAdjacentHTML('beforeend', `<tr><td>${h.side}</td><td>${new Date(h.entry_time).toLocaleString()}</td><td>${exit}</td><td>${(h.pnl_usdt||0).toFixed(2)}</td></tr>`);
  }

  // Chart data
  const chart = s.chart;
  const labels = chart.map(p=> new Date(p[0]).toLocaleTimeString());
  const prices = chart.map(p=> p[1]);
  const ema_short = s.ema_short || [];
  const ema_long = s.ema_long || [];
  const rsi = s.rsi || [];
  const markers = s.markers || [];

  if(!priceChart){
    const ctx = document.getElementById('priceChart').getContext('2d');
    priceChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          { label:'Price', data: prices, borderColor:'#4fc3f7', tension:0.12, pointRadius:0, borderWidth:1.5 },
          { label:'EMA'+{{ema_short}}, data: ema_short, borderColor:'#f39c12', tension:0.12, pointRadius:0, borderWidth:1 },
          { label:'EMA'+{{ema_long}}, data: ema_long, borderColor:'#9b59b6', tension:0.12, pointRadius:0, borderWidth:1 }
        ]
      },
      options: {
        plugins: { legend:{display:true} },
        scales: { x:{ display:true }, y:{ display:true } }
      }
    });
  } else {
    priceChart.data.labels = labels;
    priceChart.data.datasets[0].data = prices;
    priceChart.data.datasets[1].data = ema_short;
    priceChart.data.datasets[2].data = ema_long;
    priceChart.update();
  }

  // RSI chart
  if(!rsiChart){
    const ctx2 = document.getElementById('rsiChart').getContext('2d');
    rsiChart = new Chart(ctx2, {
      type:'line',
      data:{ labels: labels, datasets:[{ label:'RSI', data: rsi, borderColor:'#7bed9f', pointRadius:0, borderWidth:1 }] },
      options:{ plugins:{legend:{display:false}}, scales:{ y:{min:0, max:100} } }
    });
  } else {
    rsiChart.data.labels = labels;
    rsiChart.data.datasets[0].data = rsi;
    rsiChart.update();
  }

  // Equity (capital history)
  const eq = s.capital_history.map(p=> p[1]);
  const eqLabels = s.capital_history.map(p=> new Date(p[0]).toLocaleTimeString());
  if(!equityChart){
    const ctx3 = document.getElementById('equityChart').getContext('2d');
    equityChart = new Chart(ctx3, {
      type:'line',
      data:{ labels:eqLabels, datasets:[{ label:'Equity', data:eq, borderColor:'#19a37b', pointRadius:0, borderWidth:1 }] },
      options:{ plugins:{legend:{display:false}} }
    });
  } else {
    equityChart.data.labels = eqLabels;
    equityChart.data.datasets[0].data = eq;
    equityChart.update();
  }
}

async function downloadCSV(){
  window.location = '/export/history.csv';
}

// Realtime via SSE - also triggers UI update
const es = new EventSource('/stream');
es.onmessage = function(e){
  // parsed state update (we ignore payload content and just request /api/state to refresh)
  updateUI();
};

updateUI();
setInterval(updateUI, 15000); // fallback polling
</script>
</body>
</html>
"""

# -------------------------
# === FLASK ROUTES ===
# -------------------------
@app.route('/')
def home():
    return render_template_string(DASH_HTML,
                                  start_capital=start_capital,
                                  order_size_usdt=order_size_usdt,
                                  fee_pct=fee_pct,
                                  ema_short=ema_short,
                                  ema_long=ema_long,
                                  profit_target=profit_target,
                                  stop_loss=stop_loss)

@app.route('/api/state')
def api_state():
    # prepare open trades with unrealized pnl using latest price
    global price_history, capital_history
    latest_price = price_history[-1][1] if price_history else None

    ot = []
    for t in open_trades:
        if latest_price is None:
            unreal = 0.0
        else:
            unreal = (latest_price - t['entry_price']) * t['amount'] if t['side']=='long' else (t['entry_price'] - latest_price) * t['amount']
        copyt = dict(t)
        copyt['unrealized_pnl'] = unreal
        ot.append(copyt)

    # stats
    closed_count = len(closed_trades)
    wins = sum(1 for x in closed_trades if x.get('pnl_usdt',0) > 0)
    win_rate = (wins/closed_count*100) if closed_count>0 else 0.0

    # build chart payload: last N price points
    chart_data = price_history[-chart_history_points:]
    # compute EMA & RSI arrays server-side for last chart_history_points
    prices = pd.Series([p[1] for p in chart_data])
    ema_s = list(prices.ewm(span=ema_short, adjust=False).mean()) if len(prices)>0 else []
    ema_l = list(prices.ewm(span=ema_long, adjust=False).mean()) if len(prices)>0 else []
    # RSI
    def compute_rsi(series, period):
        if len(series) < period+1:
            return [None]*len(series)
        delta = series.diff()
        up = delta.clip(lower=0)
        down = -1*delta.clip(upper=0)
        ma_up = up.rolling(period).mean()
        ma_down = down.rolling(period).mean()
        rs = ma_up / ma_down
        rsi = 100 - (100 / (1+rs))
        return rsi.fillna(50).tolist()
    rsi_vals = compute_rsi(pd.Series([p[1] for p in chart_data]), rsi_period)

    # markers
    markers = []
    for t in closed_trades:
        if t.get('entry_time'):
            markers.append({'ts': int(t['entry_time'].timestamp()*1000), 'price': t['entry_price'], 'label':'entry', 'side':t['side']})
        if t.get('exit_time'):
            markers.append({'ts': int(t['exit_time'].timestamp()*1000), 'price': t['exit_price'], 'label':'exit', 'side':t['side']})
    for t in open_trades:
        markers.append({'ts': int(t['entry_time'].timestamp()*1000), 'price': t['entry_price'], 'label':'open', 'side':t['side']})

    # capital history
    ch = capital_history[-chart_history_points:] if capital_history else []

    return jsonify({
        'capital': capital,
        'open_trades': ot,
        'closed_count': closed_count,
        'win_rate': win_rate,
        'max_dd': 0.0,
        'chart': chart_data,
        'ema_short': [None if x is None else float(x) for x in ema_s],
        'ema_long': [None if x is None else float(x) for x in ema_l],
        'rsi': [None if x is None else float(x) for x in rsi_vals],
        'markers': markers,
        'latest_price': price_history[-1][1] if price_history else None,
        'history': closed_trades,
        'activity': [ f"{(t.get('side',''))} {t.get('entry_price',0):.2f} -> {t.get('close_reason','')}" for t in closed_trades[-20:] ],
        'capital_history': ch
    })

@app.route('/export/history.csv')
def export_history():
    si = StringIO()
    df = pd.DataFrame(closed_trades)
    if df.empty:
        si.write("No trades\n")
    else:
        # ensure datetimes serializable
        df2 = df.copy()
        if 'entry_time' in df2.columns:
            df2['entry_time'] = df2['entry_time'].astype(str)
        if 'exit_time' in df2.columns:
            df2['exit_time'] = df2['exit_time'].astype(str)
        df2.to_csv(si, index=False)
    output = si.getvalue()
    return Response(output, mimetype="text/csv", headers={"Content-disposition":"attachment; filename=trade_history.csv"})

@app.route('/stream')
def stream():
    def event_stream():
        while True:
            # send a small heartbeat with timestamp (frontend will pull /api/state)
            yield f"data: {json.dumps({'ts': int(time.time()*1000)})}\n\n"
            time.sleep(5)
    return Response(event_stream(), mimetype="text/event-stream")

# -------------------------
# === STRATEGY HELPERS ===
# -------------------------
def fetch_ohlcv_ccxt(timeframe='2h', limit=200):
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
    new_trades = []
    if len(df_2h) < 2:
        return new_trades

    current_price_2h = float(df_2h['close'].iloc[-1])
    lowest_2h = float(df_2h['low'][:-1].min())
    highest_2h = float(df_2h['high'][:-1].max())

    change_up = (current_price_2h - lowest_2h) / lowest_2h * 100 if lowest_2h > 0 else 0
    change_down = (current_price_2h - highest_2h) / highest_2h * 100 if highest_2h > 0 else 0

    signal = None
    if change_up >= t_trigger_pct:
        signal = 'long'
    elif change_down <= -t_trigger_pct:
        signal = 'short'
    if not signal: return new_trades

    start_time = df_2h.index[-2]
    end_time = df_2h.index[-1]
    df30_window = df_30m[(df_30m.index > start_time) & (df_30m.index <= end_time)]
    if df30_window.empty: return new_trades

    for ts, row in df30_window.iterrows():
        price_30m = float(row['close'])
        # check capital sufficiency and order size will be enforced by caller
        if signal == 'long' and price_30m <= current_price_2h:
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
    global open_trades, closed_trades, capital, capital_history
    if len(df_2h) == 0:
        return
    current_price_2h = float(df_2h['close'].iloc[-1])
    to_close = []
    for t in list(open_trades):
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
            exit_price = current_price_2h * (1 - t_fee if t['side']=='long' else 1 + t_fee)
            if t['side']=='long':
                pnl_usdt = (exit_price - t['entry_price']) * t['order_size'] / t['entry_price']
            else:
                pnl_usdt = (t['entry_price'] - exit_price) * t['order_size'] / t['entry_price']
            t_closed = dict(t)
            t_closed.update({'exit_price': exit_price, 'exit_time': df_2h.index[-1].to_pydatetime(), 'close_reason': reason, 'pnl_usdt': pnl_usdt})
            closed_trades.append(t_closed)
            capital += pnl_usdt
            capital_history.append([int(time.time()*1000), capital])
            to_close.append(t)
            # notify telegram
            send_telegram_message(f"Exit {t['side'].upper()} {reason} | Entry: {t['entry_price']:.2f} Exit: {exit_price:.2f} PnL: {pnl_usdt:.2f} USDT")
    for t in to_close:
        if t in open_trades:
            open_trades.remove(t)

# -------------------------
# === MAIN PAPER-TRADING LOOP ===
# -------------------------
def run_live_paper_bot():
    global open_trades, closed_trades, price_history, capital, capital_history, last_status_update

    print("Starting live paper bot loop (Binance public data) — strategy exact")
    send_telegram_message("Paper bot started (paper mode) — strategy active.") if TELEGRAM_TOKEN else None

    while True:
        try:
            df_2h = fetch_ohlcv_ccxt('2h', limit=fetch_limit_2h)
            df_30m = fetch_ohlcv_ccxt('30m', limit=fetch_limit_30m)

            # get latest price from ticker (more granular)
            try:
                ticker = exchange.fetch_ticker(symbol)
                latest_price = float(ticker['last'])
                ts_ms = int(time.time()*1000)
            except Exception:
                if not df_30m.empty:
                    latest_price = float(df_30m['close'].iloc[-1])
                    ts_ms = int(df_30m.index[-1].timestamp()*1000)
                else:
                    time.sleep(loop_sleep); continue

            price_history.append([ts_ms, latest_price])
            if len(price_history) > 2000:
                price_history = price_history[-2000:]

            # 1) entries
            new_candidates = try_enter_from_2h_breakout(df_2h, df_30m, trigger_pct, fee_pct)
            for c in new_candidates:
                # check capital sufficiency
                if capital < order_size_usdt - 1e-9:
                    print("Insufficient capital for order_size_usdt, skipping entry.")
                    continue
                side = c['side']
                open_side_count = sum(1 for t in open_trades if t['side']==side)
                if open_side_count < max_open_per_side:
                    # open trade (paper)
                    open_trades.append(c)
                    send_telegram_message(f"OPEN {c['side'].upper()} Entry: {c['entry_price']:.2f} | Size: {c['order_size']:.2f} USDT")
                    # capital remains until close (we don't deduct margin here; paper logic)
                else:
                    print(f"Pyramiding limit reached for {side}, skip.")

            # 2) evaluate and close
            evaluate_and_close_trades(df_2h, fee_pct, profit_target, stop_loss)

            # periodic status
            now = datetime.now(timezone.utc)
            if (now - last_status_update).total_seconds() >= 15*60:
                print(f"[STATUS {now.isoformat()}] Capital: {capital:.2f} | Open trades: {len(open_trades)} | Closed trades: {len(closed_trades)}")
                last_status_update = now

            time.sleep(loop_sleep)
        except Exception as e:
            print("ERROR main loop:", e)
            time.sleep(5)

# -------------------------
# === START THREAD + APP ===
# -------------------------
if __name__ == '__main__':
    # ensure initial capital history
    capital_history.append([int(time.time()*1000), capital])

    t = threading.Thread(target=run_live_paper_bot, daemon=True)
    t.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)
