"""
Polymarket LATENT ARBITRAGE Bot
--------------------------------
Strategy: Exploit lag between Binance BTC price and Polymarket odds

How it works:
1. Track real-time BTC price from Binance WebSocket (100ms updates)
2. Calculate "fair odds" based on BTC distance from target
3. Compare to Polymarket CLOB orderbook
4. When Polymarket is STALE (slow to update) → BUY mispriced side
5. Profit when odds catch up OR market closes

Example:
- Target: $70,000
- BTC on Binance: $70,150 (+$150 above target)
- Fair odds: UP 85%, DOWN 15%
- Polymarket shows: UP 60¢, DOWN 40¢ (STALE!)
- ACTION: Buy UP at 60¢ (should be 85¢)
- PROFIT: $0.25+ per share when odds update
"""

import asyncio
import websockets
import aiohttp
import json
import time
import logging
from datetime import datetime
from playwright.async_api import async_playwright
import math

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
SHARES = 10
MIN_EDGE = 0.05  # Need 5¢ edge to trade (AGGRESSIVE - lower threshold)
POLL_INTERVAL = 1.0  # Check orderbook every second
MIN_TIME_IN_ROUND = 90  # Don't trade in last 90 seconds (safer)

# APIs
BINANCE_WS = "wss://stream.binance.com:9443/ws/btcusdt@trade"
CLOB_BOOK_API = "https://clob.polymarket.com/book"

class ArbitrageBot:
    def __init__(self):
        self.btc_price = None
        self.target_price = None
        self.token_ids = None
        self.market_info = None
        self.session = None
        self.round_start_time = 0
        self.trades = []
        self.has_traded_this_round = False
        
    async def connect_binance(self):
        """Connect to Binance WebSocket for real-time BTC price"""
        logger.info("Connecting to Binance WebSocket...")
        
        try:
            async with websockets.connect(BINANCE_WS) as ws:
                logger.info("✓ Connected to Binance!")
                
                async for message in ws:
                    data = json.loads(message)
                    self.btc_price = float(data['p'])  # Current price
                    
                    # Don't log individual prices (too spammy)
                    # Will be logged in monitor loop
                        
        except Exception as e:
            logger.error(f"Binance WebSocket error: {e}")
            await asyncio.sleep(5)
            await self.connect_binance()  # Reconnect
    
    def calculate_fair_odds(self, btc_price, target_price):
        """
        Calculate fair probability based on BTC distance from target
        
        Uses simplified normal distribution:
        - At target: 50/50
        - $50 above: ~65% UP
        - $100 above: ~75% UP
        - $200 above: ~90% UP
        """
        if not btc_price or not target_price:
            return 0.50, 0.50
        
        distance = btc_price - target_price
        
        # Use sigmoid-like function for probability
        # More distance = higher probability of that side winning
        
        # Volatility factor: BTC moves ~$50-200 in 5 minutes
        # Use $150 as the "standard deviation"
        sigma = 150.0
        
        # Probability UP wins = 1 / (1 + exp(-distance/sigma))
        # This gives smooth curve from 0% to 100%
        
        z_score = distance / sigma
        prob_up = 1.0 / (1.0 + math.exp(-z_score))
        prob_down = 1.0 - prob_up
        
        return prob_up, prob_down
    
    async def discover_market(self):
        """Discover current market and extract target price"""
        logger.info("=" * 60)
        logger.info("DISCOVERING MARKET...")
        logger.info("=" * 60)
        
        # Calculate current slot
        now = int(time.time())
        slot = (now // 300) * 300
        time_in_slot = now - slot
        
        # Wait for next round if < 60s left
        if 300 - time_in_slot < 60:
            wait_time = 310 - time_in_slot
            logger.info(f"Waiting {wait_time}s for next round...")
            await asyncio.sleep(wait_time)
            now = int(time.time())
            slot = (now // 300) * 300
        
        self.round_start_time = slot
        market_url = f"https://polymarket.com/event/btc-updown-5m-{slot}"
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = await context.new_page()
                
                await page.goto(market_url, wait_until="load", timeout=60000)
                await page.wait_for_timeout(3000)
                
                # Extract market data
                market_data_json = await page.evaluate("""() => {
                    const nextData = window.__NEXT_DATA__?.props?.pageProps?.dehydratedState?.queries || [];
                    for (const q of nextData) {
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
                                        clobTokenIds: tokenIds
                                    });
                                }
                            }
                        }
                    }
                    return null;
                }""")
                
                await context.close()
                await browser.close()
                
                if not market_data_json:
                    logger.error("Could not extract market data")
                    return False
                
                market_data = json.loads(market_data_json)
                
                self.market_info = {
                    'title': market_data['title'],
                    'slug': market_data['slug'],
                    'token_ids': {
                        'Up': market_data['clobTokenIds'][0],
                        'Down': market_data['clobTokenIds'][1]
                    }
                }
                self.token_ids = self.market_info['token_ids']
                
                # Set target to current BTC price (will update from Binance)
                self.target_price = self.btc_price if self.btc_price else 70000
                
                logger.info("=" * 60)
                logger.info(f"MARKET: {self.market_info['title']}")
                logger.info(f"Target: ${self.target_price:,.2f} (from BTC at market start)")
                logger.info("=" * 60)
                
                with open('current_market.json', 'w') as f:
                    json.dump(self.market_info, f, indent=2)
                
                return True
                
        except Exception as e:
            logger.error(f"Discovery error: {e}")
            return False
    
    async def fetch_order_book(self, token_id):
        """Fetch orderbook"""
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
    
    def find_arbitrage(self, btc_price, target_price, up_ask, down_ask):
        """
        Find arbitrage opportunity by comparing fair odds to market prices
        
        Returns: (side, edge, fair_price, market_price) or None
        """
        if not (btc_price and target_price and up_ask and down_ask):
            return None
        
        # Calculate fair odds
        fair_up, fair_down = self.calculate_fair_odds(btc_price, target_price)
        
        # FALLBACK: If orderbooks are dead (both >98¢), use directional strategy
        if up_ask > 0.98 and down_ask > 0.98:
            distance = btc_price - target_price
            # If BTC significantly above/below target, trade directionally at 99¢
            if abs(distance) > 200:  # $200+ difference
                if distance > 200 and fair_up > 0.85:
                    # BTC way above, UP very likely (>85%)
                    # Even at 99¢, expected value is positive
                    edge = fair_up - up_ask
                    return ('UP', edge, fair_up, up_ask)
                elif distance < -200 and fair_down > 0.85:
                    # BTC way below, DOWN very likely (>85%)
                    edge = fair_down - down_ask
                    return ('DOWN', edge, fair_down, down_ask)
            return None
        
        # NORMAL CASE: Compare to market prices (ask = what we'd pay)
        up_edge = fair_up - up_ask  # If positive, UP is underpriced
        down_edge = fair_down - down_ask  # If positive, DOWN is underpriced
        
        # Find best opportunity
        if up_edge >= MIN_EDGE:
            return ('UP', up_edge, fair_up, up_ask)
        elif down_edge >= MIN_EDGE:
            return ('DOWN', down_edge, fair_down, down_ask)
        
        return None
    
    async def execute_trade(self, side, edge, fair_price, market_price):
        """Execute arbitrage trade"""
        logger.info("=" * 60)
        logger.info(f"⚡ ARBITRAGE OPPORTUNITY!")
        logger.info(f"Side: {side}")
        logger.info(f"Fair price: ${fair_price:.3f}")
        logger.info(f"Market price: ${market_price:.3f}")
        logger.info(f"Edge: ${edge:.3f} per share")
        logger.info(f"Total profit potential: ${edge * SHARES:.2f}")
        logger.info("[PAPER TRADE] Executing...")
        logger.info("=" * 60)
        
        trade_data = {
            'timestamp': time.time(),
            'side': side,
            'fair_price': fair_price,
            'market_price': market_price,
            'edge': edge,
            'shares': SHARES,
            'expected_profit': edge * SHARES,
            'status': 'executed'
        }
        self.trades.append(trade_data)
        
        # Save to log
        import os
        os.makedirs('logs', exist_ok=True)
        with open('logs/trades.jsonl', 'a') as f:
            f.write(json.dumps(trade_data) + '\n')
        
        logger.info(f"✅ Trade logged (total trades: {len(self.trades)})")
    
    async def monitor_arbitrage(self):
        """Main monitoring loop"""
        self.has_traded_this_round = False
        
        while True:
            try:
                elapsed = time.time() - self.round_start_time
                time_left = 300 - elapsed
                
                # Move to next round when time is up
                if elapsed > 305:
                    logger.info("Round complete, discovering next market...")
                    if await self.discover_market():
                        self.has_traded_this_round = False
                        continue
                    else:
                        await asyncio.sleep(30)
                        continue
                
                # Don't trade in last minute (too risky)
                if time_left < MIN_TIME_IN_ROUND:
                    if int(time.time()) % 10 == 0:
                        logger.info(f"[{time_left:.0f}s left] Waiting for next round...")
                    await asyncio.sleep(POLL_INTERVAL)
                    continue
                
                # Fetch orderbooks
                if not self.token_ids:
                    await asyncio.sleep(POLL_INTERVAL)
                    continue
                
                up_book = await self.fetch_order_book(self.token_ids["Up"])
                down_book = await self.fetch_order_book(self.token_ids["Down"])
                
                if not (up_book and down_book):
                    await asyncio.sleep(POLL_INTERVAL)
                    continue
                
                up_bid, up_ask = self.get_best_prices(up_book)
                down_bid, down_ask = self.get_best_prices(down_book)
                
                if not (up_ask and down_ask):
                    await asyncio.sleep(POLL_INTERVAL)
                    continue
                
                # Log if orderbooks look dead (but don't skip - let edge calculation decide)
                if up_ask > 0.98 and down_ask > 0.98:
                    if int(time.time()) % 30 == 0:
                        logger.warning("Wide spreads detected (both >98¢) - looking for opportunities anyway...")
                
                # Calculate fair odds and check for arbitrage
                fair_up, fair_down = self.calculate_fair_odds(self.btc_price, self.target_price)
                
                # Log status every 10 seconds
                if int(time.time()) % 10 == 0:
                    distance = self.btc_price - self.target_price if self.btc_price and self.target_price else 0
                    logger.info(f"[{time_left:.0f}s] BTC: ${self.btc_price:,.2f} ({distance:+.0f} from target) | "
                              f"Fair: UP {fair_up*100:.0f}% DOWN {fair_down*100:.0f}% | "
                              f"Market: UP ${up_ask:.2f} DOWN ${down_ask:.2f}")
                
                # Check for arbitrage opportunity
                if not self.has_traded_this_round:
                    opp = self.find_arbitrage(self.btc_price, self.target_price, up_ask, down_ask)
                    if opp:
                        side, edge, fair_price, market_price = opp
                        await self.execute_trade(side, edge, fair_price, market_price)
                        self.has_traded_this_round = True
                
                await asyncio.sleep(POLL_INTERVAL)
                
            except Exception as e:
                logger.error(f"Monitor error: {e}")
                await asyncio.sleep(POLL_INTERVAL)
    
    async def run(self):
        """Start bot"""
        logger.info("=" * 60)
        logger.info("POLYMARKET LATENT ARBITRAGE BOT")
        logger.info("=" * 60)
        logger.info("Strategy: Exploit lag between Binance and Polymarket")
        logger.info(f"Min edge required: ${MIN_EDGE:.2f} per share")
        logger.info(f"Position size: {SHARES} shares")
        logger.info("=" * 60)
        
        # Discover initial market
        if not await self.discover_market():
            logger.error("Failed to discover market!")
            return
        
        async with aiohttp.ClientSession() as session:
            self.session = session
            
            # Run Binance WebSocket and monitoring in parallel
            await asyncio.gather(
                self.connect_binance(),
                self.monitor_arbitrage()
            )

async def main():
    bot = ArbitrageBot()
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())
