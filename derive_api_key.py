"""
Derive Polymarket API Credentials from Wallet
"""

import os
from dotenv import load_dotenv
from py_clob_client.client import ClobClient

load_dotenv()

POLYMARKET_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137  # Polygon

def main():
    private_key = os.getenv("POLYMARKET_PRIVATE_KEY")
    
    if not private_key:
        print("No private key found in .env")
        return
    
    # Add 0x prefix if missing
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key
    
    print("=" * 60)
    print("DERIVING POLYMARKET API CREDENTIALS")
    print("=" * 60)
    
    try:
        # Create client with private key
        client = ClobClient(
            host=POLYMARKET_HOST,
            chain_id=CHAIN_ID,
            key=private_key
        )
        
        print("\nCreating or deriving API credentials...")
        creds = client.create_or_derive_api_creds()
        
        print("\nSUCCESS! Your API credentials:")
        print("-" * 60)
        print(f"API Key:      {creds.api_key}")
        print(f"Secret:       {creds.api_secret}")
        print(f"Passphrase:   {creds.api_passphrase}")
        print("-" * 60)
        
        print("\nAdd these to your .env file:")
        print(f"POLYMARKET_API_KEY={creds.api_key}")
        print(f"POLYMARKET_API_SECRET={creds.api_secret}")
        print(f"POLYMARKET_API_PASSPHRASE={creds.api_passphrase}")
        
        # Offer to update .env automatically
        print("\n" + "=" * 60)
        update = input("Update .env automatically? (y/n): ").strip().lower()
        
        if update == 'y':
            env_path = os.path.join(os.path.dirname(__file__), '.env')
            with open(env_path, 'r') as f:
                content = f.read()
            
            import re
            content = re.sub(r'POLYMARKET_API_KEY=.*', f'POLYMARKET_API_KEY={creds.api_key}', content)
            content = re.sub(r'POLYMARKET_API_SECRET=.*', f'POLYMARKET_API_SECRET={creds.api_secret}', content)
            content = re.sub(r'POLYMARKET_API_PASSPHRASE=.*', f'POLYMARKET_API_PASSPHRASE={creds.api_passphrase}', content)
            
            with open(env_path, 'w') as f:
                f.write(content)
            
            print(".env updated successfully!")
        
        return creds
        
    except Exception as e:
        print(f"\nError: {e}")

if __name__ == "__main__":
    main()
