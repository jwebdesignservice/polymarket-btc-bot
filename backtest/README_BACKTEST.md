# Polymarket BTC 5-Min Backtest & Optimiser

Simulate the dual-leg arbitrage strategy across real historical Polymarket data
and find the parameter combinations that maximise profit.

---

## Quick Start

```bash
# 1. Install dependencies (only `requests` needed)
pip install -r requirements.txt

# 2. Run the full pipeline
python run_backtest.py

# 3. Force a fresh data download (ignores cache)
python run_backtest.py --force-refetch
```

That's it. The script will:
1. Download historical BTC Up/Down 5-min markets from Polymarket's public API
2. Run 150 parameter combinations in parallel
3. Print the top 10 profitable configs and the 5 worst configs
4. Save full results to `backtest/results/optimisation_results.json`

---

## Strategy Recap

Each 5-minute BTC market has two sides: **UP** and **DOWN**.

| Step | What happens |
|------|-------------|
| **Watch** | Monitor the first `windowMin` minutes of the round |
| **Leg 1** | If either side drops `move`% in one tick → buy that side at `ask = price + 0.01` |
| **Leg 2** | After Leg 1 fills, wait until `leg1_ask + opposite_ask ≤ sum` → buy the other side |
| **Win** | Both legs filled → profit = `1.0 − (leg1_entry + leg2_entry)` per share |
| **Loss** | Round ends before Leg 2 → loss = `leg1_entry` (full stake) |
| **No trade** | Leg 1 never triggered → $0 cost |

---

## Parameter Grid

| Parameter | Values tested |
|-----------|--------------|
| `move` | 0.10, 0.12, 0.15, 0.18, 0.20, 0.25 |
| `sum` | 0.90, 0.92, 0.93, 0.95, 0.97 |
| `windowMin` | 1.0, 1.5, 2.0, 2.5, 3.0 |

**Total combinations:** 6 × 5 × 5 = **150**

---

## Interpreting Results

After the run, the console prints a table with these columns:

| Column | Meaning |
|--------|---------|
| `move` | Price drop threshold to trigger Leg 1 |
| `sum` | Max combined ask for Leg 2 entry |
| `win` | `windowMin` — observation window in minutes |
| `profit$` | Total simulated profit across all rounds (in dollars per share) |
| `win%` | % of triggered trades where Leg 2 also filled (both legs profitable) |
| `trig%` | % of rounds where Leg 1 was triggered |
| `avgP` | Average profit per trade |
| `drawdn` | Maximum drawdown (peak-to-trough equity drop) |
| `trades` | Number of rounds where Leg 1 triggered |

**A config passes if:** `total_profit > 0` over the full 24-hour test period.

**What to look for:**
- High `profit$` with reasonable `max_drawdown`
- `win%` > 50% — more wins than losses on triggered trades
- `trig%` > 0% but not too high (very high trigger rate may indicate false positives)

---

## Applying the Best Config to the Bot

Once you have your top config, apply it in the Discord bot:

```
auto on 10 sum=0.95 move=0.15 windowMin=2.0
```

Replace `0.95`, `0.15`, and `2.0` with the values from your top result.

The full bot command syntax is:
```
auto on <stake_usdc> sum=<sum> move=<move> windowMin=<windowMin>
```

---

## Output Files

| File | Contents |
|------|----------|
| `backtest/data/markets.json` | Raw market metadata fetched from Gamma API |
| `backtest/data/prices_{id}.json` | Price history (UP + DOWN) per market round |
| `backtest/results/optimisation_results.json` | All 150 configs with stats, sorted by profit |

---

## ⚠️ Data Fidelity Limitations

> **Important:** Polymarket's CLOB API returns price data at **1-minute resolution** (fidelity=1).

The live strategy detects price drops within a **3-second sliding window**. In this backtest:

- We **approximate** the 3-second trigger by comparing consecutive 1-minute ticks
- If a price drops ≥ `move` between two 1-minute bars, we call it triggered
- **Short-lived spikes** (drop and recovery within 1 minute) will be **missed**
- **Trigger rates** from this backtest are likely **lower** than in live trading
- **Profits** are likely **conservative** — real performance may be better

This means:
- The backtest gives you a **lower bound** on trigger rate and profit
- Configs that are profitable here have a good chance of being profitable live
- Do not expect exact match between backtest and live results

---

## File Structure

```
polymarket-bot/
└── backtest/
    ├── run_backtest.py        ← Main entry point
    ├── fetch_history.py       ← Downloads historical market data
    ├── simulator.py           ← Replays individual rounds
    ├── optimizer.py           ← Grid-searches all param combos
    ├── requirements.txt       ← pip install -r requirements.txt
    ├── README_BACKTEST.md     ← This file
    ├── data/
    │   ├── markets.json
    │   └── prices_*.json
    └── results/
        └── optimisation_results.json
```

---

## Troubleshooting

**"No markets loaded"**
- The Gamma API may have changed its market structure. Check `data/raw_markets_debug.json`.
- Try adding more keyword variants in `fetch_history.py` → `BTC_KEYWORDS` / `FIVEMIN_KEYWORDS`.

**"Insufficient ticks for simulation"**
- Some markets have very sparse price history. The backtest skips these gracefully.

**Slow run**
- The optimiser uses `multiprocessing.Pool` with N-1 CPU cores by default.
- You can tune `cpu_count` in `optimizer.py` if needed.

**Re-run without re-downloading data**
- Just run `python run_backtest.py` (no flag). Cached data in `backtest/data/` is reused.
