import json

trades = []
with open('logs/trades.jsonl', 'r') as f:
    for line in f:
        if line.strip():
            trades.append(json.loads(line))

# v9.5 session start timestamp (approx 06:26 GMT Feb 16)
# Find trades after this time
SESSION_START = 1771227960

closes = [t for t in trades if t.get('action') == 'CLOSE' and t.get('timestamp', 0) >= SESSION_START]

wins = sum(1 for t in closes if t.get('won'))
losses = len(closes) - wins
profit = sum(t.get('profit', 0) for t in closes)
wr = (wins / len(closes) * 100) if closes else 0

print("V9.5 SESSION - RAW TOTALS")
print("=" * 40)
print(f"Total Trades: {len(closes)}")
print(f"Wins: {wins}")
print(f"Losses: {losses}")
print(f"Win Rate: {wr:.1f}%")
print(f"P&L: ${profit:+.2f}")
