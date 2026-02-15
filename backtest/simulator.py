"""
simulator.py
------------
Replays a single BTC Up/Down 5-minute market round tick-by-tick.

DATA FIDELITY NOTE:
  Polymarket's CLOB API returns price data at 1-minute fidelity (fidelity=1).
  The live strategy detects a price drop within a 3-second sliding window.
  Here we APPROXIMATE that: if the price drops >= `move` between two consecutive
  1-minute ticks, we treat it as a trigger. This is a conservative approximation —
  real 3-second drops that don't span a full minute boundary will be missed.
  Results from this backtest should be treated as a lower bound on trigger rate.

Strategy logic:
  1. Watch the first `windowMin` minutes of the round.
  2. If either UP or DOWN price drops `move` in one tick → Leg 1 trigger.
     - Leg 1 buy at ask = price + 0.01
  3. After Leg 1, wait for leg1_price + opposite_ask <= `sum`.
     - Leg 2 buy at ask = opposite_price + 0.01
  4. If Leg 2 fills: profit = 1.0 - (leg1_entry + leg2_entry)
  5. If round ends before Leg 2: loss = leg1_entry (full stake lost)
  6. If Leg 1 never triggers: no trade
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class SimParams:
    move: float       # minimum price drop to trigger Leg 1 (e.g. 0.15 = 15%)
    sum: float        # max combined ask for Leg 2 entry (e.g. 0.95)
    windowMin: float  # only watch the first N minutes of each round


@dataclass
class SimResult:
    status: Literal["TRIGGERED", "NOT_TRIGGERED"]
    triggered_side: str | None   # "UP" or "DOWN"
    trigger_tick: int | None     # index of the tick that triggered Leg 1
    leg1_entry: float | None     # price paid for Leg 1 (ask)
    leg2_entry: float | None     # price paid for Leg 2 (ask), or None if missed
    profit: float                # net profit per share; negative = loss
    leg2_filled: bool            # True if both legs completed
    notes: str = ""              # human-readable explanation


def _ask(prob: float) -> float:
    """Convert a mid-price probability to a simulated ask price (spread = 1 cent)."""
    return round(min(prob + 0.01, 0.99), 4)


# ---------------------------------------------------------------------------
# Core simulator
# ---------------------------------------------------------------------------

def simulate_round(
    price_history_up: list[dict],
    price_history_down: list[dict],
    params: SimParams,
) -> SimResult:
    """
    Replay one round and return a SimResult.

    Parameters
    ----------
    price_history_up   : list of {t: unix_ts, p: float} for the UP side
    price_history_down : list of {t: unix_ts, p: float} for the DOWN side
    params             : SimParams with move, sum, windowMin
    """

    # Validate inputs
    if not price_history_up or not price_history_down:
        return SimResult(
            status="NOT_TRIGGERED",
            triggered_side=None,
            trigger_tick=None,
            leg1_entry=None,
            leg2_entry=None,
            profit=0.0,
            leg2_filled=False,
            notes="No price data available for this round.",
        )

    # Align both series by timestamp — use only ticks present in both
    up_by_t   = {d["t"]: d["p"] for d in price_history_up}
    down_by_t = {d["t"]: d["p"] for d in price_history_down}
    common_ts = sorted(set(up_by_t) & set(down_by_t))

    if not common_ts:
        # Fall back: use indices, zip both series
        min_len = min(len(price_history_up), len(price_history_down))
        common_ts = list(range(min_len))
        up_by_t   = {i: price_history_up[i]["p"]   for i in range(min_len)}
        down_by_t = {i: price_history_down[i]["p"] for i in range(min_len)}

    if len(common_ts) < 2:
        return SimResult(
            status="NOT_TRIGGERED",
            triggered_side=None,
            trigger_tick=None,
            leg1_entry=None,
            leg2_entry=None,
            profit=0.0,
            leg2_filled=False,
            notes="Insufficient ticks for simulation (need ≥ 2).",
        )

    # Compute round start time and observation window cutoff
    t0          = common_ts[0]
    window_secs = params.windowMin * 60
    cutoff_t    = t0 + window_secs  # only watch up to windowMin minutes in

    # --- Phase 1: Scan for Leg 1 trigger ---
    leg1_triggered = False
    triggered_side = None
    trigger_tick_idx = None
    leg1_entry = None

    for i in range(1, len(common_ts)):
        t = common_ts[i]
        if t > cutoff_t:
            break  # outside observation window

        prev_t = common_ts[i - 1]
        up_now   = up_by_t[t]
        up_prev  = up_by_t[prev_t]
        dn_now   = down_by_t[t]
        dn_prev  = down_by_t[prev_t]

        drop_up   = up_prev - up_now    # positive = price fell
        drop_down = dn_prev - dn_now

        # Check UP side drop
        if drop_up >= params.move:
            leg1_triggered = True
            triggered_side = "UP"
            trigger_tick_idx = i
            leg1_entry = _ask(up_now)
            break

        # Check DOWN side drop
        if drop_down >= params.move:
            leg1_triggered = True
            triggered_side = "DOWN"
            trigger_tick_idx = i
            leg1_entry = _ask(dn_now)
            break

    if not leg1_triggered:
        return SimResult(
            status="NOT_TRIGGERED",
            triggered_side=None,
            trigger_tick=None,
            leg1_entry=None,
            leg2_entry=None,
            profit=0.0,
            leg2_filled=False,
            notes="No drop detected within observation window.",
        )

    # --- Phase 2: Wait for Leg 2 opportunity ---
    # Opposite side is the one we DIDN'T buy in Leg 1
    opp_side = "DOWN" if triggered_side == "UP" else "UP"
    opp_by_t = down_by_t if opp_side == "DOWN" else up_by_t

    leg2_entry = None
    for i in range(trigger_tick_idx + 1, len(common_ts)):
        t = common_ts[i]
        opp_price = opp_by_t[t]
        opp_ask   = _ask(opp_price)

        if leg1_entry + opp_ask <= params.sum:
            leg2_entry = opp_ask
            break

    if leg2_entry is None:
        # Round ended before Leg 2 could fill → full loss of Leg 1 stake
        return SimResult(
            status="TRIGGERED",
            triggered_side=triggered_side,
            trigger_tick=trigger_tick_idx,
            leg1_entry=leg1_entry,
            leg2_entry=None,
            profit=-leg1_entry,
            leg2_filled=False,
            notes=f"Leg 1 filled ({triggered_side} @ {leg1_entry:.4f}), "
                  f"but Leg 2 never triggered. Full loss.",
        )

    # Both legs filled — calculate profit
    total_cost = leg1_entry + leg2_entry
    profit = round(1.0 - total_cost, 4)

    return SimResult(
        status="TRIGGERED",
        triggered_side=triggered_side,
        trigger_tick=trigger_tick_idx,
        leg1_entry=leg1_entry,
        leg2_entry=leg2_entry,
        profit=profit,
        leg2_filled=True,
        notes=f"Both legs filled. Cost={total_cost:.4f}, Profit={profit:.4f}",
    )
