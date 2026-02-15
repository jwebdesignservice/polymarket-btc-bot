# 🤖 Polymarket BTC Up/Down Trading Bot

Automated trading bot for Polymarket's BTC 5-minute Up/Down prediction markets.

## Features

- 📈 **Momentum Strategy** - Picks UP or DOWN based on BTC price movement
- ⚡ **Trades Every 5 Minutes** - 24/7 automated trading
- 📊 **Live Dashboard** - Real-time position and P&L tracking
- 🎯 **Dynamic Position Sizing** - Adjusts size based on confidence
- 💰 **Paper Trading Mode** - Test without risking real money

## Live Dashboard

View the live dashboard: [polymarket-bot.vercel.app](https://polymarket-bot.vercel.app)

*Dashboard is view-only for public visitors*

## How It Works

1. **Market Discovery** - Bot finds active BTC 5-minute markets
2. **Momentum Analysis** - Tracks BTC price vs target price
3. **Signal Generation** - Multiple signals vote on direction
4. **Position Entry** - Buys UP or DOWN based on signals
5. **Hold to Payout** - Collects $1 per share if correct

## Strategy

```
Round starts → Target price set
Wait 20 seconds for momentum
If BTC > Target + $30 → BUY UP
If BTC < Target - $30 → BUY DOWN
Hold until round ends
Collect payout if correct
```

## Tech Stack

- Python 3.x
- Binance WebSocket (real-time BTC prices)
- Polymarket CLOB API
- Chart.js for visualization
- Flask for dashboard API

## Disclaimer

This bot is for educational purposes. Trading involves risk. Only trade with money you can afford to lose.

## License

MIT
