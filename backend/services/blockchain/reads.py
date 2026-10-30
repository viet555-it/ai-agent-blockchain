"""Synchronous RPC reads and token metadata fallbacks."""

from typing import Any

from web3.exceptions import TransactionNotFound

from backend.token_amounts import UINT256_MAX, format_token_units

from .abi import STANDARD_ERC20_ABI
from .access import ContractAccess, RpcAccess


def get_native_balance(blockchain: ContractAccess, address: str) -> dict[str, Any]:
    """Fetch native ETH balance with exact decimal conversion."""
    target = blockchain.validate_and_checksum_address(address)
    raw_wei = blockchain.w3.eth.get_balance(target)
    formatted_eth = format_token_units(raw_wei, 18)
    config = blockchain.network_manager.get_network_config(blockchain.chain_id)
    return {
        "address": target,
        "chain_id": blockchain.chain_id,
        "network": config.name,
        "balance": formatted_eth,
        "raw_balance": raw_wei,
        "symbol": config.native_currency.symbol,
        "decimals": 18,
    }


def get_erc20_contract(
    blockchain: ContractAccess, token_address: str, custom_abi: list[dict[str, Any]] | None = None
):
    target = blockchain.validate_and_checksum_address(token_address)
    abi = custom_abi or STANDARD_ERC20_ABI
    return blockchain.w3.eth.contract(address=target, abi=abi)


def get_token_balance(
    blockchain: ContractAccess, token_address: str, wallet_address: str
) -> dict[str, Any]:
    """Fetch ERC-20 token balance without float rounding."""
    token_addr = blockchain.validate_and_checksum_address(token_address)
    wallet_addr = blockchain.validate_and_checksum_address(wallet_address)
    contract = blockchain.get_erc20_contract(token_addr)
    raw_balance = contract.functions.balanceOf(wallet_addr).call()
    try:
        decimals = contract.functions.decimals().call()
    except Exception:
        decimals = 18
    try:
        symbol = contract.functions.symbol().call()
    except Exception:
        symbol = "TOKEN"
    return {
        "token_address": token_addr,
        "wallet_address": wallet_addr,
        "balance": format_token_units(raw_balance, decimals),
        "raw_balance": raw_balance,
        "symbol": symbol,
        "decimals": decimals,
        "chain_id": blockchain.chain_id,
    }


def get_token_info(blockchain: ContractAccess, token_address: str) -> dict[str, Any]:
    """Fetch ERC-20 token metadata."""
    token_addr = blockchain.validate_and_checksum_address(token_address)
    contract = blockchain.get_erc20_contract(token_addr)
    try:
        name = contract.functions.name().call()
    except Exception:
        name = "Unknown Token"
    try:
        symbol = contract.functions.symbol().call()
    except Exception:
        symbol = "TOKEN"
    try:
        decimals = contract.functions.decimals().call()
    except Exception:
        decimals = 18
    try:
        total_supply_raw = contract.functions.totalSupply().call()
        total_supply = format_token_units(total_supply_raw, decimals)
    except Exception:
        total_supply_raw = 0
        total_supply = "0"
    return {
        "token_address": token_addr,
        "name": name,
        "symbol": symbol,
        "decimals": decimals,
        "total_supply": total_supply,
        "raw_total_supply": total_supply_raw,
        "chain_id": blockchain.chain_id,
    }


def get_allowance(
    blockchain: ContractAccess, token_address: str, owner: str, spender: str
) -> dict[str, Any]:
    """Check current allowance of spender on owner's tokens."""
    token_addr = blockchain.validate_and_checksum_address(token_address)
    owner_addr = blockchain.validate_and_checksum_address(owner)
    spender_addr = blockchain.validate_and_checksum_address(spender)
    contract = blockchain.get_erc20_contract(token_addr)
    raw = contract.functions.allowance(owner_addr, spender_addr).call()
    decimals = contract.functions.decimals().call()
    return {
        "token_address": token_addr,
        "owner": owner_addr,
        "spender": spender_addr,
        "allowance": format_token_units(raw, decimals),
        "raw_allowance": raw,
        "is_unlimited": raw >= UINT256_MAX // 2,
    }


def get_transaction(blockchain: RpcAccess, tx_hash: str) -> dict[str, Any]:
    tx = blockchain.w3.eth.get_transaction(tx_hash)
    result = dict(tx)
    if "value" in result:
        result["value_eth"] = format_token_units(result["value"], 18)
    return result


def get_transaction_receipt(blockchain: RpcAccess, tx_hash: str) -> dict[str, Any]:
    try:
        receipt = blockchain.w3.eth.get_transaction_receipt(tx_hash)
        return dict(receipt)
    except TransactionNotFound:
        return {"status": "pending", "tx_hash": tx_hash}


def get_block(blockchain: RpcAccess, block_identifier: int | str = "latest") -> dict[str, Any]:
    block = blockchain.w3.eth.get_block(block_identifier)
    return dict(block)


def get_gas_price(blockchain: RpcAccess) -> dict[str, Any]:
    gas_price_wei = blockchain.w3.eth.gas_price
    latest_block = blockchain.w3.eth.get_block("latest")
    base_fee = latest_block.get("baseFeePerGas", None)
    return {
        "gas_price_wei": gas_price_wei,
        "gas_price_gwei": round(gas_price_wei / 1000000000.0, 2),
        "base_fee_per_gas": base_fee,
        "suggested_max_priority_fee_per_gas": blockchain.w3.eth.max_priority_fee
        if hasattr(blockchain.w3.eth, "max_priority_fee")
        else 1500000000,
    }


def read_contract(
    blockchain: ContractAccess,
    contract_address: str,
    abi: list[dict[str, Any]],
    function_name: str,
    *args: Any,
) -> Any:
    addr = blockchain.validate_and_checksum_address(contract_address)
    contract = blockchain.w3.eth.contract(address=addr, abi=abi)
    fn = getattr(contract.functions, function_name)
    return fn(*args).call()
