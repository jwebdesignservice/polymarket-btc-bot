"""
Polymarket API Client
---------------------
Handles wallet connection and trading via Polymarket's CLOB API.

Setup:
1. Create a wallet or use existing Ethereum wallet
2. Get API credentials from Polymarket
3. Add credentials to .env file
4. Deposit USDC to your Polymarket account
"""

import os
import json
import logging
from dotenv import load_dotenv
from eth_account import Account
from eth_account.signers.local import LocalAccount

load_dotenv()
logger = logging.getLogger(__name__)

# Polymarket API endpoints
CLOB_API_URL = "https://clob.polymarket.com"
GAMMA_API_URL = "https://gamma-api.polymarket.com"

class PolymarketClient:
    """Client for interacting with Polymarket's CLOB API."""
    
    def __init__(self):
        self.private_key = os.getenv("POLYMARKET_PRIVATE_KEY")
        self.api_key = os.getenv("POLYMARKET_API_KEY")
        self.api_secret = os.getenv("POLYMARKET_API_SECRET")
        self.api_passphrase = os.getenv("POLYMARKET_API_PASSPHRASE")
        
        self.wallet: LocalAccount = None
        self.address: str = None
        self.connected = False
        
        if self.private_key:
            self._init_wallet()
    
    def _init_wallet(self):
        """Initialize wallet from private key."""
        try:
            # Remove '0x' prefix if present
            pk = self.private_key
            if pk.startswith('0x'):
                pk = pk[2:]
            
            self.wallet = Account.from_key(pk)
            self.address = self.wallet.address
            self.connected = True
            logger.info(f"Wallet connected: {self.address[:10]}...{self.address[-6:]}")
        except Exception as e:
            logger.error(f"Failed to initialize wallet: {e}")
            self.connected = False
    
    def is_connected(self) -> bool:
        """Check if wallet is connected."""
        return self.connected and self.wallet is not None
    
    def get_address(self) -> str:
        """Get wallet address."""
        return self.address if self.connected else None
    
    async def get_balance(self) -> float:
        """Get USDC balance on Polymarket."""
        if not self.connected:
            return 0.0
        
        try:
            # TODO: Implement actual balance check via API
            # For now, return mock balance
            # This will be replaced with actual API call
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Polymarket balance endpoint
                url = f"{GAMMA_API_URL}/balance"
                headers = self._get_auth_headers()
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return float(data.get('balance', 0))
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
        
        return 0.0
    
    def _get_auth_headers(self) -> dict:
        """Get authentication headers for API requests."""
        if not self.api_key:
            return {}
        
        return {
            "POLY_API_KEY": self.api_key,
            "POLY_API_SECRET": self.api_secret,
            "POLY_API_PASSPHRASE": self.api_passphrase,
        }
    
    async def place_order(self, token_id: str, side: str, size: float, price: float) -> dict:
        """
        Place an order on Polymarket.
        
        Args:
            token_id: The token ID to trade
            side: 'BUY' or 'SELL'
            size: Number of shares
            price: Price per share (0.01 - 0.99)
        
        Returns:
            Order result dict
        """
        if not self.connected:
            return {"success": False, "error": "Wallet not connected"}
        
        if not self.api_key:
            return {"success": False, "error": "API credentials not configured"}
        
        try:
            import aiohttp
            import time
            
            order = {
                "tokenID": token_id,
                "side": side.upper(),
                "size": str(size),
                "price": str(price),
                "expiration": int(time.time()) + 3600,  # 1 hour expiry
            }
            
            # Sign the order
            # TODO: Implement proper order signing with EIP-712
            
            async with aiohttp.ClientSession() as session:
                url = f"{CLOB_API_URL}/order"
                headers = self._get_auth_headers()
                headers["Content-Type"] = "application/json"
                
                async with session.post(url, json=order, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        logger.info(f"Order placed: {side} {size} @ ${price}")
                        return {"success": True, "order": data}
                    else:
                        error = await resp.text()
                        logger.error(f"Order failed: {error}")
                        return {"success": False, "error": error}
                        
        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            return {"success": False, "error": str(e)}
    
    async def cancel_order(self, order_id: str) -> dict:
        """Cancel an existing order."""
        if not self.connected:
            return {"success": False, "error": "Wallet not connected"}
        
        try:
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                url = f"{CLOB_API_URL}/order/{order_id}"
                headers = self._get_auth_headers()
                
                async with session.delete(url, headers=headers) as resp:
                    if resp.status == 200:
                        logger.info(f"Order cancelled: {order_id}")
                        return {"success": True}
                    else:
                        error = await resp.text()
                        return {"success": False, "error": error}
                        
        except Exception as e:
            logger.error(f"Failed to cancel order: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_positions(self) -> list:
        """Get current positions."""
        if not self.connected:
            return []
        
        try:
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                url = f"{GAMMA_API_URL}/positions"
                headers = self._get_auth_headers()
                
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        return await resp.json()
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
        
        return []


def generate_new_wallet() -> dict:
    """
    Generate a new Ethereum wallet for Polymarket.
    
    Returns:
        dict with 'address' and 'private_key'
    
    ⚠️ SAVE THE PRIVATE KEY SECURELY - IT CANNOT BE RECOVERED!
    """
    account = Account.create()
    return {
        "address": account.address,
        "private_key": account.key.hex()
    }


# Example usage
if __name__ == "__main__":
    # Generate a new wallet
    print("=" * 60)
    print("GENERATING NEW POLYMARKET WALLET")
    print("=" * 60)
    
    wallet = generate_new_wallet()
    print(f"\n✅ New wallet created!\n")
    print(f"Address: {wallet['address']}")
    print(f"Private Key: {wallet['private_key']}")
    print("\n⚠️  IMPORTANT:")
    print("1. Save the private key securely!")
    print("2. Add to .env file as POLYMARKET_PRIVATE_KEY")
    print("3. Fund with USDC on Polygon network")
    print("4. Apply for API credentials at polymarket.com")
