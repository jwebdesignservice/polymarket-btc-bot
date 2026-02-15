"""
Real Wallet Balance Checker
---------------------------
Connects to Polygon network to check actual USDC balance.
"""

import os
import json
import asyncio
import aiohttp
from dotenv import load_dotenv

load_dotenv()

# Polygon RPC endpoints (free public RPCs)
POLYGON_RPCS = [
    "https://polygon-rpc.com",
    "https://rpc-mainnet.matic.quiknode.pro",
    "https://polygon-mainnet.public.blastapi.io",
]

# USDC contract on Polygon
USDC_CONTRACT = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"  # Native USDC
USDC_BRIDGED = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"   # USDC.e (bridged)

# ERC20 balanceOf function signature
BALANCE_OF_SIG = "0x70a08231"


def get_wallet_address():
    """Get wallet address from private key in .env"""
    private_key = os.getenv("POLYMARKET_PRIVATE_KEY", "")
    if not private_key:
        return None
    
    try:
        from eth_account import Account
        pk = private_key[2:] if private_key.startswith('0x') else private_key
        wallet = Account.from_key(pk)
        return wallet.address
    except:
        return None


async def get_usdc_balance(address: str) -> float:
    """
    Get USDC balance for an address on Polygon.
    Returns balance in USD (USDC has 6 decimals).
    """
    if not address:
        return 0.0
    
    # Pad address to 32 bytes for the call
    padded_address = "0x" + address[2:].lower().zfill(64)
    
    # Try both USDC contracts
    total_balance = 0.0
    
    for usdc_contract in [USDC_CONTRACT, USDC_BRIDGED]:
        for rpc_url in POLYGON_RPCS:
            try:
                async with aiohttp.ClientSession() as session:
                    # eth_call to get balance
                    payload = {
                        "jsonrpc": "2.0",
                        "method": "eth_call",
                        "params": [
                            {
                                "to": usdc_contract,
                                "data": BALANCE_OF_SIG + padded_address[2:]
                            },
                            "latest"
                        ],
                        "id": 1
                    }
                    
                    async with session.post(rpc_url, json=payload, timeout=10) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if "result" in data and data["result"] != "0x":
                                # Convert hex to int, then to USDC (6 decimals)
                                balance_wei = int(data["result"], 16)
                                balance_usdc = balance_wei / 1_000_000
                                total_balance += balance_usdc
                                break  # Got balance, try next contract
                                
            except Exception as e:
                continue  # Try next RPC
    
    return total_balance


async def get_matic_balance(address: str) -> float:
    """Get MATIC balance for gas fees."""
    if not address:
        return 0.0
    
    for rpc_url in POLYGON_RPCS:
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "jsonrpc": "2.0",
                    "method": "eth_getBalance",
                    "params": [address, "latest"],
                    "id": 1
                }
                
                async with session.post(rpc_url, json=payload, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if "result" in data:
                            balance_wei = int(data["result"], 16)
                            return balance_wei / 1e18  # MATIC has 18 decimals
                            
        except:
            continue
    
    return 0.0


async def get_full_balance(address: str = None) -> dict:
    """Get complete wallet balance info."""
    if not address:
        address = get_wallet_address()
    
    if not address:
        return {
            "connected": False,
            "address": None,
            "usdc_balance": 0.0,
            "matic_balance": 0.0,
            "error": "No wallet configured"
        }
    
    try:
        usdc = await get_usdc_balance(address)
        matic = await get_matic_balance(address)
        
        return {
            "connected": True,
            "address": address,
            "usdc_balance": usdc,
            "matic_balance": matic,
            "error": None
        }
    except Exception as e:
        return {
            "connected": False,
            "address": address,
            "usdc_balance": 0.0,
            "matic_balance": 0.0,
            "error": str(e)
        }


# Synchronous wrapper for use in Flask
def get_balance_sync(address: str = None) -> dict:
    """Synchronous wrapper for get_full_balance."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(get_full_balance(address))
        loop.close()
        return result
    except Exception as e:
        return {
            "connected": False,
            "address": address,
            "usdc_balance": 0.0,
            "matic_balance": 0.0,
            "error": str(e)
        }


# Test
if __name__ == "__main__":
    import asyncio
    
    address = get_wallet_address()
    print(f"Wallet: {address}")
    
    if address:
        result = asyncio.run(get_full_balance(address))
        print(f"USDC Balance: ${result['usdc_balance']:.2f}")
        print(f"MATIC Balance: {result['matic_balance']:.4f}")
    else:
        print("No wallet configured in .env")
