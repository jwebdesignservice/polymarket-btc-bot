"""
ws_client.py — WebSocket client for real-time order book updates.

Connects to wss://clob.polymarket.com/ws and subscribes to price-change
channels for the UP and DOWN tokens of the current round.

Emits callbacks whenever mid-prices update.
"""

import asyncio
import json
import time
from typing import Callable, Optional, Awaitable
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from config import config
from logger import get_logger

log = get_logger("ws_client")

# Type alias: async callback(token_id, price, timestamp_monotonic)
PriceCallback = Callable[[str, float, float], Awaitable[None]]


class ClobWebSocket:
    """
    Manages a persistent WebSocket connection to the Polymarket CLOB.
    Reconnects automatically on drops.
    """

    def __init__(self, on_price_update: PriceCallback):
        self._on_price_update = on_price_update
        self._subscribed_tokens: set[str] = set()
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._reconnect_delay = config.ws_reconnect_delay
        self._reconnect_count = 0

        # token_id → latest mid-price
        self.prices: dict[str, float] = {}

    # ── Public API ──────────────────────────────────────────────────────────

    async def start(self):
        """Start the WebSocket loop in the current event loop."""
        self._running = True
        await self._run_loop()

    async def stop(self):
        self._running = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass

    async def subscribe(self, token_ids: list[str]):
        """Subscribe to price updates for the given token IDs."""
        new_tokens = set(token_ids) - self._subscribed_tokens
        if not new_tokens:
            return
        self._subscribed_tokens.update(new_tokens)
        log.info(f"Subscribing to tokens: {list(new_tokens)}")
        if self._ws and not self._ws.closed:
            await self._send_subscribe(new_tokens)

    async def unsubscribe(self, token_ids: list[str]):
        """Unsubscribe from price updates for the given token IDs."""
        remove = set(token_ids) & self._subscribed_tokens
        if not remove:
            return
        self._subscribed_tokens -= remove
        log.info(f"Unsubscribing from tokens: {list(remove)}")
        if self._ws and not self._ws.closed:
            await self._send_unsubscribe(remove)

    # ── Internal ────────────────────────────────────────────────────────────

    async def _run_loop(self):
        while self._running:
            try:
                log.info(f"Connecting to {config.clob_ws} ...")
                async with websockets.connect(
                    config.clob_ws,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    self._ws = ws
                    self._reconnect_count = 0
                    log.info("WebSocket connected")

                    # Re-subscribe to all tokens on reconnect
                    if self._subscribed_tokens:
                        await self._send_subscribe(self._subscribed_tokens)

                    await self._receive_loop(ws)

            except (ConnectionClosed, WebSocketException) as e:
                log.warning(f"WebSocket disconnected: {e}")
            except Exception as e:
                log.error(f"Unexpected WebSocket error: {e}", exc_info=True)

            if not self._running:
                break

            # Exponential backoff capped at 30s
            delay = min(self._reconnect_delay * (2 ** min(self._reconnect_count, 4)), 30)
            self._reconnect_count += 1
            log.info(f"Reconnecting in {delay:.1f}s (attempt #{self._reconnect_count}) ...")
            await asyncio.sleep(delay)

    async def _receive_loop(self, ws):
        async for raw in ws:
            if not self._running:
                break
            try:
                await self._handle_message(raw)
            except Exception as e:
                log.error(f"Error handling WS message: {e}", exc_info=True)

    async def _handle_message(self, raw: str | bytes):
        """Parse a CLOB WebSocket message and fire price callbacks."""
        if isinstance(raw, bytes):
            raw = raw.decode()

        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        # CLOB WS sends a list of event objects
        events = msg if isinstance(msg, list) else [msg]

        for event in events:
            event_type = event.get("event_type") or event.get("type") or ""

            # ── Price change events ──────────────────────────────────────
            if event_type in ("price_change", "book", "tick"):
                await self._process_price_event(event)

            # ── Heartbeat / subscribed ack ───────────────────────────────
            elif event_type in ("subscribed", "heartbeat", "ack"):
                pass  # silent

            else:
                log.debug(f"Unhandled WS event type: {event_type}")

    async def _process_price_event(self, event: dict):
        """
        Extract token_id and mid price from a price event.
        CLOB sends: {"event_type":"price_change","asset_id":"...","price":"0.62",...}
        or book snapshots with bids/asks.
        """
        token_id = event.get("asset_id") or event.get("token_id") or event.get("market") or ""
        if not token_id or token_id not in self._subscribed_tokens:
            return

        ts = time.monotonic()

        # Direct price field
        price_raw = event.get("price") or event.get("mid_price")
        if price_raw is not None:
            price = float(price_raw)
            self.prices[token_id] = price
            await self._on_price_update(token_id, price, ts)
            return

        # Derive from bids/asks
        bids = event.get("bids") or []
        asks = event.get("asks") or []
        best_bid = max((float(b["price"]) for b in bids), default=None)
        best_ask = min((float(a["price"]) for a in asks), default=None)

        if best_bid is not None and best_ask is not None:
            price = (best_bid + best_ask) / 2
        elif best_ask is not None:
            price = best_ask
        elif best_bid is not None:
            price = best_bid
        else:
            return

        self.prices[token_id] = price
        await self._on_price_update(token_id, price, ts)

    async def _send_subscribe(self, token_ids):
        """Send subscription message for a set of token IDs."""
        if not self._ws or self._ws.closed:
            return
        msg = {
            "auth": {"apiKey": config.api_key} if config.api_key else {},
            "type": "subscribe",
            "channels": [
                {
                    "name": "live_activity",
                    "assets": list(token_ids),
                }
            ],
        }
        try:
            await self._ws.send(json.dumps(msg))
            log.debug(f"Sent subscribe for {len(token_ids)} tokens")
        except Exception as e:
            log.warning(f"Failed to send subscribe: {e}")

    async def _send_unsubscribe(self, token_ids):
        if not self._ws or self._ws.closed:
            return
        msg = {
            "type": "unsubscribe",
            "channels": [{"name": "live_activity", "assets": list(token_ids)}],
        }
        try:
            await self._ws.send(json.dumps(msg))
        except Exception as e:
            log.warning(f"Failed to send unsubscribe: {e}")
