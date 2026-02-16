import json
from datetime import datetime

trades = []
with open('logs/trades.jsonl', 'r') as f:
    for line in f:
        if line.strip():
            trades.append(json.loads(line))

# Filter CLOSE trades from 06:28 - 08:28 GMT
closes = [t for t in trades if t.get('action') == 'CLOSE']
start = datetime(2026, 2, 16, 6, 28).timestamp()
end = datetime(2026, 2, 16, 8, 28).timestamp()

in_range = [t for t in closes if start <= t.get('timestamp', 0) <= end]
print(f'RAW CLOSE entries 06:28-08:28: {len(in_range)}')

# Show all entries
print('\nAll entries in range:')
for t in sorted(in_range, key=lambda x: x['timestamp']):
    ts = datetime.fromtimestamp(t['timestamp']).strftime('%H:%M:%S')
    side = t.get('side', '?')
    won = 'WIN' if t.get('won') else 'LOSS'
    shares = t.get('shares', 0)
    profit = t.get('profit', 0)
    print(f'  {ts} | {side:4} | {shares:2} shares | {won:4} | ${profit:+.2f}')

# RAW stats
wins = sum(1 for t in in_range if t.get('won'))
losses = len(in_range) - wins
profit = sum(t.get('profit', 0) for t in in_range)
print(f'\nRAW Stats: {wins}W/{losses}L | ${profit:+.2f}')

# The issue: if we're showing raw duplicates as unique trades,
# the numbers would be inflated by 3-4x
print(f'\nIf treating duplicates as unique: {len(in_range)} trades, {wins}W/{losses}L')
print(f'This gives win rate: {wins/len(in_range)*100:.1f}%')
