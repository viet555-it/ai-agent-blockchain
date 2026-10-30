"""Legacy intent helpers; orchestration remains in BlockchainAgent."""

import re
from typing import Any


def analyze_intent(query: str, active_wallet: str) -> tuple[str, dict[str, Any]]:
    q = query.lower().strip()
    params: dict[str, Any] = {"wallet": active_wallet}

    # Extract Ethereum address if present
    eth_matches = re.findall(r"0x[a-fA-F0-9]{40}", query)
    if eth_matches:
        params["target_address"] = eth_matches[0]
        if len(eth_matches) > 1:
            params["second_address"] = eth_matches[1]

    # Extract amount if present (e.g. 10.5, 50, 0.1)
    amt_match = re.search(r"\b([0-9]+(?:\.[0-9]+)?)\s*(?:eth|agnt|tokens?|ether)?\b", q)
    if amt_match:
        params["amount"] = amt_match.group(1)

    # Route intent
    if any(w in q for w in ["check balance", "số dư", "balance", "ví còn bao nhiêu"]):
        if "eth" in q or "native" in q:
            return "check_native_balance", params
        return "check_token_balance", params

    if any(w in q for w in ["token info", "thông tin token", "token contract", "contract info"]):
        return "get_token_info", params

    if any(w in q for w in ["gas price", "gas", "phí gas", "base fee"]):
        return "get_gas_price", params

    if any(w in q for w in ["faucet", "claim", "nhận token", "xin token"]):
        return "claim_faucet", params

    if any(w in q for w in ["transfer", "send", "chuyển", "gửi"]):
        if "eth" in q:
            return "send_native", params
        return "send_token", params

    if any(w in q for w in ["simulate", "giả lập", "dry run", "dry-run", "kiểm tra trước"]):
        return "simulate_transfer", params

    if any(w in q for w in ["recent transactions", "giao dịch", "history", "tx"]):
        return "recent_transactions", params

    if any(w in q for w in ["price", "giá", "biểu đồ", "chart", "tỷ giá", "market"]):
        if "chainlink" in q or "oracle" in q:
            params["source"] = "chainlink"
        if "7d" in q or "7 ngày" in q or "tuần" in q:
            params["timeframe"] = "7d"
        elif "1h" in q or "1 giờ" in q:
            params["timeframe"] = "1h"
        else:
            params["timeframe"] = "24h"
        return "get_crypto_price", params

    return "general_query", params


def select_tool(intent: str) -> str:
    mapping = {
        "check_native_balance": "get_native_balance",
        "check_token_balance": "get_token_balance",
        "get_token_info": "get_token_info",
        "get_gas_price": "get_gas_price",
        "claim_faucet": "faucet_claim",
        "send_native": "native_transfer",
        "send_token": "erc20_transfer",
        "simulate_transfer": "simulate_transfer",
        "recent_transactions": "get_recent_transactions",
        "get_crypto_price": "get_crypto_price",
    }
    return mapping.get(intent, "none")
