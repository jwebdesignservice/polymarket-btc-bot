# Polymarket Bot Setup Guide

Complete guide to connecting your Polymarket account and running the bot.

---

## Part 1: Get a Polymarket API Key

### Step 1: Create Polymarket Account
1. Go to https://polymarket.com
2. Sign up / log in

### Step 2: Generate API Key
1. Navigate to **Settings** → **API**
2. Click **Create API Key**
3. Save the following (you'll need them):
   - **API Key** (long string)
   - **API Secret** (password)
   - **Proxy Wallet Address** (0x... address)

### Step 3: Fund Your Account
1. Deposit USDC to your Polymarket account
2. Recommended starting balance: $100-500 for testing

---

## Part 2: Configure the Bot

### 1. Edit `.env` file

Open `polymarket-bot/.env` in a text editor and fill in:

```env
# Paste your API key here
POLYMARKET_API_KEY=your_api_key_here

# Paste your proxy wallet address
PROXY_WALLET_ADDRESS=0x...

# Start in paper trade mode (no real money)
TRADING_MODE=paper

# Bot parameters (defaults are good for testing)
BOT_SHARES=10
BOT_MOVE=0.15
BOT_SUM=0.95
BOT_WINDOW_MIN=2.0
```

**IMPORTANT:** The `.env` file is already in `.gitignore` — never commit it to git!

---

## Part 3: Run the Dashboard

### Start the dashboard:

```bash
cd dashboard
py api.py
```

Or double-click: `dashboard/start.bat`

### Open in browser:

👉 **http://localhost:5000**

You should now see:
- ✅ **Account Status** panel showing "Connected" if API key is configured
- ✅ **Paper Trade** button (yellow) at the top
- ✅ Your USDC balance
- ✅ Bot stats and trade history

---

## Part 4: Using the Dashboard

### Paper Trade Mode (Safe Testing)
- **Yellow button** = Paper trade mode
- Bot simulates trades but doesn't place real orders
- Use this to validate the strategy first
- All trades logged to `logs/trades.jsonl`

### Live Trading Mode (Real Money)
- Click the **Paper Trade** button to toggle to **Live Trading**
- Button turns **green** and glows
- Bot will place real orders on Polymarket
- **⚠️ Only switch to live mode after successful paper trading!**

### Dashboard Features
- **Auto-refresh:** Updates every 3 seconds
- **Real-time P&L:** Color-coded (green = profit, red = loss)
- **Trade history:** Last 10 trades with timestamps
- **Status indicator:** Pulsing green dot when bot is actively trading
- **Current market:** Shows the BTC Up/Down round being watched

---

## Part 5: Running the Bot

### Option 1: Paper Trade with Historical Data (Recommended First)

Test the strategy without waiting for live markets:

```bash
cd backtest
py replay_simulator.py
```

This will:
- Use the 200 rounds of historical data already downloaded
- Simulate the strategy tick-by-tick
- Update the dashboard in real-time
- Show you exactly how the bot would perform

### Option 2: Wait for Live Markets

BTC Up/Down 15-minute markets run periodically. The bot will:
- Auto-scan for active markets every 60 seconds
- Start watching when a new round begins
- Monitor the first `windowMin` minutes (default 2)
- Place Leg 1 when a 15% drop is detected
- Place Leg 2 when the arbitrage condition is met

To run the live bot:

```bash
py main.py
```

---

## Part 6: Understanding the Strategy

### How It Works

1. **Watch Phase** (first 2 minutes of each 15-min round)
   - Monitor order books for UP and DOWN tokens
   - Detect if either drops ≥15% within 3 seconds

2. **Leg 1 Trigger**
   - Buy the dumped side at ask price
   - Now holding one side of the market

3. **Leg 2 Wait**
   - Wait for: `leg1_entry + opposite_ask ≤ 0.95`
   - This guarantees 5% profit when both legs fill

4. **Profit Lock**
   - Buy opposite side
   - Guaranteed profit = `1.0 - (leg1_entry + leg2_entry)`
   - Typically 4-6% per successful trade

### Parameters (in `.env`)

- **BOT_SHARES** (default 10): Number of shares per trade
- **BOT_MOVE** (default 0.15): 15% drop threshold for Leg 1
- **BOT_SUM** (default 0.95): Max combined price for Leg 2 (5% profit minimum)
- **BOT_WINDOW_MIN** (default 2.0): Only watch first 2 minutes of each round

---

## Part 7: Market Availability

### Current Status
- **15-minute** BTC Up/Down markets (`btc-updown-15m-*`)
- **4-hour** BTC Up/Down markets (`btc-updown-4h-*`)
- **No 5-minute** markets currently available

### Market Schedule
BTC Up/Down markets typically run during US market hours (afternoons/evenings ET).

To check for active markets:
```bash
py -c "import requests; r=requests.get('https://clob.polymarket.com/markets',params={'active':'true','limit':100}); btc=[m for m in r.json()['data'] if 'btc-updown' in m.get('market_slug','')]; print(f'{len(btc)} active BTC markets')"
```

---

## Troubleshooting

### "Account Status: Not Connected"
- Check your API key in `.env`
- Make sure there are no extra spaces or quotes
- Restart the dashboard: `Ctrl+C` then `py api.py`

### "No active markets"
- Markets may not be running right now
- Check https://polymarket.com for current BTC Up/Down markets
- Use the simulator with historical data instead

### Dashboard not loading
- Make sure Flask is installed: `py -m pip install flask flask-cors python-dotenv`
- Check the dashboard is running: should see "Running on http://127.0.0.1:5000"
- Try http://127.0.0.1:5000 instead of localhost:5000

### Bot not triggering trades
- Verify paper trade mode is enabled first
- Check `logs/` folder for error messages
- Markets must have sufficient volatility for 15% drops to occur

---

## Security Best Practices

✅ **DO:**
- Keep `.env` file private (never share or commit)
- Start in paper trade mode
- Test thoroughly before live trading
- Use small position sizes initially
- Monitor the dashboard regularly

❌ **DON'T:**
- Share your API key or secret
- Commit `.env` to git
- Trade with money you can't afford to lose
- Run in live mode without paper testing first
- Leave the bot unattended during live trading

---

## Next Steps

1. ✅ Configure API key in `.env`
2. ✅ Start dashboard and verify connection
3. ✅ Run paper trade simulator
4. ✅ Review results and tune parameters
5. ✅ Wait for live markets (or continue paper trading)
6. ⚠️ Switch to live mode only after validation

---

## Support

- Dashboard: http://localhost:5000
- Logs: `polymarket-bot/logs/`
- Config: `polymarket-bot/.env`
- Docs: `polymarket-bot/dashboard/README.md`

Good luck! 🚀
