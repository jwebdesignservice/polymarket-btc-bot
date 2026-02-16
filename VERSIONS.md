# Bot Versions

## v10_SELECTIVE (Current - Feb 16, 2026)
**File:** `live_trader_v10_selective.py`

### Strategy: Skip Low Confidence, Trade Mid & High Only
- **HIGH confidence (≥75%, strong momentum):** 15 shares
- **MED confidence (≥50%, decent momentum):** 10 shares
- **LOW confidence (weak signals):** SKIP ⏭️

### Key Changes from v9:
- No more forced entries on weak signals
- Returns 0 shares (skip) instead of 2 shares on low confidence
- Entry window closing = skip, not force bet

### Performance (53 mins into test):
- **Win Rate:** 78.9% (15W / 4L)
- **P&L:** +$65.00
- **Trades:** Only taking high/mid confidence setups

### Why It Works:
1. Eliminates -$51.90 bleed from low confidence trades
2. Only bets when signals actually agree
3. Quality over quantity

---

## v9.5_SMARTSCALE (Feb 15, 2026)
**File:** `live_trader_v9_SMARTSCALE.py`

### Strategy: Confidence-Based Position Sizing
- **High confidence (>75%):** 15 shares → Big wins (+$7.50)
- **Medium confidence (50-75%):** 10 shares → Medium wins (+$5.00)
- **Low confidence (<50%):** 5 shares → Small losses (-$2.50)

### Key Features:
- DOWN bias when uncertain (77% historical win rate)
- Momentum-based direction picking
- Dynamic sizing reduces loss impact
- Trades every 5 minutes, 24/7

### Performance (Last 20 trades):
- **Win Rate:** 70.0% (14W / 6L)
- **Net P&L:** +$32.70
- **Avg Win:** $3.15
- **Avg Loss:** $2.00

### Why It Works:
1. Bigger bets on high-confidence signals (high win rate)
2. Smaller bets on uncertain signals (limits damage)
3. DOWN bias exploits market tendency
4. Asymmetric risk: wins > losses on average

---

## Previous Versions:
- v9_momentum: Fixed 15-share positions (no scaling)
- v8_hedge: Buy both sides, exit loser (spread dependent)
- v7_fast_arb: Arbitrage attempt (spread issues)
- v6_arbitrage: Market making (spread issues)
- v5_probability: Probability-based
- v4_momentum: Basic momentum
