"""Analyze v9.5 session stats (last ~2.5 hours)"""
import json
from datetime import datetime, timedelta
from collections import defaultdict

# v9.5 started around 06:26 GMT on Feb 16
SESSION_START = datetime(2026, 2, 16, 6, 26, 0)

trades = []
with open('logs/trades.jsonl', 'r') as f:
    for line in f:
        if line.strip():
            trades.append(json.loads(line))

# Filter to v9.5 session and deduplicate by minute
closes_by_min = {}
for t in trades:
    if t.get('action') != 'CLOSE':
        continue
    
    ts = datetime.fromtimestamp(t['timestamp'])
    if ts < SESSION_START:
        continue
    
    minute_key = ts.strftime('%Y-%m-%d %H:%M')
    if minute_key not in closes_by_min:
        closes_by_min[minute_key] = t

session_trades = list(closes_by_min.values())
session_trades.sort(key=lambda x: x['timestamp'])

# Calculate stats
wins = sum(1 for t in session_trades if t.get('won'))
losses = len(session_trades) - wins
total_profit = sum(t.get('profit', 0) for t in session_trades)
win_rate = (wins / len(session_trades) * 100) if session_trades else 0

print("=" * 60)
print("V9.5 SESSION STATS (since 06:26 GMT)")
print("=" * 60)
print(f"Total Trades: {len(session_trades)}")
print(f"Wins: {wins}")
print(f"Losses: {losses}")
print(f"Win Rate: {win_rate:.1f}%")
print(f"Total P&L: ${total_profit:+.2f}")
print(f"Avg Profit: ${total_profit/len(session_trades) if session_trades else 0:+.2f}")
print("=" * 60)

# Last 10 trades
print("\nLast 10 trades:")
for t in session_trades[-10:]:
    ts = datetime.fromtimestamp(t['timestamp']).strftime('%H:%M')
    side = t.get('side', '?')
    won = 'WIN' if t.get('won') else 'LOSS'
    profit = t.get('profit', 0)
    shares = t.get('shares', 0)
    print(f"  {ts} | {side:4} | {shares:2} shares | {won:4} | ${profit:+.2f}")

# Hourly breakdown
print("\nHourly breakdown:")
hourly = defaultdict(lambda: {'wins': 0, 'losses': 0, 'profit': 0})
for t in session_trades:
    hour = datetime.fromtimestamp(t['timestamp']).strftime('%H:00')
    if t.get('won'):
        hourly[hour]['wins'] += 1
    else:
        hourly[hour]['losses'] += 1
    hourly[hour]['profit'] += t.get('profit', 0)

for hour in sorted(hourly.keys()):
    h = hourly[hour]
    total = h['wins'] + h['losses']
    wr = (h['wins'] / total * 100) if total else 0
    print(f"  {hour}: {h['wins']}W/{h['losses']}L ({wr:.0f}%) | ${h['profit']:+.2f}")
