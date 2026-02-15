"""
api.py
------
Flask API backend for the bot dashboard.

Endpoints:
  GET /api/status      - Bot status (running, idle, error)
  GET /api/trades      - Recent trades
  GET /api/stats       - Summary stats (P&L, win rate, etc.)
  GET /api/markets     - Active markets being watched
"""

from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
import json
import os
import sys
import asyncio
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import live_trader

app = Flask(__name__)
CORS(app)

# Point to the main bot directory
BOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOGS_DIR = os.path.join(BOT_DIR, "logs")
STATE_FILE = os.path.join(BOT_DIR, "bot_state.json")


def read_state():
    """Read current bot state from disk."""
    # Check if bot is running by looking for current_market.json
    current_market_file = os.path.join(BOT_DIR, "current_market.json")
    
    if os.path.exists(current_market_file):
        try:
            with open(current_market_file, 'r') as f:
                market_data = json.load(f)
            
            # Bot is running autonomously
            return {
                "status": "running",
                "mode": "autonomous",
                "shares": 10,
                "current_round": market_data.get("title", "Unknown"),
                "market_slug": market_data.get("slug", ""),
                "closed": market_data.get("closed", False),
                "leg1": None,
                "leg2": None,
                "uptime": 0
            }
        except:
            pass
    
    if not os.path.exists(STATE_FILE):
        return {
            "status": "idle",
            "mode": "autonomous",
            "shares": 10,
            "current_round": None,
            "leg1": None,
            "leg2": None,
            "uptime": 0
        }
    
    with open(STATE_FILE, encoding="utf-8") as f:
        return json.load(f)


def read_trades():
    """Read trade history from logs."""
    trades_file = os.path.join(LOGS_DIR, "trades.jsonl")
    if not os.path.exists(trades_file):
        return []
    
    trades = []
    with open(trades_file, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                trades.append(json.loads(line))
    
    # Return most recent first
    return sorted(trades, key=lambda t: t.get("timestamp", 0), reverse=True)


def calculate_stats(trades):
    """Calculate summary statistics from trade history."""
    if not trades:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_profit": 0.0,
            "best_trade": 0.0,
            "worst_trade": 0.0
        }
    
    completed = [t for t in trades if t.get("status") == "completed"]
    wins = [t for t in completed if t.get("profit", 0) > 0]
    losses = [t for t in completed if t.get("profit", 0) <= 0]
    
    profits = [t.get("profit", 0) for t in completed]
    total_pnl = sum(profits)
    
    return {
        "total_trades": len(completed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(completed) if completed else 0.0,
        "total_pnl": total_pnl,
        "avg_profit": total_pnl / len(completed) if completed else 0.0,
        "best_trade": max(profits) if profits else 0.0,
        "worst_trade": min(profits) if profits else 0.0
    }


@app.route("/")
def index():
    """Serve the dashboard HTML."""
    return send_from_directory(os.path.dirname(__file__), "index.html")


@app.route("/style.css")
def styles():
    """Serve CSS."""
    return send_from_directory(os.path.dirname(__file__), "style.css")


@app.route("/api/status")
def status():
    """Get current bot status."""
    state = read_state()
    return jsonify(state)


@app.route("/api/trades")
def trades():
    """Get recent trades (last 50)."""
    all_trades = read_trades()
    return jsonify(all_trades[:50])


@app.route("/api/stats")
def stats():
    """Get summary statistics."""
    trades = read_trades()
    return jsonify(calculate_stats(trades))


@app.route("/api/markets")
def markets():
    """Get active markets being watched."""
    try:
        state = read_state()
        current_round = state.get("current_round")
        
        if not current_round:
            return jsonify([])
        
        # Handle both old format (object) and new format (string)
        if isinstance(current_round, str):
            # New format: current_round is just the title string
            return jsonify([{
                "question": current_round,
                "end_time": None,
                "up_price": None,
                "down_price": None,
                "watching": state.get("status") in ["running", "monitoring"]
            }])
        else:
            # Old format: current_round is an object
            return jsonify([{
                "question": current_round.get("question", "Unknown"),
                "end_time": current_round.get("end_time"),
                "up_price": current_round.get("up_price"),
                "down_price": current_round.get("down_price"),
                "watching": state.get("status") == "watching"
            }])
    except Exception as e:
        # Return empty array instead of error
        return jsonify([])


@app.route("/api/account")
def account():
    """Get Polymarket account info with real wallet balance."""
    import sys
    sys.path.insert(0, BOT_DIR)
    
    api_key = os.getenv("POLYMARKET_API_KEY", "")
    private_key = os.getenv("POLYMARKET_PRIVATE_KEY", "")
    mode = os.getenv("TRADING_MODE", "paper")
    
    # Check wallet connection and get real balance
    wallet_address = None
    connected = False
    usdc_balance = 0.0
    matic_balance = 0.0
    paper_balance = 0.0
    
    if private_key:
        try:
            from eth_account import Account
            pk = private_key[2:] if private_key.startswith('0x') else private_key
            wallet = Account.from_key(pk)
            wallet_address = wallet.address
            connected = True
            
            # Get real blockchain balance
            try:
                from wallet_balance import get_balance_sync
                real_balance = get_balance_sync(wallet_address)
                usdc_balance = real_balance.get('usdc_balance', 0.0)
                matic_balance = real_balance.get('matic_balance', 0.0)
            except Exception as e:
                print(f"Balance check error: {e}")
        except:
            pass
    
    # Also track paper trading P&L
    stats_file = os.path.join(BOT_DIR, "position_state.json")
    if os.path.exists(stats_file):
        try:
            with open(stats_file, 'r') as f:
                state = json.load(f)
                stats = state.get('stats', {})
                paper_balance = 100.0 + stats.get('total_profit', 0)
        except:
            paper_balance = 100.0
    else:
        paper_balance = 100.0
    
    # Use real balance if available, otherwise paper balance
    display_balance = usdc_balance if usdc_balance > 0 else paper_balance
    
    return jsonify({
        "connected": connected,
        "balance": display_balance,
        "usdc_balance": usdc_balance,
        "matic_balance": matic_balance,
        "paper_balance": paper_balance,
        "wallet_address": wallet_address,
        "api_key_configured": bool(api_key),
        "mode": mode
    })


@app.route("/api/probability-history")
def probability_history():
    """Get probability history for live chart."""
    history_file = os.path.join(BOT_DIR, "probability_history.json")
    
    if not os.path.exists(history_file):
        return jsonify([])
    
    try:
        with open(history_file, 'r') as f:
            history = json.load(f)
        return jsonify(history)
    except:
        return jsonify([])


@app.route("/api/position")
def position():
    """Get current live position with real-time P&L."""
    position_file = os.path.join(BOT_DIR, "position_state.json")
    
    if not os.path.exists(position_file):
        return jsonify({
            "has_position": False,
            "side": None,
            "shares": 0,
            "cost": 0,
            "live_pnl": 0,
            "winning": False,
            "time_remaining": 0,
            "stats": {}
        })
    
    try:
        with open(position_file, 'r') as f:
            state = json.load(f)
        return jsonify(state)
    except:
        return jsonify({
            "has_position": False,
            "side": None,
            "shares": 0,
            "cost": 0,
            "live_pnl": 0,
            "winning": False,
            "time_remaining": 0,
            "stats": {}
        })


@app.route("/api/set-mode", methods=["POST"])
def set_mode():
    """Toggle trading mode between paper and live."""
    data = request.get_json()
    new_mode = data.get("mode", "paper")
    
    if new_mode not in ["paper", "live"]:
        return jsonify({"error": "Invalid mode"}), 400
    
    # Update .env file
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    
    # Read existing .env
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            lines = f.readlines()
    else:
        lines = []
    
    # Update or add TRADING_MODE line
    mode_found = False
    for i, line in enumerate(lines):
        if line.startswith("TRADING_MODE="):
            lines[i] = f"TRADING_MODE={new_mode}\n"
            mode_found = True
            break
    
    if not mode_found:
        lines.append(f"TRADING_MODE={new_mode}\n")
    
    # Write back
    with open(env_path, "w") as f:
        f.writelines(lines)
    
    # Update environment
    os.environ["TRADING_MODE"] = new_mode
    
    return jsonify({"mode": new_mode})


@app.route("/api/start-trading", methods=["POST"])
def start_trading_endpoint():
    """Start the live trader on a specific market."""
    import requests as req
    
    data = request.get_json()
    market_input = data.get("market", "").strip()
    
    if not market_input:
        return jsonify({"error": "Please enter a market URL or condition ID"}), 400
    
    # Extract slug or condition ID from URL
    if "polymarket.com" in market_input:
        # Extract slug from URL: /event/btc-updown-5m-1771080900
        slug = market_input.split("/")[-1].split("?")[0]
        
        print(f"[api] Extracted slug: {slug}")
        
        # Search CLOB for this market by slug
        # Check multiple pages since markets may be at different offsets
        condition_id = None
        
        for offset in [0, 1000, 2000, 440000, 450000, 460000]:
            import base64
            cursor = base64.b64encode(str(offset).encode()).decode() if offset > 0 else ''
            
            params = {'limit': 1000}
            if cursor:
                params['next_cursor'] = cursor
            
            r = req.get('https://clob.polymarket.com/markets', params=params, timeout=10)
            
            if r.status_code != 200:
                continue
            
            markets = r.json().get('data', [])
            
            # Try exact match first
            exact = [m for m in markets if m.get('market_slug') == slug]
            if exact:
                condition_id = exact[0]['condition_id']
                print(f"[api] Found exact match: {condition_id}")
                break
            
            # Try partial match (slug contains the event ID)
            partial = [m for m in markets if slug in m.get('market_slug', '')]
            if partial:
                condition_id = partial[0]['condition_id']
                print(f"[api] Found partial match: {condition_id}")
                break
        
        if not condition_id:
            return jsonify({
                "error": f"Market '{slug}' not found in CLOB API. It may be closed or not yet started.",
                "suggestion": "Try a market that is currently accepting orders"
            }), 404
    
    elif market_input.startswith("0x"):
        # Direct condition ID
        condition_id = market_input
    else:
        # Assume it's a slug
        return jsonify({
            "error": "Invalid input. Please paste a full Polymarket URL or a condition ID starting with 0x"
        }), 400
    
    # Start trading in a background thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        result = loop.run_until_complete(live_trader.start_trading(condition_id))
        
        if "error" in result:
            return jsonify(result), 400
        
        return jsonify({"success": True, "market": condition_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/stop-trading", methods=["POST"])
def stop_trading_endpoint():
    """Stop the live trader."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(live_trader.stop_trading())
    
    return jsonify(result)


if __name__ == "__main__":
    print("[dashboard] Starting API server on http://localhost:5000")
    print("[dashboard] Open http://localhost:5000 in your browser")
    app.run(debug=True, port=5000, threaded=True)
