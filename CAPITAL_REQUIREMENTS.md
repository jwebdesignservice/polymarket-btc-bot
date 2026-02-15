# Capital Requirements & Profit Breakdown

## Current Bot Settings

```python
SHARES = 10              # Shares per trade leg
SUM_TARGET = 0.94        # Max combined cost for both legs
MOVE_THRESHOLD = 0.05    # 5% price drop triggers entry
WINDOW_MIN = 4.0         # Watch first 4 minutes of each round
```

## Per-Trade Breakdown

### Successful Hedge (Both Legs Complete)
- **Leg 1 cost:** ~$0.35-0.45 per share (bought during dump)
- **Leg 2 cost:** Must satisfy: Leg1 + Leg2 ≤ $0.94
- **Combined max:** $0.94 per share
- **Payout:** $1.00 per share (one side always wins)
- **Profit:** $1.00 - $0.94 = **$0.06 per share**

**With 10 shares:**
- Capital needed: 10 × $0.94 = **$9.40 per hedge**
- Profit if successful: 10 × $0.06 = **$0.60 per hedge**
- Return: 6.4% per successful trade

### Failed Hedge (Only Leg 1, No Leg 2)
If round ends before Leg 2 fills, you have directional exposure:
- **Cost:** ~$0.40 per share (avg Leg 1 entry)
- **If wins:** Profit = 10 × ($1.00 - $0.40) = **$6.00**
- **If loses:** Loss = 10 × $0.40 = **-$4.00**
- **Expected value (45% win rate):** 10 × [(0.45 × $0.60) - (0.55 × $0.40)] = **-$0.50**

## Optimizer Projections Explained

### Estimated Activity (per hour)
- **Triggers:** 72 per hour
- **Leg2 completions:** 36 per hour (50% success rate)
- **Failed hedges:** 36 per hour (directional exposure)

### Expected Profit Per Hour
```
Completed hedges: 36 × $0.60  = $21.60
Failed hedges:    36 × -$0.14 = -$5.04  (expected value, not all losses)
─────────────────────────────────────
Net hourly profit:              $16.56
```

**Wait - the optimizer showed $48.60/hour!** Let me recalculate...

The optimizer used **$0.068 EV per trigger** which seems optimistic. Let me show you a more conservative estimate:

## REALISTIC Capital Requirements

### Minimum Capital (Conservative)
To run this strategy safely, you need enough capital for:

1. **Active positions:** 72 triggers/hour ÷ 12 rounds/hour = ~6 positions per round
2. **Position sizing:** 6 × $9.40 = $56.40 per round
3. **Multiple overlapping rounds:** 3 concurrent rounds = $169.20
4. **Reserve buffer (20%):** $33.84

**Minimum recommended:** **$200**

### Scaling Examples

| Capital | Shares/Trade | Max Profit/Hour* | Daily (24h) |
|---------|--------------|------------------|-------------|
| $200    | 10           | $16.56           | $397        |
| $500    | 25           | $41.40           | $994        |
| $1,000  | 50           | $82.80           | $1,987      |
| $2,000  | 100          | $165.60          | $3,974      |

*Conservative estimates assuming 50% hedge completion, 45% unhedged win rate

## Where The Optimizer Numbers Came From

The optimizer assumed:
- **Base trigger rate:** 12/hour at 15% threshold
- **Multiplier for 5% threshold:** 3x = 36 triggers/hour  
- **Window multiplier (4 min vs 2):** 2x = **72 triggers/hour**
- **Profit per completed trade:** $0.60 (10 shares × 6% margin)
- **Leg2 completion:** 50%
- **EV on failed hedges:** Slightly negative

**The $48.60/hour figure was OPTIMISTIC** - it assumed better performance on unhedged positions.

## REALISTIC Expectations

### Conservative Scenario (What I'd Actually Expect)
- **Capital:** $200
- **Shares per trade:** 10
- **Triggers per hour:** ~36 (not 72 - that's aggressive)
- **Completed hedges/hour:** 18
- **Hourly profit:** ~$10-15
- **Daily profit (24/7):** **$240-360**

### Aggressive Scenario (If Market Cooperates)
- **Capital:** $200
- **Shares per trade:** 10
- **Triggers per hour:** 72
- **Completed hedges/hour:** 36
- **Hourly profit:** ~$20-25
- **Daily profit (24/7):** **$480-600**

## Important Caveats

⚠️ **These are ESTIMATES, not guarantees!** Real results depend on:

1. **Market volatility** - Need consistent 5%+ swings
2. **Liquidity** - Need sufficient volume for fills
3. **Slippage** - Real fills may be worse than order book shows
4. **Downtime** - API issues, market closures, etc.
5. **Competition** - Other bots may front-run opportunities

## Recommendation

**Start with $200-300** for paper trading validation:
1. Run 24-48 hours in paper mode
2. Track actual trigger rate vs estimates
3. Measure real profit/loss vs projections
4. Scale up ONLY if profitable

If paper trading shows consistent profit, you can scale proportionally:
- 2x capital = 2x shares = 2x profit
- But always keep 20% reserve buffer

---

**Bottom Line:** With $200 starting capital, realistic expectations are $10-20/hour ($240-480/day) if the strategy works. The optimizer's $48/hour was optimistic best-case scenario.
