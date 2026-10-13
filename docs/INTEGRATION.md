# Integration Guide – AI Agent Module

> Tài liệu dành cho đồng đội để tích hợp các module khác vào AI Agent.

## 1. Kiến trúc tổng quan

```
┌────────────────────────────────────────────────────────┐
│                   scripts/demo_cli.py                  │
│                   backend/api (teammates)              │
├────────────────────────────────────────────────────────┤
│                    AgentService                        │
│         (agent/service.py – public API)                │
├────────────────────────────────────────────────────────┤
│  AgentLoop (agent/core.py)       ConversationMemory    │
│  ReAct: LLM → Tool → Observe    (agent/memory.py)     │
├────────────────────────────────────────────────────────┤
│  ToolRegistry          LLM Adapters                    │
│  (tools/registry.py)   (agent/llm/gemini|anthropic|..) │
├────────────────────────────────────────────────────────┤
│  READ tools            WRITE tools (M3)                │
│  (tools/read/*.py)     (tools/write/*.py)              │
├────────────────────────────────────────────────────────┤
│             BlockchainService (Protocol)               │
│    services/blockchain.py ← Web3 hoặc Mock             │
└────────────────────────────────────────────────────────┘
```

## 2. Smart Contract Integration

### ABI Files
Đặt ABI JSON vào thư mục `abis/`:
- `abis/erc20.json` – ERC-20 standard (đã có)
- `abis/SampleVault.json` – Placeholder cho `deposit()` + `withdraw(uint256)`

### SampleVault Contract
Agent giả định contract có 2 hàm:
```solidity
function deposit() external payable;
function withdraw(uint256 amount) external;
```

**Đồng đội cần làm:**
1. Deploy contract lên Sepolia
2. Cập nhật địa chỉ contract trong `config/policy.yaml`:
```yaml
contracts:
  sample_vault:
    address: "0x_ĐỊA_CHỈ_THỰC_TẾ_"  # ← cập nhật ở đây
```
3. Cập nhật ABI trong `abis/SampleVault.json` nếu interface thay đổi

### Allowlist Functions (policy.yaml)
Chỉ các hàm nằm trong allowlist mới được agent gọi:
```yaml
contracts:
  sample_vault:
    allowed_functions:
      - "deposit"
      - "withdraw"
```

## 3. Backend / Frontend Integration

### AgentService API
```python
from agent.service import AgentService

service = AgentService.create()  # auto-wire dependencies

# Sync API
events = await service.chat("session-1", "Check balance of 0x...")

# Streaming API
async for event in service.chat_stream("session-1", "..."):
    match event.type:
        case "thought":     ...  # agent reasoning
        case "tool_call":   ...  # tool being called
        case "tool_result": ...  # tool result
        case "final":       ...  # final answer
        case "error":       ...  # error occurred
```

### Event Types
| Type | Data Fields | Mô tả |
|------|-------------|-------|
| `thought` | `content` | Agent reasoning trước khi gọi tool |
| `tool_call` | `id`, `name`, `arguments` | Tool đang được gọi |
| `tool_result` | `id`, `name`, `result`, `duration_ms` | Kết quả tool |
| `final` | `content` | Câu trả lời cuối cùng |
| `error` | `error` | Lỗi |

### FastAPI Example
```python
from fastapi import FastAPI
from agent.service import AgentService

app = FastAPI()
service = AgentService.create()

@app.post("/api/chat")
async def chat(session_id: str, message: str):
    events = await service.chat(session_id, message)
    return [{"type": e.type, "data": e.data} for e in events]
```

## 4. Environment Variables (.env)

```bash
# LLM Provider (gemini | anthropic | openai | fake)
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-key-here

# Blockchain
SEPOLIA_RPC_URL=https://eth-sepolia.g.alchemy.com/v2/YOUR_KEY
WALLET_PRIVATE_KEY=your-private-key  # NEVER commit!

# Optional
ETHERSCAN_API_KEY=your-etherscan-key  # for transaction history
LLM_MODEL=                            # empty = provider default
DRY_RUN=true                          # true = no real transactions
MAX_STEPS=10                          # max agent reasoning steps
```

## 5. Available READ Tools (9)

| Tool | Input | Output |
|------|-------|--------|
| `get_native_balance` | `address` | Balance in wei + ETH |
| `get_erc20_balance` | `token_address`, `wallet_address` | Token balance |
| `get_token_info` | `token_address` | name, symbol, decimals |
| `get_transaction` | `tx_hash` | Transaction details |
| `get_transaction_history` | `address`, `limit` | Recent txs (needs Etherscan key) |
| `get_block` | `block_identifier` | Block info |
| `get_gas_price` | (none) | Gas price in wei + gwei |
| `estimate_gas` | `to`, `value_wei`, `data` | Gas estimate + cost |
| `read_contract` | `contract_address`, `abi_filename`, `function_name`, `args` | Contract call result |

## 6. Adding New Tools

```python
# tools/read/my_new_tool.py
from tools.base import BaseTool, RiskLevel, ToolContext, ToolResult
from tools.registry import register_tool
from pydantic import BaseModel, Field

class MyInput(BaseModel):
    param: str = Field(description="...")

@register_tool
class MyNewTool(BaseTool):
    name = "my_tool_name"
    description = "What this tool does"
    risk_level = RiskLevel.READ  # or WRITE
    args_schema = MyInput

    async def run(self, validated: MyInput, ctx: ToolContext) -> ToolResult:
        try:
            result = await ctx.blockchain.some_method(validated.param)
            return ToolResult.success(result)
        except Exception as e:
            return ToolResult.failure(str(e))
```

Then add `"my_tool_name"` to `config/tools.yaml` → `enabled` list.

## 7. Running Tests

```bash
# All tests (no API keys needed)
.venv/Scripts/python -m pytest tests/ -v

# With coverage
.venv/Scripts/python -m pytest tests/ --cov=agent --cov=tools --cov=services

# Only READ tool tests
.venv/Scripts/python -m pytest tests/test_tools_read.py -v
```

## 8. Demo CLI

```bash
.venv/Scripts/python -m scripts.demo_cli
```

Set `LLM_PROVIDER=fake` in `.env` to test without API keys.
