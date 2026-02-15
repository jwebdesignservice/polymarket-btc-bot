"""
fetch_history.py
----------------
Fetches historical BTC Up/Down markets from Polymarket's CLOB API.

These are the "Bitcoin Up or Down" 15-minute binary markets.
Market slugs follow the pattern: btc-updown-15m-<timestamp>

APIs used (no auth required):
  CLOB API:   https://clob.polymarket.com
  CLOB prices: https://clob.polymarket.com/prices-history

Saves:
  backtest/data/markets.json               - filtered market metadata
  backtest/data/prices_{condition_id}.json - price history per market
"""

import os
import json
import time
import base64
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CLOB_BASE    = "https://clob.polymarket.com"
DATA_DIR     = os.path.join(os.path.dirname(__file__), "data")
MARKETS_FILE = os.path.join(DATA_DIR, "markets.json")

# How many 15-min rounds to collect (24h = 96 rounds)
TARGET_ROUNDS = 200

# Rate-limit delay between API requests (seconds)
REQUEST_DELAY = 0.3

# CLOB cursor offset range where BTC Up/Down markets live
# Determined empirically: they start around offset 300,000
SEARCH_START_OFFSET = 300_000
SEARCH_END_OFFSET   = 420_000
SEARCH_STEP         = 1000


def _get(url: str, params: dict = None, retries: int = 3) -> dict | list:
    """HTTP GET with simple retry logic."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            if attempt < retries - 1:
                print(f"  [WARN] {exc} - retrying ({attempt + 1}/{retries})...")
                time.sleep(2 ** attempt)
            else:
                print(f"  [ERROR] Failed after {retries} attempts: {exc}")
                return {}


def is_btc_updown_market(market: dict) -> bool:
    """
    Return True only for BTC 15-minute Up/Down markets with exact timestamp slugs.
    Slug format: btc-updown-15m-<unix_timestamp>
    This ensures we have exact round times and excludes ETH/XRP/etc.
    """
    slug = market.get("market_slug", "")
    if not slug.startswith("btc-updown-15m-"):
        return False
    # Verify the suffix is a valid integer timestamp
    try:
        int(slug.split("btc-updown-15m-")[1])
    except (IndexError, ValueError):
        return False
    return True


def fetch_clob_page(offset: int, limit: int = 500) -> tuple[list[dict], str]:
    """Fetch one page of CLOB markets. Returns (items, next_cursor)."""
    cursor = base64.b64encode(str(offset).encode()).decode()
    data = _get(f"{CLOB_BASE}/markets", params={"limit": limit, "next_cursor": cursor})
    if not isinstance(data, dict):
        return [], ""
    return data.get("data", []), data.get("next_cursor", "")


def fetch_market_list() -> list[dict]:
    """
    Scan the CLOB market list for BTC Up/Down markets.
    These live at offsets ~300k-420k as of early 2026.
    """
    found = []
    print(f"[fetch_history] Scanning CLOB offsets {SEARCH_START_OFFSET:,} - {SEARCH_END_OFFSET:,}...")

    MAX_MARKETS = TARGET_ROUNDS * 3  # fetch 3x what we need, then trim

    for offset in range(SEARCH_START_OFFSET, SEARCH_END_OFFSET, SEARCH_STEP):
        items, _ = fetch_clob_page(offset, limit=SEARCH_STEP)
        if not items:
            continue
        btc = [m for m in items if is_btc_updown_market(m)]
        found.extend(btc)

        # Progress every 10k offsets
        if (offset - SEARCH_START_OFFSET) % 10_000 == 0:
            pct = (offset - SEARCH_START_OFFSET) / (SEARCH_END_OFFSET - SEARCH_START_OFFSET) * 100
            print(f"  {pct:.0f}% scanned... {len(found)} markets found so far")

        # Stop early once we have enough
        if len(found) >= MAX_MARKETS:
            print(f"  Reached {len(found)} markets - stopping scan early.")
            break

        time.sleep(REQUEST_DELAY)

    # Deduplicate by condition_id
    seen = set()
    unique = []
    for m in found:
        cid = m.get("condition_id", "")
        if cid and cid not in seen:
            seen.add(cid)
            unique.append(m)

    return unique


def fetch_price_history(token_id: str, end_ts: int, fidelity: int = 1) -> list[dict]:
    """
    Fetch price history for a single token from CLOB.
    Uses start/end timestamps derived from the round's slug timestamp.
    Returns list of {t, p} sorted ascending by timestamp.
    """
    start_ts = end_ts - 15 * 60 - 60   # start 16 min before end (1 min padding)
    padded_end = end_ts + 60            # 1 min padding after
    data = _get(
        f"{CLOB_BASE}/prices-history",
        params={
            "market": token_id,
            "startTs": start_ts,
            "endTs": padded_end,
            "fidelity": fidelity,
        }
    )
    history = data.get("history", []) if isinstance(data, dict) else []
    history.sort(key=lambda x: x.get("t", 0))
    return history


def save_json(path: str, obj) -> None:
    """Write object to JSON file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    print(f"  Saved -> {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(force_refetch: bool = False) -> list[dict]:
    """
    Orchestrate the full fetch pipeline.
    Returns list of enriched market dicts (with price_history_up/down attached).
    """
    os.makedirs(DATA_DIR, exist_ok=True)

    # --- Step 1: load or fetch market metadata ---
    if not force_refetch and os.path.exists(MARKETS_FILE):
        print("[fetch_history] Loading cached markets.json...")
        with open(MARKETS_FILE, encoding="utf-8") as f:
            btc_markets = json.load(f)
        print(f"  Loaded {len(btc_markets)} cached markets.")
    else:
        btc_markets = fetch_market_list()
        print(f"  Found {len(btc_markets)} BTC Up/Down markets total.")

        if not btc_markets:
            print("[fetch_history] ERROR: No BTC Up/Down markets found.")
            return []

        # Sort by end_date_iso descending (most recent first)
        btc_markets.sort(key=lambda m: m.get("end_date_iso", ""), reverse=True)
        save_json(MARKETS_FILE, btc_markets)
        print(f"  Sample markets:")
        for m in btc_markets[:3]:
            print(f"    {m.get('question','?')}")

    # --- Step 2: fetch price history for each market ---
    enriched = []
    target = min(TARGET_ROUNDS, len(btc_markets))

    print(f"\n[fetch_history] Fetching price history for {target} markets...")

    for i, mkt in enumerate(btc_markets[:target]):
        condition_id = mkt.get("condition_id", "")
        question = mkt.get("question", "unknown")
        price_file = os.path.join(DATA_DIR, f"prices_{condition_id[:16]}.json")

        if not force_refetch and os.path.exists(price_file):
            with open(price_file, encoding="utf-8") as f:
                cached = json.load(f)
            mkt["price_history_up"]   = cached.get("up", [])
            mkt["price_history_down"] = cached.get("down", [])
            enriched.append(mkt)
            continue

        # Extract token IDs for Up and Down
        tokens = mkt.get("tokens", [])
        up_token_id   = None
        down_token_id = None
        for tok in tokens:
            outcome = tok.get("outcome", "").lower()
            if outcome == "up":
                up_token_id = tok.get("token_id")
            elif outcome == "down":
                down_token_id = tok.get("token_id")

        if not up_token_id or not down_token_id:
            continue

        # Extract exact round end timestamp from slug
        slug = mkt.get("market_slug", "")
        try:
            round_end_ts = int(slug.split("btc-updown-15m-")[1])
        except (IndexError, ValueError):
            continue

        print(f"  [{i+1}/{target}] {question}")

        history_up   = fetch_price_history(up_token_id, round_end_ts)
        time.sleep(REQUEST_DELAY)
        history_down = fetch_price_history(down_token_id, round_end_ts)
        time.sleep(REQUEST_DELAY)

        combined = {
            "condition_id": condition_id,
            "question": question,
            "up": history_up,
            "down": history_down,
        }
        save_json(price_file, combined)

        mkt["price_history_up"]   = history_up
        mkt["price_history_down"] = history_down
        enriched.append(mkt)

    print(f"\n[fetch_history] Done. Loaded {len(enriched)} market rounds.")
    return enriched


if __name__ == "__main__":
    run(force_refetch=False)
