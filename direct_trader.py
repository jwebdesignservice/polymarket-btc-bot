"""
Polymarket Direct Trader
------------------------
Trade on Polymarket WITHOUT API keys using direct order signing.

How it works:
1. Sign orders with your private key (EIP-712)
2. Submit to Polymarket's public CLOB endpoints
3. Orders execute on Polygon

Requirements:
- Private key in .env
- USDC balance on Polygon (in your wallet)
- MATIC for gas fees (small amount)
"""

import os
import json
import time
import asyncio
import aiohttp
from dotenv import load_dotenv
from eth_account import Account
from eth_account.messages import encode_structured_data

load_dotenv()

# Polymarket CLOB endpoints
CLOB_URL = "https://clob.polymarket.com"
GAMMA_URL = "https://gamma-api.polymarket.com"

# Chain ID for Polygon
POLYGON_CHAIN_ID = 137

# Polymarket Exchange Contract
EXCHANGE_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"

# USDC on Polygon
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"


class DirectTrader:
    """Trade on Polymarket using direct order signing."""
    
    def __init__(self):
        self.private_key = os.getenv("POLYMARKET_PRIVATE_KEY", "")
        self.wallet = None
        self.address = None
        
        if self.private_key:
            pk = self.private_key[2:] if self.private_key.startswith('0x') else self.private_key
            self.wallet = Account.from_key(pk)
            self.address = self.wallet.address
            print(f"✅ Wallet loaded: {self.address}")
    
    def create_order_signature(self, order_data: dict) -> str:
        """
        Sign an order using EIP-712 structured data signing.
        """
        # EIP-712 domain for Polymarket
        domain = {
            "name": "Polymarket CTF Exchange",
            "version": "1",
            "chainId": POLYGON_CHAIN_ID,
            "verifyingContract": EXCHANGE_ADDRESS
        }
        
        # Order type definition
        types = {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "Order": [
                {"name": "salt", "type": "uint256"},
                {"name": "maker", "type": "address"},
                {"name": "signer", "type": "address"},
                {"name": "taker", "type": "address"},
                {"name": "tokenId", "type": "uint256"},
                {"name": "makerAmount", "type": "uint256"},
                {"name": "takerAmount", "type": "uint256"},
                {"name": "expiration", "type": "uint256"},
                {"name": "nonce", "type": "uint256"},
                {"name": "feeRateBps", "type": "uint256"},
                {"name": "side", "type": "uint8"},
                {"name": "signatureType", "type": "uint8"},
            ]
        }
        
        # Create the structured data
        structured_data = {
            "types": types,
            "primaryType": "Order",
            "domain": domain,
            "message": order_data
        }
        
        # Sign the data
        encoded = encode_structured_data(primitive=structured_data)
        signed = self.wallet.sign_message(encoded)
        
        return signed.signature.hex()
    
    async def get_orderbook(self, token_id: str) -> dict:
        """Fetch orderbook for a token."""
        async with aiohttp.ClientSession() as session:
            url = f"{CLOB_URL}/book?token_id={token_id}"
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.json()
        return None
    
    async def place_market_order(self, token_id: str, side: str, amount: float) -> dict:
        """
        Place a market order (takes best available price).
        
        Args:
            token_id: The outcome token ID
            side: "BUY" or "SELL"
            amount: Amount in USDC to spend (for BUY) or shares to sell (for SELL)
        
        Returns:
            Order result
        """
        if not self.wallet:
            return {"success": False, "error": "Wallet not configured"}
        
        # Get current orderbook to find best price
        book = await self.get_orderbook(token_id)
        if not book:
            return {"success": False, "error": "Failed to fetch orderbook"}
        
        # Get best price
        if side == "BUY":
            asks = book.get("asks", [])
            if not asks:
                return {"success": False, "error": "No asks available"}
            best_price = float(asks[0]["price"])
        else:
            bids = book.get("bids", [])
            if not bids:
                return {"success": False, "error": "No bids available"}
            best_price = float(bids[0]["price"])
        
        # Create order
        salt = int(time.time() * 1000)
        expiration = int(time.time()) + 3600  # 1 hour
        
        # Calculate amounts (USDC has 6 decimals, shares have 6 decimals)
        if side == "BUY":
            maker_amount = int(amount * 1_000_000)  # USDC amount
            taker_amount = int((amount / best_price) * 1_000_000)  # Shares to receive
        else:
            maker_amount = int(amount * 1_000_000)  # Shares to sell
            taker_amount = int((amount * best_price) * 1_000_000)  # USDC to receive
        
        order_data = {
            "salt": salt,
            "maker": self.address,
            "signer": self.address,
            "taker": "0x0000000000000000000000000000000000000000",
            "tokenId": int(token_id),
            "makerAmount": maker_amount,
            "takerAmount": taker_amount,
            "expiration": expiration,
            "nonce": 0,
            "feeRateBps": 0,
            "side": 0 if side == "BUY" else 1,
            "signatureType": 0
        }
        
        # Sign the order
        try:
            signature = self.create_order_signature(order_data)
        except Exception as e:
            return {"success": False, "error": f"Signing failed: {e}"}
        
        # Submit order
        order_payload = {
            "order": order_data,
            "signature": signature,
            "owner": self.address,
            "orderType": "GTC"  # Good Till Cancelled
        }
        
        async with aiohttp.ClientSession() as session:
            url = f"{CLOB_URL}/order"
            headers = {"Content-Type": "application/json"}
            
            async with session.post(url, json=order_payload, headers=headers) as resp:
                result = await resp.text()
                
                if resp.status == 200:
                    return {
                        "success": True,
                        "order_id": json.loads(result).get("orderID"),
                        "side": side,
                        "amount": amount,
                        "price": best_price
                    }
                else:
                    return {
                        "success": False,
                        "error": result,
                        "status": resp.status
                    }
    
    async def check_allowance(self) -> bool:
        """Check if USDC is approved for trading."""
        # This would check the ERC20 allowance
        # For now, assume we need to approve
        return False
    
    async def approve_usdc(self) -> dict:
        """Approve USDC for trading on Polymarket."""
        # This would send an approve transaction
        # Requires web3 and gas
        return {"success": False, "error": "Manual approval needed - go to polymarket.com and make a small trade first"}


async def test_direct_trading():
    """Test the direct trading functionality."""
    trader = DirectTrader()
    
    if not trader.wallet:
        print("❌ No wallet configured")
        return
    
    print(f"\n📍 Wallet: {trader.address}")
    
    # Test fetching orderbook
    # Use a sample token ID (you'd get this from market discovery)
    test_token = "71321045679252212594626385532706912750332728571942532289631379312455583992563"
    
    print(f"\n📊 Fetching orderbook...")
    book = await trader.get_orderbook(test_token)
    
    if book:
        bids = book.get("bids", [])[:3]
        asks = book.get("asks", [])[:3]
        print(f"Best bids: {bids}")
        print(f"Best asks: {asks}")
    else:
        print("Failed to fetch orderbook")


if __name__ == "__main__":
    asyncio.run(test_direct_trading())
