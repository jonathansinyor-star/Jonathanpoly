# ============================================================
# POLYMARKET BTC BOT - Using official py-clob-client
# Strategy: Bet $2 on any side at $0.01 odds with >80s left
# ============================================================

import os
import time
import requests
from datetime import datetime, timezone
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY

# ============================================================
# CONFIG
# ============================================================
PRIVATE_KEY  = os.environ.get("POLYMARKET_PRIVATE_KEY")
ADDRESS      = os.environ.get("POLYMARKET_ADDRESS")
API_KEY      = os.environ.get("POLYMARKET_API_KEY")
API_SECRET   = os.environ.get("POLYMARKET_SECRET")
API_PASSPHRASE = os.environ.get("POLYMARKET_PASSPHRASE")

BET_SIZE      = 2.00
TRIGGER_ODDS  = 0.01
MIN_TIME_LEFT = 80
POLL_INTERVAL = 10

HOST      = "https://clob.polymarket.com"
CHAIN_ID  = 137  # Polygon
GAMMA_URL = "https://gamma-api.polymarket.com"

INTERVALS = {
    "BTC-5M":  5  * 60,
    "BTC-15M": 15 * 60,
    "BTC-1H":  60 * 60,
    "BTC-4H":  240 * 60,
}

SLUG_MAP = {
    "BTC-5M":  "btc-updown-5m",
    "BTC-15M": "btc-updown-15m",
    "BTC-1H":  "btc-updown-1h",
    "BTC-4H":  "btc-updown-4h",
}

# ============================================================
# LOGGING
# ============================================================
def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

# ============================================================
# GET CURRENT SLUG
# ============================================================
def get_current_slug_and_end(label):
    interval_secs = INTERVALS[label]
    now_ts = int(time.time())
    interval_start = (now_ts // interval_secs) * interval_secs
    end_ts = interval_start + interval_secs
    slug = f"{SLUG_MAP[label]}-{interval_start}"
    return slug, end_ts

# ============================================================
# FETCH MARKET TOKENS FROM GAMMA
# ============================================================
def get_market_tokens(slug):
    try:
        # Try exact slug first
        r = requests.get(f"{GAMMA_URL}/markets", params={"slug": slug}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            markets = data if isinstance(data, list) else data.get("data", [])
            if markets:
                m = markets[0]
                tokens = m.get("clobTokenIds", [])
                if tokens and len(tokens) >= 2:
                    log(f"  Found tokens via /markets slug")
                    return tokens

        # Try events endpoint
        r2 = requests.get(f"{GAMMA_URL}/events", params={"slug": slug}, timeout=10)
        if r2.status_code == 200:
            events = r2.json()
            if events:
                event_markets = events[0].get("markets", [])
                if event_markets:
                    tokens = event_markets[0].get("clobTokenIds", [])
                    if tokens and len(tokens) >= 2:
                        log(f"  Found tokens via /events slug")
                        return tokens

        return None
    except Exception as e:
        log(f"  Exception getting tokens: {e}")
        return None

# ============================================================
# MAIN BOT LOOP
# ============================================================
def run_bot():
    log("=" * 55)
    log("POLYMARKET BTC BOT â py-clob-client v4")
    log(f"Strategy : Bet ${BET_SIZE} when odds <= ${TRIGGER_ODDS}")
    log(f"Condition: >{MIN_TIME_LEFT}s left on market")
    log("=" * 55)

    if not all([PRIVATE_KEY, ADDRESS]):
        log("â Missing POLYMARKET_PRIVATE_KEY or POLYMARKET_ADDRESS!")
        return

    # Init CLOB client with email/magic wallet (signature_type=1)
    try:
        client = ClobClient(
            HOST,
            key=PRIVATE_KEY,
            chain_id=CHAIN_ID,
            signature_type=1,
            funder=ADDRESS,
        )
        client.set_api_creds(client.create_or_derive_api_creds())
        log("â CLOB client initialised")
    except Exception as e:
        log(f"â Failed to init CLOB client: {e}")
        return

    bets_placed = {}

    while True:
        now_ts = int(time.time())

        for label in INTERVALS:
            slug, end_ts = get_current_slug_and_end(label)
            time_left = end_ts - now_ts
            mins = int(time_left // 60)
            secs = int(time_left % 60)

            log(f"--- {label} | {mins}m {secs}s left ---")

            if time_left <= MIN_TIME_LEFT:
                log(f"  â± SKIP â too close to resolution")
                continue

            # Reset bets on new slug
            if slug not in bets_placed:
                bets_placed = {}
                bets_placed[slug] = {"YES": False, "NO": False}

            # Get token IDs
            tokens = get_market_tokens(slug)
            if not tokens:
                log(f"  â ï¸  No tokens found for {slug}")
                continue

            yes_token = tokens[0]
            no_token  = tokens[1]

            for outcome, token_id in [("YES", yes_token), ("NO", no_token)]:
                if bets_placed[slug].get(outcome):
                    continue

                try:
                    # Get best price using py-clob-client
                    price_data = client.get_price(token_id, side="BUY")
                    best_ask = float(price_data.get("price", 1.0))
                    log(f"  {outcome}: ${best_ask:.4f}")

                    if best_ask <= TRIGGER_ODDS:
                        log(f"  ð¯ SIGNAL! {label} {outcome} @ ${best_ask} | {mins}m {secs}s left")
                        # Place market order
                        order_args = MarketOrderArgs(
                            token_id=token_id,
                            amount=BET_SIZE,
                        )
                        signed = client.create_market_order(order_args)
                        resp = client.post_order(signed, OrderType.FOK)
                        log(f"  â BET PLACED: {resp}")
                        bets_placed[slug][outcome] = True
                    else:
                        log(f"  No signal (${best_ask:.4f} > ${TRIGGER_ODDS})")

                except Exception as e:
                    log(f"  â Error checking {outcome}: {e}")

        log(f"ð¤ Sleeping {POLL_INTERVAL}s...\n")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    run_bot()
