# ============================================================
# POLYMARKET BTC BOT - Dynamic Slug Generation
# Strategy: Bet $2 on any side at $0.01 odds with >80s left
# ============================================================

import os
import time
import requests
from datetime import datetime, timezone, timedelta

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

# Market intervals in seconds
INTERVALS = {
    "BTC-5M":  5  * 60,
    "BTC-15M": 15 * 60,
    "BTC-1H":  60 * 60,
    "BTC-4H":  240 * 60,
}

# ============================================================
# LOGGING
# ============================================================
def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

# ============================================================
# GENERATE CURRENT SLUG DYNAMICALLY
# The slug timestamp = start of current interval window
# e.g. btc-updown-5m-1773929400
# ============================================================
def get_current_slug(label, interval_secs):
    now_ts = int(time.time())
    # Round down to nearest interval
    interval_start = (now_ts // interval_secs) * interval_secs
    prefix = label.lower().replace("-", "")
    # Map label to slug format
    slug_map = {
        "btc5m":  "btc-updown-5m",
        "btc15m": "btc-updown-15m",
        "btc1h":  "btc-updown-1h",
        "btc4h":  "btc-updown-4h",
    }
    slug_prefix = slug_map.get(prefix, f"btc-updown-{label.lower().replace('btc-','')}")
    return f"{slug_prefix}-{interval_start}", interval_start + interval_secs

def get_next_slug(label, interval_secs):
    now_ts = int(time.time())
    interval_start = (now_ts // interval_secs) * interval_secs
    next_start = interval_start + interval_secs
    slug_map = {
        "btc5m":  "btc-updown-5m",
        "btc15m": "btc-updown-15m",
        "btc1h":  "btc-updown-1h",
        "btc4h":  "btc-updown-4h",
    }
    prefix = label.lower().replace("-", "")
    slug_prefix = slug_map.get(prefix, f"btc-updown-{label.lower().replace('btc-','')}")
    return f"{slug_prefix}-{next_start}", next_start + interval_secs

# ============================================================
# FETCH MARKET BY SLUG
# ============================================================
def fetch_market_by_slug(slug):
    try:
        r = requests.get(
            f"{GAMMA_URL}/events",
            params={"slug": slug},
            timeout=10
        )
        if r.status_code == 200:
            events = r.json()
            if events:
                return events[0]
        return None
    except Exception as e:
        log(f"  Exception fetching slug {slug}: {e}")
        return None

def get_tokens_from_event(event):
    markets = event.get("markets", [])
    if not markets:
        return []
    return markets[0].get("clobTokenIds", [])

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
    log("POLYMARKET BTC BOT â DYNAMIC SLUG v3")
    log(f"Strategy : Bet ${BET_SIZE} when odds <= ${TRIGGER_ODDS}")
    log(f"Condition: >{MIN_TIME_LEFT}s left on market")
    log("=" * 55)

    if not all([PRIVATE_KEY, API_KEY, ADDRESS]):
        log("â Missing environment variables!")
        return

    bets_placed = {}

    while True:
        now_ts = int(time.time())

        for label, interval_secs in INTERVALS.items():
            # Get current interval slug and end time
            slug, end_ts = get_current_slug(label, interval_secs)
            time_left = end_ts - now_ts

            mins = int(time_left // 60)
            secs = int(time_left % 60)
            log(f"--- {label} | {mins}m {secs}s left | slug: {slug} ---")

            # Reset bets on new cycle
            if slug not in bets_placed:
                bets_placed = {k: v for k, v in bets_placed.items() if k == slug}
                bets_placed[slug] = {"YES": False, "NO": False}

            if time_left <= MIN_TIME_LEFT:
                log(f"  â± SKIP â too close to resolution ({mins}m {secs}s)")
                continue

            # Fetch market data
            event = fetch_market_by_slug(slug)
            if not event:
                log(f"  â ï¸  Market not found for slug: {slug}")
                # Try next interval slug as fallback
                next_slug, next_end = get_next_slug(label, interval_secs)
                log(f"  Trying next interval: {next_slug}")
                event = fetch_market_by_slug(next_slug)
                if event:
                    slug = next_slug
                    time_left = next_end - now_ts
                    bets_placed[slug] = {"YES": False, "NO": False}
                else:
                    log(f"  â No market found for {label}")
                    continue

            tokens = get_tokens_from_event(event)
            if not tokens or len(tokens) < 2:
                log(f"  â ï¸  No tokens found in market")
                continue

            outcomes = ["YES", "NO"]
            for i, token_id in enumerate(tokens[:2]):
                outcome = outcomes[i]

                if bets_placed.get(slug, {}).get(outcome):
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
                        bets_placed[slug][outcome] = True
                else:
                    log(f"  No signal (${best_ask:.4f} > ${TRIGGER_ODDS})")

        log(f"ð¤ Sleeping {POLL_INTERVAL}s...\n")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    run_bot()
