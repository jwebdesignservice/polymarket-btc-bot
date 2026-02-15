import json
import ast

# Your JSON from earlier (the file you sent)
with open(r'C:\Users\Jack\.openclaw\media\inbound\f105b751-d090-4030-949a-e14a1d2ae5f3.txt', 'r', encoding='utf-8') as f:
    content = f.read()

# The file contains a Python string literal, use ast.literal_eval
try:
    json_str = ast.literal_eval(content.strip())
    data = json.loads(json_str)
except:
    # Fallback: treat it as direct JSON
    data = json.loads(content)

# Navigate to the queries
queries = data['props']['pageProps']['dehydratedState']['queries']

# Find the series query with events
for query in queries:
    if query.get('queryKey', [None])[0] == '/api/series':
        series_data = query.get('state', {}).get('data', {})
        events = series_data.get('events', [])
        
        print(f"Found {len(events)} events in series data\n")
        
        # Look for active (not closed) markets
        for event in events:
            if not event.get('closed', True):
                print(f"ACTIVE EVENT FOUND:")
                print(f"  Title: {event.get('title')}")
                print(f"  Slug: {event.get('slug')}")
                
                # This doesn't have clobTokenIds at the series level
                # Need to look in the individual event query
                break
        break

# Find the event/slug query
for query in queries:
    query_key = query.get('queryKey', [])
    if len(query_key) >= 2 and query_key[0] == '/api/event/slug':
        event_data = query.get('state', {}).get('data', {})
        markets = event_data.get('markets', [])
        
        if markets:
            market = markets[0]
            token_ids = market.get('clobTokenIds', [])
            
            print(f"\nEVENT FROM YOUR BROWSER:")
            print(f"  Title: {event_data.get('title')}")
            print(f"  Slug: {event_data.get('slug')}")
            print(f"  Closed: {event_data.get('closed')}")
            print(f"  Condition ID: {market.get('conditionId')}")
            
            if len(token_ids) == 2:
                print(f"\nTOKEN IDs:")
                print(f"  Up:   {token_ids[0]}")
                print(f"  Down: {token_ids[1]}")
                
                # Save to file
                with open('extracted_tokens.json', 'w') as out:
                    json.dump({
                        'slug': event_data.get('slug'),
                        'condition_id': market.get('conditionId'),
                        'token_ids': {
                            'Up': token_ids[0],
                            'Down': token_ids[1]
                        }
                    }, out, indent=2)
                print("\nSaved to extracted_tokens.json")
            break
