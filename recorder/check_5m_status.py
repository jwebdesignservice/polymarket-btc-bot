import requests
import base64
import time

cursor = base64.b64encode(b'440000').decode()
r = requests.get('https://clob.polymarket.com/markets', params={'limit': 1000, 'next_cursor': cursor})

markets = r.json()['data']
fivemin = [m for m in markets if 'btc-updown-5m-' in m.get('market_slug', '')]

print(f"Total 5-min markets at this offset: {len(fivemin)}")

# Check flags
now = time.time()

for m in fivemin[:10]:
    slug = m['market_slug']
    end_ts = int(slug.split('-')[-1])
    mins_from_now = (end_ts - now) / 60
    
    active = m.get('active')
    closed = m.get('closed')
    accepting = m.get('accepting_orders')
    
    status = f"active={active} closed={closed} accepting={accepting}"
    time_status = f"{mins_from_now:+.1f}min" if abs(mins_from_now) < 60 else f"{mins_from_now/60:+.1f}h"
    
    print(f"\n{m['question'][:60]}")
    print(f"  {status}")
    print(f"  End time: {time_status}")
    
    # Check if there's still time left
    if end_ts > now and (end_ts - now) < 600:  # Next 10 minutes
        print(f"  >>> UPCOMING SOON!")
