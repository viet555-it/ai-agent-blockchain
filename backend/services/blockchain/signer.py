"""Explicit private-key signing, broadcasting and receipt waiting."""

from typing import Any

from eth_account import Account

from .access import RpcAccess


def sign_and_send_transaction(
    blockchain: RpcAccess, tx_dict: dict[str, Any], private_key: str
) -> str:
    """Sign and broadcast transaction using a private key."""
    account = Account.from_key(private_key)
    # Copy the prepared payload; only the signing account determines its sender.
    tx = dict(tx_dict)
    tx["from"] = account.address
    if "nonce" not in tx:
        tx["nonce"] = blockchain.w3.eth.get_transaction_count(account.address, "pending")
    if "chainId" not in tx:
        tx["chainId"] = blockchain.chain_id
    signed = blockchain.w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = blockchain.w3.eth.send_raw_transaction(signed.raw_transaction)
    return tx_hash.hex()


def wait_for_receipt(
    blockchain: RpcAccess, tx_hash: str, timeout: int = 120, poll_latency: float = 1.0
) -> dict[str, Any]:
    """Wait for transaction receipt."""
    receipt = blockchain.w3.eth.wait_for_transaction_receipt(
        tx_hash, timeout=timeout, poll_latency=poll_latency
    )
    return dict(receipt)
