# ============================================================
# POLYMARKET BTC BOT - Updated Authentication
# Strategy: Bet $2 on any side at $0.01 odds with >80s left
# Markets: BTC 5min, 15min, 1hr, 4hr
# ============================================================

import os
import time
import requests
from datetime import datetime, timezone
from eth_account import Account
from eth_account.messages import encode_defunct

# ============================================================
# CONFIG — pulled from Railway environment variables
# ============================================================
PRIVATE_KEY       = os.environ.get("POLYMARKET_PRIVATE_KEY")
API_KEY           = os.environ.get("POLYMARKET_API_KEY")
ADDRESS           = os.environ.get("POLYMARKET_ADDRESS")

BET_SIZE        = 2.00    # $ per bet
TRIGGER_ODDS    = 0.01    # trigger at $0.01
MIN_TIME_LEFT   = 80      # seconds (1 min 20 sec)
POLL_INTERVAL   = 5       # how often to check markets (seconds)

# ============================================================
# BTC MARKET IDs — paste these in once you find them
# ============================================================
MARKETS = {
    "BTC-5MIN":  os.environ.get("MARKET_5MIN",  ""),
    "BTC-15MIN": os.environ.get("MARKET_15MIN", ""),
    "BTC-1HR":   os.environ.get("MARKET_1HR",   ""),
    "BTC-4HR":   os.environ.get("MARKET_4HR",   ""),
}

BASE_URL = "https://clob.polymarket.com"

# ============================================================
# LOGGING
# ============================================================
def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

# ============================================================
# AUTH — sign requests with private key
# ============================================================
def get_auth_headers():
    timestamp = str(int(time.time()))
    message = f"{timestamp}GET/auth/api-key"
    msg = encode_defunct(text=message)
    signed = Account.sign_message(msg, private_key=PRIVATE_KEY)
    signature = signed.signature.hex()
    return {
        "POLY_ADDRESS":   ADDRESS,
        "POLY-SIGNATURE": signature,
        "POLY-TIMESTAMP": timestamp,
        "POLY-API-KEY":   API_KEY,
        "Content-Type":   "application/json",
    }

# ============================================================
# FETCH MARKET DATA
# ============================================================
def get_market(market_id):
    try:
        r = requests.get(
            f"{BASE_URL}/markets/{market_id}",
            headers=get_auth_headers(),
            timeout=10
        )
        if r.status_code == 200:
            return r.json()
        log(f"ERROR fetching market {market_id}: {r.status_code} {r.text}")
        return None
    except Exception as e:
        log(f"EXCEPTION fetching market: {e}")
        return None

def get_orderbook(token_id):
    try:
        r = requests.get(
            f"{BASE_URL}/book?token_id={token_id}",
            timeout=10
        )
        if r.status_code == 200:
            return r.json()
        return None
    except Exception as e:
        log(f"EXCEPTION fetching orderbook: {e}")
        return None

def get_best_ask(orderbook):
    try:
        asks = orderbook.get("asks", [])
        if not asks:
            return None
        return float(min(asks, key=lambda x: float(x["price"]))["price"])
    except:
        return None

def seconds_until_resolution(market_data):
    try:
        end_time = market_data.get("end_date_iso") or market_data.get("game_start_time")
        if not end_time:
            return None
        end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        now_dt = datetime.now(timezone.utc)
        return max(0, (end_dt - now_dt).total_seconds())
    except Exception as e:
        log(f"EXCEPTION parsing time: {e}")
        return None

# ============================================================
# PLACE BET
# ============================================================
def place_bet(token_id, side, amount, odds):
    log(f">>> PLACING BET: {side} | ${amount} @ ${odds} odds")
    order = {
        "token_id": token_id,
        "price":    str(odds),
        "size":     str(amount),
        "side":     side,
        "type":     "MARKET",
        "funder":   ADDRESS,
    }
    try:
        r = requests.post(
            f"{BASE_URL}/order",
            json=order,
            headers=get_auth_headers(),
            timeout=15
        )
        if r.status_code in (200, 201):
            log(f"✅ BET PLACED: {r.json()}")
            return True
        log(f"❌ BET FAILED: {r.status_code} — {r.text}")
        return False
    except Exception as e:
        log(f"❌ EXCEPTION placing bet: {e}")
        return False

# ============================================================
# STARTUP CHECKS
# ============================================================
def check_config():
    if not PRIVATE_KEY:
        log("❌ POLYMARKET_PRIVATE_KEY not set in environment variables!")
        return False
    if not API_KEY:
        log("❌ POLYMARKET_API_KEY not set in environment variables!")
        return False
    if not ADDRESS:
        log("❌ POLYMARKET_ADDRESS not set in environment variables!")
        return False
    missing_markets = [k for k, v in MARKETS.items() if not v]
    if missing_markets:
        log(f"⚠️  Market IDs missing for: {', '.join(missing_markets)}")
        log("⚠️  Bot will skip those markets until IDs are added")
    return True

# ============================================================
# MAIN BOT LOOP
# ============================================================
def run_bot():
    log("=" * 50)
    log("POLYMARKET BTC BOT STARTING")
    log(f"Strategy : Bet ${BET_SIZE} when odds <= ${TRIGGER_ODDS}")
    log(f"Condition: >{MIN_TIME_LEFT}s left on market")
    log(f"Markets  : {', '.join(MARKETS.keys())}")
    log("=" * 50)

    if not check_config():
        log("❌ Fix config errors above then restart.")
        return

    bets_placed = {k: {"YES": False, "NO": False} for k in MARKETS}

    while True:
        for market_name, market_id in MARKETS.items():
            if not market_id:
                continue

            log(f"--- Checking {market_name} ---")
            market_data = get_market(market_id)
            if not market_data:
                continue

            time_left = seconds_until_resolution(market_data)
            if time_left is None:
                continue

            mins = int(time_left // 60)
            secs = int(time_left % 60)
            log(f"  Time left: {mins}m {secs}s")

            if time_left > (MIN_TIME_LEFT + 60):
                bets_placed[market_name] = {"YES": False, "NO": False}

            if time_left <= MIN_TIME_LEFT:
                log(f"  ⏱ SKIP — too close to resolution")
                continue

            tokens = market_data.get("tokens", [])
            for token in tokens:
                outcome = token.get("outcome", "").upper()
                token_id = token.get("token_id")

                if not token_id or outcome not in ("YES", "NO"):
                    continue
                if bets_placed[market_name][outcome]:
                    continue

                orderbook = get_orderbook(token_id)
                if not orderbook:
                    continue

                best_ask = get_best_ask(orderbook)
                if best_ask is None:
                    continue

                log(f"  {outcome} best ask: ${best_ask:.4f}")

                if best_ask <= TRIGGER_ODDS:
                    log(f"  🎯 SIGNAL! {market_name} {outcome} @ ${best_ask} | {mins}m {secs}s left")
                    success = place_bet(token_id, "BUY", BET_SIZE, best_ask)
                    if success:
                        bets_placed[market_name][outcome] = True
                else:
                    log(f"  No signal (${best_ask:.4f} > ${TRIGGER_ODDS})")

        log(f"Sleeping {POLL_INTERVAL}s...\n")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    run_bot()
