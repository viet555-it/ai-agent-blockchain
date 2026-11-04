"""Read the active AgentToken's transfer ceiling and administrative authority."""

from web3 import Web3

from backend.token_amounts import format_token_units

LIMIT_ABI = [
    {
        "type": "function",
        "name": name,
        "inputs": [],
        "outputs": [{"type": output}],
        "stateMutability": "view",
    }
    for name, output in (
        ("maxTransferLimit", "uint256"),
        ("decimals", "uint8"),
        ("owner", "address"),
    )
]


def read_transfer_ceiling(blockchain, address):
    contract = blockchain.get_erc20_contract(address, LIMIT_ABI)
    raw = contract.functions.maxTransferLimit().call()
    decimals = contract.functions.decimals().call()
    owner = contract.functions.owner().call()
    if (
        type(raw) is not int
        or raw <= 0
        or type(decimals) is not int
        or not 0 <= decimals <= 255
        or not Web3.is_address(owner)
    ):
        raise ValueError("Unable to verify AgentToken transfer ceiling")
    return {
        "address": address,
        "chain_id": blockchain.chain_id,
        "per_tx_limit": format_token_units(raw, decimals),
        "raw_limit": str(raw),
        "decimals": decimals,
        "owner": Web3.to_checksum_address(owner),
        "setter_selector": "0x"
        + Web3.keccak(text="setMaxTransferLimit(uint256)")[:4].hex().removeprefix("0x"),
    }
