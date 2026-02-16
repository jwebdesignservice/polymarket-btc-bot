"""
100 Trade Test Runner
- Starts a single bot instance
- Monitors until 100 completed trades
- Reports results
"""
import subprocess
import time
import sys
import os
import json
from datetime import datetime

BOT_SCRIPT = "live_trader_v9.5_momentum.py"
TARGET_TRADES = 100
LOG_FILE = "logs/trades.jsonl"

def count_completed_trades():
    """Count unique completed trades (deduplicated)"""
    if not os.path.exists(LOG_FILE):
        return 0, 0, 0
    
    close_by_min = {}
    with open(LOG_FILE, 'r') as f:
        for line in f:
            if not line.strip():
                continue
            t = json.loads(line)
            if t.get('action') == 'CLOSE':
                minute = datetime.fromtimestamp(t['timestamp']).strftime('%Y-%m-%d %H:%M')
                if minute not in close_by_min:
                    close_by_min[minute] = t
    
    wins = sum(1 for t in close_by_min.values() if t.get('won'))
    losses = len(close_by_min) - wins
    return len(close_by_min), wins, losses

def main():
    print("=" * 60)
    print("100 TRADE TEST - MIN_SHARES=10")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # Clear old log
    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)
    
    # Start bot
    print(f"\nStarting {BOT_SCRIPT}...")
    process = subprocess.Popen(
        [sys.executable, "-u", BOT_SCRIPT],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        universal_newlines=True
    )
    
    last_count = 0
    start_time = time.time()
    
    try:
        while True:
            # Read bot output
            line = process.stdout.readline()
            if line:
                print(line, end='')
            
            # Check trade count every 10 seconds
            if time.time() - start_time > 10:
                total, wins, losses = count_completed_trades()
                
                if total != last_count:
                    elapsed = (time.time() - start_time) / 3600
                    win_rate = (wins / total * 100) if total > 0 else 0
                    profit = (wins - losses) * 5  # Approximate $5 per trade
                    
                    print(f"\n{'='*60}")
                    print(f"PROGRESS: {total}/{TARGET_TRADES} trades")
                    print(f"Record: {wins}W / {losses}L ({win_rate:.1f}%)")
                    print(f"Est. Profit: ${profit:+.2f}")
                    print(f"Time: {elapsed:.1f} hours")
                    print(f"{'='*60}\n")
                    
                    last_count = total
                
                if total >= TARGET_TRADES:
                    print("\n" + "=" * 60)
                    print("🎉 100 TRADE TEST COMPLETE!")
                    print(f"Final: {wins}W / {losses}L ({win_rate:.1f}%)")
                    print(f"Profit: ${profit:+.2f}")
                    print("=" * 60)
                    process.terminate()
                    break
                
                start_time = time.time()
            
            # Check if process died
            if process.poll() is not None:
                print(f"\nBot exited with code {process.returncode}")
                print("Restarting in 5 seconds...")
                time.sleep(5)
                process = subprocess.Popen(
                    [sys.executable, "-u", BOT_SCRIPT],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=1,
                    universal_newlines=True
                )
            
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        print("\nTest interrupted!")
        process.terminate()
        total, wins, losses = count_completed_trades()
        win_rate = (wins / total * 100) if total > 0 else 0
        print(f"Partial results: {total} trades | {wins}W / {losses}L ({win_rate:.1f}%)")

if __name__ == "__main__":
    main()
