"""
Analyze actual price movements in 5-minute markets to find optimal thresholds.
"""
import requests
import base64

cursor = base64.b64encode(b'440000').decode()
r = requests.get('https://clob.polymarket.com/markets', params={'limit': 500, 'next_cursor': cursor})
markets = r.json()['data']
fivemin = [m for m in markets if 'btc-updown-5m-' in m.get('market_slug', '')][:10]

print("Analyzing price movements in 5-minute markets...\n")

max_drops = []

for market in fivemin:
    slug = market['market_slug']
    end_ts = int(slug.split('-')[-1])
    start_ts = end_ts - 5 * 60
    
    tokens = market.get('tokens', [])
    if len(tokens) < 2:
        continue
    
    up_token = next((t for t in tokens if t['outcome'].upper() == 'UP'), None)
    if not up_token:
        continue
    
    # Fetch price history
    r2 = requests.get(
        'https://clob.polymarket.com/prices-history',
        params={
            'market': up_token['token_id'],
            'startTs': start_ts - 60,
            'endTs': end_ts + 60,
            'fidelity': 1
        }
    )
    
    if r2.status_code != 200:
        continue
    
    history = r2.json().get('history', [])
    if len(history) < 2:
        continue
    
    # Calculate max drop within first 2 minutes
    watch_window = [h for h in history if start_ts <= h['t'] <= start_ts + 120]
    
    if len(watch_window) < 2:
        continue
    
    max_drop = 0
    prices = [h['p'] for h in watch_window]
    
    for i in range(len(prices) - 1):
        drop = prices[i] - prices[i+1]
        if drop > max_drop:
            max_drop = drop
    
    max_drops.append(max_drop)
    
    print(f"{market['question'][:60]}")
    print(f"  Price range: {min(prices):.3f} - {max(prices):.3f}")
    print(f"  Max drop (consecutive ticks): {max_drop:.3f} ({max_drop*100:.1f}%)")
    print(f"  Total ticks in 2min window: {len(watch_window)}")
    print()

if max_drops:
    print(f"\n{'='*70}")
    print(f"SUMMARY:")
    print(f"  Average max drop: {sum(max_drops)/len(max_drops)*100:.1f}%")
    print(f"  Largest drop seen: {max(max_drops)*100:.1f}%")
    print(f"  Smallest drop seen: {min(max_drops)*100:.1f}%")
    print(f"  Markets with 10%+ drop: {sum(1 for d in max_drops if d >= 0.10)}/{len(max_drops)}")
    print(f"  Markets with 5%+ drop: {sum(1 for d in max_drops if d >= 0.05)}/{len(max_drops)}")
    print(f"{'='*70}")
    print(f"\nRECOMMENDATION: Set move threshold to {max(max_drops)*0.8:.2f} ({max(max_drops)*80:.1f}%)")
else:
    print("No price data available")
