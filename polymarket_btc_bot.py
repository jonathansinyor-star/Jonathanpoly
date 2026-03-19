# ============================================================
# POLYMARKET BTC BOT - Auto Market Discovery
# Strategy: Bet $2 on any side at $0.01 odds with >80s left
# Automatically finds latest BTC updown markets every cycle
# ============================================================

import os
import time
import requests
from datetime import datetime, timezone

# ============================================================
# CONFIG — from Railway environment variables
# ============================================================
PRIVATE_KEY  = os.environ.get("POLYMARKET_PRIVATE_KEY")
API_KEY      = os.environ.get("POLYMARKET_API_KEY")
ADDRESS      = os.environ.get("POLYMARKET_ADDRESS")

BET_SIZE      = 2.00   # $ per bet
TRIGGER_ODDS  = 0.01   # bet when odds hit $0.01
MIN_TIME_LEFT = 80     # seconds remaining (1m 20s)
POLL_INTERVAL = 10     # seconds between scans

BASE_URL  = "https://clob.polymarket.com"
GAMMA_URL = "https://gamma-api.polymarket.com"

# Market slugs to search for
MARKET_SLUGS = [
    "btc-updown-5m",
    "btc-updown-15m",
    "btc-updown-1h",
    "btc-updown-4h",
]

# ============================================================
# LOGGING
# ============================================================
def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

# ============================================================
# AUTO-DISCOVER LATEST ACTIVE MARKETS
# ============================================================
def find_active_markets():
    """Search Polymarket for latest active BTC updown markets."""
    found = {}
    try:
        for slug in MARKET_SLUGS:
            # Search gamma API for active events matching slug pattern
            r = requests.get(
                f"{GAMMA_URL}/events",
                params={
                    "slug_contains": slug,
                    "active": "true",
                    "closed": "false",
                    "limit": 1,
                    "order": "endDate",
                    "ascending": "true",
                },
                timeout=10
            )
            if r.status_code != 200:
                log(f"  Could not find market for {slug}: {r.status_code}")
                continue

            events = r.json()
            if not events:
                log(f"  No active market found for {slug}")
                continue

            event = events[0]
            markets = event.get("markets", [])
            if not markets:
                continue

            # Get the condition ID / market ID
            market = markets[0]
            condition_id = market.get("conditionId") or market.get("id")
            end_date = event.get("endDate", "unknown")
            label = slug.replace("btc-updown-", "BTC-").upper()

            if condition_id:
                found[label] = {
                    "condition_id": condition_id,
                    "tokens": market.get("clobTokenIds", []),
                    "end_date": end_date,
                    "question": event.get("title", slug),
                }
                log(f"  ✅ Found {label}: ends {end_date}")

    except Exception as e:
        log(f"EXCEPTION finding markets: {e}")

    return found

# ============================================================
# FETCH ORDERBOOK
# ============================================================
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

def seconds_until(end_date_str):
    try:
        end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        now_dt = datetime.now(timezone.utc)
        return max(0, (end_dt - now_dt).total_seconds())
    except:
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
        "side":     "BUY",
        "type":     "MARKET",
        "funder":   ADDRESS,
    }
    try:
        headers = {
            "POLY-API-KEY": API_KEY,
            "POLY-ADDRESS": ADDRESS,
            "Content-Type": "application/json",
        }
        r = requests.post(
            f"{BASE_URL}/order",
            json=order,
            headers=headers,
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
# STARTUP CHECK
# ============================================================
def check_config():
    ok = True
    if not PRIVATE_KEY:
        log("❌ POLYMARKET_PRIVATE_KEY not set!"); ok = False
    if not API_KEY:
        log("❌ POLYMARKET_API_KEY not set!"); ok = False
    if not ADDRESS:
        log("❌ POLYMARKET_ADDRESS not set!"); ok = False
    return ok

# ============================================================
# MAIN BOT LOOP
# ============================================================
def run_bot():
    log("=" * 55)
    log("POLYMARKET BTC BOT — AUTO MARKET DISCOVERY")
    log(f"Strategy : Bet ${BET_SIZE} when odds <= ${TRIGGER_ODDS}")
    log(f"Condition: >{MIN_TIME_LEFT}s left on market")
    log(f"Watching : {', '.join(MARKET_SLUGS)}")
    log("=" * 55)

    if not check_config():
        log("❌ Fix config errors then restart.")
        return

    # Track bets per market condition ID
    bets_placed = {}
    last_discovery = 0
    active_markets = {}

    while True:
        now = time.time()

        # Re-discover markets every 2 minutes
        if now - last_discovery > 120:
            log("🔍 Discovering latest active markets...")
            active_markets = find_active_markets()
            last_discovery = now
            if not active_markets:
                log("⚠️  No active markets found, will retry...")
                time.sleep(POLL_INTERVAL)
                continue

        # Scan each market
        for label, market in active_markets.items():
            condition_id = market["condition_id"]
            tokens = market["tokens"]
            end_date = market["end_date"]

            time_left = seconds_until(end_date)
            if time_left is None:
                continue

            mins = int(time_left // 60)
            secs = int(time_left % 60)
            log(f"--- {label} | {mins}m {secs}s left ---")

            # Reset bet tracking when market resets
            if condition_id not in bets_placed or time_left > (MIN_TIME_LEFT + 30):
                bets_placed[condition_id] = {"YES": False, "NO": False}

            if time_left <= MIN_TIME_LEFT:
                log(f"  ⏱ SKIP — too close to resolution")
                # Force rediscovery when market is about to end
                last_discovery = 0
                continue

            # Check YES and NO tokens
            outcomes = ["YES", "NO"]
            for i, token_id in enumerate(tokens[:2]):
                outcome = outcomes[i]

                if bets_placed[condition_id].get(outcome):
                    log(f"  Already bet {outcome} this cycle")
                    continue

                orderbook = get_orderbook(token_id)
                if not orderbook:
                    continue

                best_ask = get_best_ask(orderbook)
                if best_ask is None:
                    log(f"  No asks for {outcome}")
                    continue

                log(f"  {outcome}: ${best_ask:.4f}")

                if best_ask <= TRIGGER_ODDS:
                    log(f"  🎯 SIGNAL! {label} {outcome} @ ${best_ask} | {mins}m {secs}s left")
                    success = place_bet(token_id, "BUY", BET_SIZE, best_ask)
                    if success:
                        bets_placed[condition_id][outcome] = True
                else:
                    log(f"  No signal (${best_ask:.4f} > ${TRIGGER_ODDS})")

        log(f"💤 Sleeping {POLL_INTERVAL}s...\n")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    run_bot()
