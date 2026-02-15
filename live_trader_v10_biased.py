"""
Polymarket BIASED MOMENTUM Bot v10
----------------------------------
Strategy: DOWN-biased based on historical performance

Key insight from v9 data:
- DOWN trades: 77% win rate
- UP trades: 29% win rate

v10 Strategy:
1. Default bias toward DOWN
2. Only bet UP if very high confidence (70%+)
3. Skip truly neutral rounds (45-55% confidence)
4. Larger positions on DOWN, smaller on UP
"""

import asyncio
import websockets
import aiohttp
import json
import os
import time
import logging
import math
from datetime import datetime
from playwright.async_api import async_playwright
from collections import deque

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
DOWN_SHARES = 15  # High confidence in DOWN
UP_SHARES = 5     # Lower confidence in UP
MIN_SHARES = 2
ENTRY_DELAY = 25  # Wait longer for better signal
ENTRY_WINDOW = 90

# Confidence thresholds
UP_THRESHOLD = 0.70    # Need 70%+ confidence to bet UP
DOWN_THRESHOLD = 0.45  # Only 45% needed for DOWN (bias)
SKIP_THRESHOLD = 0.55  # Skip if confidence between 45-55% for both

# Momentum settings
MOMENTUM_THRESHOLD = 25  # $25 move = signal
STRONG_MOMENTUM = 60     # $60+ = strong signal

# APIs
BINANCE_WS = "wss://stream.binance.com:9443/ws/btcusdt@trade"
CLOB_BOOK_API = "https://clob.polymarket.com/book"


class BiasedMomentumBot:
    def __init__(self):
        self.btc_price = None
        self.target_price = None
        self.round_start = None
        self.round_end = None
        self.token_ids = {}
        self.position = {
            'has_entered': False,
            'side': None,
            'shares': 0,
            'entry_price': 0
        }
        
        # Price history for momentum
        self.price_history = deque(maxlen=60)  # Last 60 prices
        self.price_times = deque(maxlen=60)
        
        # Stats
        self.stats = {
            'rounds_traded': 0,
            'wins': 0,
            'losses': 0,
            'total_profit': 0,
            'current_streak': 0,
            'skipped': 0  # Track skipped rounds
        }
        
        self.load_stats()
    
    def load_stats(self):
        """Load stats from trades file"""
        trades_file = "logs/trades.jsonl"
        if os.path.exists(trades_file):
            wins = losses = profit = 0
            with open(trades_file, 'r') as f:
                for line in f:
                    if line.strip():
                        try:
                            t = json.loads(line)
                            if t.get('action') == 'CLOSE':
                                if t.get('won'):
                                    wins += 1
                                else:
                                    losses += 1
                                profit += t.get('profit', 0)
                        except:
                            pass
            self.stats['wins'] = wins
            self.stats['losses'] = losses
            self.stats['rounds_traded'] = wins + losses
            self.stats['total_profit'] = profit
    
    def save_position_state(self):
        """Save current position state for dashboard"""
        try:
            live_pnl = 0
            winning = False
            
            if self.position['has_entered'] and self.btc_price and self.target_price:
                price_diff = self.btc_price - self.target_price
                
                if self.position['side'] == 'UP':
                    winning = price_diff > 0
                else:
                    winning = price_diff < 0
                
                if winning:
                    live_pnl = self.position['shares'] - (self.position['shares'] * self.position['entry_price'])
                else:
                    live_pnl = -(self.position['shares'] * self.position['entry_price'])
            
            # Calculate probability based on price difference
            if self.btc_price and self.target_price:
                diff = self.btc_price - self.target_price
                # Simple probability estimation
                up_probability = 50 + (diff / 10)  # $10 diff = 1% change
                up_probability = max(1, min(99, up_probability))
            else:
                up_probability = 50
            
            time_remaining = 0
            if self.round_end:
                time_remaining = max(0, self.round_end - time.time())
            
            state = {
                'has_position': self.position['has_entered'],
                'side': self.position['side'],
                'shares': self.position['shares'],
                'entry_price': self.position['entry_price'],
                'cost': self.position['shares'] * self.position['entry_price'],
                'target_price': self.target_price,
                'btc_price': self.btc_price,
                'winning': winning,
                'live_pnl': live_pnl,
                'up_probability': up_probability,
                'down_probability': 100 - up_probability,
                'potential_payout': self.position['shares'],
                'time_remaining': time_remaining,
                'round_start': self.round_start,
                'stats': self.stats,
                'updated': time.time()
            }
            
            with open('position_state.json', 'w') as f:
                json.dump(state, f, indent=2)
            
            # Save probability history
            self.save_probability_history(up_probability)
            
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
    
    def save_probability_history(self, up_prob):
        """Save probability to history file for chart"""
        history_file = "logs/probability_history.json"
        try:
            history = []
            if os.path.exists(history_file):
                with open(history_file, 'r') as f:
                    history = json.load(f)
            
            history.append({
                'timestamp': time.time(),
                'up_probability': up_prob
            })
            
            # Keep last 100 entries
            history = history[-100:]
            
            with open(history_file, 'w') as f:
                json.dump(history, f)
        except:
            pass
    
    def calculate_momentum(self):
        """Calculate momentum with DOWN bias"""
        if len(self.price_history) < 10:
            # Not enough data - default to DOWN (our edge)
            return {
                'direction': 'DOWN',
                'confidence': 0.50,
                'reason': 'insufficient_data_default_down'
            }
        
        prices = list(self.price_history)
        times = list(self.price_times)
        
        # Current vs target
        if self.btc_price and self.target_price:
            diff_from_target = self.btc_price - self.target_price
        else:
            diff_from_target = 0
        
        # Price change over different windows
        change_5s = prices[-1] - prices[-min(5, len(prices))] if len(prices) >= 5 else 0
        change_15s = prices[-1] - prices[-min(15, len(prices))] if len(prices) >= 15 else 0
        change_30s = prices[-1] - prices[-min(30, len(prices))] if len(prices) >= 30 else 0
        
        # Acceleration (is momentum increasing?)
        if len(prices) >= 10:
            recent_change = prices[-1] - prices[-5]
            older_change = prices[-5] - prices[-10]
            acceleration = recent_change - older_change
        else:
            acceleration = 0
        
        # Count signals
        up_signals = 0
        down_signals = 0
        
        # Signal 1: Price vs target
        if diff_from_target > MOMENTUM_THRESHOLD:
            up_signals += 1
        elif diff_from_target < -MOMENTUM_THRESHOLD:
            down_signals += 1
        
        # Signal 2: Recent momentum (5s)
        if change_5s > 10:
            up_signals += 1
        elif change_5s < -10:
            down_signals += 1
        
        # Signal 3: Medium momentum (15s)
        if change_15s > 20:
            up_signals += 1
        elif change_15s < -20:
            down_signals += 1
        
        # Signal 4: Longer trend (30s)
        if change_30s > 30:
            up_signals += 1
        elif change_30s < -30:
            down_signals += 1
        
        # Signal 5: Acceleration
        if acceleration > 5:
            up_signals += 1
        elif acceleration < -5:
            down_signals += 1
        
        total_signals = up_signals + down_signals
        
        # Calculate base confidence
        if total_signals == 0:
            # No clear signal - DEFAULT TO DOWN (our edge!)
            direction = 'DOWN'
            confidence = 0.50
            reason = 'no_signal_default_down'
        elif up_signals > down_signals:
            direction = 'UP'
            confidence = up_signals / max(total_signals, 1)
            reason = f'{up_signals}up_{down_signals}down'
        else:
            direction = 'DOWN'
            confidence = down_signals / max(total_signals, 1)
            reason = f'{up_signals}up_{down_signals}down'
        
        # Apply DOWN bias adjustment
        # If it's close, favor DOWN
        if direction == 'UP' and confidence < UP_THRESHOLD:
            # Not confident enough for UP - switch to DOWN
            direction = 'DOWN'
            confidence = 0.55  # Mild confidence
            reason = 'up_confidence_too_low_switch_down'
        
        return {
            'direction': direction,
            'confidence': confidence,
            'up_signals': up_signals,
            'down_signals': down_signals,
            'diff_from_target': diff_from_target,
            'change_5s': change_5s,
            'change_15s': change_15s,
            'acceleration': acceleration,
            'reason': reason
        }
    
    def should_skip_round(self, momentum):
        """Determine if we should skip this round"""
        # If truly 50/50 with no signals, consider skipping
        if momentum['up_signals'] == momentum['down_signals'] == 0:
            return False  # No signals but we default to DOWN
        
        if momentum['up_signals'] == momentum['down_signals']:
            # Equal signals - skip if within skip threshold
            confidence = momentum['confidence']
            if 0.45 <= confidence <= 0.55:
                return True  # Too close to call
        
        return False
    
    def calculate_position_size(self, momentum):
        """Calculate position size based on direction and confidence"""
        direction = momentum['direction']
        confidence = momentum['confidence']
        
        if direction == 'DOWN':
            # We're confident in DOWN - size up
            if confidence >= 0.70:
                return DOWN_SHARES  # Max size
            elif confidence >= 0.55:
                return 10
            else:
                return 5
        else:
            # UP is risky - size down
            if confidence >= 0.80:
                return UP_SHARES  # Still conservative
            else:
                return MIN_SHARES  # Minimum
    
    async def discover_market(self):
        """Discover current active BTC 5-min market"""
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                await page.goto("https://polymarket.com/markets?_c=btc-updown-5m", timeout=30000)
                await page.wait_for_selector('[data-testid="market-card"]', timeout=15000)
                
                # Find active market
                cards = await page.query_selector_all('[data-testid="market-card"]')
                
                for card in cards:
                    try:
                        text = await card.inner_text()
                        if "Bitcoin Up or Down" in text and "5-min" not in text.lower():
                            continue
                        
                        if "Bitcoin Up or Down" in text:
                            # Get market link
                            link = await card.query_selector('a')
                            if link:
                                href = await link.get_attribute('href')
                                market_url = f"https://polymarket.com{href}"
                                
                                # Navigate to market page
                                await page.goto(market_url, timeout=30000)
                                await asyncio.sleep(2)
                                
                                # Get title
                                title_el = await page.query_selector('h1')
                                title = await title_el.inner_text() if title_el else "Unknown"
                                
                                # Parse target price from title
                                if "$" in title:
                                    import re
                                    match = re.search(r'\$([0-9,]+)', title)
                                    if match:
                                        self.target_price = float(match.group(1).replace(',', ''))
                                
                                # Get token IDs from page
                                content = await page.content()
                                
                                # Find UP token
                                up_match = None
                                down_match = None
                                
                                import re
                                token_matches = re.findall(r'"tokenId":"(\d+)"', content)
                                
                                if len(token_matches) >= 2:
                                    self.token_ids = {
                                        'Up': token_matches[0],
                                        'Down': token_matches[1]
                                    }
                                
                                # Set round timing (5 min = 300 seconds)
                                self.round_start = time.time()
                                self.round_end = self.round_start + 300
                                
                                # Reset position
                                self.position = {
                                    'has_entered': False,
                                    'side': None,
                                    'shares': 0,
                                    'entry_price': 0
                                }
                                
                                # Save market info
                                with open('current_market.json', 'w') as f:
                                    json.dump({
                                        'title': title,
                                        'target_price': self.target_price,
                                        'token_ids': self.token_ids,
                                        'round_start': self.round_start,
                                        'round_end': self.round_end
                                    }, f, indent=2)
                                
                                logger.info(f"Market: {title}")
                                logger.info(f"Target: ${self.target_price:,.2f}")
                                logger.info("=" * 60)
                                
                                await browser.close()
                                
                                # Clear price history for new round
                                self.price_history.clear()
                                self.price_times.clear()
                                
                                self.save_position_state()
                                return True
                    except Exception as e:
                        continue
                
                await browser.close()
                return False
                
        except Exception as e:
            logger.error(f"Discovery error: {e}")
            return False
    
    async def fetch_order_book(self, token_id):
        """Fetch order book from CLOB API"""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{CLOB_BOOK_API}?token_id={token_id}"
                async with session.get(url, timeout=5) as resp:
                    if resp.status == 200:
                        return await resp.json()
        except Exception as e:
            logger.error(f"Orderbook fetch error: {e}")
        return None
    
    def get_best_prices(self, book):
        """Get best bid and ask from orderbook"""
        try:
            bids = book.get('bids', [])
            asks = book.get('asks', [])
            
            best_bid = float(bids[0]['price']) if bids else None
            best_ask = float(asks[0]['price']) if asks else None
            
            return best_bid, best_ask
        except:
            return None, None
    
    async def enter_position(self, direction, shares, entry_price):
        """Enter a position"""
        self.position = {
            'has_entered': True,
            'side': direction,
            'shares': shares,
            'entry_price': entry_price
        }
        
        cost = shares * entry_price
        
        logger.info("=" * 60)
        logger.info(f"🎯 ENTERING {direction} POSITION")
        logger.info(f"Direction: {direction}")
        logger.info(f"Shares: {shares}")
        logger.info(f"Entry: ${entry_price:.3f}")
        logger.info(f"Cost: ${cost:.2f}")
        logger.info(f"Potential payout: ${shares:.2f}")
        logger.info("[PAPER TRADE] Position opened")
        logger.info("=" * 60)
        
        # Log trade
        trade = {
            'timestamp': time.time(),
            'action': 'ENTER',
            'side': direction,
            'shares': shares,
            'entry_price': entry_price,
            'cost': cost,
            'target_price': self.target_price,
            'btc_at_entry': self.btc_price,
            'status': 'open'
        }
        
        os.makedirs('logs', exist_ok=True)
        with open('logs/trades.jsonl', 'a') as f:
            f.write(json.dumps(trade) + '\n')
        
        self.save_position_state()
    
    async def close_position(self, won):
        """Close position at round end"""
        payout = self.position['shares'] if won else 0
        cost = self.position['shares'] * self.position['entry_price']
        profit = payout - cost
        
        self.stats['rounds_traded'] += 1
        if won:
            self.stats['wins'] += 1
            self.stats['current_streak'] = max(1, self.stats['current_streak'] + 1)
        else:
            self.stats['losses'] += 1
            self.stats['current_streak'] = min(-1, self.stats['current_streak'] - 1)
        self.stats['total_profit'] += profit
        
        logger.info("=" * 60)
        logger.info(f"📊 ROUND COMPLETE: {'WIN ✅' if won else 'LOSS ❌'}")
        logger.info(f"Position: {self.position['shares']} {self.position['side']}")
        logger.info(f"Cost: ${cost:.2f}")
        logger.info(f"Payout: ${payout:.2f}")
        logger.info(f"Profit: ${profit:+.2f}")
        logger.info("=" * 60)
        
        win_rate = self.stats['wins'] / self.stats['rounds_traded'] * 100 if self.stats['rounds_traded'] > 0 else 0
        logger.info(f"📈 STATS: {self.stats['wins']}W / {self.stats['losses']}L ({win_rate:.1f}%) | "
                   f"Total P&L: ${self.stats['total_profit']:+.2f} | "
                   f"Streak: {self.stats['current_streak']:+d}")
        
        # Log trade
        trade = {
            'timestamp': time.time(),
            'action': 'CLOSE',
            'side': self.position['side'],
            'shares': self.position['shares'],
            'entry_price': self.position['entry_price'],
            'won': won,
            'payout': payout,
            'profit': profit,
            'status': 'completed'
        }
        
        with open('logs/trades.jsonl', 'a') as f:
            f.write(json.dumps(trade) + '\n')
        
        # Reset position
        self.position = {
            'has_entered': False,
            'side': None,
            'shares': 0,
            'entry_price': 0
        }
        
        self.save_position_state()
    
    async def connect_binance(self):
        """Connect to Binance WebSocket for BTC price"""
        logger.info("Connecting to Binance...")
        
        async for websocket in websockets.connect(BINANCE_WS):
            try:
                logger.info("✓ Binance connected")
                async for message in websocket:
                    data = json.loads(message)
                    self.btc_price = float(data['p'])
                    self.price_history.append(self.btc_price)
                    self.price_times.append(time.time())
            except websockets.ConnectionClosed:
                logger.warning("Binance disconnected, reconnecting...")
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Binance error: {e}")
                await asyncio.sleep(1)
    
    async def monitor(self):
        """Main monitoring loop"""
        logger.info("=" * 60)
        logger.info("BIASED MOMENTUM BOT v10")
        logger.info("=" * 60)
        logger.info("Strategy: DOWN-biased based on historical performance")
        logger.info("  - DOWN win rate: 77% (historical)")
        logger.info("  - UP win rate: 29% (historical)")
        logger.info("  - Default to DOWN when uncertain")
        logger.info("  - Only bet UP with 70%+ confidence")
        logger.info(f"Position sizes: DOWN={DOWN_SHARES}, UP={UP_SHARES}")
        logger.info("=" * 60)
        
        # Initial market discovery
        if not await self.discover_market():
            logger.error("Failed to discover market")
            return
        
        while True:
            try:
                if not self.round_end:
                    await asyncio.sleep(1)
                    continue
                
                elapsed = time.time() - self.round_start
                time_left = self.round_end - time.time()
                
                # Round ended
                if time_left <= 0:
                    if self.position['has_entered']:
                        # Determine winner
                        btc_final = self.btc_price or 0
                        won = False
                        
                        if self.position['side'] == 'UP' and btc_final > self.target_price:
                            won = True
                        elif self.position['side'] == 'DOWN' and btc_final < self.target_price:
                            won = True
                        
                        await self.close_position(won)
                    
                    logger.info("Round complete, discovering next...")
                    if await self.discover_market():
                        continue
                    else:
                        await asyncio.sleep(30)
                        continue
                
                if not self.token_ids:
                    await asyncio.sleep(1)
                    continue
                
                # Calculate momentum
                momentum = self.calculate_momentum()
                
                # ENTRY PHASE
                if not self.position['has_entered']:
                    if elapsed < ENTRY_DELAY:
                        if int(time.time()) % 5 == 0:
                            logger.info(f"[{time_left:.0f}s] Gathering momentum... (entry in {ENTRY_DELAY - elapsed:.0f}s)")
                    
                    elif elapsed < ENTRY_WINDOW:
                        # Check if we should skip
                        if self.should_skip_round(momentum):
                            logger.info(f"⏭️ SKIPPING ROUND - signals too balanced")
                            logger.info(f"   UP signals: {momentum['up_signals']}, DOWN signals: {momentum['down_signals']}")
                            self.stats['skipped'] += 1
                            # Wait for round to end
                            self.position['has_entered'] = True  # Prevent re-entry
                            self.position['side'] = 'SKIPPED'
                            self.position['shares'] = 0
                        else:
                            # Enter position
                            direction = momentum['direction']
                            confidence = momentum['confidence']
                            shares = self.calculate_position_size(momentum)
                            
                            # Get entry price
                            token_id = self.token_ids.get(direction.capitalize())
                            if token_id:
                                book = await self.fetch_order_book(token_id)
                                if book:
                                    bid, ask = self.get_best_prices(book)
                                    entry_price = ask if ask else 0.50
                                else:
                                    entry_price = 0.50
                            else:
                                entry_price = 0.50
                            
                            logger.info(f"Momentum: {direction} | Confidence: {confidence:.1%} | "
                                       f"Reason: {momentum['reason']}")
                            logger.info(f"Signals: {momentum['up_signals']}↑ {momentum['down_signals']}↓ | "
                                       f"Diff from target: ${momentum['diff_from_target']:+.2f}")
                            
                            await self.enter_position(direction, shares, entry_price)
                
                # HOLDING PHASE
                elif self.position['side'] != 'SKIPPED':
                    self.save_position_state()
                    
                    if int(time.time()) % 15 == 0:
                        price_diff = self.btc_price - self.target_price if self.btc_price and self.target_price else 0
                        winning = (self.position['side'] == 'UP' and price_diff > 0) or \
                                  (self.position['side'] == 'DOWN' and price_diff < 0)
                        status = "WINNING 📈" if winning else "LOSING 📉"
                        
                        logger.info(f"[{time_left:.0f}s] Holding {self.position['shares']} {self.position['side']} | "
                                   f"BTC: ${self.btc_price:,.2f} ({price_diff:+.2f}) | {status}")
                
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"Monitor error: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(2)
    
    async def run(self):
        """Run the bot"""
        await asyncio.gather(
            self.connect_binance(),
            self.monitor()
        )


async def main():
    bot = BiasedMomentumBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
