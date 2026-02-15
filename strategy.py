"""
strategy.py — Leg 1 + Leg 2 state machine for BTC Up/Down 5-minute markets.

State machine:
  IDLE ──► WATCHING ──► LEG1_FILLED ──► LEG2_FILLED ──► RESET ──► WATCHING

WATCHING:
  - Monitor UP and DOWN mid-prices for the first `window_minutes` of each round
  - Use a sliding price history keyed by time.monotonic()
  - If either price drops ≥ move_threshold in the last drop_window_sec → trigger Leg 1

LEG1_FILLED:
  - Record entry price (ask price we paid)
  - Monitor opposite side ask
  - When leg1_entry + opposite_ask ≤ hedge_sum → trigger Leg 2

LEG2_FILLED / RESET:
  - Both legs filled → guaranteed profit locked
  - Log trade, update P&L, wait for next round
"""

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from config import config
from logger import get_logger
from market_finder import BTCRound, MarketToken
from trader import trader, OrderResult

log = get_logger("strategy")


class State(Enum):
    IDLE = auto()
    WATCHING = auto()
    LEG1_FILLED = auto()
    LEG2_FILLED = auto()
    RESET = auto()


@dataclass
class PricePoint:
    price: float
    ts: float  # time.monotonic()


@dataclass
class Trade:
    round_id: str
    leg1_outcome: str
    leg1_token_id: str
    leg1_price: float
    leg1_shares: float
    leg2_outcome: str
    leg2_token_id: str
    leg2_price: float
    leg2_shares: float
    combined_cost: float
    expected_payout: float
    profit: float
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"Round={self.round_id[:8]} | "
            f"Leg1={self.leg1_outcome}@{self.leg1_price:.4f} | "
            f"Leg2={self.leg2_outcome}@{self.leg2_price:.4f} | "
            f"Cost={self.combined_cost:.4f} | "
            f"Profit={self.profit:.4f} ({self.profit / self.combined_cost * 100:.1f}%)"
        )


class Strategy:
    def __init__(self):
        self.state: State = State.IDLE
        self.enabled: bool = False
        self.current_round: Optional[BTCRound] = None

        # Config (can be overridden by CLI)
        self.shares: float = config.shares
        self.hedge_sum: float = config.hedge_sum
        self.move_threshold: float = config.move_threshold
        self.window_minutes: float = config.window_minutes
        self.drop_window_sec: float = config.drop_window_sec

        # Price history: token_id → deque of PricePoints
        self._price_history: dict[str, deque] = {}

        # Leg 1 info
        self._leg1_outcome: Optional[str] = None
        self._leg1_token: Optional[MarketToken] = None
        self._leg1_entry_price: Optional[float] = None
        self._leg1_shares: Optional[float] = None
        self._leg2_token: Optional[MarketToken] = None

        # Round timing
        self._round_started_at: Optional[float] = None  # time.monotonic()

        # P&L tracking
        self.total_profit: float = 0.0
        self.total_cost: float = 0.0
        self.trade_history: list[Trade] = []
        self.open_positions: list[dict] = []

        # Async lock to prevent concurrent state transitions
        self._lock = asyncio.Lock()

    # ── Public control ──────────────────────────────────────────────────────

    def configure(
        self,
        shares: float,
        hedge_sum: Optional[float] = None,
        move_threshold: Optional[float] = None,
        window_minutes: Optional[float] = None,
    ):
        self.shares = shares
        if hedge_sum is not None:
            self.hedge_sum = hedge_sum
        if move_threshold is not None:
            self.move_threshold = move_threshold
        if window_minutes is not None:
            self.window_minutes = window_minutes
        log.info(
            f"Strategy configured: shares={self.shares} hedge_sum={self.hedge_sum} "
            f"move={self.move_threshold} window={self.window_minutes}min"
        )

    def enable(self):
        self.enabled = True
        log.info("Strategy ENABLED")

    def disable(self):
        self.enabled = False
        log.info("Strategy DISABLED")
        self._reset_state()

    def attach_round(self, round_: BTCRound):
        """Called when a new BTC round is found. Starts WATCHING phase."""
        self.current_round = round_
        self._price_history.clear()
        self._round_started_at = time.monotonic()
        self.state = State.WATCHING
        log.info(
            f"Attached to round: {round_.question} | "
            f"Ends in {round_.seconds_remaining:.0f}s | "
            f"UP={round_.up_token.token_id[:8]}... DOWN={round_.down_token.token_id[:8]}..."
        )

    # ── Price update entry point (called from WS client) ──────────────────

    async def on_price_update(self, token_id: str, price: float, ts: float):
        """
        Called by ws_client whenever a subscribed token's price updates.
        Dispatches to the appropriate state handler.
        """
        if not self.enabled or self.state == State.IDLE:
            return

        async with self._lock:
            # Record price
            self._record_price(token_id, price, ts)

            if self.state == State.WATCHING:
                await self._handle_watching(token_id, price, ts)
            elif self.state == State.LEG1_FILLED:
                await self._handle_leg1_filled(token_id, price, ts)

    # ── State handlers ──────────────────────────────────────────────────────

    async def _handle_watching(self, token_id: str, price: float, ts: float):
        """WATCHING: look for a ≥15% drop in 3 seconds on either side."""
        if not self.current_round:
            return

        # Check if we are still within the observation window
        elapsed = time.monotonic() - self._round_started_at
        window_sec = self.window_minutes * 60
        if elapsed > window_sec:
            log.info(
                f"Observation window ({self.window_minutes}min) expired. "
                f"Waiting for next round."
            )
            self.state = State.IDLE
            return

        # Check both tokens for the drop signal
        for token, outcome in [
            (self.current_round.up_token, "UP"),
            (self.current_round.down_token, "DOWN"),
        ]:
            drop = self._compute_drop(token.token_id)
            if drop is None:
                continue

            if drop >= self.move_threshold:
                log.info(
                    f"DROP SIGNAL: {outcome} dropped {drop:.2%} in {self.drop_window_sec}s "
                    f"(threshold={self.move_threshold:.2%})"
                )
                await self._trigger_leg1(token, outcome)
                return

    async def _handle_leg1_filled(self, token_id: str, price: float, ts: float):
        """LEG1_FILLED: wait until leg1_entry + opposite_ask ≤ hedge_sum."""
        if not self._leg2_token or not self._leg1_entry_price:
            return

        # We only care about the opposite side's ask price
        if token_id != self._leg2_token.token_id:
            return

        opposite_ask = price  # WS price is typically the ask/last-trade price
        combined = self._leg1_entry_price + opposite_ask

        log.debug(
            f"Hedge check: leg1={self._leg1_entry_price:.4f} + "
            f"opp_ask={opposite_ask:.4f} = {combined:.4f} (need ≤ {self.hedge_sum})"
        )

        if combined <= self.hedge_sum:
            log.info(
                f"HEDGE CONDITION MET: {combined:.4f} ≤ {self.hedge_sum} "
                f"→ triggering Leg 2"
            )
            await self._trigger_leg2(opposite_ask)

    # ── Leg execution ───────────────────────────────────────────────────────

    async def _trigger_leg1(self, token: MarketToken, outcome: str):
        """Buy the dumped side (Leg 1)."""
        log.info(f"Executing Leg 1: BUY {self.shares} × {outcome} @ ~{token.price:.4f}")
        self.state = State.LEG1_FILLED  # Optimistic — revert on failure

        result: OrderResult = await trader.buy_market(
            token_id=token.token_id,
            outcome=outcome,
            shares=self.shares,
            max_price=token.price,
        )

        if not result.success:
            log.error(f"Leg 1 order failed: {result.error}")
            self.state = State.WATCHING
            return

        self._leg1_outcome = outcome
        self._leg1_token = token
        self._leg1_entry_price = result.filled_price
        self._leg1_shares = result.filled_shares

        # Identify the opposite token for Leg 2
        round_ = self.current_round
        if outcome == "UP":
            self._leg2_token = round_.down_token
        else:
            self._leg2_token = round_.up_token

        # Track as open position
        self.open_positions.append({
            "leg": 1,
            "outcome": outcome,
            "token_id": token.token_id,
            "price": result.filled_price,
            "shares": result.filled_shares,
        })

        log.info(
            f"Leg 1 FILLED: {outcome} × {result.filled_shares} @ {result.filled_price:.4f} "
            f"(order={result.order_id})"
        )

    async def _trigger_leg2(self, opposite_ask: float):
        """Buy the opposite side (Leg 2) to lock in the hedge."""
        token = self._leg2_token
        outcome = "DOWN" if self._leg1_outcome == "UP" else "UP"

        log.info(f"Executing Leg 2: BUY {self.shares} × {outcome} @ ~{opposite_ask:.4f}")

        result: OrderResult = await trader.buy_market(
            token_id=token.token_id,
            outcome=outcome,
            shares=self.shares,
            max_price=opposite_ask,
        )

        if not result.success:
            log.error(f"Leg 2 order failed: {result.error}")
            return

        log.info(
            f"Leg 2 FILLED: {outcome} × {result.filled_shares} @ {result.filled_price:.4f} "
            f"(order={result.order_id})"
        )

        # Record the completed trade
        combined_cost = (self._leg1_entry_price * self._leg1_shares) + (result.filled_price * result.filled_shares)
        payout = self._leg1_shares  # $1 per share when binary resolves
        profit = payout - combined_cost

        trade = Trade(
            round_id=self.current_round.condition_id,
            leg1_outcome=self._leg1_outcome,
            leg1_token_id=self._leg1_token.token_id,
            leg1_price=self._leg1_entry_price,
            leg1_shares=self._leg1_shares,
            leg2_outcome=outcome,
            leg2_token_id=token.token_id,
            leg2_price=result.filled_price,
            leg2_shares=result.filled_shares,
            combined_cost=combined_cost,
            expected_payout=payout,
            profit=profit,
        )
        self.trade_history.append(trade)
        self.total_profit += profit
        self.total_cost += combined_cost

        # Clear open positions for this round
        self.open_positions = [p for p in self.open_positions if p["leg"] != 1]

        log.info(f"TRADE COMPLETE: {trade.summary()}")
        log.info(f"Running P&L: ${self.total_profit:.4f} profit on ${self.total_cost:.4f} invested")

        self.state = State.RESET
        self._reset_round_state()

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _record_price(self, token_id: str, price: float, ts: float):
        if token_id not in self._price_history:
            self._price_history[token_id] = deque()
        q = self._price_history[token_id]
        q.append(PricePoint(price=price, ts=ts))
        # Trim entries older than drop_window_sec + buffer
        cutoff = ts - (self.drop_window_sec + 1.0)
        while q and q[0].ts < cutoff:
            q.popleft()

    def _compute_drop(self, token_id: str) -> Optional[float]:
        """
        Compute the price drop over the last drop_window_sec seconds.
        Returns the drop as a positive fraction (e.g. 0.15 = 15% drop).
        Returns None if insufficient data.
        """
        q = self._price_history.get(token_id)
        if not q or len(q) < 2:
            return None

        now = q[-1].ts
        cutoff = now - self.drop_window_sec

        # Find the oldest price within the window
        oldest_price = None
        for point in q:
            if point.ts >= cutoff:
                oldest_price = point.price
                break

        if oldest_price is None or oldest_price == 0:
            return None

        current_price = q[-1].price
        drop = (oldest_price - current_price) / oldest_price  # positive = price fell
        return drop if drop > 0 else 0.0

    def _reset_round_state(self):
        """Clear per-round leg state after a completed trade."""
        self._leg1_outcome = None
        self._leg1_token = None
        self._leg1_entry_price = None
        self._leg1_shares = None
        self._leg2_token = None
        self._round_started_at = None
        self._price_history.clear()

    def _reset_state(self):
        self._reset_round_state()
        self.state = State.IDLE
        self.current_round = None

    # ── Status reporting ─────────────────────────────────────────────────────

    def status_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "state": self.state.name,
            "current_round": self.current_round.question if self.current_round else None,
            "seconds_remaining": (
                f"{self.current_round.seconds_remaining:.0f}s"
                if self.current_round else None
            ),
            "open_positions": self.open_positions,
            "total_profit": round(self.total_profit, 4),
            "total_cost": round(self.total_cost, 4),
            "roi_pct": (
                round(self.total_profit / self.total_cost * 100, 2)
                if self.total_cost > 0 else 0.0
            ),
            "trades_completed": len(self.trade_history),
            "config": {
                "shares": self.shares,
                "hedge_sum": self.hedge_sum,
                "move_threshold": self.move_threshold,
                "window_minutes": self.window_minutes,
            },
        }


# Module-level singleton
strategy = Strategy()
