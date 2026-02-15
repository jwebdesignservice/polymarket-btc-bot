"""
Firebase Realtime Database sync for live dashboard
Pushes trade data to Firebase for real-time public viewing
"""
import json
import os
import requests
from datetime import datetime

# Firebase Realtime Database URL (free tier)
# You'll need to create a project at https://console.firebase.google.com
# Then get the database URL from Project Settings > Realtime Database
FIREBASE_URL = os.getenv('FIREBASE_URL', '')  # e.g., https://your-project.firebaseio.com

TRADES_FILE = "logs/trades.jsonl"
STATE_FILE = "logs/state.json"
STARTING_BALANCE = 100.0

def load_trades():
    """Load all trades from JSONL file"""
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

def load_state():
    """Load current bot state"""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {}

def calculate_stats(trades):
    """Calculate trading statistics"""
    completed = [t for t in trades if t.get('action') == 'CLOSE']
    
    wins = sum(1 for t in completed if t.get('won', False))
    losses = len(completed) - wins
    total_profit = sum(t.get('profit', 0) for t in completed)
    
    # Calculate streak
    streak = 0
    for t in reversed(completed):
        if t.get('won'):
            if streak >= 0:
                streak += 1
            else:
                break
        else:
            if streak <= 0:
                streak -= 1
            else:
                break
    
    return {
        'wins': wins,
        'losses': losses,
        'total_profit': round(total_profit, 2),
        'rounds_traded': len(completed),
        'current_streak': streak,
        'starting_balance': STARTING_BALANCE,
        'overall_balance': round(STARTING_BALANCE + total_profit, 2),
        'win_rate': round(wins / len(completed) * 100, 1) if completed else 0
    }

def get_current_position(trades, state):
    """Get the current open position with live details"""
    open_trades = [t for t in trades if t.get('action') == 'ENTER' and t.get('status') == 'open']
    
    if open_trades:
        latest = open_trades[-1]
        
        # Get live data from state if available
        btc_price = state.get('current_btc', 0)
        target_price = latest.get('target_price', 0)
        time_remaining = state.get('time_remaining', 0)
        
        # Calculate if winning
        side = latest.get('side', 'UP')
        if side == 'UP':
            winning = btc_price > target_price if btc_price and target_price else None
            diff = btc_price - target_price if btc_price and target_price else 0
        else:
            winning = btc_price < target_price if btc_price and target_price else None
            diff = target_price - btc_price if btc_price and target_price else 0
        
        return {
            'has_position': True,
            'side': side,
            'shares': latest.get('shares', 0),
            'cost': round(latest.get('cost', 0), 2),
            'entry_price': latest.get('entry_price', 0.5),
            'target_price': target_price,
            'btc_price': btc_price,
            'winning': winning,
            'diff': round(diff, 2),
            'time_remaining': time_remaining,
            'potential_payout': latest.get('shares', 0)
        }
    
    return {'has_position': False}

def format_recent_trades(trades, limit=10):
    """Format recent completed trades for display"""
    completed = [t for t in trades if t.get('action') == 'CLOSE']
    recent = completed[-limit:][::-1]
    
    formatted = []
    for t in recent:
        ts = t.get('timestamp', 0)
        time_str = datetime.fromtimestamp(ts).strftime('%I:%M %p') if ts else 'N/A'
        
        formatted.append({
            'time': time_str,
            'side': t.get('side', 'UP'),
            'invested': round(t.get('shares', 0) * t.get('entry_price', 0.5), 2),
            'profit': round(t.get('profit', 0), 2),
            'won': t.get('won', False)
        })
    
    return formatted

def build_data():
    """Build complete data object"""
    trades = load_trades()
    state = load_state()
    
    return {
        'updated': datetime.now().isoformat(),
        'timestamp': datetime.now().timestamp(),
        'stats': calculate_stats(trades),
        'position': get_current_position(trades, state),
        'trades': format_recent_trades(trades),
        'bot_status': state.get('status', 'running')
    }

def push_to_firebase(data):
    """Push data to Firebase Realtime Database"""
    if not FIREBASE_URL:
        print("No FIREBASE_URL configured")
        return False
    
    try:
        url = f"{FIREBASE_URL}/dashboard.json"
        response = requests.put(url, json=data)
        if response.status_code == 200:
            print(f"Pushed to Firebase: {data['stats']}")
            return True
        else:
            print(f"Firebase error: {response.status_code}")
            return False
    except Exception as e:
        print(f"Firebase error: {e}")
        return False

def export_local(data):
    """Export to local JSON file"""
    with open('public/data.json', 'w') as f:
        json.dump(data, f, indent=2)
    print(f"Exported to public/data.json")

def sync():
    """Main sync function"""
    data = build_data()
    
    # Always export locally
    export_local(data)
    
    # Push to Firebase if configured
    if FIREBASE_URL:
        push_to_firebase(data)
    
    return data

if __name__ == '__main__':
    data = sync()
    print(f"Stats: {data['stats']}")
    print(f"Position: {data['position']}")
