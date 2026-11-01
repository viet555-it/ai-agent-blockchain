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

    if tool_name == "get_crypto_price":
        if result.get("type") == "chainlink":
            data = result.get("data")
            if not data:
                return "❌ Không thể đọc giá ETH/USD từ Chainlink Sepolia Oracle."
            return (
                f"**Giá ETH/USD từ Chainlink Sepolia Oracle:**\n"
                f"- **Giá:** `${data.get('price_usd'):,.2f}`\n"
                f"- **Round ID:** `{data.get('round_id')}`\n"
                f"- **Thời điểm cập nhật:** {data.get('updated_at')}\n"
                f"- **Nguồn dữ liệu:** Chainlink Aggregator (`0x694AA1769357215DE4FAC081bf1f309aDC325306`)"
            )
        current = result.get("current", {})
        price = current.get("price_usd")
        if price is None:
            return "❌ Không thể lấy dữ liệu giá ETH từ CoinGecko (lỗi API / rate limit). Vui lòng thử lại sau."
        chg = current.get("change_24h_pct", 0)
        chg_sign = "+" if chg and chg > 0 else ""
        source = current.get("source", "coingecko")
        updated = current.get("updated_at", "")
        timeframe = result.get("timeframe", "24h")
        return (
            f"**Thị trường ETH/USD (Nguồn: {source}):**\n"
            f"- **Giá hiện tại:** `${price:,.2f}` ({chg_sign}{chg}% trong 24h)\n"
            f"- **Thời điểm cập nhật:** {updated}\n"
            f"- **Biểu đồ khung {timeframe.upper()}:** Đã đồng bộ dữ liệu lịch sử.\n\n"
            f"[CHART:ETH:{timeframe}]"
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
