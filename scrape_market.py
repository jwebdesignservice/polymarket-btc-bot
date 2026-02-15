import requests
import re
import json
import time

def scrape_current_btc_market():
    """Scrape polymarket.com to get current BTC 5-min market data"""
    
    # Calculate current 5-min slot
    now = int(time.time())
    slot = (now // 300) * 300
    
    # Try the specific market page
    url = f"https://polymarket.com/event/btc-updown-5m-{slot}"
    print(f"Trying slot {slot}...")
    
    print(f"Fetching {url}...")
    r = requests.get(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    
    if r.status_code != 200:
        print(f"Failed: {r.status_code}")
        return None
    
    # Extract window.__NEXT_DATA__ from the HTML
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>', r.text)
    
    if not match:
        print("Could not find __NEXT_DATA__ in page")
        return None
    
    data = json.loads(match.group(1))
    
    # Navigate the structure to find event data
    queries = data.get('props', {}).get('pageProps', {}).get('dehydratedState', {}).get('queries', [])
    
    # Find the event/slug query
    for query in queries:
        query_key = query.get('queryKey', [])
        if len(query_key) >= 2 and query_key[0] == '/api/event/slug':
            event_data = query.get('state', {}).get('data', {})
            
            if event_data:
                markets = event_data.get('markets', [])
                if markets:
                    market = markets[0]
                    
                    return {
                        'title': event_data.get('title'),
                        'slug': event_data.get('slug'),
                        'closed': event_data.get('closed'),
                        'condition_id': market.get('conditionId'),
                        'token_ids': {
                            'Up': market.get('clobTokenIds', [])[0] if len(market.get('clobTokenIds', [])) > 0 else None,
                            'Down': market.get('clobTokenIds', [])[1] if len(market.get('clobTokenIds', [])) > 1 else None
                        }
                    }
    
    print("Could not find market data in __NEXT_DATA__")
    return None

# Test it
market = scrape_current_btc_market()

if market:
    print("\nSUCCESS! Found active market:")
    print(f"  Title: {market['title']}")
    print(f"  Slug: {market['slug']}")
    print(f"  Closed: {market['closed']}")
    print(f"  Condition ID: {market['condition_id']}")
    print(f"  Token IDs:")
    print(f"    Up:   {market['token_ids']['Up']}")
    print(f"    Down: {market['token_ids']['Down']}")
else:
    print("\nFailed to extract market data")
