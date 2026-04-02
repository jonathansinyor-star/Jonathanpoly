# ============================================================

# POLYMARKET BTC BOT + WEB DASHBOARD

# Strategy: Bet $2 when odds are $0.05-$0.15 with >80s left

# Dashboard: visit your Railway URL to see live status

# ============================================================

import os
import time
import json
import threading
import requests
from datetime import datetime, timezone
from flask import Flask, jsonify
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs, OrderType

# ============================================================

# CONFIG

# ============================================================

PRIVATE_KEY = os.environ.get(“POLYMARKET_PRIVATE_KEY”)
ADDRESS     = os.environ.get(“POLYMARKET_ADDRESS”)
PORT        = int(os.environ.get(“PORT”, 8080))

BET_SIZE       = 2.00
ODDS_MIN       = 0.05   # minimum odds to trigger bet
ODDS_MAX       = 0.15   # maximum odds to trigger bet
MIN_TIME_LEFT  = 80
POLL_INTERVAL  = 10

HOST      = “https://clob.polymarket.com”
CHAIN_ID  = 137
GAMMA_URL = “https://gamma-api.polymarket.com”

INTERVALS = {
“BTC-5M”:  5   * 60,
“BTC-15M”: 15  * 60,
“BTC-4H”:  240 * 60,
}

SLUG_PREFIX = {
“BTC-5M”:  “btc-updown-5m”,
“BTC-15M”: “btc-updown-15m”,
“BTC-4H”:  “btc-updown-4h”,
}

# ============================================================

# SHARED STATE (for dashboard)

# ============================================================

state = {
“status”:    “starting”,
“started”:   datetime.now().strftime(”%Y-%m-%d %H:%M:%S”),
“bets_placed”: 0,
“total_wagered”: 0.0,
“markets”: {},
“log”: [],
}

def log(msg, kind=“info”):
ts = datetime.now().strftime(”%H:%M:%S”)
print(f”[{ts}] {msg}”, flush=True)
entry = {“time”: ts, “msg”: msg, “kind”: kind}
state[“log”].insert(0, entry)
state[“log”] = state[“log”][:100]  # keep last 100 entries

# ============================================================

# FLASK DASHBOARD

# ============================================================

app = Flask(**name**)

DASHBOARD_HTML = “””<!DOCTYPE html>

<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="10">
<title>PolyBot Dashboard</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:#0a0f1a; color:#c8d8e8; font-family:monospace; padding:16px; }
  h1 { color:#00ffb0; font-size:1.3rem; letter-spacing:3px; margin-bottom:4px; }
  .sub { color:#445566; font-size:0.7rem; margin-bottom:20px; }
  .pill { display:inline-block; padding:3px 12px; border-radius:20px; font-size:0.7rem; letter-spacing:2px; margin-bottom:20px; }
  .running { background:#00ffb020; border:1px solid #00ffb060; color:#00ffb0; }
  .starting { background:#ffcc0020; border:1px solid #ffcc0060; color:#ffcc00; }
  .stats { display:flex; gap:10px; margin-bottom:20px; flex-wrap:wrap; }
  .stat { background:#0d1520; border:1px solid #1a2840; border-radius:6px; padding:10px 16px; flex:1; min-width:100px; }
  .stat-label { font-size:0.6rem; color:#445566; letter-spacing:2px; margin-bottom:4px; }
  .stat-val { font-size:1.2rem; color:#00ffb0; }
  .markets { margin-bottom:20px; }
  .market { background:#0d1520; border:1px solid #1a2840; border-radius:6px; padding:12px; margin-bottom:10px; }
  .market-header { display:flex; justify-content:space-between; margin-bottom:8px; }
  .market-name { color:#7799bb; font-size:0.8rem; letter-spacing:2px; }
  .market-time { font-size:0.9rem; }
  .safe { color:#00ffb0; } .warn { color:#ffcc00; } .danger { color:#ff4444; }
  .odds-row { display:flex; gap:8px; }
  .odds-box { flex:1; background:#080c10; border:1px solid #1a2840; border-radius:4px; padding:6px; text-align:center; }
  .odds-label { font-size:0.6rem; color:#445566; }
  .odds-val { font-size:1rem; }
  .hot { color:#ff6b35; font-weight:bold; }
  .normal { color:#cce0ff; }
  .section-title { font-size:0.65rem; color:#445566; letter-spacing:3px; margin-bottom:8px; }
  .log-box { background:#080c10; border:1px solid #1a2840; border-radius:4px; padding:10px; max-height:300px; overflow-y:auto; }
  .log-entry { display:flex; gap:8px; font-size:0.7rem; line-height:1.8; border-bottom:1px solid #0d1520; }
  .log-time { color:#334455; min-width:55px; }
  .info { color:#5588aa; } .bet { color:#00ffb0; } .warn-msg { color:#ffcc00; } .skip { color:#334455; }
  .refresh { color:#334455; font-size:0.6rem; margin-top:12px; text-align:center; }
</style>
</head>
<body>
<h1>POLY<span style="color:#ff6b35">BOT</span></h1>
<div class="sub">BTC SHORT-TERM MARKETS // AUTO-REFRESHES EVERY 10s</div>
<div id="status-pill" class="pill starting">LOADING...</div>

<div class="stats">
  <div class="stat"><div class="stat-label">BETS PLACED</div><div class="stat-val" id="bets">-</div></div>
  <div class="stat"><div class="stat-label">WAGERED</div><div class="stat-val" id="wagered">-</div></div>
  <div class="stat"><div class="stat-label">STRATEGY</div><div class="stat-val" style="font-size:0.8rem;color:#7799bb" id="strategy">-</div></div>
  <div class="stat"><div class="stat-label">STARTED</div><div class="stat-val" style="font-size:0.75rem;color:#7799bb" id="started">-</div></div>
</div>

<div class="section-title">// MARKETS</div>
<div class="markets" id="markets"></div>

<div class="section-title">// ACTIVITY LOG</div>
<div class="log-box" id="log"></div>
<div class="refresh">Auto-refreshing every 10 seconds</div>

<script>
async function refresh() {
  try {
    const r = await fetch('/api/state');
    const d = await r.json();

    document.getElementById('status-pill').textContent = d.status.toUpperCase();
    document.getElementById('status-pill').className = 'pill ' + d.status;
    document.getElementById('bets').textContent = d.bets_placed;
    document.getElementById('wagered').textContent = '$' + d.total_wagered.toFixed(2);
    document.getElementById('strategy').textContent = '$' + d.odds_min + '-$' + d.odds_max;
    document.getElementById('started').textContent = d.started;

    let mHtml = '';
    for (const [name, m] of Object.entries(d.markets)) {
      const tc = m.time_left > 120 ? 'safe' : m.time_left > 80 ? 'warn' : 'danger';
      const mins = Math.floor(m.time_left / 60);
      const secs = m.time_left % 60;
      const yesHot = m.yes_ask <= d.odds_max && m.yes_ask >= d.odds_min;
      const noHot  = m.no_ask  <= d.odds_max && m.no_ask  >= d.odds_min;
      mHtml += `<div class="market">
        <div class="market-header">
          <div class="market-name">${name}</div>
          <div class="market-time ${tc}">${String(mins).padStart(2,'0')}:${String(secs).padStart(2,'0')}</div>
        </div>
        <div class="odds-row">
          <div class="odds-box">
            <div class="odds-label">YES</div>
            <div class="odds-val ${yesHot?'hot':'normal'}">${m.yes_ask != null ? '$'+m.yes_ask.toFixed(3) : 'N/A'}</div>
          </div>
          <div class="odds-box">
            <div class="odds-label">NO</div>
            <div class="odds-val ${noHot?'hot':'normal'}">${m.no_ask != null ? '$'+m.no_ask.toFixed(3) : 'N/A'}</div>
          </div>
        </div>
      </div>`;
    }
    document.getElementById('markets').innerHTML = mHtml;

    let lHtml = '';
    for (const e of d.log) {
      const cls = e.kind === 'bet' ? 'bet' : e.kind === 'warn' ? 'warn-msg' : e.kind === 'skip' ? 'skip' : 'info';
      lHtml += `<div class="log-entry"><span class="log-time">${e.time}</span><span class="${cls}">${e.msg}</span></div>`;
    }
    document.getElementById('log').innerHTML = lHtml;
  } catch(e) { console.error(e); }
}
refresh();
</script>

</body>
</html>"""

@app.route(”/”)
def dashboard():
return DASHBOARD_HTML

@app.route(”/api/state”)
def api_state():
return jsonify({
**state,
“odds_min”: ODDS_MIN,
“odds_max”: ODDS_MAX,
})

def run_dashboard():
app.run(host=“0.0.0.0”, port=PORT, debug=False, use_reloader=False)

# ============================================================

# HELPERS

# ============================================================

def get_slug_and_end(label):
interval = INTERVALS[label]
now_ts   = int(time.time())
window   = (now_ts // interval) * interval
slug     = f”{SLUG_PREFIX[label]}-{window}”
end_ts   = window + interval
return slug, end_ts

def get_token_ids(slug):
try:
r = requests.get(
f”{GAMMA_URL}/markets”,
params={“slug”: slug, “active”: “true”, “closed”: “false”},
timeout=10
)
if r.status_code != 200:
return None, None
data = r.json()
markets = data if isinstance(data, list) else data.get(“data”, [])
if not markets:
return None, None
market = markets[0]
raw = market.get(“clobTokenIds”, “[]”)
token_ids = json.loads(raw) if isinstance(raw, str) else raw
if len(token_ids) < 2:
return None, None
return token_ids[0], token_ids[1]
except Exception as e:
log(f”Exception getting tokens: {e}”, “warn”)
return None, None

def get_best_ask(token_id):
try:
r = requests.get(f”{HOST}/book”, params={“token_id”: token_id}, timeout=10)
if r.status_code != 200:
return None
asks = r.json().get(“asks”, [])
if not asks:
return None
return round(min(float(a[“price”]) for a in asks), 4)
except:
return None

def place_bet(client, token_id, amount):
try:
order_args = MarketOrderArgs(token_id=token_id, amount=amount)
signed = client.create_market_order(order_args)
resp = client.post_order(signed, OrderType.FOK)
log(f”✅ BET PLACED: {resp}”, “bet”)
return True
except Exception as e:
log(f”❌ Bet failed: {e}”, “warn”)
return False

# ============================================================

# BOT LOOP

# ============================================================

def run_bot():
log(“Bot starting up…”, “info”)
state[“status”] = “starting”

```
if not PRIVATE_KEY or not ADDRESS:
    log("❌ Missing env vars: POLYMARKET_PRIVATE_KEY or POLYMARKET_ADDRESS", "warn")
    state["status"] = "error"
    return

try:
    client = ClobClient(HOST, key=PRIVATE_KEY, chain_id=CHAIN_ID, signature_type=1, funder=ADDRESS)
    client.set_api_creds(client.create_or_derive_api_creds())
    log("✅ Connected to Polymarket CLOB", "info")
    state["status"] = "running"
except Exception as e:
    log(f"❌ CLOB init failed: {e}", "warn")
    state["status"] = "error"
    return

bets_placed = {}
token_cache = {}

while True:
    now_ts = int(time.time())

    for label in INTERVALS:
        slug, end_ts = get_slug_and_end(label)
        time_left    = end_ts - now_ts
        mins         = int(time_left // 60)
        secs         = int(time_left % 60)

        # Update market state for dashboard
        if label not in state["markets"]:
            state["markets"][label] = {}
        state["markets"][label]["time_left"] = time_left
        state["markets"][label]["slug"] = slug

        if time_left <= MIN_TIME_LEFT:
            log(f"{label}: ⏱ skip — {mins}m {secs}s left", "skip")
            token_cache.pop(slug, None)
            state["markets"][label]["yes_ask"] = None
            state["markets"][label]["no_ask"]  = None
            continue

        if slug not in bets_placed:
            bets_placed = {slug: {"YES": False, "NO": False}}

        if slug not in token_cache:
            yes_id, no_id = get_token_ids(slug)
            if not yes_id:
                log(f"{label}: no market found for {slug}", "warn")
                continue
            token_cache[slug] = (yes_id, no_id)
            log(f"{label}: tokens fetched ✓", "info")

        yes_id, no_id = token_cache[slug]

        yes_ask = get_best_ask(yes_id)
        no_ask  = get_best_ask(no_id)

        state["markets"][label]["yes_ask"] = yes_ask
        state["markets"][label]["no_ask"]  = no_ask

        log(f"{label}: YES ${yes_ask or 'N/A'} | NO ${no_ask or 'N/A'} | {mins}m {secs}s", "info")

        # YES signal
        if yes_ask and ODDS_MIN <= yes_ask <= ODDS_MAX and not bets_placed[slug]["YES"]:
            log(f"🎯 SIGNAL {label} YES @ ${yes_ask} | {mins}m {secs}s left", "bet")
            if place_bet(client, yes_id, BET_SIZE):
                bets_placed[slug]["YES"] = True
                state["bets_placed"]   += 1
                state["total_wagered"] += BET_SIZE

        # NO signal
        if no_ask and ODDS_MIN <= no_ask <= ODDS_MAX and not bets_placed[slug]["NO"]:
            log(f"🎯 SIGNAL {label} NO  @ ${no_ask} | {mins}m {secs}s left", "bet")
            if place_bet(client, no_id, BET_SIZE):
                bets_placed[slug]["NO"] = True
                state["bets_placed"]   += 1
                state["total_wagered"] += BET_SIZE

    time.sleep(POLL_INTERVAL)
```

# ============================================================

# MAIN — run dashboard + bot in parallel

# ============================================================

if **name** == “**main**”:
# Start dashboard in background thread
t = threading.Thread(target=run_dashboard, daemon=True)
t.start()
# Run bot on main thread
run_bot()
