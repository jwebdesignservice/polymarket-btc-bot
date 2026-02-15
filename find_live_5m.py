import requests
import base64
import time
from datetime import datetime, timezone

now = time.time()

print(f"Current time: {datetime.fromtimestamp(now, tz=timezone.utc)}")
print(f"Searching for 5-minute markets with FUTURE end times...\n")

# Check higher offsets where newer markets would be
for offset in [450000, 460000, 470000, 480000, 490000]:
    cursor = base64.b64encode(str(offset).encode()).decode()
    r = requests.get('https://clob.polymarket.com/markets',
                     params={'limit': 1000, 'next_cursor': cursor})
    
    if r.status_code != 200:
        continue
    
    markets = r.json()['data']
    fivemin = [m for m in markets if 'btc-updown-5m-' in m.get('market_slug', '')]
    
    # Filter to FUTURE markets
    future = []
    for m in fivemin:
        slug = m['market_slug']
        end_ts = int(slug.split('-')[-1])
        
        if end_ts > now:  # FUTURE
            mins_away = (end_ts - now) / 60
            future.append((end_ts, m, mins_away))
    
    if future:
        print(f"\nOffset {offset}: Found {len(future)} FUTURE 5-minute markets!")
        
        # Sort by soonest first
        future.sort()
        
        for end_ts, m, mins_away in future[:20]:
            start_ts = end_ts - 5*60
            mins_to_start = (start_ts - now) / 60
            
            print(f"\n  {m['question'][:70]}")
            print(f"    Starts in: {mins_to_start:.1f} min")
            print(f"    Ends in: {mins_away:.1f} min")
            print(f"    Slug: {m['market_slug']}")
            print(f"    Condition ID: {m['condition_id'][:40]}")
            print(f"    Accepting orders: {m.get('accepting_orders')}")
            
            tokens = m.get('tokens', [])
            if tokens:
                print(f"    Tokens: {len(tokens)} ({', '.join(t['outcome'] for t in tokens[:2])})")
        
        print(f"\n>>> Use these markets for live trading! <<<")
        break

if not future:
    print("\nNo future 5-minute markets found. They may start at specific times (e.g. on the hour).")
