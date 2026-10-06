export interface ChatMessage {
  role: "user" | "assistant" | "system" | "tool";
  content?: string;
  name?: string;
  tool_call_id?: string;
  tool_calls?: any[];
}

export interface GuardrailCheckItem {
  name: string;
  status: "PASSED" | "FAILED" | "INFO";
  detail: string;
}

export interface GuardrailReport {
  status: "ALLOWED" | "BLOCKED";
  is_safe: boolean;
  block_reason?: string | null;
  checks: GuardrailCheckItem[];
  human_approval_required: boolean;
  timestamp: string;
}

export interface TransactionAction {
  type: "transfer_native" | "transfer_token" | "contract_call" | "mint_nft" | "deploy_contract";
  to: string;
  value: string;
  value_eth?: string;
  data: string;
  gas_limit?: string;
  chain_id: number;
  description: string;
  params?: Record<string, any>;
  guardrail?: GuardrailReport;
}

export interface ToolExecutionResult {
  tool_name: string;
  status: "success" | "error" | "pending_signature" | "blocked_by_guardrail";
  result: any;
  action_required?: TransactionAction;
}

export interface RAGChunk {
  id: string;
  title: string;
  category: string;
  content: string;
}

export interface ChatResponse {
  response: string;
  conversation_history: ChatMessage[];
  tool_results: ToolExecutionResult[];
  proposed_transaction?: TransactionAction | null;
  rag_context: RAGChunk[];
  guardrail_status: string;
}

export interface WalletInfo {
  address: string;
  chain_id: number;
  chain_name: string;
  native_balance: string;
  native_symbol: string;
  explorer_url: string;
  block_number: number;
}

export interface GuardrailPolicies {
  max_eth_limit: number;
  max_token_limit: number;
  whitelist_count: number;
  blacklist_count: number;
  human_approval_required: boolean;
  simulation_enabled: boolean;
  whitelist: string[];
}

export interface AuditLog {
  id: string;
  timestamp: string;
  tx_type: string;
  target: string;
  value_eth?: string;
  status: "ALLOWED" | "BLOCKED";
  block_reason?: string;
  checks: GuardrailCheckItem[];
  human_approval_required: boolean;
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api";

export async function sendChatMessage(
  message: string,
  walletAddress?: string,
  chainId?: number,
  history: ChatMessage[] = [],
  apiKey?: string
): Promise<ChatResponse> {
  const response = await fetch(`${API_BASE_URL}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      message,
      wallet_address: walletAddress || null,
      chain_id: chainId || 11155111,
      conversation_history: history,
      api_key: apiKey || null,
    }),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Server error: ${response.statusText}`);
  }

  return response.json();
}

export async function fetchWalletInfo(address: string, chainId: number = 11155111): Promise<WalletInfo> {
  const response = await fetch(`${API_BASE_URL}/wallet/info?address=${address}&chain_id=${chainId}`);
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || "Failed to fetch wallet info");
  }
  return response.json();
}

export async function fetchGuardrailPolicies(): Promise<GuardrailPolicies> {
  const response = await fetch(`${API_BASE_URL}/guardrail/policies`);
  if (!response.ok) throw new Error("Failed to fetch guardrail policies");
  return response.json();
}

export async function updateGuardrailPolicies(maxEth?: number, maxToken?: number) {
  const response = await fetch(`${API_BASE_URL}/guardrail/policies`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ max_eth: maxEth, max_token: maxToken }),
  });
  if (!response.ok) throw new Error("Failed to update policies");
  return response.json();
}

export async function fetchAuditLogs(): Promise<{ count: number; logs: AuditLog[] }> {
  const response = await fetch(`${API_BASE_URL}/guardrail/audit-logs`);
  if (!response.ok) throw new Error("Failed to fetch audit logs");
  return response.json();
}

export async function fetchRAGDocs(): Promise<{ count: number; documents: RAGChunk[] }> {
  const response = await fetch(`${API_BASE_URL}/rag/docs`);
  if (!response.ok) throw new Error("Failed to fetch RAG docs");
  return response.json();
}
