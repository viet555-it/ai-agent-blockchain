"""Dry-run token operations with deployment bytecode verification."""

from typing import Any

from web3.exceptions import ContractLogicError

from backend.token_amounts import format_token_units, to_token_units

from .access import ContractAccess


def simulate_transfer(
    blockchain: ContractAccess,
    sender: str,
    recipient: str,
    amount_token: str | int,
    token_address: str | None = None,
    spender: str | None = None,
) -> dict[str, Any]:
    """Simulate real token transfer using eth_call.

    Validates caller, balances, and guardrails without modifying on-chain state.
    Contract reverts return isValid=False with exact revert reason.
    """
    sender_addr = blockchain.validate_and_checksum_address(sender)
    recipient_addr = blockchain.validate_and_checksum_address(recipient)
    if token_address is None:
        abi, manifest = blockchain.network_manager.load_deployment_manifest(blockchain.chain_id)
        token_addr = blockchain.w3.to_checksum_address(manifest["contractAddress"])
        blockchain.network_manager.verify_contract_bytecode(
            blockchain.w3, token_addr, manifest.get("runtimeCodeHash")
        )
        contract = blockchain.w3.eth.contract(address=token_addr, abi=abi)
    else:
        token_addr = blockchain.validate_and_checksum_address(token_address)
        blockchain.network_manager.verify_contract_bytecode(blockchain.w3, token_addr)
        contract = blockchain.get_erc20_contract(token_addr)
    decimals = contract.functions.decimals().call()
    units = to_token_units(amount_token, decimals)
    caller = sender_addr if spender is None else blockchain.validate_and_checksum_address(spender)
    if spender is None:
        action = contract.functions.transfer(recipient_addr, units)
    else:
        action = contract.functions.transferFrom(sender_addr, recipient_addr, units)
    try:
        valid = bool(action.call({"from": caller}))
        reason = "Valid" if valid else "Token operation returned false"
    except ContractLogicError as exc:
        valid, reason = (False, str(exc))
    return {
        "isValid": valid,
        "reason": reason,
        "sender": sender_addr,
        "recipient": recipient_addr,
        "spender": spender,
        "token_address": token_addr,
        "amount": format_token_units(units, decimals),
        "raw_amount": units,
        "chain_id": blockchain.chain_id,
    }
