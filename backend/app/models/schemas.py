from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system", "tool"]
    content: Optional[str] = None
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None

class GuardrailCheckItem(BaseModel):
    name: str
    status: Literal["PASSED", "FAILED", "INFO"]
    detail: str

class GuardrailReport(BaseModel):
    status: Literal["ALLOWED", "BLOCKED"]
    is_safe: bool
    block_reason: Optional[str] = None
    checks: List[GuardrailCheckItem] = Field(default_factory=list)
    human_approval_required: bool = True
    timestamp: str

class TransactionAction(BaseModel):
    type: Literal["transfer_native", "transfer_token", "contract_call", "mint_nft", "deploy_contract"]
    to: str
    value: str = "0"  # In Wei
    value_eth: Optional[str] = None
    data: str = "0x"
    gas_limit: Optional[str] = None
    chain_id: int
    description: str
    params: Optional[Dict[str, Any]] = None
    guardrail: Optional[GuardrailReport] = None

class ToolExecutionResult(BaseModel):
    tool_name: str
    status: Literal["success", "error", "pending_signature", "blocked_by_guardrail"]
    result: Any
    action_required: Optional[TransactionAction] = None

class RAGChunk(BaseModel):
    id: str
    title: str
    category: str
    content: str

class ChatRequest(BaseModel):
    message: str
    wallet_address: Optional[str] = None
    chain_id: Optional[int] = None
    conversation_history: Optional[List[ChatMessage]] = Field(default_factory=list)
    api_key: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    conversation_history: List[ChatMessage]
    tool_results: List[ToolExecutionResult] = Field(default_factory=list)
    proposed_transaction: Optional[TransactionAction] = None
    rag_context: List[RAGChunk] = Field(default_factory=list)
    guardrail_status: Optional[str] = "PASSED"

class WalletInfoResponse(BaseModel):
    address: str
    chain_id: int
    chain_name: str
    native_balance: str
    native_symbol: str
    explorer_url: str
    block_number: int

class TransactionStatusResponse(BaseModel):
    tx_hash: str
    status: Literal["pending", "success", "reverted", "not_found"]
    block_number: Optional[int] = None
    gas_used: Optional[int] = None
    from_address: Optional[str] = None
    to_address: Optional[str] = None
    value: Optional[str] = None
    explorer_url: str

class PolicyUpdateRequest(BaseModel):
    max_eth: Optional[float] = None
    max_token: Optional[float] = None
