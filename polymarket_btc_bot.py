# ============================================================
# POLYMARKET BTC BOT
# Strategy: Bet $2 on any side at $0.01 odds with >80s left
# Markets: BTC 5min, 15min, 1hr, 4hr
# ============================================================

import time
import requests
from datetime import datetime

# ============================================================
# CONFIG — PASTE YOUR KEYS HERE (never share these with anyone)
# ============================================================
POLYMARKET_API_KEY    = "YOUR_API_KEY_HERE"
POLYMARKET_SECRET     = "YOUR_SECRET_HERE"
POLYMARKET_PASSPHRASE = "YOUR_PASSPHRASE_HERE"

BET_SIZE        = 2.00    # $ per bet
TRIGGER_ODDS    = 0.01    # trigger at $0.01
MIN_TIME_LEFT   = 80      # seconds (1 min 20 sec)
POLL_INTERVAL   = 5       # how often to check markets (seconds)

# ============================================================
# BTC MARKET IDs on Polymarket
# Find these at polymarket.com — search BTC and copy the
# market ID from the URL e.g. polymarket.com/event/MARKET-ID
# ============================================================
MARKETS = {
    "BTC-5MIN":  "PASTE_5MIN_MARKET_ID_HERE",
    "BTC-15MIN": "PASTE_15MIN_MARKET_ID_HERE",
    "BTC-1HR":   "PASTE_1HR_MARKET_ID_HERE",
    "BTC-4HR":   "PASTE_4HR_MARKET_ID_HERE",
}

# ============================================================
# POLYMARKET API SETUP
# ============================================================
BASE_URL = "https://clob.polymarket.com"

def get_headers():
    return {
        "Authorization": f"Bearer {POLYMARKET_API_KEY}",
        "Content-Type": "application/json",
    }

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")

# ============================================================
# FETCH MARKET DATA
# ============================================================
def get_market(market_id):
    try:
        r = requests.get(f"{BASE_URL}/markets/{market_id}", headers=get_headers(), timeout=10)
        if r.status_code == 200:
            return r.json()
        else:
            log(f"ERROR fetching market {market_id}: {r.status_code}")
            return None
    except Exception as e:
        log(f"EXCEPTION fetching market: {e}")
        return None

def get_orderbook(token_id):
    try:
        r = requests.get(f"{BASE_URL}/book?token_id={token_id}", headers=get_headers(), timeout=10)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception as e:
        log(f"EXCEPTION fetching orderbook: {e}")
        return None

def get_best_ask(orderbook):
    """Get the best (lowest) ask price from the orderbook."""
    try:
        asks = orderbook.get("asks", [])
        if not asks:
            return None
        return float(min(asks, key=lambda x: float(x["price"]))["price"])
    except:
        return None

def seconds_until_resolution(market_data):
    """Calculate seconds left until market resolves."""
    try:
        end_time = market_data.get("end_date_iso") or market_data.get("game_start_time")
        if not end_time:
            return None
        from datetime import timezone
        end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        now_dt = datetime.now(timezone.utc)
        delta = (end_dt - now_dt).total_seconds()
        return max(0, delta)
    except Exception as e:
        log(f"EXCEPTION parsing time: {e}")
        return None

# ============================================================
# PLACE BET
# ============================================================
def place_bet(token_id, side, amount, odds):
    """Place a market order on Polymarket."""
    log(f">>> PLACING BET: {side} | ${amount} @ ${odds} odds | Token: {token_id[:12]}...")
    
    order = {
        "token_id": token_id,
        "price": odds,
        "size": amount,
        "side": side,       # "BUY"
        "type": "MARKET",
    }

    try:
        r = requests.post(
            f"{BASE_URL}/order",
            json=order,
            headers=get_headers(),
            timeout=15
        )
        if r.status_code in (200, 201):
            log(f"✅ BET PLACED SUCCESSFULLY: {r.json()}")
            return True
        else:
            log(f"❌ BET FAILED: {r.status_code} — {r.text}")
            return False
    except Exception as e:
        log(f"❌ EXCEPTION placing bet: {e}")
        return False

# ============================================================
# MAIN BOT LOOP
# ============================================================
def run_bot():
    log("=" * 50)
    log("POLYMARKET BTC BOT STARTING")
    log(f"Strategy : Bet ${BET_SIZE} when odds = ${TRIGGER_ODDS}")
    log(f"Condition: >{ MIN_TIME_LEFT}s left on market")
    log(f"Markets  : {', '.join(MARKETS.keys())}")
    log("=" * 50)

    # Track which markets we've already bet on this cycle
    bets_placed = {k: {"YES": False, "NO": False} for k in MARKETS}

    while True:
        for market_name, market_id in MARKETS.items():
            log(f"--- Checking {market_name} ---")

            # Fetch market
            market_data = get_market(market_id)
            if not market_data:
                continue

            # Check time left
            time_left = seconds_until_resolution(market_data)
            if time_left is None:
                log(f"  Could not determine time left for {market_name}")
                continue

            mins = int(time_left // 60)
            secs = int(time_left % 60)
            log(f"  Time left: {mins}m {secs}s")

            # Reset bets if market has reset (new cycle)
            if time_left > (MIN_TIME_LEFT + 60):
                bets_placed[market_name] = {"YES": False, "NO": False}

            if time_left <= MIN_TIME_LEFT:
                log(f"  ⏱ SKIP — too close to resolution ({mins}m {secs}s left)")
                continue

            # Get tokens (YES and NO)
            tokens = market_data.get("tokens", [])
            for token in tokens:
                outcome = token.get("outcome", "").upper()  # "YES" or "NO"
                token_id = token.get("token_id")

                if not token_id or outcome not in ("YES", "NO"):
                    continue

                if bets_placed[market_name][outcome]:
                    log(f"  Already bet {outcome} this cycle, skipping")
                    continue

                # Get orderbook to find current ask price
                orderbook = get_orderbook(token_id)
                if not orderbook:
                    continue

                best_ask = get_best_ask(orderbook)
                if best_ask is None:
                    log(f"  No asks available for {outcome}")
                    continue

                log(f"  {outcome} best ask: ${best_ask:.4f}")

                # CHECK TRIGGER
                if best_ask <= TRIGGER_ODDS:
                    log(f"  🎯 SIGNAL! {market_name} {outcome} @ ${best_ask} with {mins}m {secs}s left")
                    success = place_bet(token_id, "BUY", BET_SIZE, best_ask)
                    if success:
                        bets_placed[market_name][outcome] = True
                else:
                    log(f"  No signal for {outcome} (${best_ask:.4f} > ${TRIGGER_ODDS})")

        log(f"Sleeping {POLL_INTERVAL}s before next scan...\n")
        time.sleep(POLL_INTERVAL)

# ============================================================
# RUN
# ============================================================
if __name__ == "__main__":
    run_bot()
