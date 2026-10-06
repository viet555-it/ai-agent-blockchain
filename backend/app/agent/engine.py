import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from openai import OpenAI

from app.core.config import settings
from app.services.blockchain import BlockchainService
from app.services.guardrail import guardrail_engine
from app.services.rag import rag_service
from app.agent.tools import WEB3_TOOLS_DEFINITIONS, execute_tool
from app.models.schemas import ChatMessage, ChatResponse, ToolExecutionResult, TransactionAction, RAGChunk

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Bạn là một Web3 AI Agent thông minh, an toàn và chuyên nghiệp.
Nhiệm vụ của bạn là hỗ trợ người dùng tương tác với công nghệ Blockchain và Smart Contracts thông qua ngôn ngữ tự nhiên.

Bạn có khả năng:
1. Tra cứu số dư Native coin (ETH, Sepolia ETH...) và các token ERC-20 (USDC, USDT, LINK, WETH...).
2. Soạn thảo và chuẩn bị giao dịch chuyển tiền (ETH, Token) an toàn để người dùng ký ví (MetaMask).
3. Soạn thảo giao dịch Mint NFT hoặc tương tác hợp đồng thông minh.
4. Tra cứu trạng thái giao dịch (Transaction status) theo tx_hash.
5. Giải thích các khái niệm Blockchain, phí Gas, Smart contract một cách dễ hiểu.

Quy tắc Bảo mật (Guardrail & Security Policies):
- Mọi giao dịch WRITE (chuyển tiền, mint NFT) ĐỀU PHẢI tuân theo Guardrail Policy (hạn mức tối đa ETH, Whitelist/Blacklist).
- KHÔNG BAO GIỜ tự ý ký giao dịch riêng tư; PHẢI trả về đề xuất giao dịch để người dùng tự tay xác nhận trên ví (Human-in-the-loop).
- Nếu giao dịch bị Guardrail chặn (vượt hạn mức hoặc địa chỉ có rủi ro), hãy giải thích rõ lý do cho người dùng.
- Trả lời bằng tiếng Việt rõ ràng, ngắn gọn, có định dạng Markdown đẹp mắt (bảng, danh sách, in đậm).
"""

class AgentEngine:
    def __init__(self, rpc_url: Optional[str] = None, chain_id: Optional[int] = None):
        self.blockchain_service = BlockchainService(rpc_url=rpc_url, chain_id=chain_id)
        
    def _get_client(self, custom_api_key: Optional[str] = None) -> Optional[OpenAI]:
        key = custom_api_key or settings.OPENAI_API_KEY
        if not key or key.strip() == "" or key.startswith("your_"):
            return None
        return OpenAI(api_key=key)

    async def process_chat(
        self,
        message: str,
        wallet_address: Optional[str] = None,
        conversation_history: Optional[List[ChatMessage]] = None,
        custom_api_key: Optional[str] = None
    ) -> ChatResponse:
        client = self._get_client(custom_api_key)
        
        # 1. RAG Context Retrieval
        retrieved_docs = rag_service.retrieve(message, top_k=2)
        rag_chunks = [
            RAGChunk(
                id=d["id"],
                title=d["title"],
                category=d["category"],
                content=d["content"]
            )
            for d in retrieved_docs
        ]
        
        rag_context_text = "\n\n[Tài liệu RAG tham khảo]:\n" + "\n---\n".join(
            [f"**{d['title']}** ({d['category']}):\n{d['content']}" for d in retrieved_docs]
        )

        # 2. Format history
        history: List[Dict[str, Any]] = []
        if conversation_history:
            for msg in conversation_history:
                history.append(msg.model_dump(exclude_none=True))
                
        # 3. Contextual prompt
        user_context_info = ""
        if wallet_address:
            user_context_info += f"\n[Thông tin người dùng hiện tại]: Ví đang kết nối là `{wallet_address}` trên mạng Chain ID `{self.blockchain_service.chain_id}`."
            
        full_system_prompt = SYSTEM_PROMPT + user_context_info + rag_context_text

        # Heuristic fallback if no OpenAI API key provided
        if not client:
            return self._fallback_rule_agent(message, wallet_address, conversation_history, rag_chunks)
            
        try:
            messages = [{"role": "system", "content": full_system_prompt}]
            messages.extend(history)
            messages.append({"role": "user", "content": message})
            
            # OpenAI Tool Calling
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=messages,
                tools=WEB3_TOOLS_DEFINITIONS,
                tool_choice="auto"
            )
            
            response_message = response.choices[0].message
            tool_calls = response_message.tool_calls
            tool_results: List[ToolExecutionResult] = []
            proposed_tx: Optional[TransactionAction] = None
            guard_status = "PASSED"

            if tool_calls:
                messages.append(response_message)
                
                for tool_call in tool_calls:
                    fn_name = tool_call.function.name
                    try:
                        fn_args = json.loads(tool_call.function.arguments)
                    except Exception:
                        fn_args = {}
                        
                    if "wallet_address" in fn_args and (not fn_args["wallet_address"] or fn_args["wallet_address"] == "current") and wallet_address:
                        fn_args["wallet_address"] = wallet_address
                        
                    result = execute_tool(fn_name, fn_args, self.blockchain_service)
                    tool_results.append(result)
                    
                    if result.status == "blocked_by_guardrail":
                        guard_status = "BLOCKED"
                    
                    if result.action_required:
                        proposed_tx = result.action_required

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": fn_name,
                        "content": json.dumps(result.result, ensure_ascii=False)
                    })
                    
                second_response = client.chat.completions.create(
                    model=settings.OPENAI_MODEL,
                    messages=messages
                )
                final_content = second_response.choices[0].message.content or ""
            else:
                final_content = response_message.content or ""

            new_history: List[ChatMessage] = []
            if conversation_history:
                new_history.extend(conversation_history)
            new_history.append(ChatMessage(role="user", content=message))
            new_history.append(ChatMessage(role="assistant", content=final_content))

            return ChatResponse(
                response=final_content,
                conversation_history=new_history,
                tool_results=tool_results,
                proposed_transaction=proposed_tx,
                rag_context=rag_chunks,
                guardrail_status=guard_status
            )
            
        except Exception as e:
            logger.error(f"OpenAI error, falling back to rule agent: {e}")
            return self._fallback_rule_agent(message, wallet_address, conversation_history, rag_chunks, error_note=str(e))

    def _fallback_rule_agent(
        self,
        message: str,
        wallet_address: Optional[str] = None,
        conversation_history: Optional[List[ChatMessage]] = None,
        rag_chunks: Optional[List[RAGChunk]] = None,
        error_note: Optional[str] = None
    ) -> ChatResponse:
        """
        Rule-based heuristic Agent with full Guardrail & Tool integration.
        """
        msg_lower = message.lower().strip()
        tool_results: List[ToolExecutionResult] = []
        proposed_tx: Optional[TransactionAction] = None
        guard_status = "PASSED"
        reply = ""

        addresses = re.findall(r"0x[a-fA-F0-9]{40}", message)
        tx_hashes = re.findall(r"0x[a-fA-F0-9]{64}", message)
        amounts = re.findall(r"\b\d+(?:\.\d+)?\b", message)

        if tx_hashes:
            tx_h = tx_hashes[0]
            res = execute_tool("get_transaction_status", {"tx_hash": tx_h}, self.blockchain_service)
            tool_results.append(res)
            data = res.result
            if data.get("status") == "success":
                reply = f"✅ **Giao dịch đã xác nhận thành công trên On-chain!**\n\n- **TxHash:** `{tx_h}`\n- **Block:** `#{data.get('block_number')}`\n- **Từ:** `{data.get('from_address')}`\n- **Đến:** `{data.get('to_address')}`\n- **Giá trị:** `{data.get('value')} ETH`\n- [Xem trên Etherscan]({data.get('explorer_url')})"
            else:
                reply = f"ℹ️ **Trạng thái giao dịch:** `{data.get('status')}`\n- **TxHash:** `{tx_h}`\n- [Xem trên Etherscan]({data.get('explorer_url')})"

        elif any(k in msg_lower for k in ["chuyển", "gửi", "send", "transfer"]):
            amount = float(amounts[0]) if amounts else 0.001
            target_addr = addresses[0] if addresses else (wallet_address or "0x71C9491133502447972423423719011234567890")
            
            if any(t in msg_lower for t in ["usdc", "usdt", "link"]):
                token_sym = "USDC" if "usdc" in msg_lower else ("USDT" if "usdt" in msg_lower else "LINK")
                res = execute_tool("prepare_transfer_erc20", {
                    "token_address": token_sym,
                    "to_address": target_addr,
                    "amount": amount
                }, self.blockchain_service)
            else:
                res = execute_tool("prepare_transfer_native", {
                    "to_address": target_addr,
                    "amount_eth": amount
                }, self.blockchain_service)
                
            tool_results.append(res)
            
            if res.status == "blocked_by_guardrail":
                guard_status = "BLOCKED"
                err_msg = res.result.get("error") if isinstance(res.result, dict) else str(res.result)
                reply = f"🛡️ **Giao dịch bị chặn bởi Guardrail Policy Engine!**\n\n> [!WARNING]\n> **Lý do:** {err_msg}\n\n*Hệ thống bảo vệ tài sản tự động đã phát hiện hành động vượt quá giới hạn an toàn.*"
            elif res.action_required:
                proposed_tx = res.action_required
                reply = (
                    f"🛡️ **Kiểm tra Guardrail Policy: PASSED**\n\n"
                    f"Tôi đã tạo đề xuất giao dịch an toàn cho bạn:\n"
                    f"- **Số lượng:** `{amount}`\n"
                    f"- **Địa chỉ nhận:** `{target_addr}`\n"
                    f"- **Mạng lưới:** {settings.CHAIN_NAME}\n\n"
                    f"Vui lòng kiểm tra thẻ giao dịch bên dưới và bấm **'Xác nhận & Ký trên ví'** (Human-in-the-loop)."
                )

        elif any(k in msg_lower for k in ["mint", "nft", "tạo nft"]):
            target_addr = addresses[0] if addresses else (wallet_address or "0x71C9491133502447972423423719011234567890")
            res = execute_tool("prepare_mint_nft", {
                "recipient_address": target_addr
            }, self.blockchain_service)
            tool_results.append(res)
            if res.action_required:
                proposed_tx = res.action_required
            reply = f"🎨 Tôi đã tạo yêu cầu **Mint NFT** mẫu cho bạn về ví `{target_addr}`.\n\nNhấn vào nút **'Ký & Mint NFT'** bên dưới để gửi giao dịch lên blockchain."

        elif any(k in msg_lower for k in ["số dư", "balance", "ví", "tiền", "check"]):
            target_addr = addresses[0] if addresses else wallet_address
            if not target_addr:
                reply = "Vui lòng kết nối ví Web3 hoặc nhập địa chỉ ví (0x...) để tôi có thể tra cứu số dư giúp bạn nhé!"
            else:
                res = execute_tool("get_native_balance", {"wallet_address": target_addr}, self.blockchain_service)
                tool_results.append(res)
                data = res.result
                reply = f"💰 **Thông tin số dư ví:**\n\n- **Địa chỉ:** `{target_addr}`\n- **Số dư:** **{data.get('balance_eth')} {data.get('symbol')}**\n- **Mạng:** {settings.CHAIN_NAME} (Chain ID: {data.get('chain_id')})"

        elif any(k in msg_lower for k in ["network", "mạng", "block", "khối"]):
            res = execute_tool("get_network_info", {}, self.blockchain_service)
            tool_results.append(res)
            data = res.result
            reply = f"🌐 **Thông tin mạng Blockchain:**\n\n- **Tên mạng:** {data.get('chain_name')}\n- **Chain ID:** `{data.get('chain_id')}`\n- **Block mới nhất:** `#{data.get('latest_block')}`\n- **Trạng thái RPC:** {'🟢 Hoạt động tốt' if data.get('rpc_connected') else '🔴 Mất kết nối'}"

        elif any(k in msg_lower for k in ["rag", "abi", "policy", "quy định", "hạn mức"]):
            reply = f"📚 **Thông tin RAG Context & Guardrail Policy:**\n\n- **Hạn mức ETH tối đa:** `{settings.GUARDRAIL_MAX_ETH_TRANSFER} ETH/giao dịch`\n- **Hạn mức Token tối đa:** `{settings.GUARDRAIL_MAX_TOKEN_TRANSFER}`\n- **Human-in-the-loop:** Bắt buộc người dùng ký ví\n- **Tài liệu RAG đã nạp:** ERC-20 ABI, ERC-721 Minting, Gas Simulation."

        else:
            reply = (
                "Xin chào! Tôi là **Web3 AI Agent** 🤖⛓️\n\n"
                "Tôi có thể hỗ trợ bạn các thao tác on-chain an toàn qua ngôn ngữ tự nhiên:\n"
                "- 💰 *'Kiểm tra số dư ví của tôi'*\n"
                "- 💸 *'Gửi 0.05 ETH tới ví 0x...'* *(Kiểm tra Guardrail Policy)*\n"
                "- 🎨 *'Mint 1 NFT về ví của tôi'*\n"
                "- 🔍 *'Kiểm tra trạng thái giao dịch 0x...'* \n"
                "- 📚 *'Xem quy định Guardrail Policy và RAG context'* \n"
            )

        new_history: List[ChatMessage] = []
        if conversation_history:
            new_history.extend(conversation_history)
        new_history.append(ChatMessage(role="user", content=message))
        new_history.append(ChatMessage(role="assistant", content=reply))

        return ChatResponse(
            response=reply,
            conversation_history=new_history,
            tool_results=tool_results,
            proposed_transaction=proposed_tx,
            rag_context=rag_chunks or [],
            guardrail_status=guard_status
        )
