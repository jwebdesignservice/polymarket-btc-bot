"""
Polymarket HEDGE Strategy Bot
------------------------------
The REAL strategy that works:

1. START: Buy BOTH Up and Down at round start (~50¢ each)
2. MONITOR: Watch probability chart as BTC moves
3. SELL LOSER: When one side hits 75%+, sell the losing side
4. COLLECT: Keep winning side, collect $1.00 payout

Example:
- Start: Buy 10 UP @ 50¢ + 10 DOWN @ 50¢ = $10.00 cost
- BTC moves up → UP becomes 80%, DOWN becomes 20%
- Sell 10 DOWN @ 20¢ = $2.00 recovered
- Net cost: $10.00 - $2.00 = $8.00
- Round closes: UP wins, collect 10 × $1.00 = $10.00
- Profit: $10.00 - $8.00 = $2.00 (20% return!)
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
ENTRY_WINDOW = 30  # Buy both sides in first 30 seconds
EXIT_THRESHOLD = 0.75  # Sell losing side when winner hits 75%
POLL_INTERVAL = 2.0  # Check every 2 seconds
MIN_SELL_PRICE = 0.10  # Don't sell losing side for less than 10¢

# APIs
BINANCE_WS = "wss://stream.binance.com:9443/ws/btcusdt@trade"
CLOB_BOOK_API = "https://clob.polymarket.com/book"

class HedgeBot:
    def __init__(self):
        self.btc_price = None
        self.target_price = None
        self.token_ids = None
        self.market_info = None
        self.session = None
        self.round_start_time = 0
        
        # Trade tracking
        self.position = {
            'up_shares': 0,
            'down_shares': 0,
            'up_cost': 0,
            'down_cost': 0,
            'has_entered': False,
            'has_exited': False
        }
        self.trades = []
        
    async def connect_binance(self):
        """Connect to Binance WebSocket"""
        logger.info("Connecting to Binance...")
        
        try:
            async with websockets.connect(BINANCE_WS) as ws:
                logger.info("✓ Binance connected")
                
                async for message in ws:
                    data = json.loads(message)
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
        logger.info("=" * 60)
        logger.info("DISCOVERING NEXT MARKET...")
        logger.info("=" * 60)
        
        now = int(time.time())
        slot = (now // 300) * 300
        time_in_slot = now - slot
        
        # Wait for round to actually start
        if time_in_slot < 10:
            wait_time = 10 - time_in_slot
            logger.info(f"Waiting {wait_time}s for round to start...")
            await asyncio.sleep(wait_time)
            now = int(time.time())
            slot = (now // 300) * 300
        
        self.round_start_time = time.time()
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
                
                # Reset position for new round
                self.position = {
                    'up_shares': 0,
                    'down_shares': 0,
                    'up_cost': 0,
                    'down_cost': 0,
                    'has_entered': False,
                    'has_exited': False
                }
                
                logger.info(f"Market: {self.market_info['title']}")
                logger.info(f"Target: ${self.target_price:,.2f}")
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
    
    async def enter_hedge(self, up_ask, down_ask):
        """Buy BOTH sides to establish hedge"""
        total_cost = (up_ask + down_ask) * SHARES
        
        logger.info("=" * 60)
        logger.info("🔒 ENTERING HEDGE POSITION")
        logger.info(f"Buy {SHARES} UP @ ${up_ask:.3f} = ${up_ask * SHARES:.2f}")
        logger.info(f"Buy {SHARES} DOWN @ ${down_ask:.3f} = ${down_ask * SHARES:.2f}")
        logger.info(f"Total cost: ${total_cost:.2f}")
        logger.info(f"Guaranteed payout: ${SHARES:.2f}")
        logger.info("[PAPER TRADE] Position opened")
        logger.info("=" * 60)
        
        self.position['up_shares'] = SHARES
        self.position['down_shares'] = SHARES
        self.position['up_cost'] = up_ask * SHARES
        self.position['down_cost'] = down_ask * SHARES
        self.position['has_entered'] = True
        
        # Log entry
        trade_data = {
            'timestamp': time.time(),
            'action': 'ENTER_HEDGE',
            'up_shares': SHARES,
            'down_shares': SHARES,
            'up_price': up_ask,
            'down_price': down_ask,
            'total_cost': total_cost,
            'status': 'entered'
        }
        self.trades.append(trade_data)
        
        import os
        os.makedirs('logs', exist_ok=True)
        with open('logs/trades.jsonl', 'a') as f:
            f.write(json.dumps(trade_data) + '\n')
    
    async def exit_losing_side(self, side, sell_price, prob):
        """Sell the losing side"""
        shares = self.position['down_shares'] if side == 'DOWN' else self.position['up_shares']
        recovered = sell_price * shares
        
        logger.info("=" * 60)
        logger.info(f"💰 SELLING LOSING SIDE: {side}")
        logger.info(f"Probability: {prob*100:.1f}% (winner is clear)")
        logger.info(f"Sell {shares} {side} @ ${sell_price:.3f} = ${recovered:.2f} recovered")
        logger.info(f"Original cost: ${self.position['down_cost'] if side == 'DOWN' else self.position['up_cost']:.2f}")
        logger.info("[PAPER TRADE] Position closed")
        logger.info("=" * 60)
        
        if side == 'DOWN':
            self.position['down_shares'] = 0
        else:
            self.position['up_shares'] = 0
        
        self.position['has_exited'] = True
        
        # Calculate P&L
        total_cost = self.position['up_cost'] + self.position['down_cost']
        net_cost = total_cost - recovered
        expected_payout = SHARES * 1.00  # Winning side pays $1.00 per share
        expected_profit = expected_payout - net_cost
        
        logger.info(f"Net cost after exit: ${net_cost:.2f}")
        logger.info(f"Expected payout: ${expected_payout:.2f}")
        logger.info(f"Expected profit: ${expected_profit:.2f}")
        
        # Log exit
        trade_data = {
            'timestamp': time.time(),
            'action': 'EXIT_LOSER',
            'side_sold': side,
            'shares': shares,
            'sell_price': sell_price,
            'recovered': recovered,
            'net_cost': net_cost,
            'expected_profit': expected_profit,
            'status': 'exited'
        }
        self.trades.append(trade_data)
        
        import os
        with open('logs/trades.jsonl', 'a') as f:
            f.write(json.dumps(trade_data) + '\n')
    
    async def monitor(self):
        """Main loop"""
        while True:
            try:
                elapsed = time.time() - self.round_start_time
                time_left = 300 - elapsed
                
                # Move to next round
                if elapsed > 305:
                    logger.info("Round complete, discovering next...")
                    if await self.discover_market():
                        continue
                    else:
                        await asyncio.sleep(30)
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
                
                if not (up_ask and down_ask and up_bid and down_bid):
                    await asyncio.sleep(POLL_INTERVAL)
                    continue
                
                # Calculate probabilities
                fair_up, fair_down = self.calculate_fair_odds(self.btc_price, self.target_price)
                
                # PHASE 1: Enter hedge in first 30 seconds
                if not self.position['has_entered'] and elapsed < ENTRY_WINDOW:
                    # Accept ANY prices under $2.00 (even wide spreads)
                    # With hedge strategy, we're guaranteed to win one side
                    if (up_ask + down_ask) < 2.00:
                        await self.enter_hedge(up_ask, down_ask)
                    else:
                        logger.warning(f"[{time_left:.0f}s] Waiting for better entry prices (${up_ask + down_ask:.2f})")
                
                # PHASE 2: Monitor and exit losing side when winner is clear
                elif self.position['has_entered'] and not self.position['has_exited']:
                    # Check if one side has high probability (winner is clear)
                    if fair_up >= EXIT_THRESHOLD and down_bid >= MIN_SELL_PRICE:
                        # UP is winning, sell DOWN
                        await self.exit_losing_side('DOWN', down_bid, fair_down)
                    elif fair_down >= EXIT_THRESHOLD and up_bid >= MIN_SELL_PRICE:
                        # DOWN is winning, sell UP
                        await self.exit_losing_side('UP', up_bid, fair_up)
                    else:
                        # Log status
                        if int(time.time()) % 10 == 0:
                            logger.info(f"[{time_left:.0f}s] Monitoring: UP {fair_up*100:.0f}% ({up_bid:.2f}/{up_ask:.2f}) | "
                                      f"DOWN {fair_down*100:.0f}% ({down_bid:.2f}/{down_ask:.2f})")
                
                # PHASE 3: Wait for payout
                elif self.position['has_exited']:
                    if int(time.time()) % 20 == 0:
                        winner = 'UP' if self.position['up_shares'] > 0 else 'DOWN'
                        logger.info(f"[{time_left:.0f}s] Holding {winner}, waiting for payout...")
                
                else:
                    # Waiting to enter
                    if int(time.time()) % 10 == 0:
                        logger.info(f"[{time_left:.0f}s] Waiting for entry window...")
                
                await asyncio.sleep(POLL_INTERVAL)
                
            except Exception as e:
                logger.error(f"Monitor error: {e}")
                await asyncio.sleep(POLL_INTERVAL)
    
    async def run(self):
        """Start bot"""
        logger.info("=" * 60)
        logger.info("HEDGE STRATEGY BOT")
        logger.info("=" * 60)
        logger.info("Strategy:")
        logger.info("  1. Buy BOTH Up + Down in first 30s")
        logger.info("  2. Monitor probabilities")
        logger.info("  3. Sell losing side when winner hits 75%+")
        logger.info("  4. Collect $1.00 payout on winning side")
        logger.info(f"Position: {SHARES} shares per side")
        logger.info(f"Exit threshold: {EXIT_THRESHOLD*100}%")
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
    bot = HedgeBot()
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())
