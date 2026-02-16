import json
from datetime import datetime
from collections import OrderedDict

trades = []
with open('logs/trades.jsonl', 'r') as f:
    for line in f:
        if line.strip():
            trades.append(json.loads(line))

# Filter only CLOSE trades (completed)
closes = [t for t in trades if t.get('action') == 'CLOSE']

# Deduplicate by minute (keep first entry per minute)
seen = OrderedDict()
for t in closes:
    ts = t.get('timestamp', 0)
    minute_key = int(ts // 60)
    if minute_key not in seen:
        seen[minute_key] = t

unique_trades = list(seen.values())

# Sort by time
unique_trades.sort(key=lambda x: x['timestamp'])

print("=" * 80)
print("TRUE V9.5 TRADES (Deduplicated - One per 5-minute round)")
print("=" * 80)
print(f"{'#':<4} {'TIME':<20} {'SIDE':<6} {'SHARES':<8} {'RESULT':<8} {'PROFIT':<10}")
print("-" * 80)

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
    
    print(f"{i:<4} {ts:<20} {side:<6} {shares:<8} {result:<8} ${profit:+.2f}")

print("-" * 80)
print(f"\nTOTAL UNIQUE TRADES: {len(unique_trades)}")
print(f"WINS: {wins}")
print(f"LOSSES: {losses}")
print(f"WIN RATE: {wins/len(unique_trades)*100:.1f}%")
print(f"TOTAL P&L: ${total_profit:+.2f}")
print("=" * 80)
