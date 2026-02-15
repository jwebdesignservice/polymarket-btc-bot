"""
Supabase real-time sync for live dashboard
Pushes trade data to Supabase for public viewing
"""
import json
import os
import time
import requests
from datetime import datetime

# Supabase config
SUPABASE_URL = "https://knmiigfwovdxmeyxexqq.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImtubWlpZ2Z3b3ZkeG1leXhleHFxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzExMzI4NTQsImV4cCI6MjA4NjcwODg1NH0.uOZAykf9Ax878UCsdXJIiSw3n7MQ9V0UQGTrJRgn_1c"

STATE_FILE = "position_state.json"
TRADES_FILE = "logs/trades.jsonl"

def load_state():
    """Load current bot state"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}

def load_recent_trades(limit=10):
    """Load recent completed trades"""
    trades = []
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, 'r') as f:
            for line in f:
                if line.strip():
                    try:
                        t = json.loads(line)
                        if t.get('action') == 'CLOSE':
                            trades.append(t)
                    except:
                        pass
    
    # Return most recent, formatted
    recent = trades[-limit:][::-1]
    return [{
        'time': datetime.fromtimestamp(t.get('timestamp', 0)).strftime('%I:%M %p'),
        'side': t.get('side', 'UP'),
        'invested': round(t.get('shares', 0) * t.get('entry_price', 0.5), 2),
        'profit': round(t.get('profit', 0), 2),
        'won': t.get('won', False)
    } for t in recent]

def build_dashboard_data():
    """Build complete dashboard data"""
    state = load_state()
    
    # Stats
    stats = state.get('stats', {})
    
    # Position
    position = {
        'has_position': state.get('has_position', False),
        'side': state.get('side'),
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
        'id': 1,  # Single row, always update id=1
        'updated_at': datetime.now().isoformat(),
        'timestamp': time.time(),
        'stats': stats,
        'position': position,
        'trades': load_recent_trades(),
        'balance': 100 + stats.get('total_profit', 0)
    }

def push_to_supabase(data):
    """Push data to Supabase"""
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=minimal'
    }
    
    # Upsert to dashboard table
    url = f"{SUPABASE_URL}/rest/v1/dashboard"
    
    try:
        # Try upsert (insert or update)
        response = requests.post(
            url,
            headers={**headers, 'Prefer': 'resolution=merge-duplicates'},
            json=data
        )
        
        if response.status_code in [200, 201, 204]:
            return True
        else:
            print(f"Supabase error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"Supabase error: {e}")
        return False

def sync_once():
    """Single sync"""
    data = build_dashboard_data()
    success = push_to_supabase(data)
    return success, data

def sync_loop(interval=5):
    """Continuous sync loop"""
    print(f"Starting Supabase sync (every {interval}s)")
    print(f"URL: {SUPABASE_URL}")
    
    while True:
        try:
            success, data = sync_once()
            
            pos = data['position']
            stats = data['stats']
            
            status = "OK" if success else "FAIL"
            
            if pos['has_position']:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {status} | "
                      f"{pos['side']} | Time: {pos['time_remaining']}s | "
                      f"P&L: ${stats.get('total_profit', 0):.2f}")
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {status} | No position | "
                      f"P&L: ${stats.get('total_profit', 0):.2f}")
            
            time.sleep(interval)
            
        except KeyboardInterrupt:
            print("\nStopping sync...")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(interval)

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'once':
        success, data = sync_once()
        print(f"Sync: {'Success' if success else 'Failed'}")
        print(f"Data: {json.dumps(data, indent=2)}")
    else:
        sync_loop()
