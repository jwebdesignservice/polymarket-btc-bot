import requests
import base64
import time
from datetime import datetime, timezone

now = time.time()

print(f"Current time: {datetime.fromtimestamp(now, tz=timezone.utc)}")
print(f"Comprehensive search for 5-minute markets...\n")

# Search a VERY wide range
all_5m = []

for offset in range(400000, 520000, 5000):  # Check every 5k offsets
    cursor = base64.b64encode(str(offset).encode()).decode()
    r = requests.get('https://clob.polymarket.com/markets',
                     params={'limit': 500, 'next_cursor': cursor},
                     timeout=10)
    
    if r.status_code != 200:
        continue
    
    markets = r.json()['data']
    fivemin = [m for m in markets if 'btc-updown-5m-' in m.get('market_slug', '')]
    
    for m in fivemin:
        slug = m['market_slug']
        end_ts = int(slug.split('-')[-1])
        
        # Keep markets within ±2 hours of now
        if abs(end_ts - now) <= 7200:
            all_5m.append((end_ts, m))
    
    if offset % 20000 == 0:
        print(f"  Scanned up to offset {offset}... ({len(all_5m)} relevant markets found)")

print(f"\nFound {len(all_5m)} markets within ±2 hours of now")

# Sort by time
all_5m.sort()

if all_5m:
    print("\nMarkets (soonest first):\n")
    for end_ts, m in all_5m[:30]:
        mins_away = (end_ts - now) / 60
        status = "LIVE NOW" if -5 < mins_away < 0 else ("UPCOMING" if mins_away > 0 else "ENDED")
        
        print(f"[{status:10}] {m['question'][:60]}")
        print(f"  Time: {mins_away:+.1f} min | accepting_orders={m.get('accepting_orders')}")
        print(f"  Slug: {m['market_slug']}")
        print()
else:
    print("\nNO 5-MINUTE MARKETS FOUND within ±2 hours!")
    print("These markets may:")
    print("  1. Only run during specific hours (US market hours)")
    print("  2. Be created just-in-time before they start")
    print("  3. Use a different API endpoint")
