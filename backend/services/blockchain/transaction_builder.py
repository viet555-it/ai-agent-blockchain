"""Build unsigned transaction payloads without signing or broadcasting."""

from decimal import Decimal
from typing import Any

from backend.token_amounts import format_token_units, to_token_units

from .access import BuilderAccess


def prepare_native_transfer(
    blockchain: BuilderAccess,
    from_address: str,
    to_address: str,
    amount_eth: str | int | Decimal,
    priority: str = "medium",
) -> dict[str, Any]:
    from_addr = blockchain.validate_and_checksum_address(from_address)
    to_addr = blockchain.validate_and_checksum_address(to_address)
    units = to_token_units(str(amount_eth), 18)
    nonce = blockchain.w3.eth.get_transaction_count(from_addr, "pending")
    gas_info = blockchain.get_gas_price()
    tx: dict[str, Any] = {
        "from": from_addr,
        "to": to_addr,
        "value": units,
        "nonce": nonce,
        "chainId": blockchain.chain_id,
        "gas": 21000,
    }
    if gas_info.get("base_fee_per_gas") is not None:
        base = gas_info["base_fee_per_gas"]
        priority_fee = 2000000000 if priority == "high" else 1500000000
        tx["maxPriorityFeePerGas"] = priority_fee
        tx["maxFeePerGas"] = base * 2 + priority_fee
        tx["type"] = "0x2"
    else:
        tx["gasPrice"] = gas_info["gas_price_wei"]
    return {
        "type": "native_transfer",
        "transaction": tx,
        "description": f"Transfer {format_token_units(units, 18)} ETH to {to_addr}",
        "amount_eth": format_token_units(units, 18),
        "raw_value": units,
    }


def prepare_token_transfer(
    blockchain: BuilderAccess,
    token_address: str,
    from_address: str,
    to_address: str,
    amount_token: str | int,
) -> dict[str, Any]:
    token_addr = blockchain.validate_and_checksum_address(token_address)
    from_addr = blockchain.validate_and_checksum_address(from_address)
    to_addr = blockchain.validate_and_checksum_address(to_address)
    contract = blockchain.get_erc20_contract(token_addr)
    decimals = contract.functions.decimals().call()
    symbol = contract.functions.symbol().call()
    units = to_token_units(amount_token, decimals)
    call_data = contract.encode_abi("transfer", args=[to_addr, units])
    nonce = blockchain.w3.eth.get_transaction_count(from_addr, "pending")
    tx = {
        "from": from_addr,
        "to": token_addr,
        "value": 0,
        "data": call_data,
        "nonce": nonce,
        "chainId": blockchain.chain_id,
        "gas": 65000,
        "gasPrice": blockchain.w3.eth.gas_price,
    }
    return {
        "type": "erc20_transfer",
        "transaction": tx,
        "token_symbol": symbol,
        "token_address": token_addr,
        "amount": format_token_units(units, decimals),
        "raw_amount": units,
        "description": f"Transfer {format_token_units(units, decimals)} {symbol} to {to_addr}",
    }


def prepare_token_approve(
    blockchain: BuilderAccess,
    token_address: str,
    owner_address: str,
    spender_address: str,
    amount_token: str | int,
) -> dict[str, Any]:
    token_addr = blockchain.validate_and_checksum_address(token_address)
    owner_addr = blockchain.validate_and_checksum_address(owner_address)
    spender_addr = blockchain.validate_and_checksum_address(spender_address)
    contract = blockchain.get_erc20_contract(token_addr)
    decimals = contract.functions.decimals().call()
    symbol = contract.functions.symbol().call()
    units = to_token_units(amount_token, decimals)
    call_data = contract.encode_abi("approve", args=[spender_addr, units])
    nonce = blockchain.w3.eth.get_transaction_count(owner_addr, "pending")
    tx = {
        "from": owner_addr,
        "to": token_addr,
        "value": 0,
        "data": call_data,
        "nonce": nonce,
        "chainId": blockchain.chain_id,
        "gas": 50000,
        "gasPrice": blockchain.w3.eth.gas_price,
    }
    return {
        "type": "erc20_approve",
        "transaction": tx,
        "token_symbol": symbol,
        "token_address": token_addr,
        "spender": spender_addr,
        "amount": format_token_units(units, decimals),
        "raw_amount": units,
        "description": f"Approve {spender_addr} to spend {format_token_units(units, decimals)} {symbol}",
    }


def prepare_faucet_claim(
    blockchain: BuilderAccess, token_address: str, recipient_address: str, amount_token: str | int
) -> dict[str, Any]:
    token_addr = blockchain.validate_and_checksum_address(token_address)
    recipient_addr = blockchain.validate_and_checksum_address(recipient_address)
    abi, _ = blockchain.network_manager.load_deployment_manifest(blockchain.chain_id)
    contract = blockchain.w3.eth.contract(address=token_addr, abi=abi)
    decimals = contract.functions.decimals().call()
    units = to_token_units(amount_token, decimals)
    call_data = contract.encode_abi("faucet", args=[units])
    nonce = blockchain.w3.eth.get_transaction_count(recipient_addr, "pending")
    tx = {
        "from": recipient_addr,
        "to": token_addr,
        "value": 0,
        "data": call_data,
        "nonce": nonce,
        "chainId": blockchain.chain_id,
        "gas": 90000,
        "gasPrice": blockchain.w3.eth.gas_price,
    }
    return {
        "type": "faucet_claim",
        "transaction": tx,
        "recipient": recipient_addr,
        "amount": format_token_units(units, decimals),
        "raw_amount": units,
        "description": f"Claim {format_token_units(units, decimals)} AGNT from faucet for {recipient_addr}",
    }
