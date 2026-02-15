from playwright.sync_api import sync_playwright
import json

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    
    url = "https://polymarket.com/event/btc-up-or-down-5-min"
    print(f"Loading {url}...")
    page.goto(url, wait_until="networkidle", timeout=20000)
    page.wait_for_timeout(3000)
    
    # Get the full __NEXT_DATA__
    next_data = page.evaluate("() => window.__NEXT_DATA__")
    
    browser.close()
    
    # Save to file for inspection
    with open('next_data_dump.json', 'w') as f:
        json.dump(next_data, f, indent=2)
    
    print("Saved __NEXT_DATA__ structure to next_data_dump.json")
    print(f"\nTop-level keys: {list(next_data.keys())}")
    
    if 'props' in next_data:
        print(f"props keys: {list(next_data['props'].keys())}")
        if 'pageProps' in next_data['props']:
            print(f"pageProps keys: {list(next_data['props']['pageProps'].keys())}")
