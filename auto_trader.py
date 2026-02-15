"""
Auto-scraping Polymarket BTC 5-min arbitrage trader
Automatically discovers current market and extracts token IDs every 5 minutes
"""

import asyncio
import aiohttp
import time
import logging
from datetime import datetime
from collections import deque
from playwright.async_api import async_playwright

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Strategy parameters
MOVE_THRESHOLD = 0.15  # 15% price drop triggers Leg 1
SUM_TARGET = 0.95      # Max combined entry (5% profit target)
WINDOW_MIN = 2.0       # Watch first 2 minutes only
SHARES = 10            # Number of shares per leg
POLL_INTERVAL = 1.0    # Poll every 1 second
MARKET_REFRESH = 300   # Refresh market every 5 minutes (300 sec)

# API endpoints
CLOB_BOOK_API = "https://clob.polymarket.com/book"

# State machine
class State:
    IDLE = "IDLE"
    WATCHING = "WATCHING"
    LEG1_FILLED = "LEG1_FILLED"
    LEG2_FILLED = "LEG2_FILLED"

class AutoTrader:
    def __init__(self):
        self.state = State.IDLE
        self.token_ids = None
        self.current_market_url = None
        self.market_last_updated = 0
        self.round_start = None
        self.leg1_entry = None
        self.leg1_side = None
        self.price_history = deque(maxlen=100)
        self.session = None
        
    def get_current_market_slot(self):
        """Calculate the current 5-minute market timestamp"""
        now = int(time.time())
        # Round to nearest 5-minute boundary (300 seconds)
        current_slot = (now // 300) * 300
        
        # Try current slot first, but if it doesn't exist, try previous slots
        # Markets might be created with a delay
        slots_to_try = [
            current_slot,           # Current
            current_slot - 300,     # -5 min
            current_slot - 600,     # -10 min
            current_slot + 300,     # +5 min (future)
        ]
        return slots_to_try
    
    async def scrape_current_market(self):
        """Use Playwright to scrape token IDs from live Polymarket page"""
        slots = self.get_current_market_slot()
        
        # Try multiple slots to find an active market
        for slot in slots:
            url = f"https://polymarket.com/event/btc-updown-5m-{slot}"
            logger.info(f"Trying market slot: {slot}")
        
            async with async_playwright() as p:
                try:
                    browser = await p.chromium.launch(headless=True)
                    page = await browser.new_page()
                    
                    # Load the page (shorter timeout for faster failure)
                    await page.goto(url, wait_until="domcontentloaded", timeout=10000)
                    await page.wait_for_timeout(2000)  # Wait for React to hydrate
                    
                    # Extract window.__NEXT_DATA__
                    next_data = await page.evaluate("() => window.__NEXT_DATA__")
                    
                    await browser.close()
                    
                    if not next_data:
                        logger.warning(f"  No __NEXT_DATA__ found, trying next slot...")
                        continue
                    
                    # Navigate to market data
                    queries = next_data.get('props', {}).get('pageProps', {}).get('dehydratedState', {}).get('queries', [])
                    
                    for query in queries:
                        query_key = query.get('queryKey', [])
                        if len(query_key) >= 2 and query_key[0] == '/api/event/slug':
                            event_data = query.get('state', {}).get('data', {})
                            markets = event_data.get('markets', [])
                            
                            if not markets:
                                continue
                            
                            market = markets[0]
                            token_ids = market.get('clobTokenIds', [])
                            
                            if len(token_ids) != 2:
                                continue
                            
                            market_data = {
                                'url': url,
                                'title': event_data.get('title'),
                                'slug': event_data.get('slug'),
                                'closed': event_data.get('closed'),
                                'token_ids': {
                                    'Up': token_ids[0],
                                    'Down': token_ids[1]
                                }
                            }
                            
                            logger.info(f"SUCCESS! Found market: {market_data['title']}")
                            logger.info(f"  Closed: {market_data['closed']}")
                            logger.info(f"  Up token:   {token_ids[0][:20]}...")
                            logger.info(f"  Down token: {token_ids[1][:20]}...")
                            
                            return market_data
                    
                    # No market data found in this slot, try next
                    logger.warning(f"  No market data in __NEXT_DATA__, trying next slot...")
                    
                except Exception as e:
                    logger.warning(f"  Failed to load slot {slot}: {str(e)[:50]}")
                    continue
        
        # All slots failed
        logger.error("Could not find any active market in any slot")
        return None
    
    async def fetch_order_book(self, token_id):
        """Fetch order book for a specific token"""
        try:
            async with self.session.get(f"{CLOB_BOOK_API}?token_id={token_id}") as resp:
                if resp.status != 200:
                    return None
                return await resp.json()
        except Exception as e:
            logger.error(f"Error fetching order book: {e}")
            return None
    
    def get_best_prices(self, book):
        """Extract best bid/ask from order book"""
        if not book:
            return None, None
            
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        
        best_bid = float(bids[0]["price"]) if bids else None
        best_ask = float(asks[0]["price"]) if asks else None
        
        return best_bid, best_ask
    
    async def monitor_market(self):
        """Main monitoring loop with auto-refresh"""
        while True:
            try:
                # Check if we need to refresh market data (every 5 minutes)
                if time.time() - self.market_last_updated > MARKET_REFRESH:
                    logger.info("Refreshing market data...")
                    market_data = await self.scrape_current_market()
                    
                    if not market_data:
                        logger.warning("Failed to scrape market, retrying in 30 seconds...")
                        await asyncio.sleep(30)
                        continue
                    
                    if market_data['closed']:
                        logger.warning("Market is closed, waiting for next market...")
                        await asyncio.sleep(60)
                        continue
                    
                    self.token_ids = market_data['token_ids']
                    self.current_market_url = market_data['url']
                    self.market_last_updated = time.time()
                    
                    # Reset state for new market
                    self.state = State.IDLE
                    self.round_start = None
                    self.leg1_entry = None
                    self.leg1_side = None
                    self.price_history.clear()
                    
                    logger.info("Market data refreshed and ready to trade")
                
                # Fetch order books
                up_book = await self.fetch_order_book(self.token_ids["Up"])
                down_book = await self.fetch_order_book(self.token_ids["Down"])
                
                if not up_book or not down_book:
                    await asyncio.sleep(POLL_INTERVAL)
                    continue
                
                up_bid, up_ask = self.get_best_prices(up_book)
                down_bid, down_ask = self.get_best_prices(down_book)
                
                if not all([up_bid, up_ask, down_bid, down_ask]):
                    await asyncio.sleep(POLL_INTERVAL)
                    continue
                
                # Store price snapshot
                snapshot = {
                    "time": time.time(),
                    "up_bid": up_bid,
                    "up_ask": up_ask,
                    "down_bid": down_bid,
                    "down_ask": down_ask
                }
                self.price_history.append(snapshot)
                
                # Process based on state
                if self.state == State.IDLE:
                    await self.check_round_start()
                    
                elif self.state == State.WATCHING:
                    await self.check_leg1_entry(snapshot)
                    
                elif self.state == State.LEG1_FILLED:
                    await self.check_leg2_entry(snapshot)
                
                logger.info(f"[{self.state}] UP: {up_ask:.3f} | DOWN: {down_ask:.3f}")
                
                await asyncio.sleep(POLL_INTERVAL)
                
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                await asyncio.sleep(POLL_INTERVAL)
    
    async def check_round_start(self):
        """Detect when a new round starts"""
        if len(self.price_history) > 0:
            self.round_start = time.time()
            self.state = State.WATCHING
            logger.info(f"Round started, watching for {WINDOW_MIN} minutes")
    
    async def check_leg1_entry(self, snapshot):
        """Check if Leg 1 entry condition is met"""
        elapsed = (time.time() - self.round_start) / 60.0
        
        if elapsed > WINDOW_MIN:
            logger.info(f"Window expired ({WINDOW_MIN} min), resetting to IDLE")
            self.state = State.IDLE
            return
        
        if len(self.price_history) < 3:
            return
        
        old = self.price_history[-3]
        new = snapshot
        
        up_drop = (old["up_ask"] - new["up_ask"]) / old["up_ask"]
        down_drop = (old["down_ask"] - new["down_ask"]) / old["down_ask"]
        
        if up_drop >= MOVE_THRESHOLD:
            logger.info(f"LEG 1 TRIGGER: UP dropped {up_drop*100:.1f}%")
            self.leg1_side = "Up"
            self.leg1_entry = new["up_ask"]
            self.state = State.LEG1_FILLED
            logger.info(f"[PAPER] Bought {SHARES} UP shares @ {self.leg1_entry:.3f}")
            
        elif down_drop >= MOVE_THRESHOLD:
            logger.info(f"LEG 1 TRIGGER: DOWN dropped {down_drop*100:.1f}%")
            self.leg1_side = "Down"
            self.leg1_entry = new["down_ask"]
            self.state = State.LEG1_FILLED
            logger.info(f"[PAPER] Bought {SHARES} DOWN shares @ {self.leg1_entry:.3f}")
    
    async def check_leg2_entry(self, snapshot):
        """Check if Leg 2 hedge condition is met"""
        opposite_side = "Down" if self.leg1_side == "Up" else "Up"
        opposite_ask = snapshot["down_ask"] if opposite_side == "Down" else snapshot["up_ask"]
        
        total_cost = self.leg1_entry + opposite_ask
        
        if total_cost <= SUM_TARGET:
            profit = 1.0 - total_cost
            logger.info(f"LEG 2 TRIGGER: Total cost {total_cost:.3f}, profit {profit*100:.1f}%")
            logger.info(f"[PAPER] Bought {SHARES} {opposite_side} shares @ {opposite_ask:.3f}")
            logger.info(f"[PAPER] PROFIT LOCKED: ${profit * SHARES:.2f}")
            
            self.state = State.IDLE
            self.round_start = None
            self.leg1_entry = None
            self.leg1_side = None
            logger.info("Cycle complete, resetting to IDLE")
    
    async def run(self):
        """Main entry point"""
        logger.info("Starting Polymarket Auto-Trader (Paper Mode)")
        logger.info("="*60)
        logger.info(f"Strategy: {SHARES} shares, {MOVE_THRESHOLD*100}% move, ${SUM_TARGET} sum target")
        logger.info(f"Market refresh interval: {MARKET_REFRESH} seconds")
        logger.info("="*60)
        
        async with aiohttp.ClientSession() as session:
            self.session = session
            
            # Initial market scrape
            logger.info("\nScraping initial market data...")
            market_data = await self.scrape_current_market()
            
            if not market_data:
                logger.error("Failed to scrape initial market. Exiting.")
                return
            
            self.token_ids = market_data['token_ids']
            self.current_market_url = market_data['url']
            self.market_last_updated = time.time()
            
            logger.info("\nStarting monitoring loop...")
            logger.info("")
            
            # Start monitoring
            await self.monitor_market()

if __name__ == "__main__":
    trader = AutoTrader()
    asyncio.run(trader.run())
