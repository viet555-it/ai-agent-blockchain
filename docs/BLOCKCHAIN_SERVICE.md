# Blockchain Service, Network Manager & Integration Tests

Module này cung cấp hạ tầng kết nối Web3, quản lý mạng (Multi-Network & RPC Failover), các công cụ đọc/ghi cho AI Agent và bộ kiểm thử tích hợp (Integration Tests) với Smart Contract `AgentToken`.

---

## 1. Cấu trúc thư mục

```text
backend/
├── network/
│   ├── __init__.py
│   ├── config.py                 # Định nghĩa ChainConfig & danh sách mạng (Hardhat 31337, Sepolia 11155111, ...)
│   └── network_manager.py        # Quản lý multi-chain, RPC healthcheck, failover & bytecode verification
├── services/
│   ├── __init__.py
│   └── blockchain_service.py     # Dịch vụ Web3: Read tools, Dry-run simulation, Transaction preparation & Execution
├── tests/
│   ├── test_contract_tools.py          # Baseline tests cho amount conversion và manifest
│   ├── test_network_manager.py         # Unit & mock integration test cho NetworkManager
│   ├── test_blockchain_service.py      # Unit test cho BlockchainService (Read, Prepare, Simulation)
│   └── test_integration_blockchain.py  # End-to-end integration test chạy trên EVM thật (Hardhat local node)
├── cli_network.py                # Công cụ dòng lệnh CLI kiểm tra mạng, ping RPC latency & query số dư
├── run_integration_tests.py      # Script tự động spawn node và chạy 100% test suite
├── token_amounts.py              # Xử lý số lượng token chính xác, loại bỏ sai số floating-point
└── requirements.txt              # Thư viện phụ thuộc (web3, pydantic, pyyaml, requests, pytest)
```

---

## 2. Các tính năng chính

### 2.1. Network Manager (`backend/network/`)
- **Hỗ trợ đa chuỗi (Multi-Chain)**:
  - Localhost / Hardhat node (Chain ID `31337`).
  - Ethereum Sepolia Testnet (Chain ID `11155111`).
  - Cho phép đăng ký thêm các mạng khác (Mainnet, Polygon, Arbitrum, v.v.).
- **RPC Failover tự động**:
  - Khi một RPC bị timeout hoặc lỗi kết nối, NetworkManager tự động chuyển sang RPC dự phòng trong danh sách.
- **RPC Health Check & Latency Measurement**:
  - Đo độ trễ (latency ms), lấy block number, gas price và xác thực chain ID thực tế của RPC.
- **Bảo vệ Bytecode & Manifest**:
  - Tải manifest từ `contracts/exported/<chainId>/` và `backend/abi/<chainId>/`.
  - Từ chối các RPC trả về sai chain ID hoặc địa chỉ không có bytecode / sai mã hash runtime.

### 2.2. Blockchain Service (`backend/services/blockchain_service.py`)
- **Read Tools (cho AI Agent)**:
  - `get_native_balance(address)`: Lấy số dư ETH chính xác.
  - `get_token_balance(token_address, wallet_address)`: Lấy số dư token ERC-20 (`AgentToken`, v.v.).
  - `get_token_info(token_address)`: Metadata name, symbol, decimals, totalSupply.
  - `get_allowance(token_address, owner, spender)`: Kiểm tra hạn mức ủy quyền.
  - `get_transaction(tx_hash)` & `get_transaction_receipt(tx_hash)`: Chi tiết và trạng thái giao dịch.
  - `get_gas_price()`: Cung cấp thông số gas legacy và EIP-1559 baseFee/priorityFee.
  - `read_contract(contract_address, abi, function_name, *args)`: Gọi hàm view/pure bất kỳ.
- **Dry-Run Simulation (Pre-flight Guardrail Check)**:
  - `simulate_transfer(sender, recipient, amount, token_address, spender)`: Mô phỏng giao dịch thực tế qua `eth_call`.
  - Bắt các lỗi revert chính xác từ smart contract trước khi gửi giao dịch:
    - `"AgentToken: Transfer exceeds max limit"` (vượt trần guardrail 500 AGNT).
    - `"ERC20InsufficientBalance"` (không đủ số dư).
    - `"AgentToken: Faucet cooldown active"` (chưa hết thời gian cooldown 60s).
- **Transaction Preparation & Execution (Write Tools)**:
  - `prepare_native_transfer(from, to, amount, priority)`: Tạo payload giao dịch EIP-1559.
  - `prepare_token_transfer(token, from, to, amount)`: Mã hóa call data hàm `transfer`.
  - `prepare_token_approve(token, owner, spender, amount)`: Mã hóa call data hàm `approve`.
  - `prepare_faucet_claim(token, recipient, amount)`: Mã hóa call data nhận token thử nghiệm từ faucet.
  - `sign_and_send_transaction(tx_dict, private_key)`: Ký và phát sóng giao dịch qua `eth_sendRawTransaction`.
  - `wait_for_receipt(tx_hash)`: Đợi biên nhận xác nhận giao dịch.

---

## 3. Hướng dẫn chạy kiểm thử (Integration Tests)

### Cách 1: Chạy tự động 1 lệnh duy nhất (Khuyên dùng)
Script tự động bật local Hardhat node, thực hiện toàn bộ 36 tests (cả unit tests và real EVM integration tests), sau đó dọn dẹp tiến trình:

```powershell
backend/.venv/Scripts/python.exe backend/run_integration_tests.py
```

Kết quả:
```text
======================================================================
 ALL INTEGRATION & UNIT TESTS PASSED SUCCESSFULLY! 
======================================================================
Ran 36 tests in ~2.0s: OK
```

### Cách 2: Chạy thủ công với Hardhat node độc lập

**Terminal 1 (chạy node):**
```powershell
cd contracts
npm run node
```

**Terminal 2 (chạy test suite):**
```powershell
$env:LOCAL_TEST_RPC = "http://127.0.0.1:8545"
backend/.venv/Scripts/python.exe -m unittest discover -s backend/tests -v
```

### Cách 3: Chạy Hardhat Contract Tests (Node.js)
```powershell
cd contracts
npm test
```
(Chạy 34 contract tests bằng Mocha/Chai, kiểm tra toàn bộ logic AgentToken, Faucet, Guardrails, Security regressions).

---

## 4. Công cụ CLI (`backend/cli_network.py`)

Công cụ hỗ trợ tương tác và kiểm tra nhanh:

### Danh sách mạng:
```powershell
backend/.venv/Scripts/python.exe backend/cli_network.py networks
```

### Kiểm tra sức khỏe & độ trễ RPC (Sepolia Testnet):
```powershell
backend/.venv/Scripts/python.exe backend/cli_network.py --chain-id 11155111 health
```

### Kiểm tra số dư ví:
```powershell
backend/.venv/Scripts/python.exe backend/cli_network.py --chain-id 31337 balance 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266
```

### Mô phỏng giao dịch (Dry-Run Guardrail):
```powershell
backend/.venv/Scripts/python.exe backend/cli_network.py --chain-id 31337 simulate --sender 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266 --recipient 0x70997970C51812dc3A010C7d01b50e0d17dc79C8 --amount 600
```
*(Sẽ trả về `REVERTED / INVALID` do vượt mức trần chuyển nhượng 500 AGNT).*

---

## 5. Tích hợp với AI Agent Tools

Các thành viên khác trong nhóm (phần AI Agent & API Backend) có thể import và sử dụng trực tiếp:

```python
from backend.services.blockchain_service import BlockchainService
from backend.network.network_manager import NetworkManager

# Tự động kết nối tới RPC có độ trễ tốt nhất
manager = NetworkManager()
service = BlockchainService(chain_id=11155111, network_manager=manager)

# 1. Đọc số dư ETH & Token
eth_balance = service.get_native_balance("0xRecipient...")
token_balance = service.get_token_balance(token_address="0xToken...", wallet_address="0xRecipient...")

# 2. Dry-run kiểm tra chính sách bảo mật trước khi Agent đề xuất chuyển tiền
simulation = service.simulate_transfer(
    sender="0xSender...",
    recipient="0xRecipient...",
    amount_token="150.0",
    token_address="0xToken..."
)
if not simulation["isValid"]:
    print("Guardrail blocked transfer:", simulation["reason"])
else:
    # 3. Chuẩn bị payload giao dịch cho người dùng xác nhận
    tx_preview = service.prepare_token_transfer(
        token_address="0xToken...",
        from_address="0xSender...",
        to_address="0xRecipient...",
        amount_token="150.0"
    )
```
