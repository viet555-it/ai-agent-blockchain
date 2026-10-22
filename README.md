# AI Agent with Blockchain Tools

> **Đồ án ATI – Đại học Hà Nội**
> LLM Agent đọc dữ liệu on-chain và thực hiện transaction thông qua các tool được kiểm soát bởi guardrail.

## ✨ Tính năng

| Tính năng | Mô tả |
|-----------|--------|
| **9 READ tools** | Balance, token info, transaction, block, gas, contract read |
| **3 WRITE tools** | Transfer ETH, transfer ERC-20, call contract |
| **PolicyEngine** | Deny-by-default, allowlist (address/contract/function), per-tx + daily limits |
| **ReAct Agent** | Multi-step reasoning loop with function calling |
| **Multi-LLM** | Gemini, Anthropic Claude, OpenAI, FakeLLM (testing) |
| **Token Budget** | Tiktoken-bounded conversation memory with 20% buffer |
| **Dry-Run Mode** | Preview transactions without broadcasting |
| **Eval Framework** | 40-prompt dataset, tool accuracy scoring, markdown reports |
| **Sepolia Only** | Chain ID enforcement – refuses to operate on mainnet |

## 📁 Cấu trúc dự án

```
ai-agent-blockchain/
├── agent/                  # Agent core
│   ├── core.py             # ReAct loop
│   ├── memory.py           # Token-bounded conversation memory
│   ├── prompts.py          # System prompt (safety-first)
│   ├── service.py          # Public API (AgentService)
│   └── llm/                # LLM adapters
│       ├── base.py         # Protocol + TokenCounter
│       ├── gemini.py       # Google Gemini (google-genai)
│       ├── anthropic.py    # Anthropic Claude
│       ├── openai_adapter.py # OpenAI
│       └── fake.py         # Scripted LLM for testing
├── tools/                  # Tool layer
│   ├── base.py             # BaseTool, ToolResult, RiskLevel
│   ├── registry.py         # @register_tool, ToolRegistry
│   ├── read/               # 9 READ tools
│   │   ├── get_native_balance.py
│   │   ├── get_erc20_balance.py
│   │   ├── get_token_info.py
│   │   ├── get_transaction.py
│   │   ├── get_transaction_history.py
│   │   ├── get_block.py
│   │   ├── get_gas_price.py
│   │   ├── estimate_gas.py
│   │   └── read_contract.py
│   └── write/              # 3 WRITE tools
│       ├── transfer_eth.py
│       ├── transfer_erc20.py
│       └── call_contract.py
├── security/               # Guardrail / Policy
│   └── policy.py           # PolicyEngine (deny-by-default)
├── services/               # External service interfaces
│   ├── blockchain.py       # BlockchainService Protocol + Web3 + Mock
│   ├── etherscan.py        # Etherscan API client (optional)
│   └── retriever.py        # Retriever Protocol + NullRetriever
├── config/                 # Configuration
│   ├── settings.py         # Settings (pydantic-settings)
│   ├── tools.yaml          # Enable/disable tools
│   └── policy.yaml         # Allowlists, limits, chain ID
├── abis/                   # Smart contract ABIs
│   ├── erc20.json          # ERC-20 standard
│   └── SampleVault.json    # Placeholder (deposit/withdraw)
├── eval/                   # Evaluation framework
│   ├── dataset.jsonl       # 40 eval prompts
│   ├── run_eval.py         # Eval runner + report generator
│   └── results.md          # Latest eval results
├── scripts/
│   └── demo_cli.py         # Interactive CLI demo
├── tests/                  # 116 tests, 85% coverage
├── docs/                   # Documentation
│   ├── PLAN.md             # Development plan
│   ├── INTEGRATION.md      # Teammate integration guide
│   ├── ARCHITECTURE.md     # Architecture deep-dive
│   └── ADDING_A_TOOL.md    # How to add new tools
├── pyproject.toml
├── .env.example
└── README.md
```

## 🚀 Quick Start

### 1. Clone & setup

```bash
git clone https://github.com/viet555-it/ai-agent-blockchain.git
cd ai-agent-blockchain
git checkout ai-agent

python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # Linux/Mac

pip install -e ".[dev]"
```

### 2. Cấu hình `.env`

```bash
cp .env.example .env
# Sửa .env với API keys của bạn
```

```env
LLM_PROVIDER=gemini              # gemini | anthropic | openai | fake
GEMINI_API_KEY=your-key-here
SEPOLIA_RPC_URL=https://eth-sepolia.g.alchemy.com/v2/YOUR_KEY
WALLET_PRIVATE_KEY=your-testnet-key
DRY_RUN=true                     # true = không gửi transaction thật
```

### 3. Chạy demo

```bash
# Với FakeLLM (không cần API key)
set LLM_PROVIDER=fake
python -m scripts.demo_cli

# Với Gemini
set LLM_PROVIDER=gemini
python -m scripts.demo_cli
```

### 4. Chạy tests

```bash
# Tất cả tests (không cần API key)
python -m pytest tests/ -v

# Với coverage
python -m pytest tests/ --cov=agent --cov=tools --cov=security --cov=config

# Tool accuracy evaluation
python -m eval.run_eval --output eval/results.md
```

## 🔧 12 Tools

### READ Tools (9) – Chạy tự do

| Tool | Mô tả |
|------|--------|
| `get_native_balance` | Số dư ETH của một địa chỉ |
| `get_erc20_balance` | Số dư token ERC-20 |
| `get_token_info` | Tên, symbol, decimals, totalSupply |
| `get_transaction` | Chi tiết giao dịch theo tx hash |
| `get_transaction_history` | Lịch sử giao dịch (cần Etherscan key) |
| `get_block` | Thông tin block |
| `get_gas_price` | Gas price hiện tại |
| `estimate_gas` | Ước tính gas cho giao dịch |
| `read_contract` | Gọi hàm view/pure trên contract |

### WRITE Tools (3) – Qua PolicyEngine

| Tool | Mô tả |
|------|--------|
| `transfer_eth` | Chuyển ETH Sepolia |
| `transfer_erc20` | Chuyển token ERC-20 |
| `call_contract` | Gọi hàm state-changing (deposit, withdraw) |

## 🛡️ Guardrail – PolicyEngine

Mọi WRITE operation phải qua `security/policy.py`:

- **Deny-by-default**: Allowlist rỗng = CHẶN TẤT CẢ
- **Address allowlist**: Chỉ gửi đến địa chỉ được phép
- **Contract allowlist**: Chỉ gọi contract được phép
- **Function allowlist**: Chỉ gọi function được phép
- **Per-transaction limit**: Max ETH mỗi giao dịch (mặc định 0.1 ETH)
- **Daily limit**: Max ETH trong 24h (mặc định 0.5 ETH)
- **Chain ID check**: Chỉ Sepolia (11155111)
- **Dry-run mode**: Preview transaction trước khi gửi

Cấu hình trong `config/policy.yaml`.

## 📊 Evaluation

```bash
python -m eval.run_eval --output eval/results.md
```

Baseline (FakeScriptedLLM): **40/40 (100%)** tool accuracy across:
- READ tools (16 prompts)
- WRITE tools (8 prompts)
- No-tool / safety (8 prompts)
- Vietnamese prompts (5 prompts)
- Multi-step (2 prompts)
- Safety: mainnet refusal, key exposure, limit bypass

## 📚 Documentation

| Doc | Nội dung |
|-----|---------|
| [INTEGRATION.md](docs/INTEGRATION.md) | Hướng dẫn tích hợp cho đồng đội |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Kiến trúc chi tiết |
| [ADDING_A_TOOL.md](docs/ADDING_A_TOOL.md) | Hướng dẫn thêm tool mới |
| [PLAN.md](docs/PLAN.md) | Kế hoạch phát triển |

## 🧪 Test Coverage

| Module | Coverage |
|--------|----------|
| agent/core.py | 88% |
| agent/memory.py | 98% |
| security/policy.py | 96% |
| config/settings.py | 98% |
| tools/* (READ) | 64-95% |
| tools/* (WRITE) | 51-72% |
| **TOTAL** | **85%** |

116 tests passing, ruff clean.

## 👥 Team

| Thành viên | Phần phụ trách |
|------------|----------------|
| (Tôi) | AI Agent core, Tool calling, Guardrail, Eval |
| Đồng đội | Smart contract, Backend/Frontend, Deploy |

## License

MIT – Đồ án ATI, Đại học Hà Nội.