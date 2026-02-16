import json
from datetime import datetime

trades = []
with open('logs/trades.jsonl', 'r') as f:
    for line in f:
        if line.strip():
            trades.append(json.loads(line))

# v9.5 session start: Feb 16 06:26 GMT
from datetime import datetime, timezone
SESSION_START = datetime(2026, 2, 16, 6, 26, 0, tzinfo=timezone.utc).timestamp()

# Deduplicate CLOSE trades by minute
seen = {}
deduped = []
for t in trades:
    if t.get('action') != 'CLOSE':
        continue
    ts = t.get('timestamp', 0)
    if ts < SESSION_START:
        continue
    minute = int(ts // 60)
    if minute not in seen:
        seen[minute] = True
        deduped.append(t)

wins = sum(1 for t in deduped if t.get('won'))
losses = len(deduped) - wins
profit = sum(t.get('profit', 0) for t in deduped)
wr = (wins / len(deduped) * 100) if deduped else 0

print("V9.5 SESSION (since 06:26 GMT)")
print("=" * 40)
print(f"Trades: {len(deduped)}")
print(f"Record: {wins}W / {losses}L")
print(f"Win Rate: {wr:.1f}%")
print(f"P&L: ${profit:+.2f}")
