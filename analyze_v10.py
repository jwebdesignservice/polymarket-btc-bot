import json
from collections import defaultdict
import os

# Use the directory where the script is located
script_dir = os.path.dirname(os.path.abspath(__file__))
trades_file = os.path.join(script_dir, 'logs', 'trades.jsonl')

stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'profit': 0, 'trades': 0})

with open(trades_file) as f:
    for line in f:
        t = json.loads(line)
        if t.get('action') == 'CLOSE' and t.get('shares', 0) > 0:
            version = t.get('version', 'v10')
            won = t.get('won', False)
            profit = t.get('profit', 0)
            
            stats[version]['trades'] += 1
            stats[version]['profit'] += profit
            if won:
                stats[version]['wins'] += 1
            else:
                stats[version]['losses'] += 1

print('=== REAL TRADES BY VERSION (shares > 0) ===')
print()
total_trades = 0
total_profit = 0
total_wins = 0
total_losses = 0
for version in sorted(stats.keys()):
    s = stats[version]
    wr = (s['wins'] / s['trades'] * 100) if s['trades'] > 0 else 0
    print(f'{version}: {s["wins"]}W/{s["losses"]}L ({wr:.1f}%) | Profit: ${s["profit"]:.2f} | Trades: {s["trades"]}')
    total_trades += s['trades']
    total_profit += s['profit']
    total_wins += s['wins']
    total_losses += s['losses']

print()
total_wr = (total_wins / total_trades * 100) if total_trades > 0 else 0
print(f'TOTAL: {total_wins}W/{total_losses}L ({total_wr:.1f}%) | ${total_profit:.2f} profit | {total_trades} trades')
