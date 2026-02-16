"""
Validate Skip Decisions
-----------------------
Check if rounds we skipped would have been winners or losers.
This helps us understand if we're being too conservative.
"""
import json
import re
from datetime import datetime
from collections import defaultdict

import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "logs/bot_output.log")
TRADES_FILE = os.path.join(BASE_DIR, "logs/trades.jsonl")
SESSION_START = 1771223280  # Feb 16, 06:28 UTC

def parse_logs():
    """Parse bot logs to extract all rounds and their outcomes"""
    rounds = defaultdict(dict)
    
    with open(LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            # Parse timestamp
            ts_match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
            if not ts_match:
                continue
            ts = datetime.strptime(ts_match.group(1), '%Y-%m-%d %H:%M:%S')
            unix_ts = ts.timestamp()
            
            # Only look at session data
            if unix_ts < SESSION_START:
                continue
            
            # Round key (5-minute slot)
            slot = int(unix_ts // 300) * 300
            
            # Extract data
            if 'Target: $' in line:
                match = re.search(r'Target: \$([\d,\.]+)', line)
                if match:
                    rounds[slot]['target'] = float(match.group(1).replace(',', ''))
            
            if 'Direction:' in line:
                match = re.search(r'Direction: (\w+)', line)
                if match:
                    rounds[slot]['direction'] = match.group(1)
            
            if 'Confidence:' in line:
                match = re.search(r'Confidence: ([\d\.]+)%', line)
                if match:
                    rounds[slot]['confidence'] = float(match.group(1))
            
            if 'BTC at entry:' in line or 'btc_at_entry' in line:
                match = re.search(r'([\d,\.]+)', line)
                if match:
                    rounds[slot]['btc_entry'] = float(match.group(1).replace(',', ''))
            
            if 'SKIPPING' in line:
                rounds[slot]['skipped'] = True
            
            if 'ENTERED' in line or 'shares @' in line:
                rounds[slot]['traded'] = True
            
            if 'WON' in line:
                rounds[slot]['won'] = True
            if 'LOST' in line:
                rounds[slot]['won'] = False
    
    return rounds

def get_traded_rounds():
    """Get rounds where we actually traded from trades.jsonl"""
    traded_slots = set()
    with open(TRADES_FILE, 'r') as f:
        for line in f:
            trade = json.loads(line)
            if trade['timestamp'] >= SESSION_START and trade['action'] == 'CLOSE':
                slot = int(trade['timestamp'] // 300) * 300
                traded_slots.add(slot)
    return traded_slots

def main():
    print("=" * 60)
    print("SKIP VALIDATION REPORT")
    print("=" * 60)
    
    rounds = parse_logs()
    traded_slots = get_traded_rounds()
    
    # Categorize rounds
    traded = []
    skipped = []
    
    for slot, data in sorted(rounds.items()):
        if slot in traded_slots:
            data['slot'] = slot
            traded.append(data)
        elif data.get('direction') and data.get('target'):
            data['slot'] = slot
            skipped.append(data)
    
    print(f"\nTotal Rounds Analyzed: {len(rounds)}")
    print(f"  - Traded: {len(traded)}")
    print(f"  - Skipped: {len(skipped)}")
    
    # Analyze traded rounds
    traded_wins = sum(1 for r in traded if r.get('won') == True)
    traded_losses = sum(1 for r in traded if r.get('won') == False)
    
    print(f"\n📊 TRADED ROUNDS:")
    print(f"  Wins: {traded_wins}, Losses: {traded_losses}")
    if traded_wins + traded_losses > 0:
        print(f"  Win Rate: {traded_wins/(traded_wins+traded_losses)*100:.1f}%")
    
    # Analyze skipped rounds - estimate outcomes
    # Since we skipped, we need to check what would have happened
    # We can estimate based on the DOWN bias (if direction was DOWN, assume win ~77% of time)
    print(f"\n🔍 SKIPPED ROUNDS ANALYSIS:")
    print(f"  Total Skipped: {len(skipped)}")
    
    down_skips = sum(1 for r in skipped if r.get('direction') == 'DOWN')
    up_skips = sum(1 for r in skipped if r.get('direction') == 'UP')
    
    print(f"  - Would have bet DOWN: {down_skips}")
    print(f"  - Would have bet UP: {up_skips}")
    
    # Historical stats: DOWN wins ~77%, UP wins ~50%
    # So skipping UP is smart, skipping DOWN might cost us
    estimated_down_wins = int(down_skips * 0.77)
    estimated_down_losses = down_skips - estimated_down_wins
    estimated_up_wins = int(up_skips * 0.50)
    estimated_up_losses = up_skips - estimated_up_wins
    
    print(f"\n📈 ESTIMATED OUTCOMES (if we had traded skipped rounds):")
    print(f"  DOWN skips: ~{estimated_down_wins} wins, ~{estimated_down_losses} losses (77% WR)")
    print(f"  UP skips:   ~{estimated_up_wins} wins, ~{estimated_up_losses} losses (50% WR)")
    
    total_skip_wins = estimated_down_wins + estimated_up_wins
    total_skip_losses = estimated_down_losses + estimated_up_losses
    
    if len(skipped) > 0:
        skip_wr = total_skip_wins / len(skipped) * 100
        print(f"\n  Total estimated skip WR: ~{skip_wr:.1f}%")
        
        # P&L estimate ($5 profit per win at MIN_SHARES=10)
        skip_pnl = total_skip_wins * 5 - total_skip_losses * 5
        print(f"  Estimated missed P&L: ~${skip_pnl:.2f}")
    
    print("\n" + "=" * 60)
    print("CONCLUSION:")
    if len(skipped) > 0 and skip_wr < 70:
        print("✅ Skipping is CORRECT - estimated skip WR is below our threshold")
    elif len(skipped) > 0:
        print("⚠️  May be too conservative - skipped rounds have decent WR")
    else:
        print("ℹ️  Not enough skip data to analyze")
    print("=" * 60)

if __name__ == "__main__":
    main()
