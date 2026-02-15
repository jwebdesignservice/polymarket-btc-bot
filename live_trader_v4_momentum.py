"""
Polymarket BTC 5-Min MOMENTUM Strategy
--------------------------------------
Strategy: Trade on BTC price movements vs target
- If BTC moving toward target → Buy the likely winner
- If prices are mispriced vs BTC distance → Trade the edge
- Use order book inefficiencies when they appear
"""

import asyncio
import aiohttp
import time
import logging
import json
from datetime import datetime
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Strategy parameters
SHARES = 10
POLL_INTERVAL = 1.0  # Check every second
MIN_EDGE = 0.05      # Need 5% edge to trade

CLOB_BOOK_API = "https://clob.polymarket.com/book"
COINBASE_BTC_API = "https://api.coinbase.com/v2/prices/BTC-USD/spot"

class MomentumBot:
    def __init__(self):
        self.token_ids = None
        self.market_info = None
        self.session = None
        self.btc_price = None
        self.target_price = None
        self.trades = []
        
    async def get_btc_price(self):
        """Get current BTC price from Coinbase"""
        try:
            async with self.session.get(COINBASE_BTC_API) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return float(data['data']['amount'])
        except Exception as e:
            logger.error(f"Error fetching BTC price: {e}")
        return None
    
    async def discover_market(self):
        """Discover current market and extract target price"""
        logger.info("=" * 60)
        logger.info("DISCOVERING MARKET...")
        logger.info("=" * 60)
        
        for attempt in range(3):
            if attempt > 0:
                await asyncio.sleep(5)
            
            try:
                async with async_playwright() as p:
                    logger.info("Launching browser...")
                    browser = await p.chromium.launch(headless=True)
                    page = await browser.new_page(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    )
                    
                    # Calculate current slot
                    now = int(time.time())
                    slot = (now // 300) * 300
                    time_in_slot = now - slot
                    
                    if 300 - time_in_slot < 60:
                        await asyncio.sleep(65)
                        now = int(time.time())
                        slot = (now // 300) * 300
                    
                    market_url = f"https://polymarket.com/event/btc-updown-5m-{slot}"
                    logger.info(f"Loading {market_url}...")
                    
                    await page.goto(market_url, wait_until="load", timeout=60000)
                    await page.wait_for_timeout(3000)
                    
                    # Extract market data AND target price from page
                    result = await page.evaluate("""() => {
                        const nextData = window.__NEXT_DATA__?.props?.pageProps?.dehydratedState?.queries || [];
                        
                        // Also try to find target price from DOM
                        let targetPrice = null;
                        const priceElements = document.querySelectorAll('[class*="price"], [class*="beat"], [class*="target"]');
                        for (const el of priceElements) {
                            const text = el.textContent || "";
                            const match = text.match(/\\$?([\\d,]+\\.?\\d*)/);
                            if (match && parseFloat(match[1].replace(/,/g, '')) > 10000) {
                                targetPrice = parseFloat(match[1].replace(/,/g, ''));
                                break;
                            }
                        }
                        
                        for (const q of nextData) {
                            const key = q.queryKey || [];
                            if (key[0] === '/api/event/slug') {
                                const data = q.state?.data;
                                if (data?.markets?.[0]) {
                                    const market = data.markets[0];
                                    const tokenIds = market.clobTokenIds || [];
                                    const description = market.description || data.description || "";
                                    
                                    // Try extracting from description if not found in DOM
                                    if (!targetPrice) {
                                        const descMatch = description.match(/\\$?([\\d,]+\\.?\\d*)/);
                                        if (descMatch) {
                                            const price = parseFloat(descMatch[1].replace(/,/g, ''));
                                            if (price > 10000) targetPrice = price;
                                        }
                                    }
                                    
                                    if (tokenIds.length === 2) {
                                        return JSON.stringify({
                                            title: data.title,
                                            slug: data.slug,
                                            conditionId: market.conditionId,
                                            clobTokenIds: tokenIds,
                                            closed: data.closed,
                                            description: description,
                                            targetPrice: targetPrice
                                        });
                                    }
                                }
                            }
                        }
                        return null;
                    }""")
                    
                    await browser.close()
                    
                    if not result:
                        logger.error("No market data found")
                        continue
                    
                    market_data = json.loads(result)
                    
                    # Extract and store target price
                    target_from_data = market_data.get('targetPrice')
                    if target_from_data:
                        self.target_price = target_from_data
                        logger.info(f"✓ Target price found: ${self.target_price:,.2f}")
                    else:
                        # Will set on first monitoring loop if needed
                        logger.warning(f"⚠ No target found in page, will use first BTC reading")
                    
                    self.market_info = {
                        'title': market_data['title'],
                        'slug': market_data['slug'],
                        'closed': market_data['closed'],
                        'condition_id': market_data['conditionId'],
                        'token_ids': {
                            'Up': market_data['clobTokenIds'][0],
                            'Down': market_data['clobTokenIds'][1]
                        },
                        'target_price': self.target_price
                    }
                    
                    self.token_ids = self.market_info['token_ids']
                    
                    logger.info("=" * 60)
                    logger.info(f"MARKET: {self.market_info['title']}")
                    logger.info(f"Slug: {self.market_info['slug']}")
                    if self.target_price:
                        logger.info(f"Target: ${self.target_price:,.2f}")
                    logger.info("=" * 60)
                    
                    with open('current_market.json', 'w') as f:
                        json.dump(self.market_info, f, indent=2)
                    
                    return True
                    
            except Exception as e:
                logger.error(f"Discovery error: {e}")
        
        return False
    
    async def fetch_order_book(self, token_id):
        """Fetch order book"""
        try:
            async with self.session.get(f"{CLOB_BOOK_API}?token_id={token_id}") as resp:
                if resp.status == 200:
                    return await resp.json()
        except:
            pass
        return None
    
    def get_best_prices(self, book):
        """Get best bid/ask"""
        if not book:
            return None, None
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        best_bid = float(bids[0]["price"]) if bids else None
        best_ask = float(asks[0]["price"]) if asks else None
        return best_bid, best_ask
    
    def find_opportunity(self, up_bid, up_ask, down_bid, down_ask, btc_price, target_price):
        """
        Find trading opportunities based on:
        1. Order book arbitrage (Up + Down < 1.00)
        2. Probability mispricing vs BTC distance
        3. Momentum opportunities
        """
        opportunities = []
        
        # Check pure arbitrage
        if up_ask and down_ask and (up_ask + down_ask) < 0.98:
            profit = 1.00 - (up_ask + down_ask)
            opportunities.append({
                'type': 'ARBITRAGE',
                'action': 'BUY_BOTH',
                'up_price': up_ask,
                'down_price': down_ask,
                'profit': profit * SHARES,
                'confidence': 'GUARANTEED'
            })
        
        # Check if we can trade spread
        if up_bid and down_bid and (up_bid + down_bid) > 1.02:
            profit = (up_bid + down_bid) - 1.00
            opportunities.append({
                'type': 'REVERSE_ARB',
                'action': 'SELL_BOTH',
                'up_price': up_bid,
                'down_price': down_bid,
                'profit': profit * SHARES,
                'confidence': 'GUARANTEED'
            })
        
        # Check probability-based opportunities
        if btc_price and target_price and up_ask and down_ask:
            distance = btc_price - target_price
            
            # Calculate rough expected probabilities based on distance
            # (Very simplified - real model would use volatility, time remaining, etc.)
            
            # If BTC is $50+ above target → UP heavily favored
            if distance >= 50:
                expected_up = 0.75  # 75% chance UP wins
                expected_down = 0.25
                
                # If DOWN is priced higher than it should be, that's weird
                if down_ask > 0.40:
                    opportunities.append({
                        'type': 'PROBABILITY_MISPRICE',
                        'action': 'BUY_UP',
                        'price': up_ask,
                        'profit': (1.00 - up_ask) * SHARES,
                        'confidence': f'BTC ${distance:.0f} above target, UP favored but ask={up_ask:.2f}'
                    })
            
            # If BTC is $50+ below target → DOWN heavily favored
            elif distance <= -50:
                expected_up = 0.25
                expected_down = 0.75
                
                if up_ask > 0.40:
                    opportunities.append({
                        'type': 'PROBABILITY_MISPRICE',
                        'action': 'BUY_DOWN',
                        'price': down_ask,
                        'profit': (1.00 - down_ask) * SHARES,
                        'confidence': f'BTC ${abs(distance):.0f} below target, DOWN favored but ask={down_ask:.2f}'
                    })
            
            # Near target → should be close to 50/50
            else:
                # Both should be near 0.50
                if up_ask < 0.40 or down_ask < 0.40:
                    cheap_side = 'UP' if up_ask < down_ask else 'DOWN'
                    cheap_price = min(up_ask, down_ask)
                    opportunities.append({
                        'type': 'NEAR_TARGET_CHEAP',
                        'action': f'BUY_{cheap_side}',
                        'price': cheap_price,
                        'profit': (1.00 - cheap_price) * SHARES * 0.5,  # 50% chance
                        'confidence': f'BTC near target (${distance:.0f}), {cheap_side} cheap at {cheap_price:.2f}'
                    })
        
        return opportunities
    
    async def monitor_market(self):
        """Main monitoring loop"""
        logger.info("Starting MOMENTUM trading...")
        logger.info(f"Position size: {SHARES} shares")
        logger.info("=" * 60)
        
        round_start = time.time()
        
        while True:
            try:
                # Refresh market every 4.5 min
                if (time.time() - round_start) / 60.0 > 4.5:
                    logger.info("Discovering next market...")
                    if not await self.discover_market():
                        await asyncio.sleep(30)
                        continue
                    round_start = time.time()
                
                # Fetch data
                btc_price = await self.get_btc_price()
                up_book = await self.fetch_order_book(self.token_ids["Up"])
                down_book = await self.fetch_order_book(self.token_ids["Down"])
                
                if not up_book or not down_book:
                    await asyncio.sleep(POLL_INTERVAL)
                    continue
                
                up_bid, up_ask = self.get_best_prices(up_book)
                down_bid, down_ask = self.get_best_prices(down_book)
                
                if not (up_bid and up_ask and down_bid and down_ask):
                    if int(time.time()) % 10 == 0:
                        logger.warning("Incomplete orderbook data")
                    await asyncio.sleep(POLL_INTERVAL)
                    continue
                
                # Log every 10 seconds with target comparison
                if int(time.time()) % 10 == 0:
                    if self.target_price and btc_price:
                        diff = btc_price - self.target_price
                        logger.info(f"BTC: ${btc_price:,.2f} (target ${self.target_price:,.2f}, {diff:+.0f}) | Up: {up_bid:.3f}/{up_ask:.3f} | Down: {down_bid:.3f}/{down_ask:.3f}")
                    else:
                        logger.info(f"BTC: ${btc_price:,.2f} | Up: {up_bid:.3f}/{up_ask:.3f} | Down: {down_bid:.3f}/{down_ask:.3f}")
                
                # Set target if not set yet (fallback)
                if not self.target_price and btc_price:
                    self.target_price = btc_price
                    logger.info(f"Target set to first BTC reading: ${self.target_price:,.2f}")
                
                # Find opportunities
                opportunities = self.find_opportunity(up_bid, up_ask, down_bid, down_ask, btc_price, self.target_price)
                
                for opp in opportunities:
                    logger.info("=" * 60)
                    logger.info(f"🎯 {opp['type']} OPPORTUNITY!")
                    logger.info(f"Action: {opp['action']}")
                    logger.info(f"Expected profit: ${opp.get('profit', 0):.2f}")
                    logger.info(f"Confidence: {opp['confidence']}")
                    logger.info("[PAPER TRADE] Executing...")
                    logger.info("=" * 60)
                    
                    self.trades.append({
                        'timestamp': time.time(),
                        'type': opp['type'],
                        'action': opp['action'],
                        'profit': opp.get('profit', 0)
                    })
                    
                    # Wait before next check
                    await asyncio.sleep(5)
                
                await asyncio.sleep(POLL_INTERVAL)
                
            except Exception as e:
                logger.error(f"Error: {e}")
                await asyncio.sleep(POLL_INTERVAL)
    
    async def run(self):
        """Start bot"""
        logger.info("=" * 60)
        logger.info("POLYMARKET MOMENTUM BOT")
        logger.info("=" * 60)
        logger.info("Strategies:")
        logger.info("  1. Pure arbitrage (Up + Down < $1.00)")
        logger.info("  2. Reverse arbitrage (sell both when overpriced)")
        logger.info("  3. Momentum (buy underpriced side based on BTC movement)")
        logger.info("=" * 60)
        
        if not await self.discover_market():
            logger.error("Failed to discover market!")
            return
        
        async with aiohttp.ClientSession() as session:
            self.session = session
            await self.monitor_market()

async def main():
    bot = MomentumBot()
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())
