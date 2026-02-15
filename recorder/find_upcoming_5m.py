import requests
import base64
import time
from datetime import datetime, timezone

now = time.time()

# Search higher offsets for newer markets
for offset in [440000, 450000, 460000, 470000, 480000]:
    cursor = base64.b64encode(str(offset).encode()).decode()
    r = requests.get('https://clob.polymarket.com/markets', params={'limit': 1000, 'next_cursor': cursor})
    
    if r.status_code != 200:
        continue
    
    markets = r.json()['data']
    fivemin = [m for m in markets if 'btc-updown-5m-' in m.get('market_slug', '')]
    
    # Filter to future or very recent markets
    upcoming = []
    for m in fivemin:
        slug = m['market_slug']
        end_ts = int(slug.split('-')[-1])
        
        # Keep markets that end in the future or within last hour
        if end_ts > now - 3600:
            upcoming.append((end_ts, m))
    
    if upcoming:
        print(f"\nOffset {offset}: Found {len(upcoming)} recent/upcoming 5-min markets")
        
        # Sort by end time
        upcoming.sort()
        
        for end_ts, m in upcoming[:15]:
            mins_away = (end_ts - now) / 60
            dt = datetime.fromtimestamp(end_ts, tz=timezone.utc)
            
            if mins_away > 0:
                status = f"FUTURE: starts in {mins_away-5:.0f}min, ends in {mins_away:.0f}min"
            elif mins_away > -60:
                status = f"CLOSED {abs(mins_away):.0f}min ago"
            else:
                continue
            
            print(f"  {m['question'][:65]}")
            print(f"    {status}")
            print(f"    accepting_orders: {m.get('accepting_orders')}")

print(f"\n\nCurrent time: {datetime.fromtimestamp(now, tz=timezone.utc)}")
