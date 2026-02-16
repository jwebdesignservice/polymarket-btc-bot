"""
Live Report Generator - Creates optimization report from trade data
Run this periodically or call generate_report() from other scripts
"""
import json
import os
from datetime import datetime
from collections import defaultdict

TRADES_FILE = "logs/trades.jsonl"
REPORT_FILE = "LIVE_REPORT.md"

def load_trades():
    """Load all trades from JSONL"""
    trades = []
    if not os.path.exists(TRADES_FILE):
        return trades
    
    with open(TRADES_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    trades.append(json.loads(line))
                except:
                    pass
    return trades

def analyze_trades(trades):
    """Analyze trades for optimization insights"""
    # Filter to only CLOSE trades (completed with outcome)
    closes = [t for t in trades if t.get('action') == 'CLOSE']
    
    if not closes:
        return None
    
    stats = {
        'total_trades': len(closes),
        'wins': 0,
        'losses': 0,
        'total_profit': 0,
        'by_side': {'UP': {'wins': 0, 'losses': 0, 'profit': 0}, 
                    'DOWN': {'wins': 0, 'losses': 0, 'profit': 0}},
        'by_size': {'small': {'wins': 0, 'losses': 0, 'profit': 0, 'count': 0},  # 2 shares
                    'large': {'wins': 0, 'losses': 0, 'profit': 0, 'count': 0}}, # 15 shares
        'by_entry_price': defaultdict(lambda: {'wins': 0, 'losses': 0, 'profit': 0, 'count': 0}),
        'recent_trades': [],
        'streak': {'current': 0, 'type': None},
        'hourly': defaultdict(lambda: {'wins': 0, 'losses': 0, 'profit': 0})
    }
    
    # Analyze each trade
    for t in closes:
        side = t.get('side', 'UNKNOWN')
        won = t.get('won', False)
        profit = t.get('profit', 0)
        shares = t.get('shares', 0)
        entry_price = t.get('entry_price', 0)
        timestamp = t.get('timestamp', 0)
        
        # Overall stats
        stats['total_profit'] += profit
        if won:
            stats['wins'] += 1
        else:
            stats['losses'] += 1
        
        # By side
        if side in stats['by_side']:
            if won:
                stats['by_side'][side]['wins'] += 1
            else:
                stats['by_side'][side]['losses'] += 1
            stats['by_side'][side]['profit'] += profit
        
        # By size
        size_key = 'large' if shares >= 10 else 'small'
        stats['by_size'][size_key]['count'] += 1
        stats['by_size'][size_key]['profit'] += profit
        if won:
            stats['by_size'][size_key]['wins'] += 1
        else:
            stats['by_size'][size_key]['losses'] += 1
        
        # By entry price (bucketed)
        price_bucket = f"{int(entry_price * 10) / 10:.1f}"
        stats['by_entry_price'][price_bucket]['count'] += 1
        stats['by_entry_price'][price_bucket]['profit'] += profit
        if won:
            stats['by_entry_price'][price_bucket]['wins'] += 1
        else:
            stats['by_entry_price'][price_bucket]['losses'] += 1
        
        # By hour
        if timestamp > 1700000000:  # Valid recent timestamp
            hour = datetime.fromtimestamp(timestamp).strftime("%H:00")
            stats['hourly'][hour]['profit'] += profit
            if won:
                stats['hourly'][hour]['wins'] += 1
            else:
                stats['hourly'][hour]['losses'] += 1
        
        # Recent trades (last 10)
        stats['recent_trades'].append({
            'time': datetime.fromtimestamp(timestamp).strftime("%H:%M") if timestamp > 1700000000 else "?",
            'side': side,
            'shares': shares,
            'entry': entry_price,
            'won': won,
            'profit': profit
        })
    
    stats['recent_trades'] = stats['recent_trades'][-10:]
    
    # Calculate streak
    for t in reversed(closes):
        won = t.get('won', False)
        if stats['streak']['type'] is None:
            stats['streak']['type'] = 'W' if won else 'L'
            stats['streak']['current'] = 1
        elif (won and stats['streak']['type'] == 'W') or (not won and stats['streak']['type'] == 'L'):
            stats['streak']['current'] += 1
        else:
            break
    
    return stats

def generate_report():
    """Generate the markdown report"""
    trades = load_trades()
    stats = analyze_trades(trades)
    
    if not stats:
        report = "# Live Trading Report\n\nNo completed trades yet.\n"
    else:
        win_rate = stats['wins'] / stats['total_trades'] * 100 if stats['total_trades'] > 0 else 0
        
        # Build report
        report = f"""# 📊 Live Trading Report
*Auto-updated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*

## Summary
| Metric | Value |
|--------|-------|
| Total Trades | {stats['total_trades']} |
| Win Rate | {win_rate:.1f}% ({stats['wins']}W / {stats['losses']}L) |
| Total P&L | ${stats['total_profit']:+.2f} |
| Current Streak | {stats['streak']['current']}{stats['streak']['type']} |

## 📈 What's Working

### By Side
| Side | Win Rate | Trades | P&L |
|------|----------|--------|-----|
"""
        for side in ['DOWN', 'UP']:
            s = stats['by_side'][side]
            total = s['wins'] + s['losses']
            wr = s['wins'] / total * 100 if total > 0 else 0
            emoji = "✅" if wr >= 60 else "⚠️" if wr >= 50 else "❌"
            report += f"| {side} {emoji} | {wr:.0f}% | {total} | ${s['profit']:+.2f} |\n"
        
        report += """
### By Position Size
| Size | Win Rate | Trades | P&L | Avg P&L/Trade |
|------|----------|--------|-----|---------------|
"""
        for size, label in [('large', 'Large (15)'), ('small', 'Small (2)')]:
            s = stats['by_size'][size]
            total = s['count']
            wr = s['wins'] / total * 100 if total > 0 else 0
            avg = s['profit'] / total if total > 0 else 0
            emoji = "✅" if wr >= 60 else "⚠️" if wr >= 50 else "❌"
            report += f"| {label} {emoji} | {wr:.0f}% | {total} | ${s['profit']:+.2f} | ${avg:+.2f} |\n"
        
        report += """
### By Entry Price
| Price | Win Rate | Trades | P&L |
|-------|----------|--------|-----|
"""
        for price in sorted(stats['by_entry_price'].keys()):
            s = stats['by_entry_price'][price]
            total = s['count']
            wr = s['wins'] / total * 100 if total > 0 else 0
            emoji = "✅" if wr >= 60 else "⚠️" if wr >= 50 else "❌"
            report += f"| {price} {emoji} | {wr:.0f}% | {total} | ${s['profit']:+.2f} |\n"
        
        if stats['hourly']:
            report += """
### By Hour (GMT)
| Hour | Win Rate | Trades | P&L |
|------|----------|--------|-----|
"""
            for hour in sorted(stats['hourly'].keys()):
                s = stats['hourly'][hour]
                total = s['wins'] + s['losses']
                wr = s['wins'] / total * 100 if total > 0 else 0
                emoji = "✅" if wr >= 60 else "⚠️" if wr >= 50 else "❌"
                report += f"| {hour} {emoji} | {wr:.0f}% | {total} | ${s['profit']:+.2f} |\n"
        
        report += """
## 🔴 What's NOT Working

"""
        # Find what's failing
        problems = []
        for side in ['UP', 'DOWN']:
            s = stats['by_side'][side]
            total = s['wins'] + s['losses']
            if total > 3:
                wr = s['wins'] / total * 100
                if wr < 50:
                    problems.append(f"- **{side} trades**: {wr:.0f}% win rate (${s['profit']:+.2f})")
        
        for size, label in [('large', 'Large positions'), ('small', 'Small positions')]:
            s = stats['by_size'][size]
            if s['count'] > 3:
                wr = s['wins'] / s['count'] * 100
                if wr < 50:
                    problems.append(f"- **{label}**: {wr:.0f}% win rate (${s['profit']:+.2f})")
        
        if problems:
            report += "\n".join(problems)
        else:
            report += "*No major issues detected yet*"
        
        report += """

## 📋 Recent Trades (Last 10)
| Time | Side | Shares | Entry | Result | P&L |
|------|------|--------|-------|--------|-----|
"""
        for t in reversed(stats['recent_trades']):
            result = "✅ WIN" if t['won'] else "❌ LOSS"
            report += f"| {t['time']} | {t['side']} | {t['shares']} | ${t['entry']:.2f} | {result} | ${t['profit']:+.2f} |\n"
        
        report += """
## 🎯 Optimization Recommendations

"""
        # Generate recommendations based on data
        recs = []
        
        # Check UP vs DOWN
        up = stats['by_side']['UP']
        down = stats['by_side']['DOWN']
        up_total = up['wins'] + up['losses']
        down_total = down['wins'] + down['losses']
        
        if up_total >= 5 and down_total >= 5:
            up_wr = up['wins'] / up_total * 100
            down_wr = down['wins'] / down_total * 100
            if down_wr > up_wr + 15:
                recs.append(f"1. **Increase DOWN bias**: DOWN ({down_wr:.0f}%) significantly outperforms UP ({up_wr:.0f}%)")
            elif up_wr > down_wr + 15:
                recs.append(f"1. **Switch to UP bias**: UP ({up_wr:.0f}%) significantly outperforms DOWN ({down_wr:.0f}%)")
        
        # Check position sizes
        large = stats['by_size']['large']
        small = stats['by_size']['small']
        if large['count'] >= 5 and small['count'] >= 5:
            large_wr = large['wins'] / large['count'] * 100
            small_wr = small['wins'] / small['count'] * 100
            if large_wr > small_wr + 10:
                recs.append(f"2. **Use larger positions more**: Large ({large_wr:.0f}%) beats Small ({small_wr:.0f}%)")
            elif small_wr > large_wr + 10:
                recs.append(f"2. **Use smaller positions**: Small ({small_wr:.0f}%) beats Large ({large_wr:.0f}%)")
        
        # Check entry prices
        best_price = None
        best_wr = 0
        for price, s in stats['by_entry_price'].items():
            if s['count'] >= 3:
                wr = s['wins'] / s['count'] * 100
                if wr > best_wr:
                    best_wr = wr
                    best_price = price
        
        if best_price and best_wr > 60:
            recs.append(f"3. **Target entry price {best_price}**: {best_wr:.0f}% win rate at this price")
        
        if recs:
            report += "\n".join(recs)
        else:
            report += "*Need more data for recommendations (minimum 10 trades per category)*"
        
        report += f"""

---
*Report generated from {stats['total_trades']} completed trades*
*Bot running with v9 momentum strategy + DOWN bias*
"""
    
    # Write report
    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"Report updated: {REPORT_FILE}")
    return report

if __name__ == "__main__":
    report = generate_report()
    # Print without emojis for Windows console compatibility
    print(report.encode('ascii', 'replace').decode('ascii'))
