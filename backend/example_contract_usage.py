"""
Ví dụ tương tác giữa Python Backend / AI Agent và Smart Contract AgentToken
Sử dụng thư viện: pip install web3
"""

import json
from pathlib import Path
from web3 import Web3

# 1. Đường dẫn tới file ABI và thông tin deployment đã được export tự động
BASE_DIR = Path(__file__).resolve().parent
ABI_PATH = BASE_DIR / "abi" / "AgentToken_abi.json"
DEPLOYMENT_PATH = BASE_DIR / "abi" / "deployment.json"

def load_contract_info():
    if not ABI_PATH.exists() or not DEPLOYMENT_PATH.exists():
        raise FileNotFoundError(
            "Chưa tìm thấy file ABI hoặc deployment.json! "
            "Hãy chạy `npx hardhat run scripts/deploy.js` ở thư mục contracts trước."
        )

    with open(ABI_PATH, "r", encoding="utf-8") as f:
        abi = json.load(f)

    with open(DEPLOYMENT_PATH, "r", encoding="utf-8") as f:
        deploy_info = json.load(f)

    return abi, deploy_info["contractAddress"]

def get_agent_token_contract(w3: Web3):
    abi, address = load_contract_info()
    checksum_address = w3.to_checksum_address(address)
    return w3.eth.contract(address=checksum_address, abi=abi)

# ==========================================
# CÁC HÀM CUNG CẤP CHO AI AGENT TOOLS
# ==========================================

def tool_check_balance(w3: Web3, wallet_address: str) -> dict:
    """Read Tool: Kiểm tra số dư token AGNT của một ví."""
    contract = get_agent_token_contract(w3)
    target = w3.to_checksum_address(wallet_address)
    raw_balance = contract.functions.balanceOf(target).call()
    decimals = contract.functions.decimals().call()
    symbol = contract.functions.symbol().call()
    
    balance_formatted = raw_balance / (10 ** decimals)
    return {
        "address": target,
        "balance": balance_formatted,
        "symbol": symbol,
        "raw_balance": raw_balance
    }

def tool_simulate_transfer(w3: Web3, sender: str, recipient: str, amount_token: float) -> dict:
    """Guardrail Tool: Kiểm tra (Dry-run) xem giao dịch có hợp lệ không trước khi ký gửi."""
    contract = get_agent_token_contract(w3)
    sender_addr = w3.to_checksum_address(sender)
    recipient_addr = w3.to_checksum_address(recipient)
    decimals = contract.functions.decimals().call()
    amount_wei = int(amount_token * (10 ** decimals))

    is_valid, reason = contract.functions.validateTransfer(
        sender_addr,
        recipient_addr,
        amount_wei
    ).call()

    return {
        "isValid": is_valid,
        "reason": reason,
        "sender": sender_addr,
        "recipient": recipient_addr,
        "amount": amount_token
    }

if __name__ == "__main__":
    print("AgentToken Python Helper Module đã sẵn sàng!")
    print(f"ABI file: {ABI_PATH}")
    print(f"Deployment info: {DEPLOYMENT_PATH}")
