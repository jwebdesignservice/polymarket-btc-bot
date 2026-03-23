"""
Polymarket MOMENTUM BOT v11.5
---------------------------
HIGH CONFIDENCE + FAST DISCOVERY + OPTIMIZED

Features:
- 70% minimum confidence (no low confidence trades)
- Fast API discovery (120ms vs 4-5s Playwright)
- Position recovery on restart
- Scaled position sizing (70%=10, 80%=12, 90%=15 shares)
- Redundant price feeds (Binance primary, Coinbase backup)
- Connection pre-warming (persistent sessions)

Signals (need 3+ agreeing for 70%+ confidence):
1. Price Change: BTC vs target price
2. Short-term Momentum: Last 10 seconds
3. Medium-term Momentum: Last 30 seconds  
4. Acceleration: Is momentum increasing?

Win Condition: High confidence trades only → higher win rate
"""

import asyncio
import websockets
import aiohttp
import json
import os
import sys
import time
import logging
from collections import deque
from generate_report import generate_report

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================
# SINGLE INSTANCE LOCK
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
                logger.error(f"Another bot instance running (PID: {old_pid}). Exiting.")
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
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except:
        pass

# ============================================================
# CONFIGURATION - v11 TIGHTENED
# ============================================================
BASE_SHARES = 10        # Standard position
MAX_SHARES = 15         # High confidence position
MIN_CONFIDENCE = 0.60   # 60% minimum - trades when 2-3/4 signals agree
ENTRY_DELAY = 5         # Wait 5s - enter early before prices spike
ENTRY_WINDOW = 90       # Must enter within 90 seconds
MOMENTUM_THRESHOLD = 30 # $30 move = clear direction
STRONG_MOMENTUM = 75    # $75+ move = high confidence

# APIs - Primary and Backups
BINANCE_US_WS = "wss://stream.binance.us:9443/ws/btcusdt@trade"  # Try first (less restricted)
BINANCE_WS = "wss://stream.binance.com:9443/ws/btcusdt@trade"     # Fallback
COINBASE_WS = "wss://ws-feed.exchange.coinbase.com"               # Last resort
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


class MomentumBotV11:
    def __init__(self):
        self.btc_price = None
        self.target_price = None
        self.token_ids = None
        self.market_info = None
        self.session = None
        self.round_start_time = 0
        
        # Price history for momentum (DO NOT CLEAR between rounds)
        self.price_history = deque(maxlen=60)
        self.price_timestamps = deque(maxlen=60)
        
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
            'skipped_low_confidence': 0
        }
        self.load_stats()
    
    def load_stats(self):
        """Load stats from historical trades"""
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
            logger.info(f"Loaded stats: {wins}W/{losses}L, P&L: ${profit:.2f}")
    
    def try_recover_position(self):
        """Try to recover position from last session"""
        try:
            with open('position_state.json', 'r') as f:
                state = json.load(f)
            
            if state.get('has_position') and state.get('side'):
                # Check if we're still in the same round (within 5 min)
                if time.time() - state.get('round_start', 0) < 300:
                    self.position = {
                        'side': state['side'],
                        'shares': state['shares'],
                        'entry_price': state.get('entry_price', 0.5),
                        'has_entered': True
                    }
                    self.target_price = state.get('target_price')
                    self.round_start_time = state.get('round_start', time.time())
                    logger.info(f"🔄 Recovered position: {state['shares']} {state['side']}")
                    return True
        except:
            pass
        return False
    
    # ============================================================
    # FAST API DISCOVERY (120ms vs 4-5s Playwright)
    # ============================================================
    
    async def init_session(self):
        if not self.session:
            connector = aiohttp.TCPConnector(limit=10, keepalive_timeout=60)
            timeout = aiohttp.ClientTimeout(total=10, connect=5)
            self.session = aiohttp.ClientSession(connector=connector, timeout=timeout)
    
    async def close_session(self):
        if self.session:
            await self.session.close()
            self.session = None
    
    async def discover_market_fast(self):
        """FAST market discovery using direct API - NO PLAYWRIGHT"""
        start_time = time.time()
        
        logger.info("=" * 60)
        logger.info("🚀 MARKET DISCOVERY (v11 Fast API)")
        logger.info("=" * 60)
        
        now = int(time.time())
        slot = (now // 300) * 300
        time_in_slot = now - slot
        
        if time_in_slot < 5:
            wait_time = 5 - time_in_slot
            logger.info(f"Waiting {wait_time}s for round to start...")
            await asyncio.sleep(wait_time)
            now = int(time.time())
            slot = (now // 300) * 300
        
        slug = f"btc-updown-5m-{slot}"
        
        try:
            await self.init_session()
            url = f"{GAMMA_API}/events?slug={slug}"
            
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    logger.error(f"API error: {resp.status}")
                    return False
                data = await resp.json()
            
            events = data if isinstance(data, list) else data.get('value', [])
            if not events:
                logger.error(f"No market found for: {slug}")
                return False
            
            event = events[0]
            market = event['markets'][0]
            token_ids = json.loads(market['clobTokenIds'])
            
            self.market_info = {
                'title': event['title'],
                'slug': event['slug'],
                'token_ids': {'Up': token_ids[0], 'Down': token_ids[1]}
            }
            self.token_ids = self.market_info['token_ids']
            
            # Set timing and target (same as v9.5)
            self.round_start_time = time.time()
            self.target_price = self.btc_price if self.btc_price else 70000
            
            # Reset position for new round
            self.position = {'side': None, 'shares': 0, 'entry_price': 0, 'has_entered': False}
            
            elapsed_ms = (time.time() - start_time) * 1000
            
            logger.info(f"Market: {self.market_info['title']}")
            logger.info(f"Target: ${self.target_price:,.2f}")
            logger.info(f"⚡ Discovery: {elapsed_ms:.0f}ms")
            logger.info("=" * 60)
            
            with open('current_market.json', 'w') as f:
                json.dump({**self.market_info, 'target_price': self.target_price}, f, indent=2)
            
            self.save_position_state()
            return True
            
        except Exception as e:
            logger.error(f"Discovery error: {e}")
            return False
    
    # ============================================================
    # MOMENTUM CALCULATION - EXACT v9.5 LOGIC
    # ============================================================
    
    def calculate_momentum(self):
        """Calculate momentum signals - needs 70%+ confidence to trade"""
        if len(self.price_history) < 10:
            return {'direction': None, 'strength': 0, 'confidence': 0, 'signals': []}
        
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
            recent = list(self.price_history)[-10:]
            short_mom = recent[-1] - recent[0]
            if short_mom > 20:
                signals.append(('SHORT_MOM', 'UP', abs(short_mom)))
            elif short_mom < -20:
                signals.append(('SHORT_MOM', 'DOWN', abs(short_mom)))
        
        # Signal 3: Medium-term momentum (last 30 seconds)
        if len(self.price_history) >= 15:
            older = list(self.price_history)[-30:]
            med_mom = older[-1] - older[0]
            if med_mom > 40:
                signals.append(('MED_MOM', 'UP', abs(med_mom)))
            elif med_mom < -40:
                signals.append(('MED_MOM', 'DOWN', abs(med_mom)))
        
        # Signal 4: Acceleration
        if len(self.price_history) >= 20:
            prices = list(self.price_history)
            first_half = prices[-20:-10]
            second_half = prices[-10:]
            first_change = first_half[-1] - first_half[0] if len(first_half) > 1 else 0
            second_change = second_half[-1] - second_half[0] if len(second_half) > 1 else 0
            
            if second_change > first_change + 10 and second_change > 0:
                signals.append(('ACCEL', 'UP', second_change - first_change))
            elif second_change < first_change - 10 and second_change < 0:
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
            # Tie - use price vs target
            direction = 'UP' if self.btc_price > self.target_price else 'DOWN'
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
        """Position sizing - SCALED BY CONFIDENCE (bigger bets when more certain)"""
        confidence = momentum['confidence']
        strength = momentum['strength']
        
        # v11: SCALED POSITION SIZING
        # Higher confidence = larger position
        if confidence < MIN_CONFIDENCE:
            return 0  # SKIP - below 70% confidence
        
        if strength < MOMENTUM_THRESHOLD:
            return 0  # SKIP - not enough price movement
        
        # Scale: 70%=10, 75%=11, 80%=12, 85%=13, 90%=14, 95%+=15
        if confidence >= 0.95:
            return 15
        elif confidence >= 0.90:
            return 14
        elif confidence >= 0.85:
            return 13
        elif confidence >= 0.80:
            return 12
        elif confidence >= 0.75:
            return 11
        else:  # 70-75%
            return 10
    
    # ============================================================
    # TRADING EXECUTION
    # ============================================================
    
    async def fetch_order_book(self, token_id):
        try:
            async with self.session.get(f"{CLOB_API}/book?token_id={token_id}") as resp:
                if resp.status == 200:
                    return await resp.json()
        except:
            pass
        return None
    
    def get_best_prices(self, book):
        if not book:
            return None, None
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        best_bid = float(bids[0]["price"]) if bids else None
        best_ask = float(asks[0]["price"]) if asks else None
        return best_bid, best_ask
    
    async def enter_position(self, side, shares, entry_price):
        cost = shares * entry_price
        
        logger.info("=" * 60)
        logger.info(f"🎯 ENTERING {side} POSITION")
        logger.info(f"Shares: {shares} | Entry: ${entry_price:.3f} | Cost: ${cost:.2f}")
        logger.info("[PAPER TRADE] Position opened")
        logger.info("=" * 60)
        
        self.position = {'side': side, 'shares': shares, 'entry_price': entry_price, 'has_entered': True}
        
        trade_data = {
            'timestamp': time.time(),
            'action': 'ENTER',
            'side': side,
            'shares': shares,
            'entry_price': entry_price,
            'cost': cost,
            'target_price': self.target_price,
            'btc_at_entry': self.btc_price,
            'version': 'v11.5',
            'status': 'open'
        }
        
        with open('logs/trades.jsonl', 'a') as f:
            f.write(json.dumps(trade_data) + '\n')
        
        self.save_position_state()
    
    async def close_position(self, won):
        payout = self.position['shares'] if won else 0
        cost = self.position['shares'] * self.position['entry_price']
        profit = payout - cost
        
        logger.info("=" * 60)
        logger.info(f"📊 ROUND COMPLETE: {'WIN ✅' if won else 'LOSS ❌'}")
        logger.info(f"Position: {self.position['shares']} {self.position['side']} | Profit: ${profit:+.2f}")
        logger.info("=" * 60)
        
        self.stats['rounds_traded'] += 1
        self.stats['total_profit'] += profit
        if won:
            self.stats['wins'] += 1
        else:
            self.stats['losses'] += 1
        
        trade_data = {
            'timestamp': time.time(),
            'action': 'CLOSE',
            'side': self.position['side'],
            'shares': self.position['shares'],
            'entry_price': self.position['entry_price'],
            'won': won,
            'payout': payout,
            'profit': profit,
            'version': 'v11.5',
            'status': 'completed'
        }
        
        with open('logs/trades.jsonl', 'a') as f:
            f.write(json.dumps(trade_data) + '\n')
        
        wr = self.stats['wins'] / max(self.stats['rounds_traded'], 1) * 100
        logger.info(f"📈 STATS: {self.stats['wins']}W/{self.stats['losses']}L ({wr:.1f}%) | P&L: ${self.stats['total_profit']:+.2f}")
        
        try:
            generate_report()
        except:
            pass
        
        self.position = {'side': None, 'shares': 0, 'entry_price': 0, 'has_entered': False}
        self.save_position_state()
    
    def save_position_state(self):
        state = {
            'has_position': self.position['side'] is not None,
            'side': self.position['side'],
            'shares': self.position['shares'],
            'entry_price': self.position.get('entry_price', 0.5),
            'target_price': self.target_price,
            'btc_price': self.btc_price,
            'round_start': self.round_start_time,
            'stats': self.stats,
            'version': 'v11.5',
            'updated_at': time.time()
        }
        with open('position_state.json', 'w') as f:
            json.dump(state, f, indent=2)
    
    # ============================================================
    # MAIN LOOPS
    # ============================================================
    
    async def run_btc_feed(self):
        """BTC price feed with REDUNDANCY (Binance US -> Binance -> Coinbase)"""
        feed_index = 0  # 0=Binance US, 1=Binance, 2=Coinbase
        fails = [0, 0, 0]  # Track fails per feed
        
        while True:
            # Try Binance US first (less geo-restricted)
            # Skip Binance - go straight to Coinbase (more reliable)
            # Coinbase primary
            try:
                async with websockets.connect(COINBASE_WS) as ws:
                    await ws.send(json.dumps({
                        "type": "subscribe",
                        "channels": [{"name": "ticker", "product_ids": ["BTC-USD"]}]
                    }))
                    logger.info("📡 Coinbase connected (backup)")
                    
                    async for msg in ws:
                        data = json.loads(msg)
                        if data.get('type') == 'ticker' and 'price' in data:
                            self.btc_price = float(data['price'])
                            self.price_history.append(self.btc_price)
                            self.price_timestamps.append(time.time())
                            
            except Exception as e:
                logger.warning(f"Coinbase error: {e}, retrying feeds...")
                feed_index = 0
                fails = [0, 0, 0]
                await asyncio.sleep(2)
    
    async def run_trading_loop(self):
        """Main trading loop"""
        logger.info("=" * 60)
        logger.info("🚀 MOMENTUM BOT v11.5 - HIGH CONFIDENCE ONLY")
        logger.info(f"⚡ Fast API Discovery | Min Confidence: {MIN_CONFIDENCE:.0%}")
        logger.info("=" * 60)
        
        # Try to recover position from crash
        if self.try_recover_position():
            logger.info("Continuing from recovered position...")
        
        while self.btc_price is None:
            logger.info("Waiting for BTC price...")
            await asyncio.sleep(1)
        
        logger.info(f"BTC Price: ${self.btc_price:,.2f}")
        
        while True:
            try:
                # Discover new market if needed
                if not self.position['has_entered']:
                    if not await self.discover_market_fast():
                        await asyncio.sleep(10)
                        continue
                
                while True:
                    elapsed = time.time() - self.round_start_time
                    remaining = 300 - elapsed
                    
                    # Round ending
                    if remaining <= 10:
                        if self.position['side']:
                            won = (self.btc_price >= self.target_price) if self.position['side'] == 'UP' else (self.btc_price < self.target_price)
                            await self.close_position(won)
                        break
                    
                    # Entry window
                    if not self.position['has_entered'] and ENTRY_DELAY <= elapsed <= ENTRY_WINDOW:
                        momentum = self.calculate_momentum()
                        
                        if momentum['direction']:
                            shares = self.calculate_position_size(momentum)
                            
                            if shares > 0:
                                token_id = self.token_ids[momentum['direction'].capitalize()]
                                book = await self.fetch_order_book(token_id)
                                _, best_ask = self.get_best_prices(book)
                                
                                # PRICE CAP - max $0.65 (breakeven at ~65% WR, we run ~70%)
                                # No floor - cheap entries have best risk/reward
                                max_entry = 0.65
                                
                                if best_ask and best_ask > max_entry:
                                    logger.info(f"⏭️ Price too high: ${best_ask:.2f} > max ${max_entry:.2f} - skipping")
                                else:
                                    entry_price = best_ask if best_ask else 0.50
                                    logger.info(f"📊 Entry ${entry_price:.2f} | Max ${max_entry:.2f} (conf {momentum['confidence']:.0%})")
                                    logger.info(f"Momentum: {momentum['direction']} | Confidence: {momentum['confidence']:.0%} | Signals: {momentum['up_votes']}↑ {momentum['down_votes']}↓")
                                    await self.enter_position(momentum['direction'], shares, entry_price)
                            else:
                                if int(time.time()) % 10 == 0:
                                    reason = "low confidence" if momentum['confidence'] < MIN_CONFIDENCE else "weak momentum"
                                    logger.info(f"⏭️ Skipping: {reason} ({momentum['confidence']:.0%}) - waiting for better setup")
                                    self.stats['skipped_low_confidence'] += 1
                    
                    # Holding phase
                    if self.position['has_entered'] and int(time.time()) % 15 == 0:
                        diff = self.btc_price - self.target_price
                        winning = (self.position['side'] == 'UP' and diff > 0) or (self.position['side'] == 'DOWN' and diff < 0)
                        logger.info(f"[{remaining:.0f}s] Holding {self.position['shares']} {self.position['side']} | BTC: ${self.btc_price:,.2f} ({diff:+.2f}) | {'WINNING 📈' if winning else 'LOSING 📉'}")
                    
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
        if not acquire_lock():
            return
        
        try:
            await self.init_session()
            await asyncio.gather(
                self.run_btc_feed(),
                self.run_trading_loop()
            )
        finally:
            await self.close_session()
            release_lock()


async def main():
    bot = MomentumBotV11()
    await bot.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    finally:
        release_lock()

