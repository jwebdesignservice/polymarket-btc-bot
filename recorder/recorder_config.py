"""
recorder_config.py
------------------
Configuration for the live order book recorder.
"""

import os

# WebSocket endpoint
CLOB_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

# REST API for finding active markets
CLOB_API = "https://clob.polymarket.com"

# Where to save recorded data
DATA_DIR = os.path.join(os.path.dirname(__file__), "recordings")

# Only record BTC 5-min Up/Down markets
MARKET_FILTER = "btc-updown-5m-"

# How often to scan for new active markets (seconds)
MARKET_SCAN_INTERVAL = 60

# Recording session settings
MAX_RECORDING_HOURS = 4  # Auto-stop after this many hours
FLUSH_INTERVAL_SEC = 10  # Write buffered ticks to disk this often
