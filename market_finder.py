"""
market_finder.py — Finds active BTC Up/Down 5-minute rounds via Polymarket REST APIs.

Each "round" is a pair of markets: one UP token, one DOWN token.
We identify them by their question text containing BTC/Bitcoin keywords
and "up"/"down" within the same market group.
"""

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Optional
import aiohttp

from config import config
from logger import get_logger

log = get_logger("market_finder")


@dataclass
class MarketToken:
    token_id: str
    outcome: str          # "UP" or "DOWN"
    price: float = 0.0    # last known mid-price (0–1)


@dataclass
class BTCRound:
    condition_id: str
    question: str
    up_token: MarketToken
    down_token: MarketToken
    end_time: Optional[float] = None   # unix timestamp
    start_time: Optional[float] = None

    @property
    def seconds_remaining(self) -> float:
        if self.end_time is None:
            return float("inf")
        return max(0.0, self.end_time - time.time())

    @property
    def is_active(self) -> bool:
        return self.seconds_remaining > 0


# ── Helpers ──────────────────────────────────────────────────────────────────

_UP_RE = re.compile(r"\bup\b", re.IGNORECASE)
_DOWN_RE = re.compile(r"\bdown\b", re.IGNORECASE)
_BTC_RE = re.compile(r"\b(btc|bitcoin)\b", re.IGNORECASE)
_5MIN_RE = re.compile(r"5.?min", re.IGNORECASE)


def _is_btc_updown_market(market: dict) -> bool:
    """Return True if market looks like a BTC Up/Down 5-minute market."""
    question = market.get("question", "") or ""
    # Must mention BTC
    if not _BTC_RE.search(question):
        return False
    # Must mention up/down
    if not (_UP_RE.search(question) or _DOWN_RE.search(question)):
        return False
    return True


def _parse_end_time(market: dict) -> Optional[float]:
    """Parse end_date_iso from market dict to unix timestamp."""
    import datetime
    raw = market.get("end_date_iso") or market.get("endDateIso") or market.get("end_date") or ""
    if not raw:
        return None
    try:
        dt = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return None


def _parse_start_time(market: dict) -> Optional[float]:
    import datetime
    raw = market.get("start_date_iso") or market.get("startDateIso") or market.get("start_date") or ""
    if not raw:
        return None
    try:
        dt = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return None


def _extract_tokens(market: dict) -> tuple[Optional[MarketToken], Optional[MarketToken]]:
    """
    Extract UP and DOWN MarketToken objects from a Gamma market dict.
    Gamma markets have a 'tokens' list like:
      [{"token_id": "...", "outcome": "Yes", ...}, ...]
    Or they may use 'clob_token_ids' paired with 'outcomes'.
    """
    up_token: Optional[MarketToken] = None
    down_token: Optional[MarketToken] = None

    tokens = market.get("tokens") or []
    for tok in tokens:
        outcome = (tok.get("outcome") or tok.get("winner") or "").upper()
        tid = tok.get("token_id") or tok.get("tokenId") or ""
        price = float(tok.get("price") or 0.0)
        if "UP" in outcome or outcome == "YES":
            up_token = MarketToken(token_id=tid, outcome="UP", price=price)
        elif "DOWN" in outcome or outcome == "NO":
            down_token = MarketToken(token_id=tid, outcome="DOWN", price=price)

    # Fallback: clob_token_ids + outcomes arrays
    if not up_token and not down_token:
        token_ids = market.get("clob_token_ids") or []
        outcomes = market.get("outcomes") or []
        for tid, outcome in zip(token_ids, outcomes):
            o = outcome.upper()
            if "UP" in o or o == "YES":
                up_token = MarketToken(token_id=tid, outcome="UP")
            elif "DOWN" in o or o == "NO":
                down_token = MarketToken(token_id=tid, outcome="DOWN")

    return up_token, down_token


# ── Main finder class ─────────────────────────────────────────────────────────

class MarketFinder:
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def fetch_active_rounds(self) -> list[BTCRound]:
        """
        Query Gamma API for active BTC Up/Down markets and pair them into rounds.
        Returns a list of BTCRound objects sorted by end_time ascending.
        """
        session = await self._get_session()
        rounds: list[BTCRound] = []

        # Paginate through Gamma markets
        url = f"{config.gamma_api}/markets"
        params = {
            "tag": config.market_search_tag,
            "active": "true",
            "closed": "false",
            "limit": 100,
            "offset": 0,
        }

        raw_markets = []
        try:
            while True:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    resp.raise_for_status()
                    data = await resp.json()

                # Gamma returns a list directly
                if isinstance(data, list):
                    batch = data
                elif isinstance(data, dict):
                    batch = data.get("data") or data.get("markets") or []
                else:
                    break

                if not batch:
                    break

                raw_markets.extend(batch)

                if len(batch) < params["limit"]:
                    break
                params["offset"] += params["limit"]

        except Exception as e:
            log.error(f"Failed to fetch markets from Gamma API: {e}")
            return []

        log.info(f"Fetched {len(raw_markets)} raw markets from Gamma API")

        # Filter BTC Up/Down markets
        btc_markets = [m for m in raw_markets if _is_btc_updown_market(m)]
        log.info(f"Found {len(btc_markets)} BTC Up/Down candidate markets")

        # Group by condition_id (each condition_id = one binary market with UP+DOWN)
        by_condition: dict[str, list[dict]] = {}
        for m in btc_markets:
            cid = m.get("condition_id") or m.get("conditionId") or m.get("id") or ""
            if not cid:
                continue
            by_condition.setdefault(cid, []).append(m)

        for cid, markets in by_condition.items():
            # A single market entry may have both tokens embedded
            for m in markets:
                up_tok, down_tok = _extract_tokens(m)
                if up_tok and down_tok:
                    end_time = _parse_end_time(m)
                    start_time = _parse_start_time(m)
                    r = BTCRound(
                        condition_id=cid,
                        question=m.get("question", ""),
                        up_token=up_tok,
                        down_token=down_tok,
                        end_time=end_time,
                        start_time=start_time,
                    )
                    if r.is_active:
                        rounds.append(r)
                    break

        # Sort by soonest ending first
        rounds.sort(key=lambda r: r.end_time or float("inf"))
        log.info(f"Resolved {len(rounds)} active BTC Up/Down rounds")
        return rounds

    async def fetch_order_book(self, token_id: str) -> dict:
        """
        Fetch the current order book for a token from the CLOB REST API.
        Returns dict with 'bids' and 'asks', each a list of {price, size}.
        """
        session = await self._get_session()
        url = f"{config.clob_api}/book"
        try:
            async with session.get(
                url,
                params={"token_id": token_id},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data
        except Exception as e:
            log.warning(f"Failed to fetch order book for token {token_id}: {e}")
            return {}

    @staticmethod
    def best_ask(order_book: dict) -> Optional[float]:
        """Return the lowest ask price from an order book dict."""
        asks = order_book.get("asks") or []
        if not asks:
            return None
        try:
            return min(float(a["price"]) for a in asks)
        except Exception:
            return None

    @staticmethod
    def best_bid(order_book: dict) -> Optional[float]:
        """Return the highest bid price from an order book dict."""
        bids = order_book.get("bids") or []
        if not bids:
            return None
        try:
            return max(float(b["price"]) for b in bids)
        except Exception:
            return None

    async def get_mid_prices(self, round_: BTCRound) -> tuple[Optional[float], Optional[float]]:
        """
        Return (up_mid, down_mid) prices for a round using REST order book.
        Falls back to token price if book is empty.
        """
        up_book, down_book = await asyncio.gather(
            self.fetch_order_book(round_.up_token.token_id),
            self.fetch_order_book(round_.down_token.token_id),
        )

        def mid(book, fallback):
            bid = self.best_bid(book)
            ask = self.best_ask(book)
            if bid is not None and ask is not None:
                return (bid + ask) / 2
            if ask is not None:
                return ask
            if bid is not None:
                return bid
            return fallback

        up_mid = mid(up_book, round_.up_token.price)
        down_mid = mid(down_book, round_.down_token.price)
        return up_mid, down_mid
