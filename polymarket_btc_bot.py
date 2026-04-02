import os
import time
import json
import threading
import requests
from datetime import datetime, timezone
from flask import Flask, jsonify
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs, OrderType

PRIVATE_KEY = os.environ.get(‘POLYMARKET_PRIVATE_KEY’)
ADDRESS     = os.environ.get(‘POLYMARKET_ADDRESS’)
PORT        = int(os.environ.get(‘PORT’, 8080))

BET_SIZE      = 2.00
ODDS_MIN      = 0.05
ODDS_MAX      = 0.15
MIN_TIME_LEFT = 80
POLL_INTERVAL = 10

HOST      = ‘https://clob.polymarket.com’
CHAIN_ID  = 137
GAMMA_URL = ‘https://gamma-api.polymarket.com’

INTERVALS = {
‘BTC-5M’:  5   * 60,
‘BTC-15M’: 15  * 60,
‘BTC-4H’:  240 * 60,
}

SLUG_PREFIX = {
‘BTC-5M’:  ‘btc-updown-5m’,
‘BTC-15M’: ‘btc-updown-15m’,
‘BTC-4H’:  ‘btc-updown-4h’,
}

state = {
‘status’:        ‘starting’,
‘started’:       datetime.now().strftime(’%Y-%m-%d %H:%M:%S’),
‘bets_placed’:   0,
‘total_wagered’: 0.0,
‘markets’:       {},
‘log’:           [],
}

def log(msg, kind=‘info’):
ts = datetime.now().strftime(’%H:%M:%S’)
print(’[’ + ts + ’] ’ + msg, flush=True)
state[‘log’].insert(0, {‘time’: ts, ‘msg’: msg, ‘kind’: kind})
state[‘log’] = state[‘log’][:100]

app = Flask(**name**)

HTML = ‘’’<!DOCTYPE html>

<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="10">
<title>PolyBot</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0f1a;color:#c8d8e8;font-family:monospace;padding:16px}
h1{color:#00ffb0;font-size:1.3rem;letter-spacing:3px;margin-bottom:4px}
.sub{color:#445566;font-size:0.7rem;margin-bottom:20px}
.pill{display:inline-block;padding:3px 12px;border-radius:20px;font-size:0.7rem;letter-spacing:2px;margin-bottom:20px}
.running{background:#00ffb020;border:1px solid #00ffb060;color:#00ffb0}
.starting{background:#ffcc0020;border:1px solid #ffcc0060;color:#ffcc00}
.error{background:#ff444420;border:1px solid #ff444460;color:#ff4444}
.stats{display:flex;gap:10px;margin-bottom:20px;flex-wrap:wrap}
.stat{background:#0d1520;border:1px solid #1a2840;border-radius:6px;padding:10px 16px;flex:1;min-width:100px}
.stat-label{font-size:0.6rem;color:#445566;letter-spacing:2px;margin-bottom:4px}
.stat-val{font-size:1.2rem;color:#00ffb0}
.market{background:#0d1520;border:1px solid #1a2840;border-radius:6px;padding:12px;margin-bottom:10px}
.mh{display:flex;justify-content:space-between;margin-bottom:8px}
.mn{color:#7799bb;font-size:0.8rem;letter-spacing:2px}
.safe{color:#00ffb0}.warn{color:#ffcc00}.danger{color:#ff4444}
.odds-row{display:flex;gap:8px}
.ob{flex:1;background:#080c10;border:1px solid #1a2840;border-radius:4px;padding:6px;text-align:center}
.ol{font-size:0.6rem;color:#445566}
.ov{font-size:1rem}
.hot{color:#ff6b35;font-weight:bold}.normal{color:#cce0ff}
.sec{font-size:0.65rem;color:#445566;letter-spacing:3px;margin-bottom:8px;margin-top:16px}
.logbox{background:#080c10;border:1px solid #1a2840;border-radius:4px;padding:10px;max-height:300px;overflow-y:auto}
.le{display:flex;gap:8px;font-size:0.7rem;line-height:1.8;border-bottom:1px solid #0d1520}
.lt{color:#334455;min-width:55px}
.info{color:#5588aa}.bet{color:#00ffb0}.wm{color:#ffcc00}.skip{color:#334455}
.ref{color:#334455;font-size:0.6rem;margin-top:12px;text-align:center}
</style>
</head>
<body>
<h1>POLY<span style="color:#ff6b35">BOT</span></h1>
<div class="sub">BTC MARKETS // AUTO-REFRESHES EVERY 10s</div>
<div id="sp" class="pill starting">LOADING...</div>
<div class="stats">
<div class="stat"><div class="stat-label">BETS</div><div class="stat-val" id="bets">-</div></div>
<div class="stat"><div class="stat-label">WAGERED</div><div class="stat-val" id="wag">-</div></div>
<div class="stat"><div class="stat-label">ODDS RANGE</div><div class="stat-val" style="font-size:0.8rem;color:#7799bb" id="strat">-</div></div>
<div class="stat"><div class="stat-label">STARTED</div><div class="stat-val" style="font-size:0.7rem;color:#7799bb" id="st">-</div></div>
</div>
<div class="sec">// MARKETS</div>
<div id="markets"></div>
<div class="sec">// LOG</div>
<div class="logbox" id="log"></div>
<div class="ref">Auto-refreshes every 10s</div>
<script>
async function go(){
try{
const r=await fetch('/api/state');
const d=await r.json();
document.getElementById('sp').textContent=d.status.toUpperCase();
document.getElementById('sp').className='pill '+d.status;
document.getElementById('bets').textContent=d.bets_placed;
document.getElementById('wag').textContent='$'+d.total_wagered.toFixed(2);
document.getElementById('strat').textContent='$'+d.odds_min+'-$'+d.odds_max;
document.getElementById('st').textContent=d.started;
let m='';
for(const[n,v] of Object.entries(d.markets)){
const tl=v.time_left||0;
const tc=tl>120?'safe':tl>80?'warn':'danger';
const mi=Math.floor(tl/60);const sc=tl%60;
const yh=v.yes_ask&&v.yes_ask>=d.odds_min&&v.yes_ask<=d.odds_max;
const nh=v.no_ask&&v.no_ask>=d.odds_min&&v.no_ask<=d.odds_max;
m+=`<div class="market"><div class="mh"><div class="mn">${n}</div><div class="ov ${tc}">${String(mi).padStart(2,'0')}:${String(sc).padStart(2,'0')}</div></div><div class="odds-row"><div class="ob"><div class="ol">YES</div><div class="ov ${yh?'hot':'normal'}">${v.yes_ask!=null?'$'+v.yes_ask.toFixed(3):'N/A'}</div></div><div class="ob"><div class="ol">NO</div><div class="ov ${nh?'hot':'normal'}">${v.no_ask!=null?'$'+v.no_ask.toFixed(3):'N/A'}</div></div></div></div>`;
}
document.getElementById('markets').innerHTML=m;
let l='';
for(const e of d.log){
const c=e.kind==='bet'?'bet':e.kind==='warn'?'wm':e.kind==='skip'?'skip':'info';
l+=`<div class="le"><span class="lt">${e.time}</span><span class="${c}">${e.msg}</span></div>`;
}
document.getElementById('log').innerHTML=l;
}catch(e){console.error(e);}
}
go();
</script>
</body>
</html>'''

@app.route(’/’)
def dashboard():
return HTML

@app.route(’/api/state’)
def api_state():
return jsonify(dict(state, odds_min=ODDS_MIN, odds_max=ODDS_MAX))

def run_dashboard():
app.run(host=‘0.0.0.0’, port=PORT, debug=False, use_reloader=False)

def get_slug_and_end(label):
interval = INTERVALS[label]
now_ts   = int(time.time())
window   = (now_ts // interval) * interval
return SLUG_PREFIX[label] + ‘-’ + str(window), window + interval

def get_token_ids(slug):
try:
r = requests.get(GAMMA_URL + ‘/markets’,
params={‘slug’: slug, ‘active’: ‘true’, ‘closed’: ‘false’}, timeout=10)
if r.status_code != 200:
return None, None
data = r.json()
markets = data if isinstance(data, list) else data.get(‘data’, [])
if not markets:
return None, None
raw = markets[0].get(‘clobTokenIds’, ‘[]’)
ids = json.loads(raw) if isinstance(raw, str) else raw
if len(ids) < 2:
return None, None
return ids[0], ids[1]
except Exception as e:
log(’Token fetch error: ’ + str(e), ‘warn’)
return None, None

def get_best_ask(token_id):
try:
r = requests.get(HOST + ‘/book’, params={‘token_id’: token_id}, timeout=10)
if r.status_code != 200:
return None
asks = r.json().get(‘asks’, [])
if not asks:
return None
return round(min(float(a[‘price’]) for a in asks), 4)
except:
return None

def place_bet(client, token_id, amount):
try:
signed = client.create_market_order(MarketOrderArgs(token_id=token_id, amount=amount))
resp = client.post_order(signed, OrderType.FOK)
log(’BET PLACED: ’ + str(resp), ‘bet’)
return True
except Exception as e:
log(’Bet failed: ’ + str(e), ‘warn’)
return False

def run_bot():
log(‘Bot starting…’, ‘info’)
state[‘status’] = ‘starting’
if not PRIVATE_KEY or not ADDRESS:
log(‘Missing env vars!’, ‘warn’)
state[‘status’] = ‘error’
return
try:
client = ClobClient(HOST, key=PRIVATE_KEY, chain_id=CHAIN_ID,
signature_type=1, funder=ADDRESS)
client.set_api_creds(client.create_or_derive_api_creds())
log(‘Connected to Polymarket’, ‘info’)
state[‘status’] = ‘running’
except Exception as e:
log(’CLOB init failed: ’ + str(e), ‘warn’)
state[‘status’] = ‘error’
return

```
bets_placed = {}
token_cache = {}

while True:
    now_ts = int(time.time())
    for label in INTERVALS:
        slug, end_ts = get_slug_and_end(label)
        time_left = end_ts - now_ts
        mins = int(time_left // 60)
        secs = int(time_left % 60)

        if label not in state['markets']:
            state['markets'][label] = {}
        state['markets'][label]['time_left'] = time_left

        if time_left <= MIN_TIME_LEFT:
            log(label + ': skip ' + str(mins) + 'm ' + str(secs) + 's', 'skip')
            token_cache.pop(slug, None)
            state['markets'][label]['yes_ask'] = None
            state['markets'][label]['no_ask']  = None
            continue

        if slug not in bets_placed:
            bets_placed = {slug: {'YES': False, 'NO': False}}

        if slug not in token_cache:
            yes_id, no_id = get_token_ids(slug)
            if not yes_id:
                log(label + ': no market for ' + slug, 'warn')
                continue
            token_cache[slug] = (yes_id, no_id)

        yes_id, no_id = token_cache[slug]
        yes_ask = get_best_ask(yes_id)
        no_ask  = get_best_ask(no_id)
        state['markets'][label]['yes_ask'] = yes_ask
        state['markets'][label]['no_ask']  = no_ask

        log(label + ' YES $' + str(yes_ask) + ' NO $' + str(no_ask) +
            ' ' + str(mins) + 'm ' + str(secs) + 's', 'info')

        if yes_ask and ODDS_MIN <= yes_ask <= ODDS_MAX and not bets_placed[slug]['YES']:
            log('SIGNAL ' + label + ' YES @ $' + str(yes_ask), 'bet')
            if place_bet(client, yes_id, BET_SIZE):
                bets_placed[slug]['YES'] = True
                state['bets_placed']   += 1
                state['total_wagered'] += BET_SIZE

        if no_ask and ODDS_MIN <= no_ask <= ODDS_MAX and not bets_placed[slug]['NO']:
            log('SIGNAL ' + label + ' NO @ $' + str(no_ask), 'bet')
            if place_bet(client, no_id, BET_SIZE):
                bets_placed[slug]['NO'] = True
                state['bets_placed']   += 1
                state['total_wagered'] += BET_SIZE

    time.sleep(POLL_INTERVAL)
```

if **name** == ‘**main**’:
threading.Thread(target=run_dashboard, daemon=True).start()
run_bot()
