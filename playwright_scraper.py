"""
Scrape live market data from polymarket.com using Playwright
FULLY AUTONOMOUS - No manual input required!
"""
from playwright.sync_api import sync_playwright
import json

def get_live_btc_market():
    """
    Extract current BTC 5-min market data from polymarket.com
    Uses /series/ URL which auto-redirects to the current active market
    """
    
    with sync_playwright() as p:
        # Launch browser (headless mode)
        print("Launching browser...")
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # Use series URL - it auto-redirects to current market
        series_url = "https://polymarket.com/series/btc-up-or-down-5m"
        
        print(f"Loading {series_url}...")
        try:
            # Load page and wait for network idle
            page.goto(series_url, wait_until="networkidle", timeout=30000)
            print(f"Page loaded, waiting for JavaScript to hydrate...")
            
            # Wait additional 3 seconds for React to fully load
            page.wait_for_timeout(3000)
            
            # Get the final URL (after redirect)
            final_url = page.url
            print(f"Redirected to: {final_url}")
            
            # Extract market data from __NEXT_DATA__
            print("Extracting market data from window.__NEXT_DATA__...")
            
            market_data_json = page.evaluate("""() => {
                const queries = window.__NEXT_DATA__?.props?.pageProps?.dehydratedState?.queries || [];
                
                for (const q of queries) {
                    const key = q.queryKey || [];
                    
                    // Find the event/slug query
                    if (key[0] === '/api/event/slug') {
                        const data = q.state?.data;
                        
                        if (data?.markets?.[0]) {
                            const market = data.markets[0];
                            const tokenIds = market.clobTokenIds || [];
                            
                            if (tokenIds.length === 2) {
                                return JSON.stringify({
                                    title: data.title,
                                    slug: data.slug,
                                    conditionId: market.conditionId,
                                    clobTokenIds: tokenIds,
                                    closed: data.closed
                                });
                            }
                        }
                    }
                }
                
                return null;
            }""")
            
            browser.close()
            
            if not market_data_json:
                print("ERROR: Could not find market data in __NEXT_DATA__")
                return None
            
            # Parse the JSON string
            market_data = json.loads(market_data_json)
            
            # Format for bot
            formatted = {
                'title': market_data['title'],
                'slug': market_data['slug'],
                'closed': market_data['closed'],
                'condition_id': market_data['conditionId'],
                'token_ids': {
                    'Up': market_data['clobTokenIds'][0],
                    'Down': market_data['clobTokenIds'][1]
                }
            }
            
            return formatted
            
        except Exception as e:
            browser.close()
            print(f"ERROR: {str(e)}")
            return None

if __name__ == "__main__":
    market = get_live_btc_market()
    
    if market:
        print("\n" + "="*60)
        print("SUCCESS! Found active BTC 5-min market:")
        print("="*60)
        print(f"Title:        {market['title']}")
        print(f"Slug:         {market['slug']}")
        print(f"Closed:       {market['closed']}")
        print(f"Condition ID: {market['condition_id']}")
        print(f"\nToken IDs:")
        print(f"  Up:   {market['token_ids']['Up'][:20]}...")
        print(f"  Down: {market['token_ids']['Down'][:20]}...")
        print("="*60)
        
        # Save to file for the bot to read
        with open('current_market.json', 'w') as f:
            json.dump(market, f, indent=2)
        print("\nSaved to current_market.json")
    else:
        print("\nFailed to extract market data")
