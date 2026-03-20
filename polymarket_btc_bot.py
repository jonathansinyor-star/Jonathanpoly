# ============================================================
# POLYMARKET BTC BOT - Correct clobTokenIds parsing
# Strategy: Bet $2 on any side at $0.01 odds with >80s left
# ============================================================

import os
import time
import json
import requests
from datetime import datetime, timezone
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs, OrderType

# ============================================================
# CONFIG
# ============================================================
PRIVATE_KEY = os.environ.get("POLYMARKET_PRIVATE_KEY")
ADDRESS     = os.environ.get("POLYMARKET_ADDRESS")

BET_SIZE      = 2.00
TRIGGER_ODDS  = 0.01
MIN_TIME_LEFT = 80    # seconds (1m 20s)
POLL_INTERVAL = 10

HOST      = "https://clob.polymarket.com"
CHAIN_ID  = 137
GAMMA_URL = "https://gamma-api.polymarket.com"

INTERVALS = {
    "BTC-5M":  5   * 60,
    "BTC-15M": 15  * 60,
    "BTC-1H":  60  * 60,
    "BTC-4H":  240 * 60,
}

SLUG_PREFIX = {
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
# SLUG + TIME HELPERS
# ============================================================
def get_slug_and_end(label):
    interval = INTERVALS[label]
    now_ts   = int(time.time())
    window   = (now_ts // interval) * interval   # round down to interval
    slug     = f"{SLUG_PREFIX[label]}-{window}"
    end_ts   = window + interval
    return slug, end_ts

# ============================================================
# GET TOKEN IDs FROM GAMMA /markets (correct endpoint)
# clobTokenIds is a JSON-encoded STRING â must use json.loads
# ============================================================
def get_token_ids(slug):
    try:
        r = requests.get(
            f"{GAMMA_URL}/markets",
            params={"slug": slug, "active": "true", "closed": "false"},
            timeout=10
        )
        if r.status_code != 200:
            log(f"  Gamma /markets returned {r.status_code}")
            return None, None

        data = r.json()
        markets = data if isinstance(data, list) else data.get("data", [])

        if not markets:
            log(f"  No market found for slug: {slug}")
            return None, None

        market = markets[0]

        # clobTokenIds is stored as a JSON STRING â parse it
        raw = market.get("clobTokenIds", "[]")
        if isinstance(raw, str):
            token_ids = json.loads(raw)
        else:
            token_ids = raw

        if len(token_ids) < 2:
            log(f"  Not enough token IDs: {token_ids}")
            return None, None

        yes_id = token_ids[0]
        no_id  = token_ids[1]
        log(f"  â Tokens found â YES: ...{yes_id[-6:]}, NO: ...{no_id[-6:]}")
        return yes_id, no_id

    except Exception as e:
        log(f"  Exception getting tokens: {e}")
        return None, None

# ============================================================
# GET BEST ASK PRICE FROM CLOB ORDERBOOK
# ============================================================
def get_best_ask(token_id):
    try:
        r = requests.get(
            f"{HOST}/book",
            params={"token_id": token_id},
            timeout=10
        )
        if r.status_code != 200:
            log(f"  Orderbook returned {r.status_code} for token ...{token_id[-6:]}")
            return None

        book = r.json()
        asks = book.get("asks", [])
        if not asks:
            return None

        best = min(float(a["price"]) for a in asks)
        return best

    except Exception as e:
        log(f"  Exception getting orderbook: {e}")
        return None

# ============================================================
# PLACE BET VIA py-clob-client
# ============================================================
def place_bet(client, token_id, amount):
    try:
        order_args = MarketOrderArgs(token_id=token_id, amount=amount)
        signed = client.create_market_order(order_args)
        resp = client.post_order(signed, OrderType.FOK)
        log(f"  â BET PLACED: {resp}")
        return True
    except Exception as e:
        log(f"  â Bet failed: {e}")
        return False

# ============================================================
# MAIN LOOP
# ============================================================
def run_bot():
    log("=" * 55)
    log("POLYMARKET BTC BOT â Fixed Token IDs v6")
    log(f"Strategy : Bet ${BET_SIZE} when odds <= ${TRIGGER_ODDS}")
    log(f"Condition: >{MIN_TIME_LEFT}s left on market")
    log("=" * 55)

    if not PRIVATE_KEY or not ADDRESS:
        log("â Missing POLYMARKET_PRIVATE_KEY or POLYMARKET_ADDRESS!")
        return

    # Init CLOB client
    # signature_type=1 = Magic/email wallet (not MetaMask)
    try:
        client = ClobClient(
            HOST,
            key=PRIVATE_KEY,
            chain_id=CHAIN_ID,
            signature_type=1,
            funder=ADDRESS,
        )
        client.set_api_creds(client.create_or_derive_api_creds())
        log("â CLOB client ready")
    except Exception as e:
        log(f"â CLOB init failed: {e}")
        return

    bets_placed  = {}   # slug -> {YES: bool, NO: bool}
    token_cache  = {}   # slug -> (yes_id, no_id)

    while True:
        now_ts = int(time.time())

        for label in INTERVALS:
            slug, end_ts  = get_slug_and_end(label)
            time_left     = end_ts - now_ts
            mins          = int(time_left // 60)
            secs          = int(time_left % 60)

            log(f"--- {label} | {mins}m {secs}s left | {slug} ---")

            # Too close to resolution â skip and clear cache
            if time_left <= MIN_TIME_LEFT:
                log(f"  â± SKIP â {mins}m {secs}s left (need >{MIN_TIME_LEFT}s)")
                token_cache.pop(slug, None)
                continue

            # New slug = new cycle, reset bet tracking
            if slug not in bets_placed:
                bets_placed = {slug: {"YES": False, "NO": False}}

            # Get token IDs (cached per slug)
            if slug not in token_cache:
                yes_id, no_id = get_token_ids(slug)
                if not yes_id:
                    continue
                token_cache[slug] = (yes_id, no_id)

            yes_id, no_id = token_cache[slug]

            # Check YES
            if not bets_placed[slug]["YES"]:
                ask = get_best_ask(yes_id)
                if ask is not None:
                    log(f"  YES ask: ${ask:.4f}")
                    if ask <= TRIGGER_ODDS:
                        log(f"  ð¯ SIGNAL YES @ ${ask} | {mins}m {secs}s left")
                        if place_bet(client, yes_id, BET_SIZE):
                            bets_placed[slug]["YES"] = True
                else:
                    log(f"  YES: no ask available")

            # Check NO
            if not bets_placed[slug]["NO"]:
                ask = get_best_ask(no_id)
                if ask is not None:
                    log(f"  NO  ask: ${ask:.4f}")
                    if ask <= TRIGGER_ODDS:
                        log(f"  ð¯ SIGNAL NO  @ ${ask} | {mins}m {secs}s left")
                        if place_bet(client, no_id, BET_SIZE):
                            bets_placed[slug]["NO"] = True
                else:
                    log(f"  NO: no ask available")

        log(f"ð¤ Sleeping {POLL_INTERVAL}s...\n")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    run_bot()
