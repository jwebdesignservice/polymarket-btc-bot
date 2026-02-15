"""
recorder.py
-----------
Live order book recorder for Polymarket BTC Up/Down markets.

Connects to the CLOB WebSocket and records every order book update tick
with millisecond-precision timestamps.

Usage:
    python recorder.py [--hours 4]

Output:
    recordings/YYYY-MM-DD_HH-MM-SS/
        session.json       - metadata (markets, start/end times)
        market_<slug>.jsonl - one line per tick for each market
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional
import argparse

try:
    import websockets
    import aiohttp
except ImportError:
    print("ERROR: Missing dependencies. Install with:")
    print("  py -m pip install websockets aiohttp")
    sys.exit(1)

import recorder_config as config


class OrderBookRecorder:
    def __init__(self, max_hours: float = 4.0):
        self.max_hours = max_hours
        self.session_dir: Optional[str] = None
        self.start_time = time.time()
        self.active_markets: dict[str, dict] = {}  # slug -> market metadata
        self.tick_buffers: dict[str, list] = {}    # slug -> list of ticks
        self.ws_connections: dict[str, websockets.WebSocketClientProtocol] = {}
        self.running = False

    async def find_active_markets(self) -> list[dict]:
        """Query CLOB API for active BTC 15-min markets."""
        url = f"{config.CLOB_API}/markets"
        params = {"active": "true", "closed": "false", "limit": 100}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                markets = data.get("data", [])
        
        # Filter to BTC up/down 15-min markets
        btc_markets = [
            m for m in markets
            if config.MARKET_FILTER in m.get("market_slug", "")
        ]
        return btc_markets

    async def subscribe_market(self, market: dict):
        """Subscribe to WebSocket updates for a single market."""
        slug = market["market_slug"]
        condition_id = market["condition_id"]
        
        if slug in self.ws_connections:
            return  # Already subscribed
        
        print(f"[recorder] Subscribing to {market['question']}")
        
        try:
            # Polymarket WebSocket expects market subscription by condition_id
            ws_url = f"{config.CLOB_WS}/{condition_id}"
            ws = await websockets.connect(ws_url)
            self.ws_connections[slug] = ws
            self.active_markets[slug] = market
            self.tick_buffers[slug] = []
            
            # Start listener task
            asyncio.create_task(self._listen_market(slug, ws))
            
        except Exception as e:
            print(f"[recorder] Failed to subscribe to {slug}: {e}")

    async def _listen_market(self, slug: str, ws: websockets.WebSocketClientProtocol):
        """Listen for order book updates on a WebSocket connection."""
        try:
            async for message in ws:
                tick = {
                    "ts": time.time(),
                    "iso": datetime.now(timezone.utc).isoformat(),
                    "data": json.loads(message)
                }
                self.tick_buffers[slug].append(tick)
        except websockets.ConnectionClosed:
            print(f"[recorder] WebSocket closed for {slug}")
        except Exception as e:
            print(f"[recorder] Error on {slug}: {e}")
        finally:
            if slug in self.ws_connections:
                del self.ws_connections[slug]

    async def flush_buffers(self):
        """Write buffered ticks to disk."""
        for slug, ticks in self.tick_buffers.items():
            if not ticks:
                continue
            
            filepath = os.path.join(self.session_dir, f"market_{slug}.jsonl")
            with open(filepath, "a", encoding="utf-8") as f:
                for tick in ticks:
                    f.write(json.dumps(tick) + "\n")
            
            self.tick_buffers[slug] = []

    async def periodic_flush(self):
        """Flush buffers every N seconds."""
        while self.running:
            await asyncio.sleep(config.FLUSH_INTERVAL_SEC)
            await self.flush_buffers()

    async def periodic_scan(self):
        """Scan for new active markets periodically."""
        while self.running:
            markets = await self.find_active_markets()
            for m in markets:
                await self.subscribe_market(m)
            await asyncio.sleep(config.MARKET_SCAN_INTERVAL)

    async def run(self):
        """Main recording loop."""
        # Create session directory
        session_name = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
        self.session_dir = os.path.join(config.DATA_DIR, session_name)
        os.makedirs(self.session_dir, exist_ok=True)
        
        print(f"[recorder] Session started: {self.session_dir}")
        print(f"[recorder] Recording for up to {self.max_hours} hours")
        
        self.running = True
        
        # Start background tasks
        flush_task = asyncio.create_task(self.periodic_flush())
        scan_task = asyncio.create_task(self.periodic_scan())
        
        # Initial market scan
        markets = await self.find_active_markets()
        print(f"[recorder] Found {len(markets)} active BTC markets")
        for m in markets:
            await self.subscribe_market(m)
        
        # Run until max time or Ctrl+C
        end_time = self.start_time + (self.max_hours * 3600)
        try:
            while time.time() < end_time:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\n[recorder] Stopping (Ctrl+C)...")
        
        # Cleanup
        self.running = False
        flush_task.cancel()
        scan_task.cancel()
        
        await self.flush_buffers()
        
        for ws in self.ws_connections.values():
            await ws.close()
        
        # Write session metadata
        session_meta = {
            "start_time": self.start_time,
            "end_time": time.time(),
            "markets": list(self.active_markets.values())
        }
        with open(os.path.join(self.session_dir, "session.json"), "w", encoding="utf-8") as f:
            json.dump(session_meta, f, indent=2)
        
        print(f"[recorder] Session complete. Recorded {len(self.active_markets)} markets.")
        print(f"[recorder] Data saved to: {self.session_dir}")


def main():
    parser = argparse.ArgumentParser(description="Record Polymarket BTC Up/Down order books")
    parser.add_argument("--hours", type=float, default=4.0, help="Max recording hours")
    args = parser.parse_args()
    
    recorder = OrderBookRecorder(max_hours=args.hours)
    asyncio.run(recorder.run())


if __name__ == "__main__":
    main()
