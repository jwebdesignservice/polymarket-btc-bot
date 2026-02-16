import json
from datetime import datetime

trades = []
with open('logs/trades.jsonl', 'r') as f:
    for line in f:
        if line.strip():
            trades.append(json.loads(line))

# Filter only CLOSE actions (completed trades with results)
closed = [t for t in trades if t.get('action') == 'CLOSE']
opens = [t for t in trades if t.get('action') == 'ENTER' and t.get('status') == 'open']

print(f"Total log entries: {len(trades)}")
print(f"Completed trades: {len(closed)}")
print(f"Currently open: {len(opens)}")
print()

print("LAST 20 COMPLETED TRADES:")
print("-" * 75)
print(f"{'TIME':<20} {'SIDE':<6} {'SHARES':<8} {'RESULT':<8} {'PROFIT':<10}")
print("-" * 75)

for t in closed[-20:]:
    ts = t.get('timestamp', 0)
    ts = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')
    
    side = t.get('side', 'N/A')
    shares = t.get('shares', 0)
    won = t.get('won', False)
    result = 'WIN' if won else 'LOSS'
    profit = t.get('profit', 0)
    
    print(f"{ts:<20} {side:<6} {shares:<8} {result:<8} ${profit:+.2f}")

print("-" * 75)

# Summary
wins = sum(1 for t in closed[-20:] if t.get('won'))
losses = 20 - wins if len(closed) >= 20 else len(closed) - wins
total_profit = sum(t.get('profit', 0) for t in closed[-20:])
print(f"\nLast 20 completed: {wins}W/{losses}L | Total Profit: ${total_profit:+.2f}")

# Overall stats
all_wins = sum(1 for t in closed if t.get('won'))
all_losses = len(closed) - all_wins
all_profit = sum(t.get('profit', 0) for t in closed)
win_rate = (all_wins / len(closed) * 100) if closed else 0
print(f"All time: {all_wins}W/{all_losses}L ({win_rate:.1f}%) | Total Profit: ${all_profit:+.2f}")
