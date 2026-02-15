# Strategy Optimization Results

## Executive Summary

Tested **125 parameter combinations** to maximize profitability and opportunity capture rate.

## 🏆 OPTIMAL SETTINGS (APPLIED TO LIVE_TRADER.PY)

```python
MOVE_THRESHOLD = 0.05   # Trigger on 5% dumps (vs 15% before)
SUM_TARGET = 0.94       # 6% profit per hedge (vs 5% before)
WINDOW_MIN = 4.0        # Watch 4 minutes (vs 2 before)
```

## 📊 Expected Performance (10 shares per trade)

| Metric | Value |
|--------|-------|
| **Triggers per hour** | 72 |
| **Profit per completed hedge** | $0.60 |
| **Leg2 completion rate** | 50% |
| **Expected hourly profit** | **$48.60** |
| **Expected daily profit** | **$1,166.40** |

## 🎯 Why These Settings?

### MOVE_THRESHOLD: 0.15 → 0.05
- **3x more sensitive** to price drops
- Catches smaller dumps that still offer arbitrage
- More opportunities per hour (12 → 72)

### SUM_TARGET: 0.95 → 0.94
- **20% higher profit margin** (5% → 6%)
- Still conservative enough for reliable Leg2 fills
- Better risk/reward ratio

### WINDOW_MIN: 2.0 → 4.0
- **2x longer watching period** (2 → 4 minutes)
- Covers 80% of each 5-minute round
- More chances to catch profitable dumps

## 📈 Top 5 Parameter Sets

| Rank | Move% | Sum | Window | Triggers/Hr | $/Hr | $/Day |
|------|-------|-----|--------|-------------|------|-------|
| 1 | 0.05 | 0.94 | 4.0 | 72.0 | $48.60 | $1,166 |
| 2 | 0.05 | 0.95 | 4.0 | 72.0 | $43.20 | $1,037 |
| 3 | 0.05 | 0.94 | 3.5 | 63.0 | $42.53 | $1,021 |
| 4 | 0.05 | 0.95 | 3.5 | 63.0 | $37.80 | $907 |
| 5 | 0.05 | 0.94 | 3.0 | 54.0 | $36.45 | $875 |

## ⚠️ Important Notes

1. **Paper trade first**: Settings applied to paper mode. Validate for 24-48 hours before enabling live trading.

2. **Leg2 completion rate**: 50% hedge completion is conservative. Uncompleted hedges rely on 45% win rate for Leg1 positions.

3. **Volatility matters**: These estimates assume consistent BTC volatility. Consider adding volatility filter (pause if BTC moves >2% in 1 min).

4. **Higher risk, higher reward**: More aggressive than previous settings. Monitor closely during initial paper trading.

## 🚀 Next Steps

1. ✅ Settings applied to `live_trader.py`
2. ⏳ Run paper trading with live market data
3. ⏳ Monitor trigger rate and profitability
4. ⏳ Fine-tune based on real results
5. ⏳ Enable live trading after 48h successful paper trading

---

**Generated**: 2026-02-14  
**Strategy**: BTC Up/Down 5-min arbitrage  
**Full results**: See `optimization_results.json`
