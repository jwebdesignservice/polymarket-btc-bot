"""
Live Polymarket BTC 5-min arbitrage trader
Using manual token IDs from browser
"""

import asyncio
import aiohttp
import time
import logging
from datetime import datetime
from collections import deque

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Strategy parameters - OPTIMIZED FOR MAX PROFITABILITY
MOVE_THRESHOLD = 0.05  # 5% price drop triggers Leg 1 (AGGRESSIVE)
SUM_TARGET = 0.94      # Max combined entry (6% profit target)
WINDOW_MIN = 4.0       # Watch first 4 minutes (80% of round)
SHARES = 10            # Number of shares per leg
POLL_INTERVAL = 1.0    # Poll every 1 second

# API endpoints
CLOB_BOOK_API = "https://clob.polymarket.com/book"

# Token IDs from user's browser (current live market)
TOKEN_IDS = {
    "Up": "31075038965079981889345101642942405842536264292198998875000562469999993762543",
    "Down": "90210148003034117706442174147844478290374399008613984920949469153917019650636"
}

# State machine
class State:
    IDLE = "IDLE"
    WATCHING = "WATCHING"
    LEG1_FILLED = "LEG1_FILLED"
    LEG2_FILLED = "LEG2_FILLED"

class LiveTrader:
    def __init__(self):
        self.state = State.IDLE
        self.token_ids = TOKEN_IDS
        self.round_start = None
        self.leg1_entry = None
        self.leg1_side = None
        self.price_history = deque(maxlen=100)
        self.session = None
        
    async def fetch_order_book(self, token_id):
        """Fetch order book for a specific token"""
        try:
            async with self.session.get(f"{CLOB_BOOK_API}?token_id={token_id}") as resp:
                if resp.status != 200:
                    return None
                return await resp.json()
        except Exception as e:
            logger.error(f"Error fetching order book: {e}")
            return None
    
    def get_best_prices(self, book):
        """Extract best bid/ask from order book"""
        if not book:
            return None, None
            
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        
        best_bid = float(bids[0]["price"]) if bids else None
        best_ask = float(asks[0]["price"]) if asks else None
        
        return best_bid, best_ask
    
    async def monitor_market(self):
        """Main monitoring loop"""
        while True:
            try:
                # Fetch order books for both outcomes
                up_book = await self.fetch_order_book(self.token_ids["Up"])
                down_book = await self.fetch_order_book(self.token_ids["Down"])
                
                if not up_book or not down_book:
                    await asyncio.sleep(POLL_INTERVAL)
                    continue
                
                up_bid, up_ask = self.get_best_prices(up_book)
                down_bid, down_ask = self.get_best_prices(down_book)
                
                if not all([up_bid, up_ask, down_bid, down_ask]):
                    await asyncio.sleep(POLL_INTERVAL)
                    continue
                
                # Store price snapshot
                snapshot = {
                    "time": time.time(),
                    "up_bid": up_bid,
                    "up_ask": up_ask,
                    "down_bid": down_bid,
                    "down_ask": down_ask
                }
                self.price_history.append(snapshot)
                
                # Process based on state
                if self.state == State.IDLE:
                    await self.check_round_start()
                    
                elif self.state == State.WATCHING:
                    await self.check_leg1_entry(snapshot)
                    
                elif self.state == State.LEG1_FILLED:
                    await self.check_leg2_entry(snapshot)
                
                logger.info(f"[{self.state}] UP: {up_ask:.3f} | DOWN: {down_ask:.3f}")
                
                await asyncio.sleep(POLL_INTERVAL)
                
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                await asyncio.sleep(POLL_INTERVAL)
    
    async def check_round_start(self):
        """Detect when a new round starts"""
        # A new round starts when we have active order books
        # We'll watch for the first WINDOW_MIN minutes
        if len(self.price_history) > 0:
            self.round_start = time.time()
            self.state = State.WATCHING
            logger.info(f"Round started, watching for {WINDOW_MIN} minutes")
    
    async def check_leg1_entry(self, snapshot):
        """Check if Leg 1 entry condition is met"""
        elapsed = (time.time() - self.round_start) / 60.0
        
        # Only watch first WINDOW_MIN minutes
        if elapsed > WINDOW_MIN:
            logger.info(f"Window expired ({WINDOW_MIN} min), resetting to IDLE")
            self.state = State.IDLE
            return
        
        # Need at least 3 seconds of history (3 samples at 1-sec interval)
        if len(self.price_history) < 3:
            return
        
        # Check for 15% drop in either direction over 3 seconds
        old = self.price_history[-3]
        new = snapshot
        
        up_drop = (old["up_ask"] - new["up_ask"]) / old["up_ask"]
        down_drop = (old["down_ask"] - new["down_ask"]) / old["down_ask"]
        
        if up_drop >= MOVE_THRESHOLD:
            logger.info(f"LEG 1 TRIGGER: UP dropped {up_drop*100:.1f}%")
            self.leg1_side = "Up"
            self.leg1_entry = new["up_ask"]
            self.state = State.LEG1_FILLED
            logger.info(f"[PAPER] Bought {SHARES} UP shares @ {self.leg1_entry:.3f}")
            
        elif down_drop >= MOVE_THRESHOLD:
            logger.info(f"LEG 1 TRIGGER: DOWN dropped {down_drop*100:.1f}%")
            self.leg1_side = "Down"
            self.leg1_entry = new["down_ask"]
            self.state = State.LEG1_FILLED
            logger.info(f"[PAPER] Bought {SHARES} DOWN shares @ {self.leg1_entry:.3f}")
    
    async def check_leg2_entry(self, snapshot):
        """Check if Leg 2 hedge condition is met"""
        # Determine opposite side
        opposite_side = "Down" if self.leg1_side == "Up" else "Up"
        opposite_ask = snapshot["down_ask"] if opposite_side == "Down" else snapshot["up_ask"]
        
        # Check if leg1_entry + opposite_ask <= SUM_TARGET
        total_cost = self.leg1_entry + opposite_ask
        
        if total_cost <= SUM_TARGET:
            profit = 1.0 - total_cost
            logger.info(f"LEG 2 TRIGGER: Total cost {total_cost:.3f}, profit {profit*100:.1f}%")
            logger.info(f"[PAPER] Bought {SHARES} {opposite_side} shares @ {opposite_ask:.3f}")
            logger.info(f"[PAPER] PROFIT LOCKED: ${profit * SHARES:.2f}")
            
            self.state = State.IDLE
            self.round_start = None
            self.leg1_entry = None
            self.leg1_side = None
            logger.info("Cycle complete, resetting to IDLE")
    
    async def run(self):
        """Main entry point"""
        logger.info("Starting Polymarket Live Trader (Paper Mode)")
        logger.info("="*60)
        logger.info(f"Token IDs configured:")
        logger.info(f"  Up:   {self.token_ids['Up']}")
        logger.info(f"  Down: {self.token_ids['Down']}")
        logger.info(f"\nStrategy: {SHARES} shares, {MOVE_THRESHOLD*100}% move, ${SUM_TARGET} sum target")
        logger.info("="*60)
        
        async with aiohttp.ClientSession() as session:
            self.session = session
            
            # Test connection first
            logger.info("\nTesting connection to CLOB order book...")
            up_book = await self.fetch_order_book(self.token_ids["Up"])
            
            if not up_book:
                logger.error("Failed to connect to order book. Check token IDs.")
                return
            
            logger.info("Connection successful! Starting monitoring...")
            logger.info("")
            
            # Start monitoring
            await self.monitor_market()

if __name__ == "__main__":
    trader = LiveTrader()
    asyncio.run(trader.run())
