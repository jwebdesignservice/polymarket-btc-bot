"""
Polymarket Wallet Setup Script
------------------------------
Run this to:
1. Generate a new wallet
2. Set up your .env file
3. Check your connection status
"""

import os
import sys
from dotenv import load_dotenv

def generate_wallet():
    """Generate a new Ethereum wallet."""
    from eth_account import Account
    
    print("\n" + "=" * 60)
    print("🔐 GENERATING NEW POLYMARKET WALLET")
    print("=" * 60)
    
    account = Account.create()
    
    print(f"\n✅ Wallet created successfully!\n")
    print(f"📍 Address: {account.address}")
    print(f"🔑 Private Key: {account.key.hex()}")
    
    print("\n" + "=" * 60)
    print("⚠️  IMPORTANT - SAVE THIS INFORMATION!")
    print("=" * 60)
    print("""
1. Copy the private key above
2. Add it to your .env file:
   POLYMARKET_PRIVATE_KEY=<your_private_key>

3. Fund this address with USDC on Polygon:
   - Use a bridge like https://wallet.polygon.technology
   - Or buy USDC directly on Polygon
   - Send to: """ + account.address + """

4. Apply for Polymarket API access:
   - Go to https://polymarket.com
   - Connect your wallet
   - Go to Settings > API
   - Apply for access

5. Once approved, add API credentials to .env:
   POLYMARKET_API_KEY=<your_key>
   POLYMARKET_API_SECRET=<your_secret>
   POLYMARKET_API_PASSPHRASE=<your_passphrase>
""")
    
    return {
        "address": account.address,
        "private_key": account.key.hex()
    }


def check_setup():
    """Check current setup status."""
    load_dotenv()
    
    print("\n" + "=" * 60)
    print("📋 CHECKING SETUP STATUS")
    print("=" * 60)
    
    issues = []
    
    # Check private key
    pk = os.getenv("POLYMARKET_PRIVATE_KEY")
    if pk:
        from eth_account import Account
        try:
            if pk.startswith('0x'):
                pk = pk[2:]
            account = Account.from_key(pk)
            print(f"\n✅ Wallet configured: {account.address[:10]}...{account.address[-6:]}")
        except:
            print("\n❌ Invalid private key in .env")
            issues.append("Fix POLYMARKET_PRIVATE_KEY in .env")
    else:
        print("\n❌ No wallet configured")
        issues.append("Add POLYMARKET_PRIVATE_KEY to .env")
    
    # Check API credentials
    api_key = os.getenv("POLYMARKET_API_KEY")
    api_secret = os.getenv("POLYMARKET_API_SECRET")
    api_passphrase = os.getenv("POLYMARKET_API_PASSPHRASE")
    
    if api_key and api_secret and api_passphrase:
        print("✅ API credentials configured")
    else:
        print("❌ API credentials missing")
        issues.append("Add POLYMARKET_API_KEY, API_SECRET, and API_PASSPHRASE to .env")
    
    # Check trading mode
    mode = os.getenv("TRADING_MODE", "paper")
    print(f"📊 Trading mode: {mode.upper()}")
    
    # Summary
    print("\n" + "=" * 60)
    if issues:
        print("⚠️  SETUP INCOMPLETE")
        print("=" * 60)
        print("\nTo complete setup:")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
    else:
        print("✅ SETUP COMPLETE")
        print("=" * 60)
        print("\nYour bot is ready for live trading!")
        print("Set TRADING_MODE=live in .env to enable real trades.")
    
    return len(issues) == 0


def main():
    print("\n" + "=" * 60)
    print("🤖 POLYMARKET BOT SETUP")
    print("=" * 60)
    
    while True:
        print("\nOptions:")
        print("  1. Generate new wallet")
        print("  2. Check setup status")
        print("  3. Exit")
        
        choice = input("\nSelect option (1-3): ").strip()
        
        if choice == "1":
            generate_wallet()
        elif choice == "2":
            check_setup()
        elif choice == "3":
            print("\nGoodbye! 👋")
            break
        else:
            print("\nInvalid option. Please enter 1, 2, or 3.")


if __name__ == "__main__":
    main()
