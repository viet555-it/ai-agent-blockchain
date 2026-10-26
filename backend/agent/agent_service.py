"""AI Agent Service for Blockchain Tools.

Orchestrates intent parsing, RAG context retrieval, tool selection, parameter validation,
guardrail policy evaluation, human approval workflow, and execution timeline generation.
"""
import logging
import re
import time
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from backend.guardrail.policy_engine import GuardrailResult, PolicyEngine
from backend.network.network_manager import NetworkManager
from backend.rag.rag_adapter import RAGAdapter, RAGSearchResult
from backend.services.blockchain_service import BlockchainService

logger = logging.getLogger("agent.service")


class TimelineStep(BaseModel):
    """Step in the 9-stage Agent workflow timeline."""
    step_number: int
    name: str
    status: str  # SUCCESS, PENDING_APPROVAL, BLOCKED, FAILED, INFO
    timestamp: float = Field(default_factory=time.time)
    duration_ms: Optional[float] = None
    tool_name: Optional[str] = None
    sanitized_parameters: Optional[Dict[str, Any]] = None
    result: Optional[Any] = None
    error: Optional[str] = None


class AgentResponse(BaseModel):
    """Standardized response from the AI Agent."""
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    query: str
    reply: str
    intent: str
    tool_selected: Optional[str] = None
    timeline: List[TimelineStep] = Field(default_factory=list)
    guardrail_result: Optional[GuardrailResult] = None
    rag_result: Optional[RAGSearchResult] = None
    requires_approval: bool = False
    approval_id: Optional[str] = None
    blockchain_result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class BlockchainAgent:
    """Agent runtime integrating BlockchainService, PolicyEngine, and RAGAdapter."""

    def __init__(
        self,
        blockchain_service: BlockchainService,
        policy_engine: PolicyEngine,
        rag_adapter: Optional[RAGAdapter] = None,
        default_wallet: Optional[str] = None,
    ):
        self.blockchain = blockchain_service
        self.policy = policy_engine
        self.rag = rag_adapter or RAGAdapter()
        # Fallback to deployer address if no active wallet is passed
        self.default_wallet = default_wallet or "0xeF9F53B00B069782256fC20697E7cf6a3136F9BC"

    def process_message(self, query: str, user_wallet: Optional[str] = None) -> AgentResponse:
        """Process natural-language prompt and execute full 9-step workflow."""
        start_time = time.perf_counter()
        request_id = f"req-{uuid.uuid4().hex[:8]}"
        timeline: List[TimelineStep] = []
        active_wallet = user_wallet or self.default_wallet

        # ── Step 1: Request received ──────────────────────────────────────────
        t0 = time.perf_counter()
        timeline.append(TimelineStep(
            step_number=1,
            name="Request received",
            status="SUCCESS",
            duration_ms=round((time.perf_counter() - t0) * 1000, 2),
            result={"query": query, "request_id": request_id, "active_wallet": active_wallet},
        ))

        # ── Step 2: Intent analyzed ───────────────────────────────────────────
        t0 = time.perf_counter()
        intent, extracted_params = self._analyze_intent(query, active_wallet)
        rag_result = self.rag.retrieve(query)
        timeline.append(TimelineStep(
            step_number=2,
            name="Intent analyzed",
            status="SUCCESS",
            duration_ms=round((time.perf_counter() - t0) * 1000, 2),
            result={
                "intent": intent,
                "extracted_parameters": extracted_params,
                "has_rag_context": rag_result.has_relevant_context,
            },
        ))

        # ── Step 3: Tool selected ─────────────────────────────────────────────
        t0 = time.perf_counter()
        tool_name = self._select_tool(intent)
        timeline.append(TimelineStep(
            step_number=3,
            name="Tool selected",
            status="SUCCESS",
            duration_ms=round((time.perf_counter() - t0) * 1000, 2),
            tool_name=tool_name,
            result={"tool_name": tool_name},
        ))

        # If it's a pure conversation / FAQ without tool call:
        if tool_name == "none":
            reply = self._generate_faq_reply(query, rag_result)
            timeline.append(TimelineStep(
                step_number=9,
                name="Final Agent response",
                status="SUCCESS",
                duration_ms=round((time.perf_counter() - start_time) * 1000, 2),
                result={"reply": reply},
            ))
            return AgentResponse(
                request_id=request_id,
                query=query,
                reply=reply,
                intent=intent,
                tool_selected=None,
                timeline=timeline,
                rag_result=rag_result,
            )

        # ── Step 4: Parameters validated ──────────────────────────────────────
        t0 = time.perf_counter()
        val_ok, val_err, clean_params = self._validate_parameters(tool_name, extracted_params)
        timeline.append(TimelineStep(
            step_number=4,
            name="Parameters validated",
            status="SUCCESS" if val_ok else "FAILED",
            duration_ms=round((time.perf_counter() - t0) * 1000, 2),
            tool_name=tool_name,
            sanitized_parameters=clean_params,
            error=val_err,
        ))

        if not val_ok:
            reply = f"Parameter validation failed: {val_err}"
            return AgentResponse(
                request_id=request_id,
                query=query,
                reply=reply,
                intent=intent,
                tool_selected=tool_name,
                timeline=timeline,
                error=val_err,
            )

        # ── Step 5: Guardrail evaluation ──────────────────────────────────────
        t0 = time.perf_counter()
        # If write operation, optionally perform dry-run simulation first
        sim_data = None
        if tool_name in ("erc20_transfer", "native_transfer"):
            try:
                sim_data = self.blockchain.simulate_transfer(
                    sender=active_wallet,
                    recipient=clean_params["recipient"],
                    amount_token=clean_params["amount"],
                    token_address=clean_params.get("token_address"),
                )
            except Exception as e:
                sim_data = {"isValid": False, "reason": f"Simulation check error: {str(e)}"}

        guardrail_res = self.policy.evaluate_request(
            operation=tool_name,
            parameters=clean_params,
            simulation_data=sim_data,
        )

        step_status = "SUCCESS"
        if not guardrail_res.is_allowed:
            step_status = "BLOCKED"
        elif guardrail_res.requires_approval:
            step_status = "PENDING_APPROVAL"

        timeline.append(TimelineStep(
            step_number=5,
            name="Guardrail evaluation",
            status=step_status,
            duration_ms=round((time.perf_counter() - t0) * 1000, 2),
            tool_name=tool_name,
            result={
                "is_allowed": guardrail_res.is_allowed,
                "operation_type": guardrail_res.operation_type,
                "violations": guardrail_res.violations,
                "warnings": guardrail_res.warnings,
                "simulation": sim_data,
            },
        ))

        if not guardrail_res.is_allowed:
            violations_str = "; ".join(guardrail_res.violations)
            reply = f"Operation rejected by Guardrail Policy Engine: {violations_str}"
            timeline.append(TimelineStep(
                step_number=9,
                name="Final Agent response",
                status="BLOCKED",
                duration_ms=round((time.perf_counter() - start_time) * 1000, 2),
                result={"reply": reply},
            ))
            return AgentResponse(
                request_id=request_id,
                query=query,
                reply=reply,
                intent=intent,
                tool_selected=tool_name,
                timeline=timeline,
                guardrail_result=guardrail_res,
                rag_result=rag_result,
            )

        # ── Step 6: User approval required, if applicable ─────────────────────
        if guardrail_res.requires_approval:
            t0 = time.perf_counter()
            approval = guardrail_res.pending_approval
            timeline.append(TimelineStep(
                step_number=6,
                name="User approval required",
                status="PENDING_APPROVAL",
                duration_ms=round((time.perf_counter() - t0) * 1000, 2),
                tool_name=tool_name,
                result={
                    "approval_id": approval.approval_id,
                    "description": approval.description,
                    "expires_at": approval.expires_at,
                    "parameters": approval.parameters,
                    "simulation": sim_data,
                },
            ))

            reply = (
                f"I have prepared the transaction ({approval.description}). "
                f"Because this is a state-changing write operation, explicit human approval is required. "
                f"Please review the details in the approval panel to approve or reject."
            )
            timeline.append(TimelineStep(
                step_number=9,
                name="Final Agent response",
                status="PENDING_APPROVAL",
                duration_ms=round((time.perf_counter() - start_time) * 1000, 2),
                result={"reply": reply},
            ))

            return AgentResponse(
                request_id=request_id,
                query=query,
                reply=reply,
                intent=intent,
                tool_selected=tool_name,
                timeline=timeline,
                guardrail_result=guardrail_res,
                rag_result=rag_result,
                requires_approval=True,
                approval_id=approval.approval_id,
            )

        # ── Step 7: Tool executed (for Read-only operations) ──────────────────
        t0 = time.perf_counter()
        tool_res, exec_err = self._execute_read_tool(tool_name, clean_params)
        timeline.append(TimelineStep(
            step_number=7,
            name="Tool executed",
            status="SUCCESS" if exec_err is None else "FAILED",
            duration_ms=round((time.perf_counter() - t0) * 1000, 2),
            tool_name=tool_name,
            result=tool_res,
            error=exec_err,
        ))

        # ── Step 8: Blockchain result received ────────────────────────────────
        t0 = time.perf_counter()
        timeline.append(TimelineStep(
            step_number=8,
            name="Blockchain result received",
            status="SUCCESS" if exec_err is None else "FAILED",
            duration_ms=round((time.perf_counter() - t0) * 1000, 2),
            result=tool_res or {"error": exec_err},
        ))

        # ── Step 9: Final Agent response ──────────────────────────────────────
        t0 = time.perf_counter()
        reply = self._format_read_reply(tool_name, tool_res, exec_err, rag_result)
        timeline.append(TimelineStep(
            step_number=9,
            name="Final Agent response",
            status="SUCCESS" if exec_err is None else "FAILED",
            duration_ms=round((time.perf_counter() - start_time) * 1000, 2),
            result={"reply": reply},
        ))

        return AgentResponse(
            request_id=request_id,
            query=query,
            reply=reply,
            intent=intent,
            tool_selected=tool_name,
            timeline=timeline,
            guardrail_result=guardrail_res,
            rag_result=rag_result,
            blockchain_result=tool_res,
            error=exec_err,
        )

    # ── Intent Analysis & Routing ─────────────────────────────────────────────

    def _analyze_intent(self, query: str, active_wallet: str) -> Tuple[str, Dict[str, Any]]:
        q = query.lower().strip()
        params: Dict[str, Any] = {"wallet": active_wallet}

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

        return "general_query", params

    def _select_tool(self, intent: str) -> str:
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
        }
        return mapping.get(intent, "none")

    def _validate_parameters(self, tool_name: str, raw_params: Dict[str, Any]) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        clean = dict(raw_params)
        wallet = raw_params.get("target_address") or raw_params.get("wallet")

        if tool_name in ("get_native_balance", "get_token_balance"):
            if not wallet or not self.blockchain.validate_and_checksum_address(wallet):
                return False, f"Invalid wallet address: {wallet}", clean
            clean["address"] = self.blockchain.validate_and_checksum_address(wallet)
            return True, None, clean

        if tool_name == "get_token_info":
            # Use configured AgentToken deployment if none provided
            return True, None, clean

        if tool_name == "get_gas_price":
            return True, None, clean

        if tool_name in ("erc20_transfer", "native_transfer"):
            recipient = raw_params.get("target_address") or raw_params.get("second_address")
            if not recipient:
                return False, "Recipient address is required for transfers. (e.g., 'Transfer 50 AGNT to 0x...')", clean
            clean["recipient"] = recipient
            amount = raw_params.get("amount")
            if not amount:
                return False, "Transfer amount is required.", clean
            clean["amount"] = amount
            clean["token_symbol"] = "ETH" if tool_name == "native_transfer" else "AGNT"
            return True, None, clean

        if tool_name == "faucet_claim":
            clean["recipient"] = wallet
            clean["amount"] = raw_params.get("amount", "100")
            return True, None, clean

        if tool_name == "simulate_transfer":
            recipient = raw_params.get("target_address") or raw_params.get("second_address")
            clean["recipient"] = recipient or self.default_wallet
            clean["amount"] = raw_params.get("amount", "10")
            return True, None, clean

        return True, None, clean

    def _execute_read_tool(self, tool_name: str, params: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        try:
            if tool_name == "get_native_balance":
                addr = params.get("address", self.default_wallet)
                res = self.blockchain.get_native_balance(addr)
                return res, None

            if tool_name == "get_token_balance":
                addr = params.get("address", self.default_wallet)
                # Resolve deployed AgentToken
                _, manifest = self.blockchain.network_manager.load_deployment_manifest(self.blockchain.chain_id)
                token_addr = manifest["contractAddress"]
                res = self.blockchain.get_token_balance(token_addr, addr)
                return res, None

            if tool_name == "get_token_info":
                _, manifest = self.blockchain.network_manager.load_deployment_manifest(self.blockchain.chain_id)
                token_addr = manifest["contractAddress"]
                res = self.blockchain.get_token_info(token_addr)
                return res, None

            if tool_name == "get_gas_price":
                res = self.blockchain.get_gas_price()
                return res, None

            if tool_name == "simulate_transfer":
                sender = params.get("wallet", self.default_wallet)
                res = self.blockchain.simulate_transfer(
                    sender=sender,
                    recipient=params["recipient"],
                    amount_token=params["amount"],
                )
                return res, None

            if tool_name == "get_recent_transactions":
                # Simulated recent block/tx summary for active network
                latest_block = self.blockchain.get_block("latest")
                return {
                    "block_number": latest_block.get("number"),
                    "block_hash": latest_block.get("hash", {}).hex() if hasattr(latest_block.get("hash"), "hex") else str(latest_block.get("hash")),
                    "tx_count": len(latest_block.get("transactions", [])),
                    "chain_id": self.blockchain.chain_id,
                }, None

            return None, f"Tool {tool_name} is not a recognized read operation"
        except Exception as e:
            logger.error(f"Error executing {tool_name}: {e}")
            return None, str(e)

    def _format_read_reply(
        self,
        tool_name: str,
        result: Optional[Dict[str, Any]],
        error: Optional[str],
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

    def _generate_faq_reply(self, query: str, rag_result: RAGSearchResult) -> str:
        """Answer informational questions with RAG context."""
        if rag_result.has_relevant_context:
            doc = rag_result.documents[0]
            return (
                f"{doc.excerpt}\n\n"
                f"> **Source:** *{doc.title}* ({doc.source_file})"
            )
        return (
            "I am your AI Blockchain Assistant. You can ask me to check wallet balances, "
            "inspect token contracts, simulate transactions, check gas prices, or prepare transfers. "
            "How can I assist you with the blockchain today?"
        )
