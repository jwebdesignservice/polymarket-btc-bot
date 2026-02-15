"""
trader.py — ORDER EXECUTION STUB

All functions in this module print what they WOULD do.
Real API integration requires:
  1. Set PRIVATE_KEY, WALLET_ADDRESS in .env
  2. Install py-clob-client and configure credentials
  3. Replace stub implementations below with real calls

TODO: Replace stubs with py-clob-client integration.
"""

from dataclasses import dataclass
from typing import Optional
from logger import get_logger
from config import config

log = get_logger("trader")


@dataclass
class OrderResult:
    success: bool
    order_id: Optional[str] = None
    filled_price: Optional[float] = None
    filled_shares: Optional[float] = None
    error: Optional[str] = None


class TraderStub:
    """
    Stub trader — logs intended actions but does not place real orders.
    Replace methods with real py-clob-client calls when ready.
    """

    def __init__(self):
        self._initialized = False
        log.warning("TraderStub loaded — NO real orders will be placed.")

    def initialize(self):
        """
        TODO: Initialize the py-clob-client with credentials from config.
        Example:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds

            creds = ApiCreds(
                api_key=config.api_key,
                api_secret=config.api_secret,
                api_passphrase=config.api_passphrase,
            )
            self.client = ClobClient(
                host=config.clob_api,
                key=config.private_key,
                chain_id=137,  # Polygon
                creds=creds,
            )
        """
        if not config.private_key:
            log.warning("No PRIVATE_KEY in .env — trader running in stub mode only.")
        else:
            log.info(f"[STUB] Would initialize ClobClient for wallet {config.wallet_address}")
        self._initialized = True

    async def buy_market(
        self,
        token_id: str,
        outcome: str,
        shares: float,
        max_price: float,
    ) -> OrderResult:
        """
        Place a market BUY order for `shares` of the given token.

        TODO: Replace stub with:
            order = self.client.create_market_order(
                token_id=token_id,
                side="BUY",
                amount=shares,
                price=max_price,
            )
            resp = self.client.post_order(order)
            return OrderResult(
                success=resp.get("status") == "matched",
                order_id=resp.get("orderID"),
                filled_price=float(resp.get("price", max_price)),
                filled_shares=float(resp.get("size", shares)),
            )
        """
        log.info(
            f"[STUB] BUY {shares} shares of {outcome} (token={token_id[:8]}...) "
            f"@ max_price={max_price:.4f}"
        )
        # Simulate an immediate fill at max_price for strategy logic
        return OrderResult(
            success=True,
            order_id=f"stub-{token_id[:6]}-{outcome}",
            filled_price=max_price,
            filled_shares=shares,
        )

    async def sell_market(
        self,
        token_id: str,
        outcome: str,
        shares: float,
        min_price: float,
    ) -> OrderResult:
        """
        Place a market SELL order for `shares` of the given token.

        TODO: Replace stub with real sell order via py-clob-client.
        """
        log.info(
            f"[STUB] SELL {shares} shares of {outcome} (token={token_id[:8]}...) "
            f"@ min_price={min_price:.4f}"
        )
        return OrderResult(
            success=True,
            order_id=f"stub-sell-{token_id[:6]}-{outcome}",
            filled_price=min_price,
            filled_shares=shares,
        )

    async def get_balance(self) -> Optional[float]:
        """
        Return the USDC balance of the wallet on Polygon.

        TODO: Replace stub with:
            balance = self.client.get_balance()
            return float(balance)
        """
        log.info("[STUB] Would fetch USDC balance from Polygon wallet")
        return None

    async def get_positions(self) -> list[dict]:
        """
        Return current open positions.

        TODO: Replace stub with:
            return self.client.get_positions()
        """
        log.info("[STUB] Would fetch open positions from CLOB API")
        return []

    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order by ID.

        TODO: Replace stub with:
            resp = self.client.cancel(order_id=order_id)
            return resp.get("canceled", False)
        """
        log.info(f"[STUB] Would cancel order {order_id}")
        return True


# Module-level singleton
trader = TraderStub()
