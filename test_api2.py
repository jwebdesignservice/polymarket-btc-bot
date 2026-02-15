import requests
import time

# Try different query approaches
print("1. Checking CLOB markets with offset...")
r = requests.get('https://clob.polymarket.com/markets?limit=100&offset=440000')
markets = r.json()['data']
btc_5m = [m for m in markets if 'btc-updown-5m' in m.get('market_slug', '')]
print(f"   Found {len(btc_5m)} BTC 5-min markets at offset 440000")
if btc_5m:
    latest = btc_5m[0]
    print(f"   Latest: {latest['market_slug']}")
    print(f"   Closed: {latest['closed']}, Accepting: {latest['accepting_orders']}")
    print()

print("2. Checking Gamma series endpoint...")
r2 = requests.get('https://gamma-api.polymarket.com/series/btc-up-or-down-5m')
print(f"   Response: {r2.status_code}")
if r2.status_code == 200:
    data = r2.json()
    print(f"   Series data keys: {list(data.keys())}")
    if 'events' in data:
        print(f"   Events: {len(data['events'])}")
        active = [e for e in data['events'] if e.get('active')]
        print(f"   Active events: {len(active)}")
        if active:
            print(f"   First active: {active[0].get('slug', 'N/A')}")
print()

print("3. Current Unix timestamp:")
print(f"   {int(time.time())}")
print(f"   Expected slug: btc-updown-5m-{int(time.time())}")
