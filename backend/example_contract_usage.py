"""Read tools and exact-call simulation for AgentToken. Amounts are decimal strings."""
import json
from pathlib import Path
from web3 import Web3
from web3.exceptions import ContractLogicError

if __package__:
    from .token_amounts import to_token_units, format_token_units
else:
    from token_amounts import to_token_units, format_token_units

BASE_DIR = Path(__file__).resolve().parent
ABI_DIR = BASE_DIR / "abi"


def load_contract_info(chain_id: int):
    deployment_dir = ABI_DIR / str(chain_id)
    abi_path = deployment_dir / "AgentToken_abi.json"
    manifest_path = deployment_dir / "deployment.json"
    if not abi_path.exists() or not manifest_path.exists():
        raise FileNotFoundError(f"No AgentToken deployment for chain {chain_id}; deploy to that network first")
    with manifest_path.open(encoding="utf-8") as f:
        manifest = json.load(f)
    if str(manifest.get("chainId")) != str(chain_id):
        raise ValueError("Deployment chainId does not match the RPC chain")
    with abi_path.open(encoding="utf-8") as f:
        abi = json.load(f)
    return abi, manifest


def get_agent_token_contract(w3: Web3):
    abi, manifest = load_contract_info(w3.eth.chain_id)
    address = w3.to_checksum_address(manifest["contractAddress"])
    code = w3.eth.get_code(address)
    if not code:
        raise ValueError("No contract bytecode at the configured address on this chain")
    expected_hash = manifest.get("runtimeCodeHash")
    if expected_hash and w3.keccak(code).hex().removeprefix("0x").lower() != expected_hash.removeprefix("0x").lower():
        raise ValueError("Contract bytecode does not match the deployment manifest")
    return w3.eth.contract(address=address, abi=abi)


def tool_check_balance(w3: Web3, wallet_address: str) -> dict:
    contract = get_agent_token_contract(w3)
    target = w3.to_checksum_address(wallet_address)
    raw = contract.functions.balanceOf(target).call()
    decimals = contract.functions.decimals().call()
    return {"address": target, "balance": format_token_units(raw, decimals),
            "symbol": contract.functions.symbol().call(), "raw_balance": raw}


def tool_simulate_transfer(w3: Web3, sender: str, recipient: str,
                           amount_token: str | int, *, spender: str | None = None) -> dict:
    """eth_call of the actual transfer. Pass spender for every transferFrom, even self-spending.

    A successful simulation only describes the state at the time of eth_call.
    RPC/network errors propagate; only contract reverts become isValid=False.
    """
    contract = get_agent_token_contract(w3)
    sender_addr = w3.to_checksum_address(sender)
    recipient_addr = w3.to_checksum_address(recipient)
    decimals = contract.functions.decimals().call()
    units = to_token_units(amount_token, decimals)
    caller = sender_addr if spender is None else w3.to_checksum_address(spender)
    if spender is None:
        action = contract.functions.transfer(recipient_addr, units)
    else:
        action = contract.functions.transferFrom(sender_addr, recipient_addr, units)
    try:
        valid = bool(action.call({"from": caller}))
        reason = "Valid" if valid else "Token operation returned false"
    except ContractLogicError as exc:
        valid, reason = False, str(exc)
    return {"isValid": valid, "reason": reason, "sender": sender_addr,
            "recipient": recipient_addr, "spender": spender,
            "amount": format_token_units(units, decimals), "raw_amount": units}
