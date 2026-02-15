"""
Quick script to find active 5-minute BTC markets for the recorder.
"""
import requests
import base64

CLOB_BASE = "https://clob.polymarket.com"

# Search at offset 440k where 5-min markets live
cursor = base64.b64encode(b'440000').decode()
r = requests.get(f"{CLOB_BASE}/markets", params={'limit': 1000, 'next_cursor': cursor})

if r.status_code == 200:
    markets = r.json()['data']
    active_5m = [m for m in markets 
                 if 'btc-updown-5m-' in m.get('market_slug', '') 
                 and m.get('active', False) 
                 and not m.get('closed', False)]
    
    print(f"Found {len(active_5m)} ACTIVE 5-minute BTC markets")
    print("\nNext 10 rounds:")
    
    # Sort by end time
    import time
    now = time.time()
    
    for m in sorted(active_5m, key=lambda x: int(x['market_slug'].split('-')[-1]))[:10]:
        slug = m['market_slug']
        end_ts = int(slug.split('-')[-1])
        mins_left = (end_ts - now) / 60
        
        if mins_left > 0:
            print(f"  {m['question']}")
            print(f"    {mins_left:.1f} minutes left")
            print(f"    condition_id: {m['condition_id']}")
else:
    print(f"Failed: {r.status_code}")
