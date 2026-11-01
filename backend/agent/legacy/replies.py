"""Legacy replies helpers; orchestration remains in BlockchainAgent."""

from typing import Any

from backend.agent.language import is_conversational_query, resolve_language
from backend.rag.rag_adapter import RAGSearchResult


def format_read_reply(
    tool_name: str,
    result: dict[str, Any] | None,
    error: str | None,
    rag_result: RAGSearchResult,
    language: str = "auto",
) -> str:
    lang = resolve_language(language, "")

    if error:
        return f"❌ {('Lỗi truy vấn blockchain: ' + str(error)) if lang == 'vi' else ('Failed to fetch blockchain data: ' + str(error))}"

    if not result:
        return "Không có dữ liệu trả về từ blockchain node." if lang == "vi" else "No data returned from the blockchain node."

    if tool_name == "get_native_balance":
        if lang == "vi":
            return (
                f"Ví `{result.get('address')}` có số dư gốc là "
                f"**{result.get('balance')} {result.get('symbol')}** trên mạng {result.get('network')} (Chain ID {result.get('chain_id')})."
            )
        return (
            f"Wallet `{result.get('address')}` has a native balance of "
            f"**{result.get('balance')} {result.get('symbol')}** on {result.get('network')} (Chain {result.get('chain_id')})."
        )

    if tool_name == "get_token_balance":
        if lang == "vi":
            return (
                f"Ví `{result.get('wallet_address')}` đang giữ **{result.get('balance')} {result.get('symbol')}** token "
                f"(Hợp đồng token: `{result.get('token_address')}`)."
            )
        return (
            f"Wallet `{result.get('wallet_address')}` holds **{result.get('balance')} {result.get('symbol')}** tokens "
            f"(Token contract: `{result.get('token_address')}`)."
        )

    if tool_name == "get_token_info":
        if lang == "vi":
            return (
                f"Chi tiết hợp đồng **{result.get('name')} ({result.get('symbol')})**:\n"
                f"- Địa chỉ hợp đồng: `{result.get('token_address')}`\n"
                f"- Số thập phân: {result.get('decimals')}\n"
                f"- Tổng cung: {result.get('total_supply')} {result.get('symbol')}\n"
                f"- Chain ID: {result.get('chain_id')}"
            )
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
        if lang == "vi":
            return (
                f"Giá gas hiện tại trên mạng:\n"
                f"- Phí gas: **{result.get('gas_price_gwei')} Gwei**\n"
                f"- Phí cơ bản (Base Fee): **{base_gwei} Gwei**\n"
                f"- Phí ưu tiên tối đa: **1.5 Gwei**"
            )
        return (
            f"Current Gas Prices on network:\n"
            f"- Gas Price: **{result.get('gas_price_gwei')} Gwei**\n"
            f"- Base Fee: **{base_gwei} Gwei**\n"
            f"- Max Priority Fee: **1.5 Gwei**"
        )

    if tool_name == "simulate_transfer":
        status = "✅ HỢP LỆ" if result.get("isValid") else "❌ REVERT" if lang == "vi" else ("✅ VALID" if result.get("isValid") else "❌ REVERTED")
        if lang == "vi":
            return (
                f"Kết quả giả lập giao dịch: **{status}**\n"
                f"- Trạng thái: {result.get('reason')}\n"
                f"- Người gửi: `{result.get('sender')}`\n"
                f"- Người nhận: `{result.get('recipient')}`\n"
                f"- Số lượng: {result.get('amount')} AGNT"
            )
        return (
            f"Simulation Dry-Run Result: **{status}**\n"
            f"- Status: {result.get('reason')}\n"
            f"- From: `{result.get('sender')}`\n"
            f"- To: `{result.get('recipient')}`\n"
            f"- Amount: {result.get('amount')} AGNT"
        )

    if tool_name in {"get_crypto_price", "get_token_price"}:
        sym = result.get("symbol", "ETH")
        if result.get("type") == "chainlink":
            data = result.get("data") or result
            p = data.get("price_usd")
            if p is None:
                return "❌ Không thể đọc giá ETH/USD từ Chainlink Sepolia Oracle." if lang == "vi" else "❌ Unable to read ETH/USD price from Chainlink Sepolia Oracle."
            if lang == "vi":
                return (
                    f"**Giá ETH/USD từ Chainlink Sepolia Oracle:**\n"
                    f"- **Giá:** `${p:,.2f}`\n"
                    f"- **Round ID:** `{data.get('round_id')}`\n"
                    f"- **Thời điểm cập nhật:** {data.get('updated_at')}\n"
                    f"- **Nguồn dữ liệu:** Chainlink Aggregator (`0x694AA1769357215DE4FAC081bf1f309aDC325306`)"
                )
            return (
                f"**ETH/USD Price from Chainlink Sepolia Oracle:**\n"
                f"- **Price:** `${p:,.2f}`\n"
                f"- **Round ID:** `{data.get('round_id')}`\n"
                f"- **Updated:** {data.get('updated_at')}\n"
                f"- **Data Source:** Chainlink Aggregator (`0x694AA1769357215DE4FAC081bf1f309aDC325306`)"
            )

        current = result.get("current") or result
        price = current.get("price_usd")
        if price is None:
            return (
                f"❌ Không thể lấy dữ liệu giá {sym} từ CoinGecko (lỗi API / rate limit). Vui lòng thử lại sau."
                if lang == "vi"
                else f"❌ Failed to fetch {sym} price data from CoinGecko (API error or rate limit). Please try again later."
            )
        chg = current.get("change_24h_pct", 0)
        chg_sign = "+" if chg and chg > 0 else ""
        source = current.get("source", "coingecko")
        updated = current.get("updated_at", "")
        timeframe = result.get("timeframe", "24h")
        marker = result.get("chart_marker", f"[CHART:{sym}:{timeframe}]")

        if lang == "vi":
            return (
                f"**Thị trường {sym}/USD (Nguồn: {source}):**\n"
                f"- **Giá hiện tại:** `${price:,.2f}` ({chg_sign}{chg}% trong 24h)\n"
                f"- **Thời điểm cập nhật:** {updated}\n"
                f"- **Biểu đồ khung {timeframe.upper()}:** Đã đồng bộ dữ liệu lịch sử.\n\n"
                f"{marker}"
            )
        return (
            f"**{sym}/USD Market (Source: {source}):**\n"
            f"- **Current Price:** `${price:,.2f}` ({chg_sign}{chg}% in 24h)\n"
            f"- **Updated:** {updated}\n"
            f"- **{timeframe.upper()} Chart:** Historical data synced.\n\n"
            f"{marker}"
        )

    return f"Blockchain operation completed successfully: {result}"


def generate_faq_reply(query: str, rag_result: RAGSearchResult, language: str = "auto") -> str:
    """Answer informational questions or greetings with localized context."""
    lang = resolve_language(language, query)

    # Conversational greetings / general pleasantries
    if is_conversational_query(query):
        if lang == "vi":
            return (
                "Xin chào! Tôi là trợ lý AI Blockchain của bạn trên mạng Ethereum Sepolia. "
                "Tôi có thể giúp bạn kiểm tra số dư ví, tra cứu thông tin token, xem giá thị trường ETH/BTC/LINK "
                "với biểu đồ tương tác, kiểm tra phí gas và chuẩn bị các giao dịch an toàn được bảo vệ bởi Guardrail."
            )
        return (
            "Hello! I am your AI Blockchain Assistant on the Ethereum Sepolia network. "
            "I can help you check wallet balances, inspect token contracts, monitor market prices (ETH/BTC/LINK) "
            "with interactive charts, check gas prices, and prepare safe transactions protected by our Guardrail Policy Engine."
        )

    if rag_result.has_relevant_context and rag_result.documents:
        doc = rag_result.documents[0]
        return f"{doc.excerpt}\n\n> **Source:** *{doc.title}* ({doc.source_file})"

    if lang == "vi":
        return (
            "Tôi là trợ lý AI Blockchain của bạn. Bạn có thể yêu cầu tôi kiểm tra số dư ví, "
            "tra cứu hợp đồng token, xem giá ETH tuần này kèm biểu đồ, kiểm tra phí gas hoặc chuẩn bị giao dịch chuyển tiền. "
            "Mọi giao dịch đều được kiểm soát bởi Policy Guardrail và cần bạn duyệt trên giao diện."
        )
    return (
        "I am your AI Blockchain Assistant. You can ask me to check wallet balances, "
        "inspect token contracts, check crypto prices (e.g. 'ETH price this week'), check gas prices, or prepare transfers. "
        "All transactions are protected by our security guardrail and require human confirmation."
    )
