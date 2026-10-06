import json
from typing import Any, Dict, List, Tuple
from app.services.blockchain import BlockchainService, KNOWN_CONTRACTS
from app.services.guardrail import guardrail_engine
from app.models.schemas import ToolExecutionResult, TransactionAction, GuardrailReport
from app.core.config import settings

WEB3_TOOLS_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_native_balance",
            "description": "Kiểm tra số dư tiền ảo native (ETH, Sepolia ETH, POL...) của một địa chỉ ví EVM.",
            "parameters": {
                "type": "object",
                "properties": {
                    "wallet_address": {
                        "type": "string",
                        "description": "Địa chỉ ví Ethereum (ví dụ: 0x71C... hoặc ví người dùng hiện tại)"
                    }
                },
                "required": ["wallet_address"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_token_balance",
            "description": "Kiểm tra số dư token ERC-20 (như USDT, USDC, LINK, WETH...) của một địa chỉ ví.",
            "parameters": {
                "type": "object",
                "properties": {
                    "wallet_address": {
                        "type": "string",
                        "description": "Địa chỉ ví cần tra cứu số dư token"
                    },
                    "token_address": {
                        "type": "string",
                        "description": "Địa chỉ hợp đồng thông minh (Smart Contract) của token ERC-20 hoặc ký hiệu quen thuộc (USDC, LINK, WETH)"
                    }
                },
                "required": ["wallet_address", "token_address"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_transfer_native",
            "description": "Tạo giao dịch gửi native coin (ETH / Sepolia ETH) từ ví người dùng đến ví nhận. Được kiểm duyệt qua Guardrail Policy trước khi tạo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to_address": {
                        "type": "string",
                        "description": "Địa chỉ ví người nhận (bắt đầu bằng 0x)"
                    },
                    "amount_eth": {
                        "type": "number",
                        "description": "Số lượng ETH muốn gửi (ví dụ: 0.01, 0.05)"
                    }
                },
                "required": ["to_address", "amount_eth"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_transfer_erc20",
            "description": "Tạo giao dịch gửi token ERC-20 (như USDC, LINK...) từ ví người dùng đến ví nhận.",
            "parameters": {
                "type": "object",
                "properties": {
                    "token_address": {
                        "type": "string",
                        "description": "Địa chỉ smart contract của token ERC-20 (hoặc USDC, LINK)"
                    },
                    "to_address": {
                        "type": "string",
                        "description": "Địa chỉ ví nhận token"
                    },
                    "amount": {
                        "type": "number",
                        "description": "Số lượng token muốn gửi (ví dụ: 10, 50.5)"
                    }
                },
                "required": ["token_address", "to_address", "amount"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_transaction_status",
            "description": "Kiểm tra trạng thái (thành công, thất bại, đang chờ) và chi tiết của một giao dịch on-chain theo mã băm (tx_hash).",
            "parameters": {
                "type": "object",
                "properties": {
                    "tx_hash": {
                        "type": "string",
                        "description": "Mã băm giao dịch (transaction hash 66 ký tự bắt đầu bằng 0x)"
                    }
                },
                "required": ["tx_hash"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_network_info",
            "description": "Lấy thông tin mạng blockchain hiện tại (block number mới nhất, chain ID, tên mạng).",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_mint_nft",
            "description": "Tạo giao dịch Mint NFT đại diện (ERC-721) về ví người dùng.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nft_contract_address": {
                        "type": "string",
                        "description": "Địa chỉ Smart Contract NFT (nếu để trống hoặc default, hệ thống dùng mock contract)"
                    },
                    "recipient_address": {
                        "type": "string",
                        "description": "Địa chỉ ví nhận NFT"
                    },
                    "token_uri": {
                        "type": "string",
                        "description": "URI metadata của NFT"
                    }
                },
                "required": ["recipient_address"]
            }
        }
    }
]

def resolve_token_shortcut(token_addr_or_symbol: str, chain_id: int) -> str:
    cleaned = token_addr_or_symbol.strip().upper()
    if chain_id in KNOWN_CONTRACTS and cleaned in KNOWN_CONTRACTS[chain_id]:
        return KNOWN_CONTRACTS[chain_id][cleaned]
    return token_addr_or_symbol

def execute_tool(
    name: str,
    args: Dict[str, Any],
    blockchain_service: BlockchainService
) -> ToolExecutionResult:
    try:
        if name == "get_native_balance":
            wallet_address = args.get("wallet_address")
            data = blockchain_service.get_native_balance(wallet_address)
            return ToolExecutionResult(
                tool_name=name,
                status="success",
                result=data
            )
            
        elif name == "get_token_balance":
            wallet_addr = args.get("wallet_address")
            token_input = args.get("token_address")
            token_addr = resolve_token_shortcut(token_input, blockchain_service.chain_id)
            data = blockchain_service.get_token_balance(token_addr, wallet_addr)
            return ToolExecutionResult(
                tool_name=name,
                status="success",
                result=data
            )
            
        elif name == "prepare_transfer_native":
            to_address = args.get("to_address")
            amount_eth = args.get("amount_eth")
            
            # Guardrail Policy Evaluation
            guard_eval = guardrail_engine.evaluate_transaction(
                tx_type="transfer_native",
                to_address=to_address,
                value_eth=str(amount_eth)
            )
            
            if not guard_eval["is_safe"]:
                return ToolExecutionResult(
                    tool_name=name,
                    status="blocked_by_guardrail",
                    result={
                        "error": guard_eval["block_reason"],
                        "guardrail": guard_eval
                    }
                )

            tx_data = blockchain_service.prepare_native_transfer(to_address, amount_eth)
            tx_data["guardrail"] = guard_eval
            action = TransactionAction(**tx_data)
            return ToolExecutionResult(
                tool_name=name,
                status="pending_signature",
                result=tx_data,
                action_required=action
            )
            
        elif name == "prepare_transfer_erc20":
            token_input = args.get("token_address")
            token_addr = resolve_token_shortcut(token_input, blockchain_service.chain_id)
            to_address = args.get("to_address")
            amount = args.get("amount")
            
            # Guardrail Policy Evaluation
            guard_eval = guardrail_engine.evaluate_transaction(
                tx_type="transfer_token",
                to_address=to_address,
                token_amount=str(amount)
            )
            
            if not guard_eval["is_safe"]:
                return ToolExecutionResult(
                    tool_name=name,
                    status="blocked_by_guardrail",
                    result={
                        "error": guard_eval["block_reason"],
                        "guardrail": guard_eval
                    }
                )

            tx_data = blockchain_service.prepare_erc20_transfer(token_addr, to_address, amount)
            tx_data["guardrail"] = guard_eval
            action = TransactionAction(**tx_data)
            return ToolExecutionResult(
                tool_name=name,
                status="pending_signature",
                result=tx_data,
                action_required=action
            )
            
        elif name == "get_transaction_status":
            tx_hash = args.get("tx_hash")
            data = blockchain_service.get_transaction_status(tx_hash)
            return ToolExecutionResult(
                tool_name=name,
                status="success",
                result=data
            )
            
        elif name == "get_network_info":
            block_num = blockchain_service.get_latest_block_number()
            is_conn = blockchain_service.is_connected()
            return ToolExecutionResult(
                tool_name=name,
                status="success",
                result={
                    "chain_id": blockchain_service.chain_id,
                    "chain_name": settings.CHAIN_NAME,
                    "latest_block": block_num,
                    "rpc_connected": is_conn,
                    "explorer_url": settings.EXPLORER_URL
                }
            )
            
        elif name == "prepare_mint_nft":
            recipient = args.get("recipient_address")
            nft_contract = args.get("nft_contract_address") or "0x8888888888888888888888888888888888888888"
            token_uri = args.get("token_uri") or "ipfs://bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
            
            guard_eval = guardrail_engine.evaluate_transaction(
                tx_type="mint_nft",
                to_address=recipient
            )
            
            tx_data = blockchain_service.prepare_nft_mint(nft_contract, recipient, token_uri)
            tx_data["guardrail"] = guard_eval
            action = TransactionAction(**tx_data)
            return ToolExecutionResult(
                tool_name=name,
                status="pending_signature",
                result=tx_data,
                action_required=action
            )
            
        else:
            return ToolExecutionResult(
                tool_name=name,
                status="error",
                result=f"Unknown tool: '{name}'"
            )
    except Exception as e:
        return ToolExecutionResult(
            tool_name=name,
            status="error",
            result=f"Lỗi khi thực thi tool {name}: {str(e)}"
        )
