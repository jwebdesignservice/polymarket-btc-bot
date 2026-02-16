"""
Polymarket FAST MOMENTUM Bot v10.1
----------------------------------
Strategy: Same as v10 but with WEBSOCKET ORDER BOOK

Phase 2 Optimization:
- WebSocket for CLOB prices (replaces HTTP polling)
- Real-time order book streaming
- ~200ms faster price updates

Target: <300ms total latency
"""

import asyncio
import aiohttp
import websockets
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
CLOB_WS = "wss://clob.polymarket.com/ws"


class FastMomentumBotV101:
    def __init__(self):
        self.btc_price = None
        self.target_price = None
        self.token_ids = None
        self.market_info = None
        self.session = None
        
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
        
        # WebSocket order book prices (Phase 2)
        self.clob_prices = {}  # token_id -> {'bid': x, 'ask': y, 'mid': z}
        self.clob_ws = None
        self.clob_connected = False
        
        # Timing metrics
        self.discovery_times = deque(maxlen=20)
    
    async def init_session(self):
        if self.session is None:
            connector = aiohttp.TCPConnector(limit=10, keepalive_timeout=60)
            timeout = aiohttp.ClientTimeout(total=5, connect=2)
            self.session = aiohttp.ClientSession(
                connector=connector, timeout=timeout,
                headers={"Accept": "application/json", "User-Agent": "PolyBot/10.1"}
            )
        return self.session
    
    async def close_session(self):
        if self.session:
            await self.session.close()
            self.session = None
    
    # ============================================================
    # PHASE 2: WebSocket Order Book
    # ============================================================
    
    async def run_clob_ws(self):
        """WebSocket connection for real-time CLOB prices (with HTTP fallback)."""
        ws_failed_count = 0
        
        while True:
            # After 3 failures, switch to HTTP polling mode
            if ws_failed_count >= 3:
                logger.info("📊 CLOB WS unavailable, using HTTP polling fallback")
                await self._run_http_price_polling()
                return
            
            try:
                async with websockets.connect(CLOB_WS, ping_interval=20) as ws:
                    self.clob_ws = ws
                    self.clob_connected = True
                    ws_failed_count = 0
                    logger.info("📡 CLOB WebSocket connected")
                    
                    if self.token_ids:
                        await self._subscribe_tokens()
                    
                    async for msg in ws:
                        await self._handle_clob_message(msg)
                        
            except Exception as e:
                ws_failed_count += 1
                logger.warning(f"CLOB WS error ({ws_failed_count}/3): {e}")
                self.clob_connected = False
                await asyncio.sleep(2)
    
    async def _run_http_price_polling(self):
        """Fallback: Poll CLOB API for prices every second."""
        logger.info("📊 Running HTTP price polling mode")
        session = await self.init_session()
        
        while True:
            try:
                if self.token_ids:
                    for side in ['Up', 'Down']:
                        token_id = self.token_ids[side]
                        url = f"{CLOB_API}/book?token_id={token_id}"
                        
                        try:
                            async with session.get(url) as resp:
                                if resp.status == 200:
                                    book = await resp.json()
                                    bids = book.get("bids", [])
                                    asks = book.get("asks", [])
                                    
                                    best_bid = float(bids[0]["price"]) if bids else None
                                    best_ask = float(asks[0]["price"]) if asks else None
                                    mid = ((best_bid or 0.5) + (best_ask or 0.5)) / 2
                                    
                                    self.clob_prices[token_id] = {
                                        'bid': best_bid,
                                        'ask': best_ask,
                                        'mid': mid
                                    }
                        except Exception:
                            pass
                
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.debug(f"HTTP polling error: {e}")
                await asyncio.sleep(2)
    
    async def _subscribe_tokens(self):
        """Subscribe to price updates for current tokens."""
        if not self.clob_ws or not self.token_ids:
            return
        
        tokens = [self.token_ids['Up'], self.token_ids['Down']]
        msg = {
            "type": "subscribe",
            "channel": "market",
            "assets_ids": tokens
        }
        try:
            await self.clob_ws.send(json.dumps(msg))
            logger.info(f"📊 Subscribed to {len(tokens)} tokens")
        except Exception as e:
            logger.warning(f"Subscribe failed: {e}")
    
    async def _handle_clob_message(self, raw):
        """Process CLOB WebSocket message."""
        try:
            data = json.loads(raw)
            
            # Handle different message types
            if isinstance(data, list):
                for event in data:
                    await self._process_clob_event(event)
            else:
                await self._process_clob_event(data)
                
        except Exception as e:
            pass  # Silently ignore parse errors
    
    async def _process_clob_event(self, event):
        """Extract prices from CLOB event."""
        token_id = event.get("asset_id") or event.get("market")
        if not token_id:
            return
        
        # Direct price
        if "price" in event:
            mid = float(event["price"])
            self.clob_prices[token_id] = {'mid': mid, 'ask': mid, 'bid': mid}
            return
        
        # Order book update
        bids = event.get("bids", [])
        asks = event.get("asks", [])
        
        if bids or asks:
            best_bid = float(bids[0]["price"]) if bids else None
            best_ask = float(asks[0]["price"]) if asks else None
            
            if best_bid and best_ask:
                mid = (best_bid + best_ask) / 2
            else:
                mid = best_ask or best_bid or 0.5
            
            self.clob_prices[token_id] = {
                'bid': best_bid,
                'ask': best_ask,
                'mid': mid
            }
    
    def get_ws_price(self, token_id):
        """Get best ask price from WebSocket (or fallback to 0.50)."""
        if token_id in self.clob_prices:
            return self.clob_prices[token_id].get('ask', 0.50)
        return 0.50
    
    # ============================================================
    # Market Discovery (same as v10)
    # ============================================================
    
    async def discover_market_fast(self):
        start_time = time.time()
        
        logger.info("=" * 60)
        logger.info("🚀 FAST MARKET DISCOVERY")
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
        
        self.round_start_time = float(slot)
        slug = f"btc-updown-5m-{slot}"
        
        try:
            session = await self.init_session()
            url = f"{GAMMA_API}/events?slug={slug}"
            
            async with session.get(url) as resp:
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
            
            old_tokens = self.token_ids
            self.market_info = {
                'title': event['title'],
                'slug': event['slug'],
                'token_ids': {'Up': token_ids[0], 'Down': token_ids[1]}
            }
            self.token_ids = self.market_info['token_ids']
            
            self.target_price = self.btc_price if self.btc_price else 70000
            self.round_start_btc = self.btc_price
            
            # Reset position
            self.position = {'side': None, 'shares': 0, 'entry_price': 0, 'has_entered': False}
            self.price_history.clear()
            
            # Subscribe to new tokens via WebSocket
            if self.clob_connected:
                await self._subscribe_tokens()
            
            elapsed = (time.time() - start_time) * 1000
            self.discovery_times.append(elapsed)
            avg = sum(self.discovery_times) / len(self.discovery_times)
            
            logger.info(f"Market: {self.market_info['title']}")
            logger.info(f"Target: ${self.target_price:,.2f}")
            logger.info(f"⚡ Discovery time: {elapsed:.0f}ms (avg: {avg:.0f}ms)")
            logger.info("=" * 60)
            
            with open('current_market.json', 'w') as f:
                json.dump({**self.market_info, 'target_price': self.target_price}, f, indent=2)
            
            self.save_position_state()
            return True
            
        except Exception as e:
            logger.error(f"Discovery error: {e}")
            return False
    
    # ============================================================
    # Trading Logic
    # ============================================================
    
    def analyze_momentum(self):
        if not self.target_price or not self.btc_price:
            return None, 0, {}
        
        price_diff = self.btc_price - self.target_price
        momentum = acceleration = trend_score = 0
        
        if len(self.price_history) >= 5:
            recent = list(self.price_history)[-5:]
            momentum = recent[-1] - recent[0]
            
            if len(self.price_history) >= 10:
                older = list(self.price_history)[-10:-5]
                acceleration = momentum - (older[-1] - older[0])
            
            ups = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i-1])
            trend_score = (ups / (len(recent) - 1)) * 100 if len(recent) > 1 else 50
        
        signals = {'price_diff': price_diff, 'momentum': momentum, 'acceleration': acceleration, 'trend_score': trend_score}
        
        up_score = down_score = 0
        
        if price_diff > MOMENTUM_THRESHOLD: up_score += 2
        elif price_diff < -MOMENTUM_THRESHOLD: down_score += 2
        elif price_diff > 10: up_score += 1
        elif price_diff < -10: down_score += 1
        
        if momentum > 20: up_score += 2
        elif momentum < -20: down_score += 2
        elif momentum > 5: up_score += 1
        elif momentum < -5: down_score += 1
        
        if acceleration > 5: up_score += 1
        elif acceleration < -5: down_score += 1
        
        if trend_score > 70: up_score += 1
        elif trend_score < 30: down_score += 1
        
        if up_score > down_score and up_score >= 2:
            return 'UP', up_score, signals
        elif down_score > up_score and down_score >= 2:
            return 'DOWN', down_score, signals
        return None, 0, signals
    
    def calculate_position_size(self, confidence):
        if confidence >= 5: return MAX_SHARES
        elif confidence >= 3: return BASE_SHARES
        elif confidence >= 2: return MIN_SHARES
        return 0
    
    async def enter_position(self, side, shares, entry_price):
        cost = shares * entry_price
        
        logger.info("=" * 60)
        logger.info(f"🎯 ENTERING {side} POSITION")
        logger.info(f"Shares: {shares} | Entry: ${entry_price:.3f} | Cost: ${cost:.2f}")
        logger.info("[PAPER TRADE] Position opened")
        logger.info("=" * 60)
        
        self.position = {'side': side, 'shares': shares, 'entry_price': entry_price, 'has_entered': True}
        
        trade_data = {
            'timestamp': time.time(), 'action': 'ENTER', 'side': side,
            'shares': shares, 'entry_price': entry_price, 'cost': cost,
            'target_price': self.target_price, 'btc_at_entry': self.btc_price, 'status': 'open'
        }
        os.makedirs('logs', exist_ok=True)
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
            'timestamp': time.time(), 'action': 'CLOSE', 'side': self.position['side'],
            'shares': self.position['shares'], 'entry_price': self.position['entry_price'],
            'won': won, 'payout': payout, 'profit': profit, 'status': 'completed'
        }
        with open('logs/trades.jsonl', 'a') as f:
            f.write(json.dumps(trade_data) + '\n')
        
        win_rate = (self.stats['wins'] / self.stats['rounds_traded'] * 100) if self.stats['rounds_traded'] > 0 else 0
        logger.info(f"📈 STATS: {self.stats['wins']}W/{self.stats['losses']}L ({win_rate:.1f}%) | P&L: ${self.stats['total_profit']:+.2f}")
        
        self.position = {'side': None, 'shares': 0, 'entry_price': 0, 'has_entered': False}
        self.save_position_state()
    
    def save_position_state(self):
        state = {
            'has_position': self.position['side'] is not None,
            'side': self.position['side'],
            'shares': self.position['shares'],
            'target_price': self.target_price,
            'btc_price': self.btc_price,
            'stats': self.stats,
            'updated_at': time.time()
        }
        with open('position_state.json', 'w') as f:
            json.dump(state, f, indent=2)
    
    # ============================================================
    # Main Loops
    # ============================================================
    
    async def run_btc_feed(self):
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
        logger.info("🚀 FAST MOMENTUM BOT v10.1 STARTING")
        logger.info("⚡ Phase 2: WebSocket order book enabled!")
        
        while self.btc_price is None:
            logger.info("Waiting for BTC price...")
            await asyncio.sleep(1)
        
        logger.info(f"BTC Price: ${self.btc_price:,.2f}")
        
        while True:
            try:
                if not await self.discover_market_fast():
                    logger.error("Discovery failed, retrying in 10s...")
                    await asyncio.sleep(10)
                    continue
                
                while True:
                    elapsed = time.time() - self.round_start_time
                    remaining = 300 - elapsed
                    
                    if remaining <= 10:
                        if self.position['side']:
                            won = (self.btc_price >= self.target_price) if self.position['side'] == 'UP' else (self.btc_price < self.target_price)
                            await self.close_position(won)
                        break
                    
                    if not self.position['has_entered'] and ENTRY_DELAY <= elapsed <= ENTRY_WINDOW:
                        direction, confidence, _ = self.analyze_momentum()
                        
                        if direction and confidence >= 2:
                            shares = self.calculate_position_size(confidence)
                            if shares >= MIN_SHARES:
                                # Phase 2: Use WebSocket price if available
                                token_id = self.token_ids[direction.capitalize()]
                                entry_price = self.get_ws_price(token_id)
                                
                                # Cap entry price
                                if entry_price > 0.70:
                                    entry_price = 0.50
                                
                                await self.enter_position(direction, shares, entry_price)
                    
                    self.save_position_state()
                    await asyncio.sleep(1)
                
                now = int(time.time())
                next_slot = ((now // 300) + 1) * 300
                wait_time = next_slot - now + 2
                logger.info(f"⏳ Next round in {wait_time}s...")
                await asyncio.sleep(wait_time)
                
            except Exception as e:
                logger.error(f"Trading loop error: {e}")
                await asyncio.sleep(5)
    
    async def run(self):
        if not acquire_lock():
            return
        
        try:
            await asyncio.gather(
                self.run_btc_feed(),
                self.run_clob_ws(),  # Phase 2: CLOB WebSocket
                self.run_trading_loop()
            )
        finally:
            await self.close_session()
            release_lock()


async def main():
    bot = FastMomentumBotV101()
    await bot.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    finally:
        release_lock()
