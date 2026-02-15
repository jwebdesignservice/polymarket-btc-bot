import requests

# Try Gamma events API  
print("Testing Gamma Events API:")
r = requests.get('https://gamma-api.polymarket.com/events?limit=100&offset=0')
if r.status_code == 200:
    events = r.json()
    
    # Filter for BTC 5-min markets
    btc_5m = [e for e in events if 'btc-updown-5m' in e.get('slug', '')]
    
    print(f"Total BTC 5-min events: {len(btc_5m)}")
    print("\nFirst 5:")
    for event in btc_5m[:5]:
        print(f"  {event.get('slug', 'N/A')}")
        print(f"    Title: {event.get('title', 'N/A')}")
        print(f"    Closed: {event.get('closed', 'N/A')}")
        print(f"    Active: {event.get('active', 'N/A')}")
        
        # Check if markets data is present
        if 'markets' in event and event['markets']:
            market = event['markets'][0]
            print(f"    Condition ID: {market.get('conditionId', 'N/A')}")
            clob_ids = market.get('clobTokenIds', [])
            if clob_ids:
                print(f"    Token IDs: {len(clob_ids)} tokens")
        print()
else:
    print(f"Error: HTTP {r.status_code}")
