import json
from datetime import datetime
from collections import OrderedDict

trades = []
with open('logs/trades.jsonl', 'r') as f:
    for line in f:
        if line.strip():
            trades.append(json.loads(line))

# 2-hour test period start: Feb 16 06:28 UTC
from datetime import timezone
TEST_START = datetime(2026, 2, 16, 6, 28, 0, tzinfo=timezone.utc).timestamp()

# Filter CLOSE trades from test period onwards
closes = [t for t in trades if t.get('action') == 'CLOSE' and t.get('timestamp', 0) >= TEST_START]

# Deduplicate by minute
seen = OrderedDict()
for t in closes:
    minute_key = int(t['timestamp'] // 60)
    if minute_key not in seen:
        seen[minute_key] = t

unique_trades = list(seen.values())
unique_trades.sort(key=lambda x: x['timestamp'])

print("=" * 70)
print("V9.5 TRADES - FROM 2-HOUR TEST ONWARDS (06:28 GMT Feb 16)")
print("=" * 70)
print(f"{'#':<3} {'TIME':<18} {'SIDE':<6} {'SHARES':<7} {'RESULT':<7} {'PROFIT':<10}")
print("-" * 70)

total_profit = 0
wins = 0
losses = 0

for i, t in enumerate(unique_trades, 1):
    ts = datetime.fromtimestamp(t['timestamp']).strftime('%Y-%m-%d %H:%M')
    side = t.get('side', '?')
    shares = t.get('shares', 0)
    won = t.get('won', False)
    profit = t.get('profit', 0)
    result = 'WIN' if won else 'LOSS'
    
    total_profit += profit
    if won:
        wins += 1
    else:
        losses += 1
    
    print(f"{i:<3} {ts:<18} {side:<6} {shares:<7} {result:<7} ${profit:+.2f}")

print("-" * 70)
wr = (wins/len(unique_trades)*100) if unique_trades else 0
print(f"\nTOTAL TRADES: {len(unique_trades)}")
print(f"WINS: {wins}")
print(f"LOSSES: {losses}")
print(f"WIN RATE: {wr:.1f}%")
print(f"TOTAL P&L: ${total_profit:+.2f}")
print("=" * 70)
