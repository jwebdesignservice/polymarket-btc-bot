import requests
import time

# Calculate current 5-min slot
now = int(time.time())
current_slot = (now // 300) * 300

print(f"Current time: {now}")
print(f"Current slot: {current_slot}")
print()

# Try multiple slots (current, next, previous)
slots_to_try = [
    current_slot,           # Current
    current_slot + 300,     # Next (+5 min)
    current_slot - 300,     # Previous (-5 min)
]

for slot in slots_to_try:
    market_slug = f"btc-updown-5m-{slot}"
    print(f"Trying: {market_slug}")
    
    r = requests.get(f'https://clob.polymarket.com/markets/{market_slug}')
    
    if r.status_code == 200:
        market = r.json()
        print(f"  SUCCESS!")
        print(f"  Question: {market.get('question')}")
        print(f"  Condition: {market.get('condition_id')}")
        print(f"  Tokens: {market.get('clob_token_ids')}")
        print(f"  Closed: {market.get('closed')}, Accepting: {market.get('accepting_orders')}")
        break
    else:
        print(f"  404 - not found")
        
print("\nDone.")
