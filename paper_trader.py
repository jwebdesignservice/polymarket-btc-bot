"""
paper_trader.py
---------------
Paper trading simulator using historical 5-minute BTC Up/Down data.
Simulates live trading and updates the dashboard in real-time.
"""

import os
import sys
import json
import time
import requests
import base64
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))

BOT_DIR = Path(__file__).parent
STATE_FILE = BOT_DIR / "bot_state.json"
TRADES_FILE = BOT_DIR / "logs" / "trades.jsonl"

# Create logs directory
TRADES_FILE.parent.mkdir(exist_ok=True)

# Strategy parameters
MOVE_THRESHOLD = 0.15  # 15% drop to trigger Leg 1
SUM_TARGET = 0.95      # Max combined price for Leg 2
WINDOW_MIN = 2.0       # Watch first 2 minutes only
SHARES = 10            # Number of shares per trade


class PaperTrader:
    def __init__(self):
        self.state = self.load_state()
        self.round_count = 0
    
    def load_state(self):
        """Load bot state from disk."""
        if STATE_FILE.exists():
            with open(STATE_FILE, encoding='utf-8') as f:
                return json.load(f)
        return {
            "status": "idle",
            "mode": "paper",
            "shares": SHARES,
            "current_round": None,
            "leg1": None,
            "leg2": None,
            "uptime": 0,
            "last_update": time.time()
        }
    
    def save_state(self):
        """Save bot state to disk."""
        self.state["last_update"] = time.time()
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, indent=2)
    
    def log_trade(self, trade_data):
        """Append trade to JSONL log."""
        with open(TRADES_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(trade_data) + '\n')
    
    def fetch_5min_markets(self):
        """Fetch historical 5-minute markets."""
        print("[paper_trader] Fetching 5-minute BTC markets...")
        
        cursor = base64.b64encode(b'440000').decode()
        r = requests.get(
            'https://clob.polymarket.com/markets',
            params={'limit': 1000, 'next_cursor': cursor},
            timeout=15
        )
        
        if r.status_code != 200:
            print(f"[paper_trader] Failed to fetch markets: {r.status_code}")
            return []
        
        markets = r.json()['data']
        fivemin = [m for m in markets if 'btc-updown-5m-' in m.get('market_slug', '')]
        
        # Sort by end time (oldest first)
        fivemin.sort(key=lambda m: int(m['market_slug'].split('-')[-1]))
        
        print(f"[paper_trader] Loaded {len(fivemin)} markets")
        return fivemin[:50]  # Use first 50 for speed
    
    def fetch_price_history(self, token_id, end_ts):
        """Fetch price ticks for a token."""
        start_ts = end_ts - 5 * 60 - 60  # 5 min + 1 min padding
        
        r = requests.get(
            'https://clob.polymarket.com/prices-history',
            params={
                'market': token_id,
                'startTs': start_ts,
                'endTs': end_ts + 60,
                'fidelity': 1
            },
            timeout=10
        )
        
        if r.status_code != 200:
            return []
        
        history = r.json().get('history', [])
        history.sort(key=lambda x: x['t'])
        return history
    
    def simulate_round(self, market):
        """Simulate strategy on one 5-minute round."""
        self.round_count += 1
        
        slug = market['market_slug']
        end_ts = int(slug.split('-')[-1])
        start_ts = end_ts - 5 * 60
        watch_end_ts = start_ts + WINDOW_MIN * 60
        
        tokens = market.get('tokens', [])
        if len(tokens) < 2:
            return None
        
        up_token = next((t for t in tokens if t['outcome'].upper() == 'UP'), None)
        down_token = next((t for t in tokens if t['outcome'].upper() == 'DOWN'), None)
        
        if not up_token or not down_token:
            return None
        
        print(f"\n[{self.round_count}] Simulating: {market['question']}")
        
        # Update dashboard state
        self.state['status'] = 'watching'
        self.state['current_round'] = {
            'question': market['question'],
            'end_time': end_ts,
            'up_price': 0.5,
            'down_price': 0.5
        }
        self.save_state()
        
        # Fetch price data
        print(f"  Fetching price history...")
        up_history = self.fetch_price_history(up_token['token_id'], end_ts)
        down_history = self.fetch_price_history(down_token['token_id'], end_ts)
        
        if not up_history or not down_history:
            print(f"  No price data - skipping")
            return None
        
        # Simulate watching
        prev_up = None
        prev_down = None
        leg1_side = None
        leg1_entry = None
        leg1_ts = None
        
        for up_tick, down_tick in zip(up_history, down_history):
            t = up_tick['t']
            
            # Only watch during window
            if t < start_ts or t > watch_end_ts:
                continue
            
            up_price = up_tick['p']
            down_price = down_tick['p']
            
            # Update dashboard
            self.state['current_round']['up_price'] = up_price
            self.state['current_round']['down_price'] = down_price
            
            # Check for Leg 1 trigger
            if leg1_side is None:
                if prev_up and (prev_up - up_price) >= MOVE_THRESHOLD:
                    leg1_side = 'UP'
                    leg1_entry = up_price + 0.01  # Slippage
                    leg1_ts = t
                    self.state['status'] = 'leg1_filled'
                    self.state['leg1'] = {'side': leg1_side, 'entry': leg1_entry}
                    print(f"  [LEG 1] Triggered! Bought {leg1_side} @ {leg1_entry:.4f}")
                
                elif prev_down and (prev_down - down_price) >= MOVE_THRESHOLD:
                    leg1_side = 'DOWN'
                    leg1_entry = down_price + 0.01
                    leg1_ts = t
                    self.state['status'] = 'leg1_filled'
                    self.state['leg1'] = {'side': leg1_side, 'entry': leg1_entry}
                    print(f"  [LEG 1] Triggered! Bought {leg1_side} @ {leg1_entry:.4f}")
            
            # Check for Leg 2
            elif leg1_side:
                opposite_price = down_price if leg1_side == 'UP' else up_price
                
                if leg1_entry + opposite_price <= SUM_TARGET:
                    leg2_entry = opposite_price + 0.01
                    profit = 1.0 - (leg1_entry + leg2_entry)
                    
                    print(f"  [LEG 2] Filled! Bought opposite @ {leg2_entry:.4f}")
                    print(f"  [PROFIT] ${profit * SHARES:.4f} ({profit*100:.2f}%)")
                    
                    # Log trade
                    trade = {
                        'timestamp': int(time.time()),
                        'side': leg1_side,
                        'leg1_entry': leg1_entry,
                        'leg2_entry': leg2_entry,
                        'profit': profit * SHARES,
                        'status': 'completed',
                        'notes': 'Both legs filled'
                    }
                    self.log_trade(trade)
                    
                    self.state['status'] = 'idle'
                    self.state['leg1'] = None
                    self.state['leg2'] = {'side': 'DOWN' if leg1_side == 'UP' else 'UP', 'entry': leg2_entry}
                    self.save_state()
                    
                    time.sleep(1)  # Pause for dashboard update
                    return trade
            
            prev_up = up_price
            prev_down = down_price
        
        # Round ended without Leg 2
        if leg1_side:
            loss = -leg1_entry * SHARES
            print(f"  [TIMEOUT] Leg 2 never filled - Lost ${abs(loss):.4f}")
            
            trade = {
                'timestamp': int(time.time()),
                'side': leg1_side,
                'leg1_entry': leg1_entry,
                'leg2_entry': None,
                'profit': loss,
                'status': 'timeout',
                'notes': 'Leg 2 timeout - lost stake'
            }
            self.log_trade(trade)
            
            self.state['status'] = 'idle'
            self.state['leg1'] = None
            self.save_state()
            
            time.sleep(1)
            return trade
        
        print(f"  [NO TRIGGER]")
        self.state['status'] = 'idle'
        self.save_state()
        return None
    
    def run(self):
        """Main simulation loop."""
        print("="*70)
        print("  PAPER TRADER - Simulating with Historical 5-Min Data")
        print("="*70)
        print(f"\nParameters:")
        print(f"  Move threshold: {MOVE_THRESHOLD*100}%")
        print(f"  Sum target: {SUM_TARGET}")
        print(f"  Window: {WINDOW_MIN} minutes")
        print(f"  Shares: {SHARES}")
        print(f"\nDashboard: http://localhost:5000")
        print(f"Mode: PAPER TRADE\n")
        
        markets = self.fetch_5min_markets()
        
        if not markets:
            print("[paper_trader] No markets found!")
            return
        
        trades = []
        
        for market in markets:
            result = self.simulate_round(market)
            if result:
                trades.append(result)
            time.sleep(0.5)  # Pause between rounds
        
        # Summary
        print("\n" + "="*70)
        print("  SIMULATION COMPLETE")
        print("="*70)
        print(f"  Rounds simulated: {self.round_count}")
        print(f"  Trades triggered: {len(trades)}")
        
        if trades:
            wins = [t for t in trades if t['profit'] > 0]
            losses = [t for t in trades if t['profit'] <= 0]
            total_pnl = sum(t['profit'] for t in trades)
            
            print(f"  Wins: {len(wins)}")
            print(f"  Losses: {len(losses)}")
            print(f"  Total P&L: ${total_pnl:.4f}")
            print(f"  Avg profit: ${total_pnl/len(trades):.4f}")
        
        print("="*70 + "\n")
        
        self.state['status'] = 'idle'
        self.save_state()


if __name__ == '__main__':
    trader = PaperTrader()
    trader.run()
