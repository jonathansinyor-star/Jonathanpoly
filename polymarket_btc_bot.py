# ============================================================
# POLYMARKET BTC BOT - Fixed Market Discovery
# Strategy: Bet $2 on any side at $0.01 odds with >80s left
# ============================================================

import os
import time
import requests
from datetime import datetime, timezone

# ============================================================
# CONFIG
# ============================================================
PRIVATE_KEY  = os.environ.get("POLYMARKET_PRIVATE_KEY")
API_KEY      = os.environ.get("POLYMARKET_API_KEY")
ADDRESS      = os.environ.get("POLYMARKET_ADDRESS")

BET_SIZE      = 2.00
TRIGGER_ODDS  = 0.01
MIN_TIME_LEFT = 80
POLL_INTERVAL = 10

BASE_URL  = "https://clob.polymarket.com"
GAMMA_URL = "https://gamma-api.polymarket.com"

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
    found = {}
    now_utc = datetime.now(timezone.utc)

    try:
        for slug in MARKET_SLUGS:
            # Fetch multiple results and find the one ending in the future
            r = requests.get(
                f"{GAMMA_URL}/events",
                params={
                    "slug_contains": slug,
                    "active": "true",
                    "closed": "false",
                    "limit": 10,
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
                log(f"  No events returned for {slug}")
                continue

            # Find first event that ends in the future
            chosen = None
            for event in events:
                end_date = event.get("endDate") or event.get("end_date_iso")
                if not end_date:
                    continue
                try:
                    end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                    if end_dt > now_utc:
                        chosen = event
                        break
                except:
                    continue

            if not chosen:
                # Try fetching without active filter as fallback
                r2 = requests.get(
                    f"{GAMMA_URL}/events",
                    params={
                        "slug_contains": slug,
                        "limit": 20,
                        "order": "endDate",
                        "ascending": "false",
                    },
                    timeout=10
                )
                if r2.status_code == 200:
                    for event in r2.json():
                        end_date = event.get("endDate") or event.get("end_date_iso")
                        if not end_date:
                            continue
                        try:
                            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                            if end_dt > now_utc:
                                chosen = event
                                break
                        except:
                            continue

            if not chosen:
                log(f"  No future market found for {slug}")
                continue

            markets = chosen.get("markets", [])
            if not markets:
                continue

            market = markets[0]
            condition_id = market.get("conditionId") or market.get("id")
            end_date = chosen.get("endDate") or chosen.get("end_date_iso")
            label = slug.replace("btc-updown-", "BTC-").upper()
            tokens = market.get("clobTokenIds", [])

            if condition_id and tokens:
                found[label] = {
                    "condition_id": condition_id,
                    "tokens": tokens,
                    "end_date": end_date,
                }
                end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                secs = int((end_dt - now_utc).total_seconds())
                log(f"  â {label}: {secs//60}m {secs%60}s remaining")
            else:
                log(f"  â ï¸  {label}: found event but missing tokens/condition_id")

    except Exception as e:
        log(f"EXCEPTION finding markets: {e}")

    return found

# ============================================================
# ORDERBOOK
# ============================================================
def get_orderbook(token_id):
    try:
        r = requests.get(f"{BASE_URL}/book?token_id={token_id}", timeout=10)
        if r.status_code == 200:
            return r.json()
        return None
    except:
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
        return max(0, (end_dt - datetime.now(timezone.utc)).total_seconds())
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
        r = requests.post(f"{BASE_URL}/order", json=order, headers=headers, timeout=15)
        if r.status_code in (200, 201):
            log(f"â BET PLACED: {r.json()}")
            return True
        log(f"â BET FAILED: {r.status_code} â {r.text}")
        return False
    except Exception as e:
        log(f"â EXCEPTION: {e}")
        return False

# ============================================================
# MAIN LOOP
# ============================================================
def run_bot():
    log("=" * 55)
    log("POLYMARKET BTC BOT â AUTO MARKET DISCOVERY v2")
    log(f"Strategy : Bet ${BET_SIZE} when odds <= ${TRIGGER_ODDS}")
    log(f"Condition: >{MIN_TIME_LEFT}s left on market")
    log("=" * 55)

    if not all([PRIVATE_KEY, API_KEY, ADDRESS]):
        log("â Missing environment variables â check Railway Variables tab")
        return

    bets_placed = {}
    last_discovery = 0
    active_markets = {}

    while True:
        now = time.time()

        # Rediscover every 2 minutes or when markets expire
        if now - last_discovery > 120:
            log("ð Discovering latest active markets...")
            active_markets = find_active_markets()
            last_discovery = now
            if not active_markets:
                log("â ï¸  No active markets found, retrying in 30s...")
                time.sleep(30)
                last_discovery = 0
                continue

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

            # Reset bets on new cycle
            if condition_id not in bets_placed:
                bets_placed[condition_id] = {"YES": False, "NO": False}

            if time_left <= MIN_TIME_LEFT:
                log(f"  â± SKIP â too close to resolution")
                last_discovery = 0  # force rediscover next loop
                continue

            outcomes = ["YES", "NO"]
            for i, token_id in enumerate(tokens[:2]):
                outcome = outcomes[i]

                if bets_placed[condition_id].get(outcome):
                    log(f"  Already bet {outcome} this cycle")
                    continue

                orderbook = get_orderbook(token_id)
                if not orderbook:
                    log(f"  No orderbook for {outcome}")
                    continue

                best_ask = get_best_ask(orderbook)
                if best_ask is None:
                    log(f"  No asks for {outcome}")
                    continue

                log(f"  {outcome}: ${best_ask:.4f}")

                if best_ask <= TRIGGER_ODDS:
                    log(f"  ð¯ SIGNAL! {label} {outcome} @ ${best_ask} | {mins}m {secs}s left")
                    success = place_bet(token_id, "BUY", BET_SIZE, best_ask)
                    if success:
                        bets_placed[condition_id][outcome] = True
                else:
                    log(f"  No signal (${best_ask:.4f} > ${TRIGGER_ODDS})")

        log(f"ð¤ Sleeping {POLL_INTERVAL}s...\n")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    run_bot()
