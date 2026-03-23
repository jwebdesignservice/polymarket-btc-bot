# Bot Fixes - Investigation Results

## Issue 1: Bot Stability (Crashes)
**Root Cause:** Multiple factors identified
- Previous crashes were from duplicate bot instances killing each other
- Windows process linkage when using Start-Process with pipes
- No graceful shutdown on errors

**Fix:** Already mostly resolved by:
- Single instance lock ✓
- Using `-WindowStyle Hidden` without pipes ✓
- Clean startup script ✓

**Additional fix needed:** Add watchdog auto-restart (see Issue 4)

---

## Issue 2: Target Price Accuracy
**Root Cause:** v9.5 line 488:
```python
self.target_price = self.btc_price if self.btc_price else 70000
```
Uses current BTC price, not actual market target.

**Fix:** Parse target from market title:
```python
# Extract target from title like "Bitcoin Up or Down - $68,642.00"
import re
title = event['title']  # from Gamma API
match = re.search(r'\$([0-9,]+\.?\d*)', title)
if match:
    self.target_price = float(match.group(1).replace(',', ''))
else:
    self.target_price = self.btc_price  # fallback
```

**Risk:** LOW - only affects edge cases where BTC moves significantly during discovery

---

## Issue 4: Single Point of Failure
**Root Cause:** No auto-restart if bot dies

**Fix:** Create watchdog script that:
1. Checks if bot is running every 60 seconds
2. Restarts if dead
3. Logs restarts

```powershell
# watchdog.ps1
while ($true) {
    $lock = Get-Content "logs/bot.lock" -ErrorAction SilentlyContinue
    $running = $false
    if ($lock) {
        try { Get-Process -Id $lock -ErrorAction Stop; $running = $true } catch {}
    }
    
    if (-not $running) {
        "$(Get-Date): Bot died, restarting..." | Add-Content "logs/watchdog.log"
        Remove-Item "logs/bot.lock" -Force -ErrorAction SilentlyContinue
        Start-Process python -ArgumentList "-u", "live_trader_v9.5_momentum.py" -WindowStyle Hidden
    }
    Start-Sleep -Seconds 60
}
```

---

## Issue 5: Binance Feed Dependency
**Current State:** Already has robust reconnection (100 retries, exponential backoff)

**Fix:** Add secondary price source as fallback (optional, low priority)
- Coinbase API: `wss://ws-feed.exchange.coinbase.com`
- Only needed if Binance has extended outage

**Risk:** LOW - Binance is reliable, current retry logic handles brief outages

---

## Issue 6: Position Recovery
**Root Cause:** Position state saved but not recovered on restart

**Current code saves to:** `position_state.json`
**Missing:** Recovery logic on startup

**Fix:** Add to `run()` method:
```python
async def run(self):
    # Try to recover position from last session
    try:
        with open('position_state.json', 'r') as f:
            state = json.load(f)
        if state.get('has_position') and state.get('side'):
            # Check if we're still in the same round
            if time.time() - state.get('round_start', 0) < 300:
                self.position = {
                    'side': state['side'],
                    'shares': state['shares'],
                    'entry_price': state.get('entry_price', 0.5),
                    'has_entered': True
                }
                self.target_price = state['target_price']
                self.round_start_time = state['round_start']
                logger.info(f"Recovered position: {state['shares']} {state['side']}")
    except Exception as e:
        logger.info("No position to recover")
```

---

## Implementation Priority

1. **Watchdog script** (Issue 4) - Prevents missed trades from crashes
2. **Position recovery** (Issue 6) - Prevents lost position tracking
3. **Target price parsing** (Issue 2) - Improves accuracy on edge cases

## Safe to Implement Now?
YES - All fixes are additive, don't change trading logic
