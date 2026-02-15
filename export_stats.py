"""
Export trade stats to JSON for public dashboard
Run this periodically to update the public view
"""
import json
import os
from datetime import datetime

TRADES_FILE = "logs/trades.jsonl"
OUTPUT_FILE = "public/data.json"
STARTING_BALANCE = 100.0

def load_trades():
    """Load all trades from JSONL file"""
    trades = []
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, 'r') as f:
            for line in f:
                if line.strip():
                    trades.append(json.loads(line))
    return trades

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
        'overall_balance': round(STARTING_BALANCE + total_profit, 2)
    }

def get_current_position(trades):
    """Get the current open position if any"""
    # Find the last ENTER that doesn't have a corresponding CLOSE
    open_trades = [t for t in trades if t.get('action') == 'ENTER' and t.get('status') == 'open']
    
    if open_trades:
        latest = open_trades[-1]
        return {
            'has_position': True,
            'side': latest.get('side', 'UP'),
            'shares': latest.get('shares', 0),
            'cost': latest.get('cost', 0),
            'entry_price': latest.get('entry_price', 0.5),
            'target_price': latest.get('target_price', 0)
        }
    
    return {'has_position': False}

def format_recent_trades(trades, limit=10):
    """Format recent completed trades for display"""
    completed = [t for t in trades if t.get('action') == 'CLOSE']
    recent = completed[-limit:][::-1]  # Most recent first
    
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

def export_data():
    """Export all data to JSON file"""
    trades = load_trades()
    
    data = {
        'updated': datetime.now().isoformat(),
        'stats': calculate_stats(trades),
        'position': get_current_position(trades),
        'trades': format_recent_trades(trades)
    }
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"Exported stats to {OUTPUT_FILE}")
    print(f"Stats: {data['stats']}")
    return data

if __name__ == '__main__':
    export_data()
