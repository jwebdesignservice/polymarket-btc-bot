"""
replay_backtest.py
------------------
Replays recorded order book ticks through the strategy and validates profitability.

Usage:
    python replay_backtest.py recordings/2026-02-14_16-30-00

Output:
    - Per-market simulation results
    - Summary stats (trigger rate, win rate, profit)
    - Comparison against strategy parameters
"""

import json
import os
import sys
from dataclasses import dataclass
from typing import Optional


@dataclass
class StrategyParams:
    move: float = 0.15       # 15% drop threshold
    sum: float = 0.95        # max combined ask for Leg 2
    windowMin: float = 2.0   # only watch first 2 minutes


@dataclass
class Trade:
    triggered_side: str      # "UP" or "DOWN"
    trigger_ts: float
    leg1_entry: float
    leg2_entry: Optional[float]
    profit: float
    leg2_filled: bool
    notes: str


class OrderBookSnapshot:
    """Parsed order book state at a single point in time."""
    def __init__(self, tick: dict):
        self.ts = tick["ts"]
        self.data = tick["data"]
        self.up_ask: Optional[float] = None
        self.up_bid: Optional[float] = None
        self.down_ask: Optional[float] = None
        self.down_bid: Optional[float] = None
        self._parse()
    
    def _parse(self):
        """Extract best bid/ask from WebSocket message."""
        # Polymarket WS format varies — adapt based on actual messages
        # Example structure (needs verification with real data):
        # {"asset_id": "...", "bids": [...], "asks": [...]}
        
        # This is a placeholder — will need to adjust based on real WS format
        if "book" in self.data:
            book = self.data["book"]
            up_book = book.get("UP") or book.get("Yes") or {}
            down_book = book.get("DOWN") or book.get("No") or {}
            
            if "asks" in up_book and up_book["asks"]:
                self.up_ask = float(up_book["asks"][0]["price"])
            if "bids" in up_book and up_book["bids"]:
                self.up_bid = float(up_book["bids"][0]["price"])
            
            if "asks" in down_book and down_book["asks"]:
                self.down_ask = float(down_book["asks"][0]["price"])
            if "bids" in down_book and down_book["bids"]:
                self.down_bid = float(down_book["bids"][0]["price"])


def simulate_market(ticks: list[dict], params: StrategyParams, market_meta: dict) -> Optional[Trade]:
    """
    Simulate strategy on a single market's recorded ticks.
    Returns Trade object if triggered, None otherwise.
    """
    if not ticks:
        return None
    
    # Extract round start time from slug
    slug = market_meta["market_slug"]
    try:
        round_end_ts = int(slug.split("btc-updown-15m-")[1])
    except (IndexError, ValueError):
        return None
    
    round_start_ts = round_end_ts - 15 * 60
    watch_end_ts = round_start_ts + params.windowMin * 60
    
    # State machine
    state = "WATCHING"
    prev_up_ask: Optional[float] = None
    prev_down_ask: Optional[float] = None
    leg1_side: Optional[str] = None
    leg1_entry: Optional[float] = None
    leg1_ts: Optional[float] = None
    
    for tick in ticks:
        snap = OrderBookSnapshot(tick)
        
        # Only watch during the windowMin period
        if snap.ts < round_start_ts or snap.ts > watch_end_ts:
            continue
        
        if state == "WATCHING":
            # Check for price drop trigger
            if prev_up_ask and snap.up_ask:
                drop = prev_up_ask - snap.up_ask
                if drop >= params.move:
                    # Leg 1: buy UP (dumped side)
                    leg1_side = "UP"
                    leg1_entry = snap.up_ask + 0.01  # simulate slippage
                    leg1_ts = snap.ts
                    state = "LEG1_FILLED"
            
            if prev_down_ask and snap.down_ask:
                drop = prev_down_ask - snap.down_ask
                if drop >= params.move:
                    # Leg 1: buy DOWN
                    leg1_side = "DOWN"
                    leg1_entry = snap.down_ask + 0.01
                    leg1_ts = snap.ts
                    state = "LEG1_FILLED"
            
            prev_up_ask = snap.up_ask
            prev_down_ask = snap.down_ask
        
        elif state == "LEG1_FILLED":
            # Wait for Leg 2 condition: leg1_entry + opposite_ask <= sum
            opposite_ask = snap.down_ask if leg1_side == "UP" else snap.up_ask
            
            if opposite_ask and leg1_entry + opposite_ask <= params.sum:
                # Leg 2: buy opposite
                leg2_entry = opposite_ask + 0.01
                profit = 1.0 - (leg1_entry + leg2_entry)
                
                return Trade(
                    triggered_side=leg1_side,
                    trigger_ts=leg1_ts,
                    leg1_entry=leg1_entry,
                    leg2_entry=leg2_entry,
                    profit=profit,
                    leg2_filled=True,
                    notes="Both legs filled"
                )
    
    # If we exited the loop still in LEG1_FILLED, Leg 2 never filled
    if state == "LEG1_FILLED":
        return Trade(
            triggered_side=leg1_side,
            trigger_ts=leg1_ts,
            leg1_entry=leg1_entry,
            leg2_entry=None,
            profit=-leg1_entry,
            leg2_filled=False,
            notes="Leg 2 timeout - lost stake"
        )
    
    # Never triggered
    return None


def replay_session(session_dir: str, params: StrategyParams):
    """Replay an entire recording session."""
    # Load session metadata
    session_file = os.path.join(session_dir, "session.json")
    if not os.path.exists(session_file):
        print(f"ERROR: {session_file} not found")
        return
    
    with open(session_file, encoding="utf-8") as f:
        session = json.load(f)
    
    markets = session["markets"]
    print(f"[replay] Session: {os.path.basename(session_dir)}")
    print(f"[replay] Markets recorded: {len(markets)}")
    print(f"[replay] Parameters: move={params.move} sum={params.sum} windowMin={params.windowMin}\n")
    
    results = []
    
    for market in markets:
        slug = market["market_slug"]
        tick_file = os.path.join(session_dir, f"market_{slug}.jsonl")
        
        if not os.path.exists(tick_file):
            continue
        
        # Load ticks
        ticks = []
        with open(tick_file, encoding="utf-8") as f:
            for line in f:
                ticks.append(json.load(line.strip()))
        
        print(f"  {market['question']}: {len(ticks)} ticks recorded")
        
        trade = simulate_market(ticks, params, market)
        if trade:
            results.append(trade)
            status = "WIN" if trade.profit > 0 else "LOSS"
            print(f"    -> {status}: ${trade.profit:.4f} | {trade.notes}")
        else:
            print(f"    -> No trigger")
    
    # Summary
    print("\n" + "="*70)
    print("  REPLAY SUMMARY")
    print("="*70)
    print(f"  Markets analyzed  : {len(markets)}")
    print(f"  Trades triggered  : {len(results)}")
    
    if results:
        wins = [t for t in results if t.leg2_filled and t.profit > 0]
        losses = [t for t in results if not t.leg2_filled or t.profit <= 0]
        total_profit = sum(t.profit for t in results)
        
        print(f"  Wins              : {len(wins)}")
        print(f"  Losses            : {len(losses)}")
        print(f"  Win rate          : {len(wins)/len(results)*100:.1f}%")
        print(f"  Total profit      : ${total_profit:.4f}")
        print(f"  Avg profit/trade  : ${total_profit/len(results):.4f}")
    
    print("="*70 + "\n")


def main():
    if len(sys.argv) < 2:
        print("Usage: python replay_backtest.py <session_dir>")
        print("Example: python replay_backtest.py recordings/2026-02-14_16-30-00")
        sys.exit(1)
    
    session_dir = sys.argv[1]
    params = StrategyParams()  # Use defaults; could add CLI args here
    
    replay_session(session_dir, params)


if __name__ == "__main__":
    main()
