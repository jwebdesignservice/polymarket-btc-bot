"""
optimizer.py
------------
Grid-searches all parameter combinations for the BTC Up/Down strategy
and identifies which configs are profitable over the backtested period.

Grid:
  move:      [0.10, 0.12, 0.15, 0.18, 0.20, 0.25]
  sum:       [0.90, 0.92, 0.93, 0.95, 0.97]
  windowMin: [1.0,  1.5,  2.0,  2.5,  3.0]

Total combinations: 6 × 5 × 5 = 150

Uses multiprocessing.Pool for parallelism — one worker per param combo.
"""

from __future__ import annotations

import os
import json
import itertools
import multiprocessing
from typing import Any

from simulator import SimParams, simulate_round

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

RESULTS_DIR  = os.path.join(os.path.dirname(__file__), "results")
RESULTS_FILE = os.path.join(RESULTS_DIR, "optimisation_results.json")

PARAM_GRID = {
    "move":      [0.10, 0.12, 0.15, 0.18, 0.20, 0.25],
    "sum":       [0.90, 0.92, 0.93, 0.95, 0.97],
    "windowMin": [1.0,  1.5,  2.0,  2.5,  3.0],
}


# ---------------------------------------------------------------------------
# Per-combo evaluation (runs in a subprocess)
# ---------------------------------------------------------------------------

def _evaluate_combo(args: tuple) -> dict[str, Any]:
    """
    Worker function: evaluate one parameter combo over all market rounds.
    Receives a tuple (params_dict, rounds) where rounds is a list of
    (price_history_up, price_history_down) pairs.
    """
    params_dict, rounds = args
    params = SimParams(**params_dict)

    total_profit    = 0.0
    trades          = 0       # rounds where Leg 1 triggered
    wins            = 0       # rounds where Leg 2 also filled (profit > 0)
    triggers        = 0       # same as trades (alias for clarity)
    cumulative      = []      # equity curve (profit after each round)
    equity          = 0.0

    for (hist_up, hist_down) in rounds:
        result = simulate_round(hist_up, hist_down, params)

        if result.status == "TRIGGERED":
            triggers += 1
            trades   += 1
            equity   += result.profit
            total_profit += result.profit

            if result.leg2_filled:
                wins += 1
        # NOT_TRIGGERED rounds contribute 0

        cumulative.append(round(equity, 4))

    # ---- Statistics --------------------------------------------------------
    total_rounds = len(rounds)
    trigger_rate = triggers / total_rounds if total_rounds else 0.0
    win_rate     = wins / triggers if triggers else 0.0
    avg_profit   = total_profit / trades if trades else 0.0

    # Max drawdown: largest peak-to-trough drop in equity curve
    max_drawdown = 0.0
    peak = 0.0
    for val in cumulative:
        if val > peak:
            peak = val
        dd = peak - val
        if dd > max_drawdown:
            max_drawdown = dd

    return {
        "move":               params.move,
        "sum":                params.sum,
        "windowMin":          params.windowMin,
        "total_profit":       round(total_profit, 4),
        "win_rate":           round(win_rate, 4),
        "trigger_rate":       round(trigger_rate, 4),
        "avg_profit_per_trade": round(avg_profit, 4),
        "max_drawdown":       round(max_drawdown, 4),
        "total_rounds":       total_rounds,
        "trades":             trades,
        "wins":               wins,
        "profitable":         total_profit > 0,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run(markets: list[dict]) -> list[dict]:
    """
    Run the grid search optimisation.

    Parameters
    ----------
    markets : list of market dicts with 'price_history_up' and 'price_history_down' keys.

    Returns
    -------
    List of all result dicts (including unprofitable), sorted by total_profit desc.
    """
    os.makedirs(RESULTS_DIR, exist_ok=True)

    # Build round list: list of (up_history, down_history) tuples
    rounds = []
    for mkt in markets:
        up   = mkt.get("price_history_up",   [])
        down = mkt.get("price_history_down", [])
        if up or down:
            rounds.append((up, down))

    if not rounds:
        print("[optimizer] No valid rounds found — aborting.")
        return []

    print(f"[optimizer] Loaded {len(rounds)} rounds for optimisation.")

    # Generate all parameter combos
    combos = list(itertools.product(
        PARAM_GRID["move"],
        PARAM_GRID["sum"],
        PARAM_GRID["windowMin"],
    ))
    total_combos = len(combos)
    print(f"[optimizer] Testing {total_combos} parameter combinations…")

    # Package args for worker: (params_dict, rounds)
    worker_args = [
        ({"move": m, "sum": s, "windowMin": w}, rounds)
        for (m, s, w) in combos
    ]

    # Parallel execution
    cpu_count = max(1, multiprocessing.cpu_count() - 1)
    print(f"[optimizer] Using {cpu_count} worker processes…")

    with multiprocessing.Pool(processes=cpu_count) as pool:
        all_results = pool.map(_evaluate_combo, worker_args)

    # Sort by total_profit descending
    all_results.sort(key=lambda x: x["total_profit"], reverse=True)

    # Save everything (winners + losers)
    save_json(RESULTS_FILE, all_results)

    # Print top 10
    _print_table(all_results)

    return all_results


def save_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)
    print(f"\n[optimizer] Results saved -> {path}")


def _print_table(results: list[dict]) -> None:
    """Pretty-print top 10 and bottom 5 configs to console."""
    sep = "-" * 92
    header = (
        f"{'#':>3}  {'move':>6}  {'sum':>5}  {'win':>5}  "
        f"{'profit$':>9}  {'win%':>6}  {'trig%':>6}  "
        f"{'avgP':>7}  {'drawdn':>7}  {'trades':>7}"
    )

    def _row(i: int, r: dict) -> str:
        return (
            f"{i:>3}  {r['move']:>6.2f}  {r['sum']:>5.2f}  {r['windowMin']:>5.1f}  "
            f"{r['total_profit']:>9.4f}  {r['win_rate']*100:>5.1f}%  "
            f"{r['trigger_rate']*100:>5.1f}%  "
            f"{r['avg_profit_per_trade']:>7.4f}  {r['max_drawdown']:>7.4f}  "
            f"{r['trades']:>7}"
        )

    winners = [r for r in results if r["profitable"]]
    losers  = [r for r in results if not r["profitable"]]

    print(f"\n{'='*92}")
    print(f"  TOP {min(10, len(winners))} PROFITABLE CONFIGS")
    print(sep)
    print(header)
    print(sep)
    for i, r in enumerate(winners[:10], 1):
        print(_row(i, r))

    print(f"\n  BOTTOM 5 CONFIGS (worst losses - avoid these)")
    print(sep)
    print(header)
    print(sep)
    for i, r in enumerate(reversed(losers[-5:]), 1):
        print(_row(i, r))

    print(f"{'='*92}")
    print(f"  Profitable: {len(winners)}/{len(results)}  |  "
          f"Unprofitable: {len(losers)}/{len(results)}")
    print(f"{'='*92}\n")


if __name__ == "__main__":
    # Quick standalone test with dummy data
    import fetch_history
    markets = fetch_history.run()
    run(markets)
