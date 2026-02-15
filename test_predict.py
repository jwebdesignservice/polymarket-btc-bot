import requests
import time
from datetime import datetime

def get_current_5min_slot():
    """Calculate the current 5-minute market slot"""
    now = int(time.time())
    # Round to nearest 5-minute boundary (300 seconds)
    slot = (now // 300) * 300
    return slot

# Test prediction
current_slot = get_current_5min_slot()
slug = f"btc-updown-5m-{current_slot}"

print(f"Current time: {datetime.now()}")
print(f"Current Unix: {int(time.time())}")
print(f"Predicted slot: {current_slot}")
print(f"Expected slug: {slug}")
print()

# Try querying this specific event
print(f"Querying: https://gamma-api.polymarket.com/events/{slug}")
r = requests.get(f'https://gamma-api.polymarket.com/events/{slug}')
print(f"Status: {r.status_code}")

if r.status_code == 200:
    event = r.json()
    print(f"\nSUCCESS!")
    print(f"Title: {event.get('title')}")
    print(f"Active: {event.get('active')}")
    print(f"Closed: {event.get('closed')}")
    
    markets = event.get('markets', [])
    if markets:
        m = markets[0]
        print(f"\nMarket data:")
        print(f"  Condition ID: {m.get('conditionId')}")
        print(f"  Token IDs: {m.get('clobTokenIds')}")
else:
    print(f"Failed. Response: {r.text[:200]}")
    print("\nTrying next slot (+5 min)...")
    next_slot = current_slot + 300
    r2 = requests.get(f'https://gamma-api.polymarket.com/events/btc-updown-5m-{next_slot}')
    print(f"Status: {r2.status_code}")
    if r2.status_code == 200:
        event = r2.json()
        print(f"Title: {event.get('title')}")
        markets = event.get('markets', [])
        if markets:
            print(f"Condition ID: {markets[0].get('conditionId')}")
