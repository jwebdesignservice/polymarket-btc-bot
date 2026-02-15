# Polymarket Bot Dashboard

**Live, real-time dashboard to track the bot's performance**

Clean, responsive, degen-inspired UI with dark mode and neon accents.

---

## Features

- **Live Status** — Bot state (idle, watching, leg1_filled, error) with pulsing indicator
- **P&L Tracking** — Total profit/loss, win rate, average profit per trade
- **Current Market** — Real-time view of the active BTC Up/Down round being watched
- **Trade History** — Last 10 trades with timestamps, side, profit, and status
- **Auto-Refresh** — Updates every 3 seconds automatically
- **Fully Responsive** — Works on desktop, tablet, and mobile

---

## Quick Start

### 1. Start the dashboard server

```bash
cd dashboard
py api.py
```

Or on Windows, double-click: `start.bat`

### 2. Open in browser

Navigate to: **http://localhost:5000**

---

## How It Works

**Backend (`api.py`):**
- Flask API server
- Reads `bot_state.json` for current status
- Reads `logs/trades.jsonl` for trade history
- Calculates stats (win rate, P&L, etc.)
- Serves JSON endpoints at `/api/*`

**Frontend (`index.html` + `style.css`):**
- Single-page dashboard
- Fetches data from API every 3 seconds
- Color-coded P&L (green = profit, red = loss)
- Pulsing status indicator when bot is active

---

## API Endpoints

- `GET /` — Dashboard HTML
- `GET /api/status` — Bot status (running, idle, etc.)
- `GET /api/stats` — Summary stats (P&L, win rate)
- `GET /api/trades` — Recent trades (last 50)
- `GET /api/markets` — Active markets being watched

---

## Customization

### Colors
Edit `style.css` `:root` section to change the color scheme:

```css
:root {
    --bg-dark: #0a0a0f;      /* Background */
    --accent: #6366f1;        /* Primary accent */
    --green: #00ff88;         /* Profit color */
    --red: #ff3366;           /* Loss color */
}
```

### Refresh Rate
Edit `index.html` line ~200:

```javascript
updateInterval = setInterval(updateAll, 3000); // Change 3000 to desired ms
```

---

## Production Deployment

For production (VPS), use a real WSGI server instead of Flask's dev server:

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 api:app
```

Or use Waitress (Windows-compatible):

```bash
pip install waitress
waitress-serve --port=5000 api:app
```

---

## File Structure

```
dashboard/
  api.py              <- Flask API server
  index.html          <- Dashboard UI
  style.css           <- Degen-inspired styling
  start.bat           <- Windows launcher
  README.md           <- This file
```

---

## Sample Data

The dashboard currently shows demo trades from `logs/trades.jsonl`. Once the bot runs live, it will automatically populate with real data.

**Bot state file:** `bot_state.json` (at project root)
**Trade log:** `logs/trades.jsonl` (JSONL format, one trade per line)

---

## Notes

- Dashboard runs locally by default (localhost:5000)
- No authentication — assumes trusted local network
- For remote access, add auth middleware or run behind a reverse proxy
- CORS enabled for local development

Enjoy! 🚀
