"""
Aggressive Strategy Optimizer
Tests multiple parameter combinations to maximize opportunity capture rate.
"""
import json
import time
from itertools import product

# Aggressive parameter ranges to test
MOVE_THRESHOLDS = [0.05, 0.08, 0.10, 0.12, 0.15]  # Lower = more triggers
SUM_TARGETS = [0.94, 0.95, 0.96, 0.97, 0.98]      # Higher = more Leg2 entries (lower profit)
WINDOW_MINS = [2.0, 2.5, 3.0, 3.5, 4.0]           # Longer = more watching time

def calculate_expected_profit(move_threshold, sum_target, window_min):
    """
    Estimate profitability metrics for given parameters.
    
    Returns:
        dict with trigger_rate, profit_per_trade, expected_hourly
    """
    # Lower threshold = more triggers
    base_trigger_rate = 12  # triggers per hour at 0.15 threshold
    trigger_multiplier = 0.15 / move_threshold  # e.g., 0.08 = 1.875x more triggers
    estimated_triggers_per_hour = base_trigger_rate * trigger_multiplier
    
    # Window affects trigger rate (longer window = more chances)
    window_multiplier = window_min / 2.0  # baseline 2 minutes
    estimated_triggers_per_hour *= window_multiplier
    
    # Profit per successful round (both legs complete = guaranteed hedge)
    guaranteed_profit = 1.0 - sum_target  # e.g., 0.95 = $0.05/share profit
    
    # Leg2 completion rate (higher sum_target = easier to fill Leg2)
    # Estimate: at 0.95, ~70% complete; at 0.98, ~90% complete
    leg2_completion_rate = 0.5 + (sum_target - 0.94) * 10  # rough estimate
    leg2_completion_rate = min(0.95, max(0.50, leg2_completion_rate))
    
    # If Leg2 doesn't complete before round ends, we have directional exposure
    # Leg1 cost when bought during dump (typically 0.30-0.45)
    avg_leg1_cost = 0.35 + (move_threshold * 0.5)  # bigger dumps = cheaper entry
    
    # Win rate for unhedged Leg1 positions (bought during dump)
    # Dumps may be informed, so win rate < 50%
    leg1_win_rate = 0.45  # conservative estimate
    
    # Expected value for failed hedge scenarios
    # If wins: profit = 1.00 - avg_leg1_cost
    # If loses: loss = avg_leg1_cost
    ev_failed_hedge = (leg1_win_rate * (1.0 - avg_leg1_cost)) + ((1 - leg1_win_rate) * (-avg_leg1_cost))
    
    # Combined expected value per trigger
    ev_per_trigger = (guaranteed_profit * leg2_completion_rate) + (ev_failed_hedge * (1 - leg2_completion_rate))
    
    # Hourly expected profit (assuming 10 shares per trade)
    shares = 10
    expected_hourly = ev_per_trigger * estimated_triggers_per_hour * shares
    
    return {
        'move_threshold': move_threshold,
        'sum_target': sum_target,
        'window_min': window_min,
        'triggers_per_hour': round(estimated_triggers_per_hour, 2),
        'profit_per_trade': round(guaranteed_profit * shares, 3),
        'leg2_completion_rate': round(leg2_completion_rate, 3),
        'ev_per_trigger': round(ev_per_trigger, 4),
        'expected_hourly_profit': round(expected_hourly, 2),
        'expected_daily_profit': round(expected_hourly * 24, 2)
    }

def main():
    print("=" * 80)
    print("AGGRESSIVE STRATEGY OPTIMIZER")
    print("=" * 80)
    print(f"\nTesting {len(MOVE_THRESHOLDS)} x {len(SUM_TARGETS)} x {len(WINDOW_MINS)} = {len(MOVE_THRESHOLDS) * len(SUM_TARGETS) * len(WINDOW_MINS)} combinations...")
    print()
    
    results = []
    
    for move, sum_t, window in product(MOVE_THRESHOLDS, SUM_TARGETS, WINDOW_MINS):
        result = calculate_expected_profit(move, sum_t, window)
        results.append(result)
    
    # Sort by expected hourly profit (descending)
    results.sort(key=lambda x: x['expected_hourly_profit'], reverse=True)
    
    # Show top 10
    print("\nTOP 10 MOST PROFITABLE PARAMETER SETS:")
    print("-" * 80)
    print(f"{'Rank':<5} {'Move%':<8} {'Sum':<7} {'Window':<8} {'Trig/Hr':<10} {'EV/Trig':<10} {'$/Hr':<10} {'$/Day':<10}")
    print("-" * 80)
    
    for i, r in enumerate(results[:10], 1):
        print(f"{i:<5} {r['move_threshold']:<8.2f} {r['sum_target']:<7.2f} {r['window_min']:<8.1f} "
              f"{r['triggers_per_hour']:<10.1f} ${r['ev_per_trigger']:<9.3f} ${r['expected_hourly_profit']:<9.2f} ${r['expected_daily_profit']:<9.2f}")
    
    # Show bottom 5 (worst performers)
    print("\n\nWORST 5 PARAMETER SETS (for comparison):")
    print("-" * 80)
    for i, r in enumerate(results[-5:], len(results)-4):
        print(f"{i:<5} {r['move_threshold']:<8.2f} {r['sum_target']:<7.2f} {r['window_min']:<8.1f} "
              f"{r['triggers_per_hour']:<10.1f} ${r['ev_per_trigger']:<9.3f} ${r['expected_hourly_profit']:<9.2f} ${r['expected_daily_profit']:<9.2f}")
    
    # Save full results
    output_file = "optimization_results.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n\nFull results saved to: {output_file}")
    
    # Recommended settings
    best = results[0]
    print("\n" + "=" * 80)
    print("RECOMMENDED SETTINGS (MOST AGGRESSIVE & PROFITABLE):")
    print("=" * 80)
    print(f"MOVE_THRESHOLD = {best['move_threshold']}")
    print(f"SUM_TARGET = {best['sum_target']}")
    print(f"WINDOW_MIN = {best['window_min']}")
    print()
    print(f"Expected Performance:")
    print(f"  - Triggers per hour: {best['triggers_per_hour']}")
    print(f"  - Profit per completed trade: ${best['profit_per_trade']}")
    print(f"  - Leg2 completion rate: {best['leg2_completion_rate'] * 100:.1f}%")
    print(f"  - Expected hourly profit: ${best['expected_hourly_profit']}")
    print(f"  - Expected daily profit: ${best['expected_daily_profit']}")
    print("=" * 80)
    
    return best

if __name__ == "__main__":
    best_params = main()
