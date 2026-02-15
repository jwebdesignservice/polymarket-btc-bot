"""
config.py — All parameters and environment loading for the Polymarket bot.
"""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # ── Trading parameters ──────────────────────────────────────────────────
    shares: float = 10.0           # number of shares per leg
    hedge_sum: float = 0.95        # leg1_entry + leg2_ask must be ≤ this
    move_threshold: float = 0.15   # probability drop needed to trigger Leg 1
    window_minutes: float = 2.0    # watch only first N minutes of each round
    drop_window_sec: float = 3.0   # measure drop over this many seconds

    # ── Polymarket endpoints ────────────────────────────────────────────────
    gamma_api: str = "https://gamma-api.polymarket.com"
    clob_api: str = "https://clob.polymarket.com"
    clob_ws: str = "wss://clob.polymarket.com/ws"

    # ── Auth (populated from .env) ──────────────────────────────────────────
    private_key: str = field(default_factory=lambda: os.getenv("PRIVATE_KEY", ""))
    polygon_rpc: str = field(default_factory=lambda: os.getenv("POLYGON_RPC", "https://polygon-rpc.com"))
    wallet_address: str = field(default_factory=lambda: os.getenv("WALLET_ADDRESS", ""))
    api_key: str = field(default_factory=lambda: os.getenv("POLYMARKET_API_KEY", ""))
    api_secret: str = field(default_factory=lambda: os.getenv("POLYMARKET_API_SECRET", ""))
    api_passphrase: str = field(default_factory=lambda: os.getenv("POLYMARKET_API_PASSPHRASE", ""))

    # ── Logging ─────────────────────────────────────────────────────────────
    log_file: str = field(default_factory=lambda: os.getenv("LOG_FILE", "bot.log"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    # ── WebSocket ────────────────────────────────────────────────────────────
    ws_reconnect_delay: float = 2.0   # seconds between reconnect attempts
    ws_max_reconnects: int = 0        # 0 = unlimited

    # ── Market filter ────────────────────────────────────────────────────────
    market_search_tag: str = "bitcoin"
    market_name_keywords: list = field(default_factory=lambda: ["btc", "bitcoin", "up", "down", "5-min", "5min", "5 min"])

    def update_from_args(self, shares=None, hedge_sum=None, move_threshold=None, window_minutes=None):
        if shares is not None:
            self.shares = float(shares)
        if hedge_sum is not None:
            self.hedge_sum = float(hedge_sum)
        if move_threshold is not None:
            self.move_threshold = float(move_threshold)
        if window_minutes is not None:
            self.window_minutes = float(window_minutes)


# Singleton
config = Config()
