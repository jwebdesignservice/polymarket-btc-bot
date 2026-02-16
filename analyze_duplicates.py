import json
from datetime import datetime
from collections import defaultdict

trades = [json.loads(l) for l in open('logs/trades.jsonl') if l.strip()]

enters = [t for t in trades if t.get('action') == 'ENTER']
closes = [t for t in trades if t.get('action') == 'CLOSE']

# Group by minute to count unique trades
unique_enter_mins = set(datetime.fromtimestamp(t['timestamp']).strftime('%Y-%m-%d %H:%M') for t in enters)
unique_close_mins = set(datetime.fromtimestamp(t['timestamp']).strftime('%Y-%m-%d %H:%M') for t in closes)

print('=== DUPLICATE ANALYSIS ===')
print(f'Raw ENTER records: {len(enters)}')
print(f'Raw CLOSE records: {len(closes)}')
print(f'Unique entry minutes: {len(unique_enter_mins)}')
print(f'Unique close minutes: {len(unique_close_mins)}')

# Deduplicate - one trade per unique minute
close_by_min = {}
for t in closes:
    minute = datetime.fromtimestamp(t['timestamp']).strftime('%Y-%m-%d %H:%M')
    if minute not in close_by_min:
        close_by_min[minute] = t

unique_closes = list(close_by_min.values())
wins = sum(1 for t in unique_closes if t.get('won'))
losses = len(unique_closes) - wins
profit = sum(t.get('profit', 0) for t in unique_closes)

print(f'\n=== TRUE STATS (1 trade per 5-min window) ===')
print(f'Completed trades: {len(unique_closes)}')
print(f'Wins: {wins}')
print(f'Losses: {losses}')
print(f'Win rate: {wins/len(unique_closes)*100:.1f}%')
print(f'Total profit: ${profit:+.2f}')

# Last 20 unique trades
print(f'\n=== LAST 20 UNIQUE TRADES ===')
sorted_closes = sorted(unique_closes, key=lambda x: x['timestamp'])
for t in sorted_closes[-20:]:
    ts = datetime.fromtimestamp(t['timestamp']).strftime('%m-%d %H:%M')
    side = t.get('side', '?')
    won = 'WIN' if t.get('won') else 'LOSS'
    prof = t.get('profit', 0)
    print(f'  {ts} | {side:4} | {won:4} | ${prof:+.2f}')
