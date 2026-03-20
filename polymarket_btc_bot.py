# ============================================================
# POLYMARKET BTC BOT - Correct Token ID fetching from CLOB
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
PRIVATE_KEY = os.environ.get("POLYMARKET_PRIVATE_KEY")
ADDRESS     = os.environ.get("POLYMARKET_ADDRESS")

BET_SIZE      = 2.00
TRIGGER_ODDS  = 0.01
MIN_TIME_LEFT = 80
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
# GET CURRENT SLUG AND END TIME
# ============================================================
def get_slug_and_end(label):
    interval_secs = INTERVALS[label]
    now_ts = int(time.time())
    interval_start = (now_ts // interval_secs) * interval_secs
    end_ts = interval_start + interval_secs
    slug = f"{SLUG_MAP[label]}-{interval_start}"
    return slug, end_ts

# ============================================================
# GET TOKEN IDs FROM CLOB API (correct source)
# ============================================================
def get_tokens_from_clob(client, slug):
    """Fetch token IDs directly from CLOB /markets endpoint by slug."""
    try:
        # Get paginated markets and search for our slug
        result = client.get_markets()
        markets = result.get("data", []) if isinstance(result, dict) else result

        for market in markets:
            if market.get("market_slug") == slug:
                tokens = market.get("tokens", [])
                if len(tokens) >= 2:
                    yes_id = next((t["token_id"] for t in tokens if t["outcome"] == "Yes"), None)
                    no_id  = next((t["token_id"] for t in tokens if t["outcome"] == "No"),  None)
                    if yes_id and no_id:
                        log(f"  â Found tokens via CLOB for {slug}")
                        return yes_id, no_id, market.get("end_date_iso")

        # Fallback: try Gamma API for condition_id then CLOB
        r = requests.get(f"{GAMMA_URL}/events", params={"slug": slug}, timeout=10)
        if r.status_code == 200 and r.json():
            event = r.json()[0]
            event_markets = event.get("markets", [])
            if event_markets:
                condition_id = event_markets[0].get("conditionId")
                if condition_id:
                    clob_market = client.get_market(condition_id)
                    if clob_market:
                        tokens = clob_market.get("tokens", [])
                        if len(tokens) >= 2:
                            yes_id = next((t["token_id"] for t in tokens if t["outcome"] == "Yes"), None)
                            no_id  = next((t["token_id"] for t in tokens if t["outcome"] == "No"),  None)
                            end_date = clob_market.get("end_date_iso")
                            if yes_id and no_id:
                                log(f"  â Found tokens via Gamma+CLOB for {slug}")
                                return yes_id, no_id, end_date

        return None, None, None
    except Exception as e:
        log(f"  Exception getting tokens: {e}")
        return None, None, None

# ============================================================
# PLACE BET
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
    log("POLYMARKET BTC BOT â CLOB Token IDs v5")
    log(f"Strategy : Bet ${BET_SIZE} when odds <= ${TRIGGER_ODDS}")
    log(f"Condition: >{MIN_TIME_LEFT}s left on market")
    log("=" * 55)

    if not all([PRIVATE_KEY, ADDRESS]):
        log("â Missing POLYMARKET_PRIVATE_KEY or POLYMARKET_ADDRESS!")
        return

    # Init CLOB client (email/magic wallet = signature_type=1)
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

    bets_placed = {}
    token_cache = {}  # cache tokens per slug

    while True:
        now_ts = int(time.time())

        for label in INTERVALS:
            slug, end_ts = get_slug_and_end(label)
            time_left = end_ts - now_ts
            mins = int(time_left // 60)
            secs = int(time_left % 60)

            log(f"--- {label} | {mins}m {secs}s left ---")

            if time_left <= MIN_TIME_LEFT:
                log(f"  â± SKIP â too close to resolution")
                # Clear cache so new market fetched next cycle
                token_cache.pop(slug, None)
                continue

            # Reset bets on new slug
            if slug not in bets_placed:
                bets_placed = {slug: {"YES": False, "NO": False}}

            # Get token IDs (use cache if available)
            if slug not in token_cache:
                yes_id, no_id, _ = get_tokens_from_clob(client, slug)
                if yes_id and no_id:
                    token_cache[slug] = (yes_id, no_id)
                else:
                    log(f"  â Could not get tokens for {slug}")
                    continue
            else:
                yes_id, no_id = token_cache[slug]

            for outcome, token_id in [("YES", yes_id), ("NO", no_id)]:
                if bets_placed[slug].get(outcome):
                    continue

                try:
                    price_data = client.get_price(token_id, side="BUY")
                    best_ask = float(price_data.get("price", 1.0))
                    log(f"  {outcome}: ${best_ask:.4f}")

                    if best_ask <= TRIGGER_ODDS:
                        log(f"  ð¯ SIGNAL! {label} {outcome} @ ${best_ask} | {mins}m {secs}s left")
                        success = place_bet(client, token_id, BET_SIZE)
                        if success:
                            bets_placed[slug][outcome] = True
                    else:
                        log(f"  No signal (${best_ask:.4f} > ${TRIGGER_ODDS})")

                except Exception as e:
                    log(f"  Error for {outcome}: {e}")

        log(f"ð¤ Sleeping {POLL_INTERVAL}s...\n")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    run_bot()
