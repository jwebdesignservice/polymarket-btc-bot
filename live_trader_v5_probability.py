"""
Polymarket BTC 5-Min PROBABILITY Strategy
-----------------------------------------
Strategy: Scrape live probability from Polymarket, buy when 75%+ confident

Timeline:
- Monitor probability throughout round
- When UP or DOWN hits 75%+ → BUY that side at market price
- Wait for close, collect profit
- Move to next round

Win rate: 75%+ should win most trades
Profit: $1.00 payout - cost (even small profits add up)
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
PROBABILITY_THRESHOLD = 0.75  # 75% confidence required
POLL_INTERVAL = 3.0  # Check every 3 seconds (faster!)
MIN_TIME_IN_ROUND = 90  # Trade after 90 seconds (more opportunities)

CLOB_BOOK_API = "https://clob.polymarket.com/book"

class ProbabilityBot:
    def __init__(self):
        self.token_ids = None
        self.market_info = None
        self.session = None
        self.round_start_time = 0
        self.trades = []
        self.has_traded_this_round = False
        
    async def discover_and_monitor_market(self):
        """Discover market and monitor probabilities in same browser session"""
        logger.info("=" * 60)
        logger.info("DISCOVERING MARKET AND STARTING MONITOR...")
        logger.info("=" * 60)
        
        # Calculate current slot
        now = int(time.time())
        slot = (now // 300) * 300
        time_in_slot = now - slot
        
        # Wait for next round if less than 60s left
        if 300 - time_in_slot < 60:
            wait_time = 310 - time_in_slot
            logger.info(f"Waiting {wait_time}s for next round...")
            await asyncio.sleep(wait_time)
            now = int(time.time())
            slot = (now // 300) * 300
        
        self.round_start_time = slot
        market_url = f"https://polymarket.com/event/btc-updown-5m-{slot}"
        
        logger.info(f"Market URL: {market_url}")
        logger.info(f"Round start: {time.strftime('%H:%M:%S', time.gmtime(slot))} GMT")
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)  # Headless for stability
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = await context.new_page()
                
                await page.goto(market_url, wait_until="load", timeout=60000)
                await page.wait_for_timeout(5000)  # Wait for full page load
                
                # Extract market data once
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
                                        clobTokenIds: tokenIds,
                                        closed: data.closed
                                    });
                                }
                            }
                        }
                    }
                    return null;
                }""")
                
                if not market_data_json:
                    logger.error("Could not extract market data")
                    await browser.close()
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
                
                logger.info("=" * 60)
                logger.info(f"MARKET: {self.market_info['title']}")
                logger.info(f"MONITORING PROBABILITIES (threshold: {PROBABILITY_THRESHOLD*100}%)")
                logger.info("=" * 60)
                
                # Save market data for dashboard
                with open('current_market.json', 'w') as f:
                    json.dump(self.market_info, f, indent=2)
                
                # Monitor probabilities in loop
                await self.monitor_probabilities(page)
                
                await context.close()
                await browser.close()
                return True
                
        except Exception as e:
            logger.error(f"Error: {e}")
            return False
    
    async def monitor_probabilities(self, page):
        """Monitor live probabilities and trade when threshold hit"""
        self.has_traded_this_round = False
        
        while True:
            try:
                # Check if round should be over
                elapsed = time.time() - self.round_start_time
                if elapsed > 320:  # 5min 20s (give buffer)
                    logger.info("Round complete, moving to next...")
                    break
                
                # Don't trade in first 2 minutes
                if elapsed < MIN_TIME_IN_ROUND:
                    remaining = MIN_TIME_IN_ROUND - elapsed
                    if int(elapsed) % 30 == 0:
                        logger.info(f"Waiting {remaining:.0f}s before trading window opens...")
                    await asyncio.sleep(5)
                    continue
                
                # Scrape current probabilities from page
                probs = await page.evaluate("""() => {
                    // Try to find probability elements
                    // Look for text like "51% chance" or probability displays
                    const textContent = document.body.innerText;
                    
                    // Try to find UP probability
                    const upMatch = textContent.match(/UP[\\s\\S]{0,100}?(\\d+)%/i) || 
                                   textContent.match(/(\\d+)%[\\s\\S]{0,100}?chance/i);
                    
                    // Also try structured data
                    let upProb = null;
                    let downProb = null;
                    
                    // Look for elements with probability class/data
                    const probElements = document.querySelectorAll('[class*="probability"], [class*="chance"], [class*="percent"]');
                    for (const el of probElements) {
                        const text = el.textContent;
                        const match = text.match(/(\\d+)%/);
                        if (match) {
                            const pct = parseInt(match[1]);
                            if (pct >= 1 && pct <= 99) {
                                if (!upProb) upProb = pct;
                                else if (!downProb) downProb = pct;
                            }
                        }
                    }
                    
                    // If we found probabilities, ensure they sum to ~100
                    if (upProb && downProb && Math.abs((upProb + downProb) - 100) < 5) {
                        return { up: upProb / 100, down: downProb / 100 };
                    }
                    
                    // Fallback: try to parse from first match
                    if (upMatch) {
                        const up = parseInt(upMatch[1]) / 100;
                        const down = 1.0 - up;
                        return { up: up, down: down };
                    }
                    
                    return null;
                }""")
                
                if not probs:
                    logger.warning("Could not extract probabilities from page")
                    await asyncio.sleep(POLL_INTERVAL)
                    continue
                
                up_prob = probs['up']
                down_prob = probs['down']
                
                # Log current state
                time_left = 300 - elapsed
                logger.info(f"[{time_left:.0f}s left] UP: {up_prob*100:.1f}% | DOWN: {down_prob*100:.1f}%")
                
                # Update status file for dashboard
                with open('bot_state.json', 'w') as f:
                    json.dump({
                        'status': 'monitoring',
                        'mode': 'probability',
                        'shares': SHARES,
                        'current_round': self.market_info['title'],
                        'market_slug': self.market_info['slug'],
                        'time_left': time_left,
                        'up_probability': up_prob,
                        'down_probability': down_prob,
                        'threshold': PROBABILITY_THRESHOLD,
                        'has_traded': self.has_traded_this_round,
                        'total_trades': len(self.trades)
                    }, f, indent=2)
                
                # Check if we should trade
                if not self.has_traded_this_round:
                    if up_prob >= PROBABILITY_THRESHOLD:
                        logger.info(f"🚨 THRESHOLD HIT! UP at {up_prob*100:.1f}% (threshold: {PROBABILITY_THRESHOLD*100}%)")
                        await self.execute_trade('UP', up_prob)
                        self.has_traded_this_round = True
                        logger.info("✅ Trade executed, marked as traded")
                    elif down_prob >= PROBABILITY_THRESHOLD:
                        logger.info(f"🚨 THRESHOLD HIT! DOWN at {down_prob*100:.1f}% (threshold: {PROBABILITY_THRESHOLD*100}%)")
                        await self.execute_trade('DOWN', down_prob)
                        self.has_traded_this_round = True
                        logger.info("✅ Trade executed, marked as traded")
                
                await asyncio.sleep(POLL_INTERVAL)
                
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                await asyncio.sleep(POLL_INTERVAL)
    
    async def execute_trade(self, side, probability):
        """Execute trade for given side"""
        logger.info("=" * 60)
        logger.info(f"🎯 TRADE SIGNAL: {side}")
        logger.info(f"Probability: {probability*100:.1f}%")
        logger.info(f"Position: {SHARES} shares")
        
        # Get current ask price from orderbook
        token_id = self.token_ids[side]
        logger.info(f"Fetching orderbook for {side} (token: {token_id[:20]}...)")
        
        try:
            async with self.session.get(f"{CLOB_BOOK_API}?token_id={token_id}") as resp:
                if resp.status == 200:
                    book = await resp.json()
                    asks = book.get('asks', [])
                    if asks:
                        best_ask = float(asks[0]['price'])
                        total_cost = best_ask * SHARES
                        expected_payout = 1.00 * SHARES * probability  # Expected value
                        
                        logger.info(f"Best ask: ${best_ask:.3f}")
                        logger.info(f"Total cost: ${total_cost:.2f}")
                        logger.info(f"Expected payout: ${expected_payout:.2f}")
                        logger.info(f"Expected profit: ${expected_payout - total_cost:.2f}")
                        logger.info("[PAPER TRADE] Executing...")
                        logger.info("=" * 60)
                        
                        trade_data = {
                            'timestamp': time.time(),
                            'side': side,
                            'probability': probability,
                            'price': best_ask,
                            'shares': SHARES,
                            'cost': total_cost,
                            'expected_profit': expected_payout - total_cost,
                            'status': 'pending'
                        }
                        self.trades.append(trade_data)
                        
                        # Save to trades log
                        import os
                        os.makedirs('logs', exist_ok=True)
                        with open('logs/trades.jsonl', 'a') as f:
                            f.write(json.dumps(trade_data) + '\n')
                        
                        return
        except Exception as e:
            logger.error(f"Error fetching orderbook: {e}")
            logger.warning("Continuing with trade execution anyway (paper mode)")
        
        # Always execute the trade (paper mode doesn't need orderbook)
        logger.info(f"[PAPER TRADE] BUY {SHARES} {side} shares at {probability*100:.1f}% confidence")
        logger.info("=" * 60)
        
        trade_data = {
            'timestamp': time.time(),
            'side': side,
            'probability': probability,
            'shares': SHARES,
            'status': 'executed',
            'expected_profit': (1.00 - 0.80) * SHARES  # Conservative estimate
        }
        self.trades.append(trade_data)
        
        # Save to trades log
        import os
        os.makedirs('logs', exist_ok=True)
        with open('logs/trades.jsonl', 'a') as f:
            f.write(json.dumps(trade_data) + '\n')
        
        logger.info(f"✅ Trade logged successfully (total trades: {len(self.trades)})")
    
    async def run(self):
        """Main loop"""
        logger.info("=" * 60)
        logger.info("POLYMARKET PROBABILITY BOT")
        logger.info("=" * 60)
        logger.info(f"Strategy: Buy when probability ≥ {PROBABILITY_THRESHOLD*100}%")
        logger.info(f"Trading window: After first 2 minutes of each round")
        logger.info(f"Position size: {SHARES} shares")
        logger.info("=" * 60)
        
        async with aiohttp.ClientSession() as session:
            self.session = session
            
            while True:
                success = await self.discover_and_monitor_market()
                if not success:
                    logger.error("Failed to monitor market, retrying in 30s...")
                    await asyncio.sleep(30)
                else:
                    # Small pause before next round
                    await asyncio.sleep(5)

async def main():
    bot = ProbabilityBot()
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())
