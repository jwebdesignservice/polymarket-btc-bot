"""
Polymarket FAST MOMENTUM Bot v10
--------------------------------
Strategy: Same as v9.5 but with SPEED OPTIMIZATIONS

Changes from v9.5:
- NO PLAYWRIGHT - Direct API calls (~4 seconds faster)
- Pre-cached connections
- Optimized market discovery
- Same trading logic, just faster execution

Target: <500ms total latency vs 4-5s before
"""

import asyncio
import aiohttp
import json
import os
import sys
import time
import logging
import math
from datetime import datetime
from collections import deque
from generate_report import generate_report

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================
# SINGLE INSTANCE LOCK - Prevent duplicate bot instances
# ============================================================
LOCK_FILE = "logs/bot.lock"

def acquire_lock():
    """Acquire single-instance lock. Exit if another instance is running."""
    os.makedirs("logs", exist_ok=True)
    try:
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE, 'r') as f:
                old_pid = f.read().strip()
            try:
                old_pid = int(old_pid)
                os.kill(old_pid, 0)
                logger.error(f"Another bot instance is already running (PID: {old_pid}). Exiting.")
                sys.exit(1)
            except (ProcessLookupError, ValueError, OSError):
                pass
        
        with open(LOCK_FILE, 'w') as f:
            f.write(str(os.getpid()))
        logger.info(f"Lock acquired (PID: {os.getpid()})")
        return True
    except Exception as e:
        logger.error(f"Failed to acquire lock: {e}")
        return False

def release_lock():
    """Release the lock file on exit."""
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
            logger.info("Lock released")
    except Exception as e:
        logger.warning(f"Failed to release lock: {e}")

# Configuration
BASE_SHARES = 10
MIN_SHARES = 10
MAX_SHARES = 15
ENTRY_DELAY = 20
ENTRY_WINDOW = 90
MOMENTUM_THRESHOLD = 30
STRONG_MOMENTUM = 75

# APIs
BINANCE_WS = "wss://stream.binance.com:9443/ws/btcusdt@trade"
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


class FastMomentumBot:
    def __init__(self):
        self.btc_price = None
        self.target_price = None
        self.token_ids = None
        self.market_info = None
        self.session = None  # Persistent aiohttp session
        
        # Position tracking
        self.position = {
            'side': None,
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
        
        # Momentum tracking
        self.price_history = deque(maxlen=60)
        self.round_start_time = None
        self.round_start_btc = None
        
        # Timing metrics
        self.discovery_times = deque(maxlen=20)
    
    async def init_session(self):
        """Initialize persistent HTTP session with connection pooling."""
        if self.session is None:
            connector = aiohttp.TCPConnector(
                limit=10,
                keepalive_timeout=60,
                enable_cleanup_closed=True
            )
            timeout = aiohttp.ClientTimeout(total=5, connect=2)
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "PolyBot/10.0"
                }
            )
        return self.session
    
    async def close_session(self):
        """Close HTTP session."""
        if self.session:
            await self.session.close()
            self.session = None
    
    async def discover_market_fast(self):
        """
        FAST market discovery using direct API calls.
        No browser/Playwright needed!
        
        Typical time: <300ms (vs 4-5 seconds with Playwright)
        """
        start_time = time.time()
        
        logger.info("=" * 60)
        logger.info("🚀 FAST MARKET DISCOVERY")
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
        
        self.round_start_time = float(slot)  # Use actual slot start, not discovery time
        slug = f"btc-updown-5m-{slot}"
        
        try:
            session = await self.init_session()
            
            # Direct API call - no browser!
            url = f"{GAMMA_API}/events?slug={slug}"
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.error(f"API error: {resp.status}")
                    return False
                
                data = await resp.json()
            
            # Handle both list and dict responses
            events = data if isinstance(data, list) else data.get('value', [])
            
            if not events:
                logger.error(f"No market found for slug: {slug}")
                return False
            
            event = events[0]
            market = event['markets'][0]
            
            # Parse token IDs from JSON string
            token_ids = json.loads(market['clobTokenIds'])
            
            self.market_info = {
                'title': event['title'],
                'slug': event['slug'],
                'token_ids': {
                    'Up': token_ids[0],
                    'Down': token_ids[1]
                },
                'event_start': market.get('eventStartTime')
            }
            self.token_ids = self.market_info['token_ids']
            
            # Set target price from current BTC
            self.target_price = self.btc_price if self.btc_price else 70000
            self.round_start_btc = self.btc_price
            
            # Reset position for new round
            self.position = {
                'side': None,
                'shares': 0,
                'entry_price': 0,
                'has_entered': False
            }
            
            # Clear price history for new round
            self.price_history.clear()
            
            elapsed = (time.time() - start_time) * 1000
            self.discovery_times.append(elapsed)
            avg_discovery = sum(self.discovery_times) / len(self.discovery_times)
            
            logger.info(f"Market: {self.market_info['title']}")
            logger.info(f"Target: ${self.target_price:,.2f}")
            logger.info(f"⚡ Discovery time: {elapsed:.0f}ms (avg: {avg_discovery:.0f}ms)")
            logger.info("=" * 60)
            
            # Save for dashboard
            with open('current_market.json', 'w') as f:
                json.dump({
                    **self.market_info,
                    'target_price': self.target_price,
                    'round_start': self.round_start_time,
                    'discovery_ms': elapsed
                }, f, indent=2)
            
            self.save_position_state()
            return True
            
        except asyncio.TimeoutError:
            logger.error("API timeout during discovery")
            return False
        except Exception as e:
            logger.error(f"Discovery error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def fetch_order_book(self, token_id):
        """Fetch orderbook from Polymarket CLOB."""
        try:
            session = await self.init_session()
            async with session.get(f"{CLOB_API}/book?token_id={token_id}") as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            logger.debug(f"Order book fetch error: {e}")
        return None
    
    def get_best_prices(self, book):
        """Extract best bid/ask from orderbook."""
        if not book:
            return None, None
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        best_bid = float(bids[0]["price"]) if bids else None
        best_ask = float(asks[0]["price"]) if asks else None
        return best_bid, best_ask
    
    def analyze_momentum(self):
        """Analyze BTC momentum to determine trade direction."""
        if not self.target_price or not self.btc_price:
            return None, 0, {}
        
        price_diff = self.btc_price - self.target_price
        
        # Calculate momentum from price history
        momentum = 0
        acceleration = 0
        trend_score = 0
        
        if len(self.price_history) >= 5:
            recent = list(self.price_history)[-5:]
            momentum = recent[-1] - recent[0]
            
            if len(self.price_history) >= 10:
                older = list(self.price_history)[-10:-5]
                old_momentum = older[-1] - older[0]
                acceleration = momentum - old_momentum
            
            ups = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i-1])
            trend_score = (ups / (len(recent) - 1)) * 100 if len(recent) > 1 else 50
        
        # Determine direction
        signals = {
            'price_diff': price_diff,
            'momentum': momentum,
            'acceleration': acceleration,
            'trend_score': trend_score
        }
        
        # Score calculation
        up_score = 0
        down_score = 0
        
        # Price position
        if price_diff > MOMENTUM_THRESHOLD:
            up_score += 2
        elif price_diff < -MOMENTUM_THRESHOLD:
            down_score += 2
        elif price_diff > 10:
            up_score += 1
        elif price_diff < -10:
            down_score += 1
        
        # Momentum
        if momentum > 20:
            up_score += 2
        elif momentum < -20:
            down_score += 2
        elif momentum > 5:
            up_score += 1
        elif momentum < -5:
            down_score += 1
        
        # Acceleration
        if acceleration > 5:
            up_score += 1
        elif acceleration < -5:
            down_score += 1
        
        # Trend
        if trend_score > 70:
            up_score += 1
        elif trend_score < 30:
            down_score += 1
        
        # Determine direction and confidence
        if up_score > down_score and up_score >= 2:
            return 'UP', up_score, signals
        elif down_score > up_score and down_score >= 2:
            return 'DOWN', down_score, signals
        else:
            return None, 0, signals
    
    def calculate_position_size(self, confidence):
        """Calculate position size based on confidence."""
        if confidence >= 5:
            return MAX_SHARES
        elif confidence >= 3:
            return BASE_SHARES
        elif confidence >= 2:
            return MIN_SHARES
        else:
            return 0
    
    async def enter_position(self, side, shares, entry_price):
        """Enter a directional position."""
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
        
        os.makedirs('logs', exist_ok=True)
        with open('logs/trades.jsonl', 'a') as f:
            f.write(json.dumps(trade_data) + '\n')
        
        self.save_position_state()
    
    async def close_position(self, won):
        """Close position at round end."""
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
        
        # Log completion
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
        
        # Print running stats
        win_rate = (self.stats['wins'] / self.stats['rounds_traded'] * 100) if self.stats['rounds_traded'] > 0 else 0
        logger.info(f"📈 STATS: {self.stats['wins']}W/{self.stats['losses']}L ({win_rate:.1f}%) | P&L: ${self.stats['total_profit']:+.2f}")
        
        # Reset position
        self.position = {
            'side': None,
            'shares': 0,
            'entry_price': 0,
            'has_entered': False
        }
        self.save_position_state()
    
    def save_position_state(self):
        """Save position state for dashboard."""
        state = {
            'has_position': self.position['side'] is not None,
            'side': self.position['side'],
            'shares': self.position['shares'],
            'entry_price': self.position['entry_price'],
            'target_price': self.target_price,
            'btc_price': self.btc_price,
            'round_start_time': self.round_start_time,
            'stats': self.stats,
            'updated_at': time.time()
        }
        
        with open('position_state.json', 'w') as f:
            json.dump(state, f, indent=2)
    
    async def run_btc_feed(self):
        """Run BTC price feed via WebSocket."""
        import websockets
        
        while True:
            try:
                async with websockets.connect(BINANCE_WS) as ws:
                    logger.info("📡 Connected to Binance BTC feed")
                    async for msg in ws:
                        data = json.loads(msg)
                        self.btc_price = float(data['p'])
                        self.price_history.append(self.btc_price)
            except Exception as e:
                logger.warning(f"BTC feed error: {e}, reconnecting...")
                await asyncio.sleep(1)
    
    async def run_trading_loop(self):
        """Main trading loop."""
        logger.info("🚀 FAST MOMENTUM BOT v10 STARTING")
        logger.info("⚡ Optimized for speed - no browser scraping!")
        
        # Wait for BTC price
        while self.btc_price is None:
            logger.info("Waiting for BTC price...")
            await asyncio.sleep(1)
        
        logger.info(f"BTC Price: ${self.btc_price:,.2f}")
        
        while True:
            try:
                # Discover market with fast API
                if not await self.discover_market_fast():
                    logger.error("Failed to discover market, retrying in 10s...")
                    await asyncio.sleep(10)
                    continue
                
                # Trading window
                entry_made = False
                while True:
                    elapsed = time.time() - self.round_start_time
                    remaining = 300 - elapsed
                    
                    if remaining <= 10:
                        # Round ending
                        if self.position['side']:
                            # Determine outcome
                            won = False
                            if self.position['side'] == 'UP':
                                won = self.btc_price >= self.target_price
                            else:
                                won = self.btc_price < self.target_price
                            
                            await self.close_position(won)
                        break
                    
                    # Entry window
                    if not self.position['has_entered'] and ENTRY_DELAY <= elapsed <= ENTRY_WINDOW:
                        direction, confidence, signals = self.analyze_momentum()
                        
                        if direction and confidence >= 2:
                            shares = self.calculate_position_size(confidence)
                            
                            if shares >= MIN_SHARES:
                                # Get order book for entry price
                                token_id = self.token_ids[direction.capitalize()]
                                book = await self.fetch_order_book(token_id)
                                _, best_ask = self.get_best_prices(book)
                                
                                entry_price = best_ask if best_ask and best_ask <= 0.70 else 0.50
                                
                                await self.enter_position(direction, shares, entry_price)
                                entry_made = True
                    
                    # Update dashboard
                    self.save_position_state()
                    
                    await asyncio.sleep(1)
                
                # Wait for next round
                now = int(time.time())
                next_slot = ((now // 300) + 1) * 300
                wait_time = next_slot - now + 2
                logger.info(f"⏳ Next round in {wait_time}s...")
                await asyncio.sleep(wait_time)
                
            except Exception as e:
                logger.error(f"Trading loop error: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(5)
    
    async def run(self):
        """Main entry point."""
        if not acquire_lock():
            return
        
        try:
            await asyncio.gather(
                self.run_btc_feed(),
                self.run_trading_loop()
            )
        finally:
            await self.close_session()
            release_lock()


async def main():
    bot = FastMomentumBot()
    await bot.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    finally:
        release_lock()
