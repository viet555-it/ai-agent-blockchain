"""Legacy replies helpers; orchestration remains in BlockchainAgent."""

from typing import Any

from backend.rag.rag_adapter import RAGSearchResult


def format_read_reply(
    tool_name: str,
    result: dict[str, Any] | None,
    error: str | None,
    rag_result: RAGSearchResult,
) -> str:
    if error:
        return f"❌ Failed to fetch blockchain data: {error}"

    if not result:
        return "No data returned from the blockchain node."

    if tool_name == "get_native_balance":
        return (
            f"Wallet `{result.get('address')}` has a native balance of "
            f"**{result.get('balance')} {result.get('symbol')}** on {result.get('network')} (Chain {result.get('chain_id')})."
        )

    if tool_name == "get_token_balance":
        return (
            f"Wallet `{result.get('wallet_address')}` holds **{result.get('balance')} {result.get('symbol')}** tokens "
            f"(Token contract: `{result.get('token_address')}`)."
        )

    if tool_name == "get_token_info":
        return (
            f"**{result.get('name')} ({result.get('symbol')})** Contract Details:\n"
            f"- Contract Address: `{result.get('token_address')}`\n"
            f"- Decimals: {result.get('decimals')}\n"
            f"- Total Supply: {result.get('total_supply')} {result.get('symbol')}\n"
            f"- Chain ID: {result.get('chain_id')}"
        )

    if tool_name == "get_gas_price":
        base = result.get("base_fee_per_gas")
        base_gwei = round(base / 1e9, 2) if base else "N/A"
        return (
            f"Current Gas Prices on network:\n"
            f"- Gas Price: **{result.get('gas_price_gwei')} Gwei**\n"
            f"- Base Fee: **{base_gwei} Gwei**\n"
            f"- Max Priority Fee: **1.5 Gwei**"
        )

    if tool_name == "simulate_transfer":
        status = "✅ VALID" if result.get("isValid") else "❌ REVERTED"
        return (
            f"Simulation Dry-Run Result: **{status}**\n"
            f"- Status: {result.get('reason')}\n"
            f"- From: `{result.get('sender')}`\n"
            f"- To: `{result.get('recipient')}`\n"
            f"- Amount: {result.get('amount')} AGNT"
        )

    return f"Blockchain operation completed successfully: {result}"


def generate_faq_reply(query: str, rag_result: RAGSearchResult) -> str:
    """Answer informational questions with RAG context."""
    if rag_result.has_relevant_context:
        doc = rag_result.documents[0]
        return f"{doc.excerpt}\n\n> **Source:** *{doc.title}* ({doc.source_file})"
    return (
        "I am your AI Blockchain Assistant. You can ask me to check wallet balances, "
        "inspect token contracts, simulate transactions, check gas prices, or prepare transfers. "
        "How can I assist you with the blockchain today?"
    )
