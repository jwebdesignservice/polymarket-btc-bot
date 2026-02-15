"""
Polymarket BTC 5-Min TRUE ARBITRAGE Bot
----------------------------------------
Strategy: Look for mispricing where Up_ask + Down_ask < $1.00
This guarantees profit since one side MUST pay $1.00

Example:
- Up ask: $0.52
- Down ask: $0.47
- Total cost: $0.99
- Guaranteed payout: $1.00
- Risk-free profit: $0.01 per share
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

# Strategy parameters - TRUE ARBITRAGE
MIN_PROFIT_MARGIN = 0.02  # Need at least 2¢ profit per share ($1.00 payout - $0.98 cost)
SHARES = 10               # Number of shares per arbitrage
POLL_INTERVAL = 0.5       # Poll every 0.5 seconds (faster for arb opportunities)
MAX_COST = 0.98           # Never pay more than $0.98 for both sides combined

# API endpoints
CLOB_BOOK_API = "https://clob.polymarket.com/book"

class ArbitrageBot:
    def __init__(self):
        self.token_ids = None
        self.market_info = None
        self.session = None
        self.last_market_refresh = 0
        self.arb_count = 0
        self.total_profit = 0.0
        
    async def discover_market(self):
        """Discover current BTC 5-min market using Playwright"""
        logger.info("=" * 60)
        logger.info("DISCOVERING CURRENT BTC 5-MIN MARKET...")
        logger.info("=" * 60)
        
        for attempt in range(3):
            if attempt > 0:
                logger.info(f"Retry attempt {attempt + 1}/3...")
                await asyncio.sleep(5)
        
            try:
                success = await self._discover_market_attempt()
                if success:
                    return True
                logger.warning("Got stale market, retrying...")
            except Exception as e:
                logger.error(f"Discovery attempt failed: {e}")
        
        return False
    
    async def _discover_market_attempt(self):
        """Single attempt to discover market"""
        try:
            async with async_playwright() as p:
                logger.info("Launching browser...")
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                
                # Calculate timing
                current_timestamp = int(time.time())
                current_slot = (current_timestamp // 300) * 300
                time_in_slot = current_timestamp - current_slot
                time_remaining = 300 - time_in_slot
                
                # Wait for next market if < 60s left
                if time_remaining < 60:
                    logger.info(f"Only {time_remaining}s left, waiting for next market...")
                    await asyncio.sleep(time_remaining + 5)
                
                # Calculate current slot and use direct URL
                fresh_timestamp = int(time.time())
                fresh_slot = (fresh_timestamp // 300) * 300
                
                # Use direct timestamp URL
                market_url = f"https://polymarket.com/event/btc-updown-5m-{fresh_slot}"
                logger.info(f"Loading {market_url}...")
                logger.info(f"Current slot: {fresh_slot} ({time.strftime('%H:%M', time.gmtime(fresh_slot))} GMT)")
                
                await page.goto(market_url, wait_until="load", timeout=60000)
                logger.info("Page loaded, extracting data...")
                
                # Wait for JS
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
                    logger.error("Could not find market data")
                    return False
                
                market_data = json.loads(market_data_json)
                
                # Validate market timestamp
                slug = market_data['slug']
                if 'btc-updown-5m-' in slug:
                    market_timestamp = int(slug.split('-')[-1])
                    current_slot = (int(time.time()) // 300) * 300
                    time_diff = abs(market_timestamp - current_slot)
                    
                    if time_diff > 300:
                        logger.warning(f"Market is stale! Diff: {time_diff}s")
                        return False
                
                # Save market info
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
                logger.info("MARKET DISCOVERED!")
                logger.info("=" * 60)
                logger.info(f"Title: {self.market_info['title']}")
                logger.info(f"Slug: {self.market_info['slug']}")
                logger.info("=" * 60)
                
                self.last_market_refresh = time.time()
                
                with open('current_market.json', 'w') as f:
                    json.dump(self.market_info, f, indent=2)
                
                return True
                
        except Exception as e:
            logger.error(f"Error: {e}")
            return False
    
    async def fetch_order_book(self, token_id):
        """Fetch order book"""
        try:
            async with self.session.get(f"{CLOB_BOOK_API}?token_id={token_id}") as resp:
                if resp.status != 200:
                    return None
                return await resp.json()
        except Exception as e:
            logger.error(f"Error fetching book: {e}")
            return None
    
    def get_best_prices(self, book):
        """Get best bid/ask from order book"""
        if not book:
            return None, None
        
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        
        best_bid = float(bids[0]["price"]) if bids else None
        best_ask = float(asks[0]["price"]) if asks else None
        
        return best_bid, best_ask
    
    def check_arbitrage(self, up_ask, down_ask):
        """
        Check if there's an arbitrage opportunity
        
        Logic:
        - One side MUST win and pays $1.00
        - If we can buy both for < $1.00, we profit
        - Min profit: 2¢ per share ($0.20 for 10 shares)
        """
        if not up_ask or not down_ask:
            return False, 0
        
        total_cost = up_ask + down_ask
        guaranteed_payout = 1.00
        profit_per_share = guaranteed_payout - total_cost
        
        # Check if profitable AND within max cost
        if profit_per_share >= MIN_PROFIT_MARGIN and total_cost <= MAX_COST:
            return True, profit_per_share
        
        return False, profit_per_share
    
    async def monitor_market(self):
        """Main monitoring loop - looking for TRUE arbitrage"""
        logger.info("Starting TRUE ARBITRAGE monitoring...")
        logger.info(f"Min profit: ${MIN_PROFIT_MARGIN:.3f}/share")
        logger.info(f"Max combined cost: ${MAX_COST:.2f}")
        logger.info(f"Position size: {SHARES} shares")
        logger.info("=" * 60)
        
        round_start = time.time()
        
        while True:
            try:
                # Check if market needs refresh (every 4 minutes = when round ends)
                elapsed = (time.time() - round_start) / 60.0
                if elapsed > 4.5:  # Refresh at 4.5 min mark
                    logger.info("Round ending, discovering next market...")
                    if not await self.discover_market():
                        logger.error("Failed to discover market")
                        await asyncio.sleep(30)
                        continue
                    round_start = time.time()
                
                # Fetch order books
                up_book = await self.fetch_order_book(self.token_ids["Up"])
                down_book = await self.fetch_order_book(self.token_ids["Down"])
                
                if not up_book or not down_book:
                    await asyncio.sleep(POLL_INTERVAL)
                    continue
                
                # Get best prices (we care about ASK prices - what we'd pay to buy)
                up_bid, up_ask = self.get_best_prices(up_book)
                down_bid, down_ask = self.get_best_prices(down_book)
                
                if not up_ask or not down_ask:
                    # Log every 10 seconds when missing data
                    if int(time.time()) % 10 == 0:
                        missing = []
                        if not up_ask: missing.append("Up ask")
                        if not down_ask: missing.append("Down ask")
                        logger.warning(f"Incomplete data: {', '.join(missing)}")
                    await asyncio.sleep(POLL_INTERVAL)
                    continue
                
                # Check for arbitrage opportunity
                is_arb, profit_per_share = self.check_arbitrage(up_ask, down_ask)
                
                # Log prices every 10 seconds
                if int(time.time()) % 10 == 0:
                    total_cost = up_ask + down_ask
                    logger.info(f"Prices - Up: ${up_ask:.3f}, Down: ${down_ask:.3f}, Total: ${total_cost:.3f}, Profit: ${profit_per_share:.4f}")
                
                if is_arb:
                    # ARBITRAGE OPPORTUNITY FOUND!
                    total_cost = up_ask + down_ask
                    total_profit = profit_per_share * SHARES
                    
                    logger.info("=" * 60)
                    logger.info("🎯 ARBITRAGE OPPORTUNITY DETECTED!")
                    logger.info("=" * 60)
                    logger.info(f"Up ask: ${up_ask:.4f}")
                    logger.info(f"Down ask: ${down_ask:.4f}")
                    logger.info(f"Total cost: ${total_cost:.4f}")
                    logger.info(f"Guaranteed payout: $1.0000")
                    logger.info(f"Profit per share: ${profit_per_share:.4f}")
                    logger.info(f"Total profit ({SHARES} shares): ${total_profit:.2f}")
                    logger.info("=" * 60)
                    logger.info("[PAPER TRADE] Executing both legs...")
                    logger.info(f"[LEG 1] Buy {SHARES} Up @ ${up_ask:.4f} = ${up_ask * SHARES:.2f}")
                    logger.info(f"[LEG 2] Buy {SHARES} Down @ ${down_ask:.4f} = ${down_ask * SHARES:.2f}")
                    logger.info(f"[COMPLETE] Total cost: ${total_cost * SHARES:.2f}")
                    logger.info(f"[PROFIT] Guaranteed profit: ${total_profit:.2f}")
                    logger.info("=" * 60)
                    
                    # Track stats
                    self.arb_count += 1
                    self.total_profit += total_profit
                    
                    logger.info(f"Session stats: {self.arb_count} arbs, ${self.total_profit:.2f} total profit")
                    
                    # Wait a bit before next check (avoid spam if opportunity persists)
                    await asyncio.sleep(5)
                
                await asyncio.sleep(POLL_INTERVAL)
                
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                await asyncio.sleep(POLL_INTERVAL)
    
    async def run(self):
        """Start the bot"""
        logger.info("=" * 60)
        logger.info("POLYMARKET TRUE ARBITRAGE BOT")
        logger.info("=" * 60)
        logger.info("Strategy: Buy both Up + Down when total < $1.00")
        logger.info(f"Min profit margin: ${MIN_PROFIT_MARGIN:.3f} per share")
        logger.info(f"Position size: {SHARES} shares")
        logger.info("=" * 60)
        
        # Discover initial market
        if not await self.discover_market():
            logger.error("Failed to discover market!")
            return
        
        # Start monitoring
        async with aiohttp.ClientSession() as session:
            self.session = session
            await self.monitor_market()

async def main():
    bot = ArbitrageBot()
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())
