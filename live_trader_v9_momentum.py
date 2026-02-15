"""
Polymarket MOMENTUM DIRECTIONAL Bot v9
--------------------------------------
Strategy: Pick ONE side based on BTC momentum, trade EVERY round

Key Changes from v8:
- NO HEDGING - pick a direction
- Trade every 5 minutes regardless of spreads
- Multi-signal momentum detection
- Dynamic position sizing based on confidence
- Limit order logic for better entries

Signals:
1. Price Change: BTC vs target price
2. Momentum: Rate of price change
3. Acceleration: Is momentum increasing?
4. Trend: Short-term direction

Win Condition: Be right >50% with good entries
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
BASE_SHARES = 10
MIN_SHARES = 2
MAX_SHARES = 15
ENTRY_DELAY = 20  # Wait 20s into round before entering
ENTRY_WINDOW = 90  # Must enter within first 90 seconds
MOMENTUM_THRESHOLD = 30  # $30 move = clear direction
STRONG_MOMENTUM = 75  # $75+ move = high confidence

# APIs
BINANCE_WS = "wss://stream.binance.com:9443/ws/btcusdt@trade"
CLOB_BOOK_API = "https://clob.polymarket.com/book"


class MomentumBot:
    def __init__(self):
        self.btc_price = None
        self.target_price = None
        self.token_ids = None
        self.market_info = None
        self.session = None
        self.round_start_time = 0
        
        # Price history for momentum calculation
        self.price_history = deque(maxlen=60)  # Last 60 price points
        self.price_timestamps = deque(maxlen=60)
        
        # Trade tracking
        self.position = {
            'side': None,  # 'UP' or 'DOWN'
            'shares': 0,
            'entry_price': 0,
            'has_entered': False
        }
        
        # Stats
        self.stats = {
            'rounds_traded': 0,
            'wins': 0,
            'losses': 0,
            'total_profit': 0,
            'current_streak': 0
        }
        self.load_stats()  # Load historical stats
    
    def load_stats(self):
        """Load stats from historical trades"""
        trades_file = "logs/trades.jsonl"
        if os.path.exists(trades_file):
            wins = losses = profit = 0
            last_results = []
            with open(trades_file, 'r') as f:
                for line in f:
                    if line.strip():
                        try:
                            t = json.loads(line)
                            if t.get('action') == 'CLOSE':
                                if t.get('won'):
                                    wins += 1
                                    last_results.append(True)
                                else:
                                    losses += 1
                                    last_results.append(False)
                                profit += t.get('profit', 0)
                        except:
                            pass
            
            # Calculate current streak
            streak = 0
            for won in reversed(last_results):
                if won:
                    if streak >= 0:
                        streak += 1
                    else:
                        break
                else:
                    if streak <= 0:
                        streak -= 1
                    else:
                        break
            
            self.stats['wins'] = wins
            self.stats['losses'] = losses
            self.stats['rounds_traded'] = wins + losses
            self.stats['total_profit'] = profit
            self.stats['current_streak'] = streak
            
            logger.info(f"Loaded historical stats: {wins}W/{losses}L, P&L: ${profit:.2f}")
    
    def save_position_state(self):
        """Save current position state for dashboard"""
        try:
            # Calculate live P&L and probability
            live_pnl = 0
            winning = False
            up_probability = 50
            
            if self.btc_price and self.target_price:
                # Calculate probability based on BTC vs target
                diff = self.btc_price - self.target_price
                # Use sigmoid-like function: bigger diff = higher certainty
                z = diff / 100  # Scale factor
                up_probability = min(99, max(1, 50 + (z * 10)))
            
            if self.position['has_entered'] and self.btc_price and self.target_price:
                cost = self.position['shares'] * self.position['entry_price']
                
                # Check if currently winning
                if self.position['side'] == 'UP':
                    winning = self.btc_price > self.target_price
                else:
                    winning = self.btc_price < self.target_price
                
                # Calculate unrealized P&L
                if winning:
                    live_pnl = self.position['shares'] - cost
                else:
                    live_pnl = -cost
            
            state = {
                'has_position': self.position['has_entered'],
                'side': self.position['side'],
                'shares': self.position['shares'],
                'entry_price': self.position['entry_price'],
                'cost': self.position['shares'] * self.position['entry_price'] if self.position['has_entered'] else 0,
                'target_price': self.target_price,
                'btc_price': self.btc_price,
                'winning': winning,
                'live_pnl': live_pnl,
                'up_probability': up_probability,
                'down_probability': 100 - up_probability,
                'potential_payout': self.position['shares'] if self.position['has_entered'] else 0,
                'time_remaining': max(0, 300 - (time.time() - self.round_start_time)),
                'round_start': self.round_start_time,
                'stats': self.stats,
                'updated': time.time()
            }
            
            with open('position_state.json', 'w') as f:
                json.dump(state, f, indent=2)
            
            # Also save to probability history for chart
            self.save_probability_history(up_probability)
            
        except Exception as e:
            pass  # Don't crash on state save errors
    
    def save_probability_history(self, up_prob):
        """Save probability history for live chart"""
        try:
            history_file = 'probability_history.json'
            history = []
            
            # Load existing history
            if os.path.exists(history_file):
                with open(history_file, 'r') as f:
                    history = json.load(f)
            
            # Add new data point
            now = time.time()
            history.append({
                'timestamp': now,
                'up_probability': up_prob,
                'btc_price': self.btc_price,
                'target_price': self.target_price
            })
            
            # Keep only last 5 minutes (300 seconds) of data
            cutoff = now - 300
            history = [h for h in history if h['timestamp'] > cutoff]
            
            # Save
            with open(history_file, 'w') as f:
                json.dump(history, f)
                
        except Exception as e:
            pass
        
    async def connect_binance(self):
        """Connect to Binance WebSocket for real-time BTC price"""
        logger.info("Connecting to Binance...")
        
        try:
            async with websockets.connect(BINANCE_WS) as ws:
                logger.info("✓ Binance connected")
                
                async for message in ws:
                    data = json.loads(message)
                    price = float(data['p'])
                    self.btc_price = price
                    
                    # Store price history
                    now = time.time()
                    self.price_history.append(price)
                    self.price_timestamps.append(now)
                        
        except Exception as e:
            logger.error(f"Binance error: {e}")
            await asyncio.sleep(5)
            await self.connect_binance()
    
    def calculate_momentum(self):
        """Calculate momentum signals from price history"""
        if len(self.price_history) < 10:
            return {
                'direction': None,
                'strength': 0,
                'confidence': 0,
                'signals': []
            }
        
        signals = []
        
        # Signal 1: Price vs Target
        if self.btc_price and self.target_price:
            price_diff = self.btc_price - self.target_price
            if price_diff > MOMENTUM_THRESHOLD:
                signals.append(('PRICE', 'UP', abs(price_diff)))
            elif price_diff < -MOMENTUM_THRESHOLD:
                signals.append(('PRICE', 'DOWN', abs(price_diff)))
        
        # Signal 2: Short-term momentum (last 10 seconds)
        if len(self.price_history) >= 5:
            recent_prices = list(self.price_history)[-10:]
            short_momentum = recent_prices[-1] - recent_prices[0]
            if short_momentum > 20:
                signals.append(('SHORT_MOM', 'UP', abs(short_momentum)))
            elif short_momentum < -20:
                signals.append(('SHORT_MOM', 'DOWN', abs(short_momentum)))
        
        # Signal 3: Medium-term momentum (last 30 seconds)
        if len(self.price_history) >= 15:
            older_prices = list(self.price_history)[-30:]
            med_momentum = older_prices[-1] - older_prices[0]
            if med_momentum > 40:
                signals.append(('MED_MOM', 'UP', abs(med_momentum)))
            elif med_momentum < -40:
                signals.append(('MED_MOM', 'DOWN', abs(med_momentum)))
        
        # Signal 4: Acceleration (is momentum increasing?)
        if len(self.price_history) >= 20:
            prices = list(self.price_history)
            first_half = prices[-20:-10]
            second_half = prices[-10:]
            
            first_change = first_half[-1] - first_half[0] if len(first_half) > 1 else 0
            second_change = second_half[-1] - second_half[0] if len(second_half) > 1 else 0
            
            if second_change > first_change + 10:
                # Accelerating up
                if second_change > 0:
                    signals.append(('ACCEL', 'UP', second_change - first_change))
            elif second_change < first_change - 10:
                # Accelerating down
                if second_change < 0:
                    signals.append(('ACCEL', 'DOWN', abs(second_change - first_change)))
        
        # Count direction votes
        up_votes = sum(1 for s in signals if s[1] == 'UP')
        down_votes = sum(1 for s in signals if s[1] == 'DOWN')
        up_strength = sum(s[2] for s in signals if s[1] == 'UP')
        down_strength = sum(s[2] for s in signals if s[1] == 'DOWN')
        
        # Determine direction and confidence
        if up_votes > down_votes:
            direction = 'UP'
            confidence = up_votes / max(len(signals), 1)
            strength = up_strength
        elif down_votes > up_votes:
            direction = 'DOWN'
            confidence = down_votes / max(len(signals), 1)
            strength = down_strength
        else:
            # Tie - use price vs target as tiebreaker
            if self.btc_price and self.target_price:
                direction = 'UP' if self.btc_price > self.target_price else 'DOWN'
            else:
                direction = 'UP'  # Default
            confidence = 0.5
            strength = max(up_strength, down_strength)
        
        return {
            'direction': direction,
            'strength': strength,
            'confidence': confidence,
            'signals': signals,
            'up_votes': up_votes,
            'down_votes': down_votes
        }
    
    def calculate_position_size(self, momentum):
        """Dynamic position sizing based on confidence"""
        confidence = momentum['confidence']
        strength = momentum['strength']
        
        if confidence >= 0.75 and strength >= STRONG_MOMENTUM:
            return MAX_SHARES  # High confidence
        elif confidence >= 0.5 and strength >= MOMENTUM_THRESHOLD:
            return BASE_SHARES  # Medium confidence
        else:
            return MIN_SHARES  # Low confidence, but still trade
    
    async def discover_market(self):
        """Discover the current 5-minute market"""
        logger.info("=" * 60)
        logger.info("DISCOVERING NEXT MARKET...")
        logger.info("=" * 60)
        
        now = int(time.time())
        slot = (now // 300) * 300
        time_in_slot = now - slot
        
        # Wait for round to start
        if time_in_slot < 5:
            wait_time = 5 - time_in_slot
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
                    logger.error("Failed to extract market data")
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
                
                # Set target price from current BTC (this is what market uses)
                self.target_price = self.btc_price if self.btc_price else 70000
                
                # Reset position for new round
                self.position = {
                    'side': None,
                    'shares': 0,
                    'entry_price': 0,
                    'has_entered': False
                }
                
                logger.info(f"Market: {self.market_info['title']}")
                logger.info(f"Target: ${self.target_price:,.2f}")
                logger.info("=" * 60)
                
                # Save for dashboard
                with open('current_market.json', 'w') as f:
                    json.dump({
                        **self.market_info,
                        'target_price': self.target_price,
                        'round_start': self.round_start_time
                    }, f, indent=2)
                
                # Clear position state for new round
                self.save_position_state()
                
                return True
                
        except Exception as e:
            logger.error(f"Discovery error: {e}")
            return False
    
    async def fetch_order_book(self, token_id):
        """Fetch orderbook from Polymarket CLOB"""
        try:
            async with self.session.get(f"{CLOB_BOOK_API}?token_id={token_id}") as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            pass
        return None
    
    def get_best_prices(self, book):
        """Extract best bid/ask from orderbook"""
        if not book:
            return None, None
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        best_bid = float(bids[0]["price"]) if bids else None
        best_ask = float(asks[0]["price"]) if asks else None
        return best_bid, best_ask
    
    def get_fair_entry_price(self, book, side_ask):
        """Calculate fair entry price (try to beat the ask)"""
        if not book:
            return side_ask
        
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        
        if not asks:
            return side_ask
        
        best_ask = float(asks[0]["price"])
        
        # If ask is reasonable (<60¢), take it
        if best_ask <= 0.60:
            return best_ask
        
        # If ask is expensive, try to get better price
        # Place limit order at midpoint between bid and ask
        if bids:
            best_bid = float(bids[0]["price"])
            midpoint = (best_bid + best_ask) / 2
            # Don't pay more than 70¢
            return min(midpoint, 0.70)
        
        # No bids, just use ask but cap at 70¢
        return min(best_ask, 0.70)
    
    async def enter_position(self, side, shares, entry_price):
        """Enter a directional position"""
        cost = shares * entry_price
        
        logger.info("=" * 60)
        logger.info(f"🎯 ENTERING {side} POSITION")
        logger.info(f"Direction: {side}")
        logger.info(f"Shares: {shares}")
        logger.info(f"Entry: ${entry_price:.3f}")
        logger.info(f"Cost: ${cost:.2f}")
        logger.info(f"Potential payout: ${shares:.2f}")
        logger.info("[PAPER TRADE] Position opened")
        logger.info("=" * 60)
        
        self.position['side'] = side
        self.position['shares'] = shares
        self.position['entry_price'] = entry_price
        self.position['has_entered'] = True
        
        # Log trade
        trade_data = {
            'timestamp': time.time(),
            'action': 'ENTER',
            'side': side,
            'shares': shares,
            'entry_price': entry_price,
            'cost': cost,
            'target_price': self.target_price,
            'btc_at_entry': self.btc_price,
            'status': 'open'
        }
        
        import os
        os.makedirs('logs', exist_ok=True)
        with open('logs/trades.jsonl', 'a') as f:
            f.write(json.dumps(trade_data) + '\n')
        
        # Save position state for dashboard
        self.save_position_state()
    
    async def close_position(self, won):
        """Close position at round end"""
        payout = self.position['shares'] if won else 0
        cost = self.position['shares'] * self.position['entry_price']
        profit = payout - cost
        
        result = "WIN ✅" if won else "LOSS ❌"
        
        logger.info("=" * 60)
        logger.info(f"📊 ROUND COMPLETE: {result}")
        logger.info(f"Position: {self.position['shares']} {self.position['side']}")
        logger.info(f"Cost: ${cost:.2f}")
        logger.info(f"Payout: ${payout:.2f}")
        logger.info(f"Profit: ${profit:+.2f}")
        logger.info("=" * 60)
        
        # Update stats
        self.stats['rounds_traded'] += 1
        self.stats['total_profit'] += profit
        
        if won:
            self.stats['wins'] += 1
            self.stats['current_streak'] = max(0, self.stats['current_streak']) + 1
        else:
            self.stats['losses'] += 1
            self.stats['current_streak'] = min(0, self.stats['current_streak']) - 1
        
        win_rate = self.stats['wins'] / max(self.stats['rounds_traded'], 1) * 100
        
        logger.info(f"📈 STATS: {self.stats['wins']}W / {self.stats['losses']}L ({win_rate:.1f}%) | "
                   f"Total P&L: ${self.stats['total_profit']:+.2f} | Streak: {self.stats['current_streak']}")
        
        # Log trade result
        trade_data = {
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
            f.write(json.dumps(trade_data) + '\n')
    
    async def monitor(self):
        """Main trading loop"""
        while True:
            try:
                elapsed = time.time() - self.round_start_time
                time_left = 300 - elapsed
                
                # Round complete - check result and move to next
                if elapsed > 300:
                    if self.position['has_entered']:
                        # Determine if we won
                        btc_final = self.btc_price
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
                
                # ENTRY PHASE: Wait for entry delay, then enter
                if not self.position['has_entered']:
                    if elapsed < ENTRY_DELAY:
                        # Waiting for momentum to develop
                        if int(time.time()) % 5 == 0:
                            logger.info(f"[{time_left:.0f}s] Gathering momentum data... "
                                       f"(entry in {ENTRY_DELAY - elapsed:.0f}s)")
                    
                    elif elapsed < ENTRY_WINDOW:
                        # Time to enter!
                        direction = momentum['direction']
                        confidence = momentum['confidence']
                        
                        # DOWN BIAS: If confidence < 55%, default to DOWN
                        # Based on data: DOWN wins 77%, UP wins 29%
                        if confidence < 0.55:
                            direction = 'DOWN'
                            logger.info(f"Low confidence ({confidence:.0%}) - defaulting to DOWN (77% win rate)")
                        
                        # Fetch orderbook for our chosen side
                        token_id = self.token_ids[direction.capitalize()]
                        book = await self.fetch_order_book(token_id)
                        
                        if book:
                            bid, ask = self.get_best_prices(book)
                            
                            if ask:
                                entry_price = self.get_fair_entry_price(book, ask)
                                shares = self.calculate_position_size(momentum)
                                
                                logger.info(f"Momentum: {direction} | Confidence: {confidence:.1%} | "
                                           f"Signals: {momentum['up_votes']}↑ {momentum['down_votes']}↓")
                                
                                await self.enter_position(direction, shares, entry_price)
                            else:
                                logger.warning(f"[{time_left:.0f}s] No ask price available")
                        else:
                            logger.warning(f"[{time_left:.0f}s] Failed to fetch orderbook")
                    
                    else:
                        # Missed entry window - force entry with DOWN (our edge)
                        logger.warning("Entry window closing - forcing DOWN entry")
                        direction = 'DOWN'  # DOWN has 77% win rate
                        await self.enter_position(direction, MIN_SHARES, 0.50)
                
                # HOLDING PHASE: Monitor position
                else:
                    # Save position state for live dashboard updates
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
        """Start the bot"""
        logger.info("=" * 60)
        logger.info("MOMENTUM DIRECTIONAL BOT v9")
        logger.info("=" * 60)
        logger.info("Strategy:")
        logger.info("  1. Wait 20s for momentum to develop")
        logger.info("  2. Analyze BTC movement signals")
        logger.info("  3. Pick direction (UP or DOWN)")
        logger.info("  4. Enter position with dynamic sizing")
        logger.info("  5. Hold until round end")
        logger.info("  6. Trade EVERY round, 24/7")
        logger.info(f"Base position: {BASE_SHARES} shares")
        logger.info(f"Momentum threshold: ${MOMENTUM_THRESHOLD}")
        logger.info("=" * 60)
        
        # Discover first market
        if not await self.discover_market():
            logger.error("Failed to discover market!")
            return
        
        async with aiohttp.ClientSession() as session:
            self.session = session
            
            # Run both tasks
            await asyncio.gather(
                self.connect_binance(),
                self.monitor()
            )


async def main():
    bot = MomentumBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
