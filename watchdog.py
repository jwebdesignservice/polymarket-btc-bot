"""
Watchdog - Keeps the bot running 24/7
Auto-restarts on crash, logs all restarts
"""
import subprocess
import time
import sys
import os
from datetime import datetime

BOT_SCRIPT = "live_trader_v9.5_momentum.py"
LOG_FILE = "logs/watchdog.log"
MAX_RESTARTS_PER_HOUR = 10  # Circuit breaker

os.makedirs("logs", exist_ok=True)

def log(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def run_bot():
    """Run the bot and return exit code"""
    log(f"Starting {BOT_SCRIPT}...")
    process = subprocess.Popen(
        [sys.executable, "-u", BOT_SCRIPT],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        universal_newlines=True
    )
    
    # Stream output in real-time
    for line in process.stdout:
        print(line, end='')
    
    process.wait()
    return process.returncode

def main():
    log("=" * 60)
    log("WATCHDOG STARTED - 8 HOUR DATA COLLECTION MODE")
    log("=" * 60)
    
    restart_times = []
    start_time = time.time()
    end_time = start_time + (8 * 60 * 60)  # 8 hours from now
    
    while time.time() < end_time:
        # Circuit breaker - too many restarts
        hour_ago = time.time() - 3600
        restart_times = [t for t in restart_times if t > hour_ago]
        
        if len(restart_times) >= MAX_RESTARTS_PER_HOUR:
            log(f"CIRCUIT BREAKER: {MAX_RESTARTS_PER_HOUR} restarts in 1 hour. Pausing 10 min...")
            time.sleep(600)
            restart_times = []
        
        # Run the bot
        exit_code = run_bot()
        restart_times.append(time.time())
        
        remaining = (end_time - time.time()) / 3600
        log(f"Bot exited with code {exit_code}. {remaining:.1f} hours remaining.")
        
        if remaining > 0:
            log("Restarting in 5 seconds...")
            time.sleep(5)
    
    log("=" * 60)
    log("8 HOUR DATA COLLECTION COMPLETE")
    log("=" * 60)

if __name__ == "__main__":
    main()
