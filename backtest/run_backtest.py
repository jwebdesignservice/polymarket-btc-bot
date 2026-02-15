"""
run_backtest.py
---------------
Main entry point for the Polymarket BTC 5-min Up/Down backtester.

Usage:
    python run_backtest.py [--force-refetch]

Flags:
    --force-refetch   Re-download all market and price data even if cached.
"""

from __future__ import annotations

import sys
import json
import os
import time

# Make sure we can import sibling modules regardless of CWD
sys.path.insert(0, os.path.dirname(__file__))

import fetch_history
import optimizer


def load_existing_results() -> list[dict] | None:
    """Load previously saved results if they exist."""
    path = os.path.join(os.path.dirname(__file__), "results", "optimisation_results.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def print_summary(all_results: list[dict]) -> None:
    """Print a human-friendly summary to console."""
    if not all_results:
        print("\n[run_backtest] No results to display.")
        return

    winners = [r for r in all_results if r["profitable"]]
    losers  = [r for r in all_results if not r["profitable"]]
    total   = len(all_results)

    top = winners[0] if winners else None
    worst = losers[-1] if losers else None

    print("\n" + "=" * 70)
    print("  BACKTEST SUMMARY")
    print("=" * 70)
    print(f"  Tested configurations : {total}")
    print(f"  Profitable            : {len(winners)}")
    print(f"  Unprofitable          : {len(losers)}")

    if top:
        print(f"\n  [TOP CONFIG]")
        print(f"     move={top['move']}  sum={top['sum']}  windowMin={top['windowMin']}")
        print(f"     Total profit : ${top['total_profit']:.4f}")
        print(f"     Win rate     : {top['win_rate']*100:.1f}%")
        print(f"     Trigger rate : {top['trigger_rate']*100:.1f}%")
        print(f"     Avg per trade: ${top['avg_profit_per_trade']:.4f}")
        print(f"     Max drawdown : ${top['max_drawdown']:.4f}")
        print(f"     Trades taken : {top['trades']} / {top['total_rounds']} rounds")
        print()
        print(f"  >> To apply in the bot:")
        print(f"     auto on 10 sum={top['sum']} move={top['move']} windowMin={top['windowMin']}")

    if worst:
        print(f"\n  [WORST CONFIG - avoid]")
        print(f"     move={worst['move']}  sum={worst['sum']}  windowMin={worst['windowMin']}")
        print(f"     Total loss : ${worst['total_profit']:.4f}")

    if winners:
        print(f"\n  Top 5 configs by profit:")
        print(f"  {'move':>6}  {'sum':>5}  {'win':>5}  {'profit':>9}  {'win%':>6}  {'trig%':>6}")
        print("  " + "-" * 55)
        for r in winners[:5]:
            print(
                f"  {r['move']:>6.2f}  {r['sum']:>5.2f}  {r['windowMin']:>5.1f}  "
                f"${r['total_profit']:>8.4f}  {r['win_rate']*100:>5.1f}%  "
                f"{r['trigger_rate']*100:>5.1f}%"
            )

    print("=" * 70 + "\n")


def main():
    force_refetch = "--force-refetch" in sys.argv

    t0 = time.time()
    print("\n" + "=" * 70)
    print("  POLYMARKET BTC 5-MIN BACKTEST & OPTIMISER")
    print("=" * 70 + "\n")

    # --- Step 1: Fetch historical data ---
    print("[Step 1/2] Fetching historical market data...\n")
    markets = fetch_history.run(force_refetch=force_refetch)

    if not markets:
        print("\n[ERROR] No markets loaded. Possible reasons:")
        print("  • API returned no matching BTC 5-min markets")
        print("  • Network connectivity issue")
        print("  • Check backtest/data/raw_markets_debug.json for API output")
        print("\nTip: Try --force-refetch to clear the cache.\n")
        sys.exit(1)

    # --- Step 2: Run optimiser ---
    print(f"\n[Step 2/2] Running grid-search optimisation over {len(markets)} rounds...\n")
    all_results = optimizer.run(markets)

    # --- Step 3: Print summary ---
    print_summary(all_results)

    elapsed = time.time() - t0
    print(f"  Completed in {elapsed:.1f}s\n")


if __name__ == "__main__":
    main()
