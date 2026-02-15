"""
Live sync - pushes data to jsonbin.io every 5 seconds for real-time public dashboard
Run this alongside the bot: py live_sync.py
"""
import json
import os
import time
import requests
from datetime import datetime

STATE_FILE = "position_state.json"
TRADES_FILE = "logs/trades.jsonl"
STARTING_BALANCE = 100.0

# JSONBin.io - Free JSON storage with API
# Create a bin at https://jsonbin.io and get the bin ID
JSONBIN_ID = os.getenv('JSONBIN_ID', '')
JSONBIN_KEY = os.getenv('JSONBIN_KEY', '')  # Optional for public bins

def load_state():
    """Load current bot state"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}

def load_trades():
    """Load trades from file"""
    trades = []
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, 'r') as f:
            for line in f:
                if line.strip():
                    try:
                        trades.append(json.loads(line))
                    except:
                        pass
    return trades

def calculate_stats(trades):
    """Calculate trading stats"""
    completed = [t for t in trades if t.get('action') == 'CLOSE']
    wins = sum(1 for t in completed if t.get('won', False))
    losses = len(completed) - wins
    total_profit = sum(t.get('profit', 0) for t in completed)
    
    # Streak
    streak = 0
    for t in reversed(completed):
        if t.get('won'):
            streak = streak + 1 if streak >= 0 else 1
        else:
            streak = streak - 1 if streak <= 0 else -1
        if abs(streak) == 1 and t.get('won') != (streak > 0):
            break
    
    return {
        'wins': wins,
        'losses': losses,
        'total_profit': round(total_profit, 2),
        'rounds_traded': len(completed),
        'current_streak': streak,
        'starting_balance': STARTING_BALANCE,
        'overall_balance': round(STARTING_BALANCE + total_profit, 2)
    }

def format_trades(trades, limit=10):
    """Format recent trades"""
    completed = [t for t in trades if t.get('action') == 'CLOSE'][-limit:][::-1]
    return [{
        'time': datetime.fromtimestamp(t.get('timestamp', 0)).strftime('%I:%M %p'),
        'side': t.get('side', 'UP'),
        'invested': round(t.get('shares', 0) * t.get('entry_price', 0.5), 2),
        'profit': round(t.get('profit', 0), 2),
        'won': t.get('won', False)
    } for t in completed]

def build_data():
    """Build complete data object"""
    state = load_state()
    trades = load_trades()
    
    position = {'has_position': False}
    if state.get('has_position'):
        position = {
            'has_position': True,
            'side': state.get('side', 'UP'),
            'shares': state.get('shares', 0),
            'cost': round(state.get('cost', 0), 2),
            'btc_price': state.get('btc_price', 0),
            'target_price': state.get('target_price', 0),
            'winning': state.get('winning'),
            'live_pnl': round(state.get('live_pnl', 0), 2),
            'up_probability': round(state.get('up_probability', 50), 1),
            'time_remaining': int(state.get('time_remaining', 0))
        }
    
    return {
        'updated': datetime.now().isoformat(),
        'timestamp': time.time(),
        'stats': calculate_stats(trades),
        'position': position,
        'trades': format_trades(trades)
    }

def push_jsonbin(data):
    """Push to JSONBin.io"""
    if not JSONBIN_ID:
        return False
    
    headers = {'Content-Type': 'application/json'}
    if JSONBIN_KEY:
        headers['X-Master-Key'] = JSONBIN_KEY
    
    try:
        url = f"https://api.jsonbin.io/v3/b/{JSONBIN_ID}"
        r = requests.put(url, json=data, headers=headers)
        return r.status_code == 200
    except Exception as e:
        print(f"JSONBin error: {e}")
        return False

def save_local(data):
    """Save locally for GitHub Pages fallback"""
    os.makedirs('public', exist_ok=True)
    with open('public/data.json', 'w') as f:
        json.dump(data, f)
    with open('data.json', 'w') as f:
        json.dump(data, f)

def sync_loop():
    """Main sync loop - runs every 5 seconds"""
    print("Starting live sync...")
    print(f"JSONBin ID: {JSONBIN_ID or 'Not configured'}")
    
    while True:
        try:
            data = build_data()
            save_local(data)
            
            if JSONBIN_ID:
                if push_jsonbin(data):
                    status = "✓ Pushed to JSONBin"
                else:
                    status = "✗ JSONBin failed"
            else:
                status = "Local only"
            
            pos = data['position']
            if pos['has_position']:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {status} | "
                      f"{pos['side']} {pos['shares']} | "
                      f"P&L: ${pos['live_pnl']:+.2f} | "
                      f"Time: {pos['time_remaining']}s")
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {status} | No position")
            
            time.sleep(5)
            
        except KeyboardInterrupt:
            print("\nStopping sync...")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

if __name__ == '__main__':
    sync_loop()
