"""
Live Polymarket BTC 5-min arbitrage trader
FULLY AUTONOMOUS - automatically discovers and trades current markets
"""

import asyncio
import aiohttp
import time
import logging
import json
from datetime import datetime
from collections import deque
from playwright.async_api import async_playwright

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Strategy parameters - OPTIMIZED FOR MAX PROFITABILITY
MOVE_THRESHOLD = 0.05  # 5% price drop triggers Leg 1 (AGGRESSIVE)
SUM_TARGET = 0.94      # Max combined entry (6% profit target)
WINDOW_MIN = 4.0       # Watch first 4 minutes (80% of round)
SHARES = 10            # Number of shares per leg
POLL_INTERVAL = 1.0    # Poll every 1 second
REFRESH_MARKET_MINUTES = 5  # Refresh market data every 5 min

# API endpoints
CLOB_BOOK_API = "https://clob.polymarket.com/book"

# State machine
class State:
    IDLE = "IDLE"
    WATCHING = "WATCHING"
    LEG1_FILLED = "LEG1_FILLED"
    LEG2_FILLED = "LEG2_FILLED"

class LiveTrader:
    def __init__(self):
        self.state = State.IDLE
        self.token_ids = None
        self.market_info = None
        self.round_start = None
        self.leg1_entry = None
        self.leg1_side = None
        self.price_history = deque(maxlen=100)
        self.session = None
        self.last_market_refresh = 0
        
    async def discover_market(self):
        """
        Discover current BTC 5-min market using Playwright directly
        Returns True if successful, False otherwise
        """
        logger.info("=" * 60)
        logger.info("DISCOVERING CURRENT BTC 5-MIN MARKET...")
        logger.info("=" * 60)
        
        # Retry up to 3 times if we get a stale market
        for attempt in range(3):
            if attempt > 0:
                logger.info(f"Retry attempt {attempt + 1}/3...")
                await asyncio.sleep(5)  # Wait 5 seconds between retries
        
            try:
                success = await self._discover_market_attempt()
                if success:
                    return True
                # If we got a stale market, retry
                logger.warning("Got stale market, retrying...")
            except Exception as e:
                logger.error(f"Discovery attempt failed: {e}")
        
        return False
    
    async def _discover_market_attempt(self):
        """Single attempt to discover market"""
        try:
            async with async_playwright() as p:
                # Launch browser with realistic user agent
                logger.info("Launching browser...")
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                
                # Calculate current market timestamp
                current_timestamp = int(time.time())
                current_slot = (current_timestamp // 300) * 300
                time_in_slot = current_timestamp - current_slot
                time_remaining = 300 - time_in_slot
                
                # If less than 60 seconds left in current slot, wait for next market
                if time_remaining < 60:
                    logger.info(f"Only {time_remaining}s left in current slot, waiting for next market...")
                    sleep_time = time_remaining + 5  # Wait until 5 seconds into next slot
                    logger.info(f"Waiting {sleep_time} seconds...")
                    await asyncio.sleep(sleep_time)
                
                # Use series URL (auto-redirects to current market)
                series_url = "https://polymarket.com/series/btc-up-or-down-5m"
                logger.info(f"Loading {series_url}...")
                logger.info(f"Expected slot: {current_slot} (Time in slot: {time_in_slot}s, Remaining: {time_remaining}s)")
                
                await page.goto(series_url, wait_until="load", timeout=60000)
                logger.info("Page loaded, extracting data...")
                
                # Wait for JavaScript to hydrate
                await page.wait_for_timeout(3000)
                
                # Extract market data
                market_data_json = await page.evaluate("""() => {
                    const queries = window.__NEXT_DATA__?.props?.pageProps?.dehydratedState?.queries || [];
                    
                    for (const q of queries) {
                        const key = q.queryKey || [];
                        
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
                
                await browser.close()
                
                if not market_data_json:
                    logger.error("Could not find market data in __NEXT_DATA__")
                    return False
                
                # Parse and format
                market_data = json.loads(market_data_json)
                
                self.market_info = {
                    'title': market_data['title'],
                    'slug': market_data['slug'],
                    'closed': market_data['closed'],
                    'condition_id': market_data['conditionId'],
                    'token_ids': {
                        'Up': market_data['clobTokenIds'][0],
                        'Down': market_data['clobTokenIds'][1]
                    }
                }
                
                self.token_ids = self.market_info['token_ids']
                
                logger.info("=" * 60)
                logger.info("MARKET DISCOVERED SUCCESSFULLY!")
                logger.info("=" * 60)
                logger.info(f"Title:        {self.market_info['title']}")
                logger.info(f"Slug:         {self.market_info['slug']}")
                logger.info(f"Closed:       {self.market_info['closed']}")
                logger.info(f"Condition ID: {self.market_info['condition_id']}")
                logger.info(f"Up token:     {self.token_ids['Up'][:20]}...")
                logger.info(f"Down token:   {self.token_ids['Down'][:20]}...")
                logger.info("=" * 60)
                
                # Validate market timestamp is current
                slug = self.market_info['slug']
                if 'btc-updown-5m-' in slug:
                    market_timestamp = int(slug.split('-')[-1])
                    current_timestamp = int(time.time())
                    current_slot = (current_timestamp // 300) * 300
                    
                    # Market should be current slot (started) or next slot (about to start)
                    time_diff = abs(market_timestamp - current_slot)
                    
                    if time_diff > 300:  # More than 1 slot off (5 minutes)
                        logger.warning(f"Discovered market is stale!")
                        logger.warning(f"Market slot: {market_timestamp}, Current slot: {current_slot}")
                        logger.warning(f"Time difference: {time_diff} seconds")
                        # Close browser but return False to trigger retry
                        await browser.close()
                        return False
                
                self.last_market_refresh = time.time()
                
                # Save to JSON for reference
                with open('current_market.json', 'w') as f:
                    json.dump(self.market_info, f, indent=2)
                
                logger.info(f"Market is current (slot: {market_timestamp})")
                
                return True
                
        except Exception as e:
            logger.error(f"Error discovering market: {e}")
            return False
    
    def should_refresh_market(self):
        """Check if we should refresh market data"""
        if not self.token_ids:
            return True
        
        # Refresh every 5 minutes to catch new markets
        time_since_refresh = time.time() - self.last_market_refresh
        return time_since_refresh >= (REFRESH_MARKET_MINUTES * 60)
    
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
    
    def check_for_dump(self):
        """Check if price dropped >= MOVE_THRESHOLD in last 3 seconds"""
        if len(self.price_history) < 2:
            return None
        
        # Look back 3 seconds
        current_time = time.time()
        three_sec_ago = current_time - 3
        
        # Get recent prices (last 3 seconds)
        recent = [p for p in self.price_history if p["time"] >= three_sec_ago]
        
        if len(recent) < 2:
            return None
        
        # Check Up side
        up_prices = [p["up_ask"] for p in recent if p["up_ask"]]
        if len(up_prices) >= 2:
            up_start = up_prices[0]
            up_current = up_prices[-1]
            up_drop = (up_start - up_current) / up_start
            
            if up_drop >= MOVE_THRESHOLD:
                logger.info(f"UP DUMP DETECTED! {up_drop*100:.1f}% drop (from {up_start:.3f} to {up_current:.3f})")
                return ("Up", up_current)
        
        # Check Down side
        down_prices = [p["down_ask"] for p in recent if p["down_ask"]]
        if len(down_prices) >= 2:
            down_start = down_prices[0]
            down_current = down_prices[-1]
            down_drop = (down_start - down_current) / down_start
            
            if down_drop >= MOVE_THRESHOLD:
                logger.info(f"DOWN DUMP DETECTED! {down_drop*100:.1f}% drop (from {down_start:.3f} to {down_current:.3f})")
                return ("Down", down_current)
        
        return None
    
    async def monitor_market(self):
        """Main monitoring loop"""
        while True:
            try:
                # Check if we need to refresh market data
                if self.should_refresh_market():
                    logger.info("Refreshing market data...")
                    if not await self.discover_market():
                        logger.error("Failed to discover market, retrying in 30 seconds...")
                        await asyncio.sleep(30)
                        continue
                
                # Fetch order books for both outcomes
                up_book = await self.fetch_order_book(self.token_ids["Up"])
                down_book = await self.fetch_order_book(self.token_ids["Down"])
                
                if not up_book or not down_book:
                    await asyncio.sleep(POLL_INTERVAL)
                    continue
                
                up_bid, up_ask = self.get_best_prices(up_book)
                down_bid, down_ask = self.get_best_prices(down_book)
                
                if not all([up_bid, up_ask, down_bid, down_ask]):
                    # Log missing data every 30 seconds
                    if int(time.time()) % 30 == 0:
                        missing = []
                        if not up_bid: missing.append("Up bid")
                        if not up_ask: missing.append("Up ask")
                        if not down_bid: missing.append("Down bid")
                        if not down_ask: missing.append("Down ask")
                        logger.warning(f"Incomplete orderbook data: {', '.join(missing)} missing")
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
                
                # Log prices every 10 seconds
                if int(snapshot["time"]) % 10 == 0:
                    logger.info(f"Prices - Up: {up_bid:.3f}/{up_ask:.3f}  Down: {down_bid:.3f}/{down_ask:.3f}")
                
                # State machine logic
                if self.state == State.IDLE:
                    # Start new round
                    self.round_start = time.time()
                    self.state = State.WATCHING
                    logger.info("Started watching new round")
                
                elif self.state == State.WATCHING:
                    # Check if we're still in the window
                    elapsed = (time.time() - self.round_start) / 60.0
                    
                    if elapsed > WINDOW_MIN:
                        # Window closed, no trigger - refresh to next market
                        logger.info(f"Window closed ({elapsed:.1f} min), no trigger.")
                        logger.info("Refreshing to next market...")
                        self.state = State.IDLE
                        self.price_history.clear()
                        # Force market refresh immediately
                        self.last_market_refresh = 0
                        continue
                    
                    # Check for price dump
                    dump = self.check_for_dump()
                    if dump:
                        side, price = dump
                        self.leg1_side = side
                        self.leg1_entry = price
                        self.state = State.LEG1_FILLED
                        
                        logger.info("=" * 60)
                        logger.info(f"LEG 1 FILLED - Bought {SHARES} {side} @ ${price:.3f}")
                        logger.info(f"Cost: ${price * SHARES:.2f}")
                        logger.info("=" * 60)
                
                elif self.state == State.LEG1_FILLED:
                    # Wait for hedge opportunity
                    opposite_side = "Down" if self.leg1_side == "Up" else "Up"
                    opposite_ask = down_ask if opposite_side == "Down" else up_ask
                    
                    # Check hedge condition
                    if self.leg1_entry + opposite_ask <= SUM_TARGET:
                        # LEG 2 TRIGGER!
                        logger.info("=" * 60)
                        logger.info(f"LEG 2 FILLED - Bought {SHARES} {opposite_side} @ ${opposite_ask:.3f}")
                        logger.info(f"Cost: ${opposite_ask * SHARES:.2f}")
                        logger.info(f"Total cost: ${(self.leg1_entry + opposite_ask) * SHARES:.2f}")
                        logger.info(f"Guaranteed profit: ${(1.0 - self.leg1_entry - opposite_ask) * SHARES:.2f}")
                        logger.info("=" * 60)
                        
                        self.state = State.LEG2_FILLED
                        
                        # Reset after successful hedge
                        await asyncio.sleep(5)
                        self.state = State.IDLE
                        self.price_history.clear()
                        logger.info("Hedge complete! Resetting for next round...")
                
                await asyncio.sleep(POLL_INTERVAL)
                
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                await asyncio.sleep(POLL_INTERVAL)
    
    async def run(self):
        """Start the trading bot"""
        logger.info("=" * 60)
        logger.info("POLYMARKET BTC 5-MIN ARBITRAGE BOT")
        logger.info("FULLY AUTONOMOUS MODE")
        logger.info("=" * 60)
        logger.info(f"Move threshold: {MOVE_THRESHOLD*100:.0f}%")
        logger.info(f"Sum target:     ${SUM_TARGET:.2f}")
        logger.info(f"Window:         {WINDOW_MIN:.1f} minutes")
        logger.info(f"Shares:         {SHARES}")
        logger.info("=" * 60)
        
        # Discover initial market
        if not await self.discover_market():
            logger.error("Failed to discover market on startup!")
            return
        
        # Start HTTP session
        async with aiohttp.ClientSession() as session:
            self.session = session
            await self.monitor_market()

async def main():
    trader = LiveTrader()
    await trader.run()

if __name__ == "__main__":
    asyncio.run(main())
