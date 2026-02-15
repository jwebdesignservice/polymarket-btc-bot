import requests

# Try searching by slug pattern directly
print("1. Searching for slug pattern 'btc-updown-5m'...")
r = requests.get('https://gamma-api.polymarket.com/events?limit=100&closed=false')
if r.status_code == 200:
    events = r.json()
    btc_events = [e for e in events if e.get('slug', '').startswith('btc-updown-5m')]
    print(f"   Found {len(btc_events)} BTC 5-min markets")
    
    if btc_events:
        e = btc_events[0]
        print(f"   Title: {e.get('title')}")
        print(f"   Slug: {e.get('slug')}")
        markets = e.get('markets', [])
        if markets:
            m = markets[0]
            print(f"   Condition: {m.get('conditionId')}")
            print(f"   Tokens: {m.get('clobTokenIds', 'N/A')}")
    else:
        print(f"   Slugs in response: {[e.get('slug','')[:30] for e in events[:5]]}")

print("\n2. Trying markets endpoint directly...")
r2 = requests.get('https://gamma-api.polymarket.com/markets?limit=100&closed=false&active=true')
if r2.status_code == 200:
    markets = r2.json()
    btc_markets = [m for m in markets if 'btc-updown-5m' in m.get('slug', '')]
    print(f"   Found {len(btc_markets)} BTC 5-min markets")
    if btc_markets:
        m = btc_markets[0]
        print(f"   Question: {m.get('question')}")
        print(f"   Condition: {m.get('conditionId')}")
else:
    print(f"   Status: {r2.status_code}")

print("\n3. Trying event by slug (from user's data)...")
# From user's JSON: "btc-updown-5m-1771080900"
r3 = requests.get('https://gamma-api.polymarket.com/events/btc-updown-5m-1771093500')
print(f"   Status: {r3.status_code}")
if r3.status_code == 200:
    event = r3.json()
    print(f"   Title: {event.get('title')}")
    print(f"   Closed: {event.get('closed')}")
    markets = event.get('markets', [])
    if markets:
        m = markets[0]
        print(f"   Condition: {m.get('conditionId')}")
        print(f"   Tokens: {m.get('clobTokenIds')}")
