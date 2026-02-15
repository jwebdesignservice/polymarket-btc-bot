# Live Order Book Recorder & Replay Backtest

This system captures **real-time order book data** from Polymarket's WebSocket and replays it through the strategy to validate profitability with **second-level precision**.

## Why This Exists

The CLOB REST API only provides 1-minute price snapshots, which can't capture the 3-second arbitrage windows our strategy targets. This recorder logs **every tick** with millisecond timestamps, giving us the data fidelity we need for honest backtesting.

---

## Setup

Install dependencies:

```bash
cd recorder
py -m pip install -r requirements.txt
```

---

## Step 1: Record Live Data

Run the recorder during active market hours (when BTC Up/Down markets are live):

```bash
py recorder.py --hours 2
```

**What it does:**
- Connects to Polymarket's WebSocket
- Subscribes to all active BTC 15-min Up/Down markets
- Logs every order book update to `recordings/YYYY-MM-DD_HH-MM-SS/market_<slug>.jsonl`
- Runs for 2 hours (or until you press Ctrl+C)
- Auto-scans for new markets every 60 seconds

**Output:**
```
recordings/2026-02-14_16-30-00/
  session.json              ← metadata (markets, timestamps)
  market_btc-updown-15m-1768191300.jsonl  ← tick data (one line per update)
  market_btc-updown-15m-1768192200.jsonl
  ...
```

---

## Step 2: Replay & Validate

Once you have recorded data, replay it through the strategy:

```bash
py replay_backtest.py recordings/2026-02-14_16-30-00
```

**What it does:**
- Loads all ticks from the session
- Simulates the strategy tick-by-tick (watching for 15% drop, then leg 2 arbitrage)
- Reports:
  - How many rounds triggered
  - Win/loss breakdown
  - Total profit/loss
  - Whether the strategy is actually profitable

---

## Expected Output (Replay)

```
[replay] Session: 2026-02-14_16-30-00
[replay] Markets recorded: 8
[replay] Parameters: move=0.15 sum=0.95 windowMin=2.0

  Bitcoin Up or Down - Jan 14, 4:00PM-4:15PM ET: 342 ticks recorded
    -> WIN: $0.0487 | Both legs filled
  Bitcoin Up or Down - Jan 14, 4:15PM-4:30PM ET: 289 ticks recorded
    -> No trigger
  Bitcoin Up or Down - Jan 14, 4:30PM-4:45PM ET: 401 ticks recorded
    -> LOSS: $-0.5200 | Leg 2 timeout - lost stake
  ...

======================================================================
  REPLAY SUMMARY
======================================================================
  Markets analyzed  : 8
  Trades triggered  : 3
  Wins              : 2
  Losses            : 1
  Win rate          : 66.7%
  Total profit      : $0.1234
  Avg profit/trade  : $0.0411
======================================================================
```

---

## Tuning Parameters

Edit `replay_backtest.py` to test different strategy params:

```python
params = StrategyParams(
    move=0.12,      # Trigger on 12% drop
    sum=0.93,       # Tighter arbitrage window
    windowMin=3.0   # Watch first 3 minutes
)
```

---

## Next Steps

1. **Record for a few hours** during US market hours (afternoons/evenings ET)
2. **Replay and validate** — does it show profit?
3. If YES → proceed to live paper-trading with $1 stakes
4. If NO → tune params or reconsider strategy

---

## Notes

- **WebSocket format:** The recorder assumes Polymarket's WS sends order book snapshots. The exact message format will need adjustment after seeing real messages (currently a placeholder in `OrderBookSnapshot._parse()`).
- **Recording bandwidth:** Each market generates ~1KB per tick. Recording 10 markets for 2 hours ≈ a few MB.
- **Strategy fidelity:** The replay simulates the exact strategy logic with 0.01 slippage added to each leg.
