from typing import Any, Dict, Optional, Tuple
from decimal import Decimal
from web3 import Web3
from web3.exceptions import TransactionNotFound, Web3RPCError
from eth_account import Account
from app.core.config import settings

# Minimal ERC-20 Standard ABI
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "name",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "success", "type": "bool"}],
        "type": "function",
    },
]

# Minimal ERC-721 / NFT Minting ABI
ERC721_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "string", "name": "uri", "type": "string"}
        ],
        "name": "mintNFT",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [{"internalType": "address", "name": "to", "type": "address"}],
        "name": "safeMint",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [{"internalType": "address", "name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "name",
        "outputs": [{"internalType": "string", "name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "symbol",
        "outputs": [{"internalType": "string", "name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# Known Testnet Tokens / Contracts for quick reference
KNOWN_CONTRACTS = {
    11155111: { # Sepolia
        "USDC": "0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238",
        "LINK": "0x779877A7B0D9E8603169DdbD7836e478b4624789",
        "WETH": "0xfFf9976782d46CC05630D1f6eBAb18b2324d6B14",
    }
}

class BlockchainService:
    def __init__(self, rpc_url: Optional[str] = None, chain_id: Optional[int] = None):
        self.rpc_url = rpc_url or settings.RPC_URL
        self.chain_id = chain_id or settings.CHAIN_ID
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        
    def is_connected(self) -> bool:
        try:
            return self.w3.is_connected()
        except Exception:
            return False

    def validate_address(self, address: str) -> str:
        if not Web3.is_address(address):
            raise ValueError(f"Invalid Ethereum address format: '{address}'")
        return Web3.to_checksum_address(address)

    def get_latest_block_number(self) -> int:
        return self.w3.eth.block_number

    def get_native_balance(self, address: str) -> Dict[str, Any]:
        checksum_address = self.validate_address(address)
        balance_wei = self.w3.eth.get_balance(checksum_address)
        balance_eth = Web3.from_wei(balance_wei, "ether")
        return {
            "address": checksum_address,
            "balance_wei": str(balance_wei),
            "balance_eth": f"{Decimal(str(balance_eth)):.6f}".rstrip("0").rstrip(".") or "0",
            "symbol": "ETH" if self.chain_id in [1, 5, 11155111] else "POL",
            "chain_id": self.chain_id
        }

    def get_token_balance(self, token_address: str, wallet_address: str) -> Dict[str, Any]:
        token_addr = self.validate_address(token_address)
        wallet_addr = self.validate_address(wallet_address)
        
        contract = self.w3.eth.contract(address=token_addr, abi=ERC20_ABI)
        
        try:
            symbol = contract.functions.symbol().call()
        except Exception:
            symbol = "TOKEN"
            
        try:
            name = contract.functions.name().call()
        except Exception:
            name = "Unknown Token"
            
        try:
            decimals = contract.functions.decimals().call()
        except Exception:
            decimals = 18

        raw_balance = contract.functions.balanceOf(wallet_addr).call()
        formatted_balance = Decimal(raw_balance) / Decimal(10 ** decimals)

        return {
            "wallet_address": wallet_addr,
            "token_address": token_addr,
            "token_name": name,
            "token_symbol": symbol,
            "decimals": decimals,
            "raw_balance": str(raw_balance),
            "balance": f"{formatted_balance:.6f}".rstrip("0").rstrip(".") or "0"
        }

    def get_transaction_status(self, tx_hash: str) -> Dict[str, Any]:
        if not tx_hash.startswith("0x") or len(tx_hash) != 66:
            raise ValueError("Invalid transaction hash format. Must be a 66-character hex string starting with 0x.")
        
        try:
            tx = self.w3.eth.get_transaction(tx_hash)
            receipt = None
            try:
                receipt = self.w3.eth.get_transaction_receipt(tx_hash)
            except TransactionNotFound:
                pass
                
            if receipt is None:
                return {
                    "tx_hash": tx_hash,
                    "status": "pending",
                    "from_address": tx["from"],
                    "to_address": tx.get("to"),
                    "value": str(Web3.from_wei(tx["value"], "ether")),
                    "explorer_url": f"{settings.EXPLORER_URL}/tx/{tx_hash}"
                }
            
            status_str = "success" if receipt["status"] == 1 else "reverted"
            return {
                "tx_hash": tx_hash,
                "status": status_str,
                "block_number": receipt["blockNumber"],
                "gas_used": receipt["gasUsed"],
                "from_address": receipt["from"],
                "to_address": receipt.get("to"),
                "value": str(Web3.from_wei(tx["value"], "ether")),
                "explorer_url": f"{settings.EXPLORER_URL}/tx/{tx_hash}"
            }
        except TransactionNotFound:
            return {
                "tx_hash": tx_hash,
                "status": "not_found",
                "explorer_url": f"{settings.EXPLORER_URL}/tx/{tx_hash}"
            }
        except Exception as e:
            return {
                "tx_hash": tx_hash,
                "status": "not_found",
                "error": str(e),
                "explorer_url": f"{settings.EXPLORER_URL}/tx/{tx_hash}"
            }

    def prepare_native_transfer(self, to_address: str, amount_eth: float | str) -> Dict[str, Any]:
        to_addr = self.validate_address(to_address)
        amount_dec = Decimal(str(amount_eth))
        if amount_dec <= 0:
            raise ValueError("Transfer amount must be greater than 0")
        
        value_wei = Web3.to_wei(amount_dec, "ether")
        
        return {
            "type": "transfer_native",
            "to": to_addr,
            "value": str(value_wei),
            "value_eth": str(amount_dec),
            "data": "0x",
            "gas_limit": "21000",
            "chain_id": self.chain_id,
            "description": f"Chuyển {amount_dec} ETH tới địa chỉ {to_addr}",
            "params": {
                "recipient": to_addr,
                "amount_eth": str(amount_dec),
                "value_wei": str(value_wei)
            }
        }

    def prepare_erc20_transfer(self, token_address: str, to_address: str, amount: float | str) -> Dict[str, Any]:
        token_addr = self.validate_address(token_address)
        to_addr = self.validate_address(to_address)
        contract = self.w3.eth.contract(address=token_addr, abi=ERC20_ABI)
        
        try:
            decimals = contract.functions.decimals().call()
            symbol = contract.functions.symbol().call()
        except Exception:
            decimals = 18
            symbol = "TOKEN"

        amount_dec = Decimal(str(amount))
        raw_amount = int(amount_dec * Decimal(10 ** decimals))
        
        # Encode transfer(to, amount)
        call_data = contract.encodeABI(fn_name="transfer", args=[to_addr, raw_amount])
        
        return {
            "type": "transfer_token",
            "to": token_addr,
            "value": "0",
            "value_eth": "0",
            "data": call_data,
            "gas_limit": "65000",
            "chain_id": self.chain_id,
            "description": f"Chuyển {amount_dec} {symbol} tới địa chỉ {to_addr}",
            "params": {
                "token_address": token_addr,
                "token_symbol": symbol,
                "recipient": to_addr,
                "amount": str(amount_dec),
                "raw_amount": str(raw_amount)
            }
        }

    def prepare_nft_mint(self, nft_contract_address: str, recipient_address: str, token_uri: str = "ipfs://QmDefaultNFT") -> Dict[str, Any]:
        contract_addr = self.validate_address(nft_contract_address)
        recipient = self.validate_address(recipient_address)
        contract = self.w3.eth.contract(address=contract_addr, abi=ERC721_ABI)
        
        call_data = contract.encodeABI(fn_name="mintNFT", args=[recipient, token_uri])
        
        return {
            "type": "mint_nft",
            "to": contract_addr,
            "value": "0",
            "value_eth": "0",
            "data": call_data,
            "gas_limit": "150000",
            "chain_id": self.chain_id,
            "description": f"Mint NFT cho ví {recipient} trên Smart Contract {contract_addr}",
            "params": {
                "nft_contract": contract_addr,
                "recipient": recipient,
                "token_uri": token_uri
            }
        }

