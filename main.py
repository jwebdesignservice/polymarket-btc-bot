"""
main.py — Entry point + CLI loop for the Polymarket BTC Up/Down trading bot.

Usage:
    python main.py

CLI commands (at the `bot>` prompt):
    auto on <shares> [sum=0.95] [move=0.15] [windowMin=2]
    auto off
    status
    history
    quit / exit
"""

import asyncio
import json
import sys
import time
from typing import Optional

from config import config
from logger import get_logger
from market_finder import MarketFinder, BTCRound
from ws_client import ClobWebSocket
from strategy import strategy, State
from trader import trader

log = get_logger("main")

# ── Background tasks ──────────────────────────────────────────────────────────

async def market_poll_loop(finder: MarketFinder, ws: ClobWebSocket):
    """
    Periodically polls for active BTC rounds and attaches the strategy
    to the nearest upcoming round. Also manages WS subscriptions.
    """
    current_round_id: Optional[str] = None
    subscribed_tokens: set[str] = set()

    while True:
        try:
            if strategy.enabled:
                rounds = await finder.fetch_active_rounds()

                if not rounds:
                    log.info("No active BTC Up/Down rounds found. Retrying in 30s.")
                else:
                    nearest = rounds[0]

                    # Only switch rounds when strategy is IDLE or current round ended
                    need_new_round = (
                        current_round_id != nearest.condition_id
                        and (
                            strategy.state in (State.IDLE, State.RESET)
                            or current_round_id is None
                        )
                    )

                    if need_new_round:
                        log.info(f"New round detected: {nearest.question}")

                        # Unsubscribe from old tokens
                        if subscribed_tokens:
                            await ws.unsubscribe(list(subscribed_tokens))
                            subscribed_tokens.clear()

                        # Subscribe to new round's tokens
                        new_tokens = [nearest.up_token.token_id, nearest.down_token.token_id]
                        await ws.subscribe(new_tokens)
                        subscribed_tokens.update(new_tokens)

                        current_round_id = nearest.condition_id
                        strategy.attach_round(nearest)

                    else:
                        log.debug(f"Staying on current round: {nearest.question}")

        except Exception as e:
            log.error(f"market_poll_loop error: {e}", exc_info=True)

        await asyncio.sleep(30)  # poll every 30s


async def ws_loop(ws: ClobWebSocket):
    """Run the WebSocket client (reconnects automatically)."""
    await ws.start()


# ── CLI parsing ───────────────────────────────────────────────────────────────

def parse_kwarg(tokens: list[str], key: str, default=None):
    """Parse key=value pairs from CLI token list."""
    for t in tokens:
        if t.startswith(f"{key}="):
            return t.split("=", 1)[1]
    return default


def handle_auto_on(parts: list[str]):
    """
    auto on <shares> [sum=0.95] [move=0.15] [windowMin=2]
    """
    if len(parts) < 3:
        print("Usage: auto on <shares> [sum=0.95] [move=0.15] [windowMin=2]")
        return

    try:
        shares = float(parts[2])
    except ValueError:
        print(f"Invalid shares value: {parts[2]}")
        return

    hedge_sum = float(parse_kwarg(parts[3:], "sum", config.hedge_sum))
    move = float(parse_kwarg(parts[3:], "move", config.move_threshold))
    window = float(parse_kwarg(parts[3:], "windowMin", config.window_minutes))

    strategy.configure(
        shares=shares,
        hedge_sum=hedge_sum,
        move_threshold=move,
        window_minutes=window,
    )
    trader.initialize()
    strategy.enable()

    print(
        f"✅ Auto trading ON | shares={shares} sum={hedge_sum} "
        f"move={move} windowMin={window}"
    )


def handle_status():
    s = strategy.status_dict()
    print("\n── Bot Status ──────────────────────────────────")
    print(f"  State      : {s['state']}")
    print(f"  Enabled    : {s['enabled']}")
    print(f"  Round      : {s['current_round'] or 'None'}")
    print(f"  Time left  : {s['seconds_remaining'] or 'N/A'}")
    print(f"  Open pos.  : {len(s['open_positions'])}")
    for p in s['open_positions']:
        print(f"    {p['outcome']} × {p['shares']} @ {p['price']:.4f}")
    print(f"  Trades done: {s['trades_completed']}")
    print(f"  Total cost : ${s['total_cost']:.4f}")
    print(f"  Total P&L  : ${s['total_profit']:.4f} ({s['roi_pct']}%)")
    print(f"  Config     : {s['config']}")
    print("─" * 48 + "\n")


def handle_history(n: int = 20):
    hist = strategy.trade_history[-n:]
    if not hist:
        print("No completed trades yet.")
        return
    print(f"\n── Last {len(hist)} Trades ──────────────────────────")
    for i, t in enumerate(hist, 1):
        import datetime
        ts = datetime.datetime.fromtimestamp(t.timestamp).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  [{i:02d}] {ts} | {t.summary()}")
    print("─" * 48 + "\n")


def print_help():
    print("""
Commands:
  auto on <shares> [sum=0.95] [move=0.15] [windowMin=2]
      Start automated trading with given parameters.
      shares   — number of shares per leg
      sum      — max combined price (leg1 + leg2) to trigger hedge [default 0.95]
      move     — minimum price drop % to trigger Leg 1 [default 0.15]
      windowMin— only trade in first N minutes of each round [default 2]

  auto off     — Stop automated trading
  status       — Show current state, open positions, P&L
  history [N]  — Show last N completed trades (default 20)
  help         — Show this message
  quit/exit    — Shut down the bot
""")


# ── CLI loop ──────────────────────────────────────────────────────────────────

async def cli_loop():
    """Run the interactive CLI in a separate thread to avoid blocking asyncio."""
    loop = asyncio.get_event_loop()

    def _read_input():
        try:
            return input("bot> ").strip()
        except EOFError:
            return "exit"

    print_help()
    print("Bot started. Type 'help' for commands.\n")

    while True:
        try:
            line = await loop.run_in_executor(None, _read_input)
        except Exception:
            break

        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower() if parts else ""

        if cmd in ("quit", "exit", "q"):
            print("Shutting down...")
            strategy.disable()
            # Cancel all running tasks
            for task in asyncio.all_tasks():
                if task is not asyncio.current_task():
                    task.cancel()
            break

        elif cmd == "auto":
            if len(parts) < 2:
                print("Usage: auto on|off")
            elif parts[1].lower() == "on":
                handle_auto_on(parts)
            elif parts[1].lower() == "off":
                strategy.disable()
                print("⛔ Auto trading OFF")
            else:
                print(f"Unknown auto subcommand: {parts[1]}")

        elif cmd == "status":
            handle_status()

        elif cmd == "history":
            n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 20
            handle_history(n)

        elif cmd == "help":
            print_help()

        else:
            print(f"Unknown command: {cmd}. Type 'help' for available commands.")


# ── Main entry ────────────────────────────────────────────────────────────────

async def main():
    log.info("=== Polymarket BTC Up/Down Trading Bot starting ===")

    finder = MarketFinder()

    async def price_update_callback(token_id: str, price: float, ts: float):
        await strategy.on_price_update(token_id, price, ts)

    ws = ClobWebSocket(on_price_update=price_update_callback)

    # Launch background tasks
    tasks = [
        asyncio.create_task(ws_loop(ws), name="ws_loop"),
        asyncio.create_task(market_poll_loop(finder, ws), name="market_poll"),
        asyncio.create_task(cli_loop(), name="cli"),
    ]

    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        pass
    finally:
        log.info("Shutting down — cleaning up ...")
        await ws.stop()
        await finder.close()
        log.info("Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted. Bye!")
