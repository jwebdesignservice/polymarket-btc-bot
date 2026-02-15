"""
Polymarket FAST ARBITRAGE Bot
------------------------------
Strategy: Catch 1-2 second windows when spreads tighten after BTC moves

Key insight: Spreads are normally wide (99¢/99¢)
But when BTC moves:
1. Binance updates instantly
2. Polymarket takes 1-5 seconds to update
3. In that window, spreads might be 50¢/50¢ or 60¢/40¢
4. We BUY immediately before spreads widen again
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
MIN_EDGE = 0.03  # 3¢ edge minimum (VERY aggressive)
POLL_INTERVAL = 0.5  # Check TWICE per second (faster!)
MAX_SPREAD_SUM = 1.05  # Only trade when Up ask + Down ask < $1.05
MIN_TIME_IN_ROUND = 120  # Don't trade last 2 minutes

# APIs
BINANCE_WS = "wss://stream.binance.com:9443/ws/btcusdt@trade"
CLOB_BOOK_API = "https://clob.polymarket.com/book"

class FastArbBot:
    def __init__(self):
        self.btc_price = None
        self.prev_btc_price = None
        self.target_price = None
        self.token_ids = None
        self.market_info = None
        self.session = None
        self.round_start_time = 0
        self.trades = []
        self.has_traded_this_round = False
        self.last_good_spread_time = 0
        
    async def connect_binance(self):
        """Connect to Binance WebSocket"""
        logger.info("Connecting to Binance...")
        
        try:
            async with websockets.connect(BINANCE_WS) as ws:
                logger.info("✓ Binance connected")
                
                async for message in ws:
                    data = json.loads(message)
                    self.prev_btc_price = self.btc_price
                    self.btc_price = float(data['p'])
                        
        except Exception as e:
            logger.error(f"Binance error: {e}")
            await asyncio.sleep(5)
            await self.connect_binance()
    
    def calculate_fair_odds(self, btc_price, target_price):
        """Calculate fair probability"""
        if not btc_price or not target_price:
            return 0.50, 0.50
        
        distance = btc_price - target_price
        sigma = 150.0
        z_score = distance / sigma
        prob_up = 1.0 / (1.0 + math.exp(-z_score))
        prob_down = 1.0 - prob_up
        
        return prob_up, prob_down
    
    async def discover_market(self):
        """Discover market"""
        logger.info("Discovering market...")
        
        now = int(time.time())
        slot = (now // 300) * 300
        time_in_slot = now - slot
        
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
                self.target_price = self.btc_price if self.btc_price else 70000
                
                logger.info(f"Market: {self.market_info['title']}")
                logger.info(f"Target: ${self.target_price:,.2f}")
                
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
    
    async def execute_trade(self, side, edge, fair_price, market_price):
        """Execute trade"""
        logger.info("=" * 60)
        logger.info(f"⚡ FAST ARB! {side}")
        logger.info(f"Fair: ${fair_price:.3f} | Market: ${market_price:.3f} | Edge: ${edge:.3f}")
        logger.info(f"Profit: ${edge * SHARES:.2f}")
        logger.info("[PAPER TRADE]")
        logger.info("=" * 60)
        
        trade_data = {
            'timestamp': time.time(),
            'side': side,
            'fair_price': fair_price,
            'market_price': market_price,
            'edge': edge,
            'shares': SHARES,
            'profit': edge * SHARES,
            'status': 'executed'
        }
        self.trades.append(trade_data)
        
        import os
        os.makedirs('logs', exist_ok=True)
        with open('logs/trades.jsonl', 'a') as f:
            f.write(json.dumps(trade_data) + '\n')
    
    async def monitor(self):
        """Main loop - check TWICE per second"""
        self.has_traded_this_round = False
        
        while True:
            try:
                elapsed = time.time() - self.round_start_time
                time_left = 300 - elapsed
                
                if elapsed > 305:
                    logger.info("Round complete")
                    if await self.discover_market():
                        self.has_traded_this_round = False
                        continue
                    else:
                        await asyncio.sleep(30)
                        continue
                
                if time_left < MIN_TIME_IN_ROUND:
                    await asyncio.sleep(POLL_INTERVAL)
                    continue
                
                if not self.token_ids:
                    await asyncio.sleep(POLL_INTERVAL)
                    continue
                
                # Fetch orderbooks
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
                
                # Calculate fair odds
                fair_up, fair_down = self.calculate_fair_odds(self.btc_price, self.target_price)
                
                # Check if spreads are TIGHT (opportunity!)
                spread_sum = up_ask + down_ask
                
                if spread_sum < MAX_SPREAD_SUM:
                    # TIGHT SPREADS - this is our window!
                    self.last_good_spread_time = time.time()
                    
                    # Calculate edges
                    up_edge = fair_up - up_ask
                    down_edge = fair_down - down_ask
                    
                    # Log good spread
                    logger.info(f"✓ TIGHT SPREAD! Up:{up_ask:.2f} + Down:{down_ask:.2f} = ${spread_sum:.2f} | "
                              f"Edges: Up{up_edge:+.2f} Down{down_edge:+.2f}")
                    
                    # Trade if edge is good
                    if not self.has_traded_this_round:
                        if up_edge >= MIN_EDGE:
                            await self.execute_trade('UP', up_edge, fair_up, up_ask)
                            self.has_traded_this_round = True
                        elif down_edge >= MIN_EDGE:
                            await self.execute_trade('DOWN', down_edge, fair_down, down_ask)
                            self.has_traded_this_round = True
                else:
                    # Wide spreads - normal state
                    if int(time.time()) % 10 == 0:
                        seconds_since_tight = time.time() - self.last_good_spread_time if self.last_good_spread_time > 0 else 999
                        logger.info(f"[{time_left:.0f}s] Wide spreads (${spread_sum:.2f}) - "
                                  f"last tight: {seconds_since_tight:.0f}s ago")
                
                await asyncio.sleep(POLL_INTERVAL)
                
            except Exception as e:
                logger.error(f"Monitor error: {e}")
                await asyncio.sleep(POLL_INTERVAL)
    
    async def run(self):
        """Start bot"""
        logger.info("=" * 60)
        logger.info("FAST ARBITRAGE BOT")
        logger.info("=" * 60)
        logger.info("Strategy: Catch tight spreads when BTC moves")
        logger.info(f"Max spread sum: ${MAX_SPREAD_SUM}")
        logger.info(f"Min edge: ${MIN_EDGE}")
        logger.info(f"Poll rate: Every {POLL_INTERVAL}s")
        logger.info("=" * 60)
        
        if not await self.discover_market():
            logger.error("Failed to discover market!")
            return
        
        async with aiohttp.ClientSession() as session:
            self.session = session
            await asyncio.gather(
                self.connect_binance(),
                self.monitor()
            )

async def main():
    bot = FastArbBot()
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())
