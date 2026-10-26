# AI Agent with Blockchain Tools

Dự án phát triển Hệ thống **AI Agent** tích hợp các công cụ **Blockchain (Web3 Tools)** và hệ thống rào chắn an toàn (**Guardrail & Policy Engine**).

---

## 1. Phân hệ Blockchain Service & Network

Phân hệ này đảm nhiệm toàn bộ việc kết nối mạng blockchain, quản lý RPC, các công cụ tương tác On-chain (Read & Write tools cho AI Agent), kiểm tra an toàn Dry-run và bộ kiểm thử tích hợp (Integration Tests):

- **Network Manager** ([`backend/network/`](file:///d:/DowloadsD/ATI/backend/network/)):
  - Hỗ trợ đa mạng: Local Hardhat Node (Chain 31337) và Sepolia Testnet (Chain 11155111).
  - Tự động chuyển đổi RPC dự phòng (**RPC Failover**) khi có endpoint bị gián đoạn hoặc quá tải.
  - Kiểm tra sức khỏe RPC (**Health Check**) & đo độ trễ (latency ms).
  - Xác thực bytecode runtime và chống xung đột chain ID.

- **Blockchain Service** ([`backend/services/blockchain_service.py`](file:///d:/DowloadsD/ATI/backend/services/blockchain_service.py)):
  - **Read Tools**: Truy vấn số dư ETH, số dư Token ERC-20 (`AgentToken`), thông tin token, trạng thái giao dịch, phí gas EIP-1559.
  - **Pre-flight Simulation (Dry-Run)**: Sử dụng `eth_call` để giả lập giao dịch trước khi phát sóng, bắt trọn các lỗi vượt hạn mức chuyển nhượng (Guardrail 500 AGNT), thiếu số dư hay vi phạm thời gian hồi faucet.
  - **Write Tools**: Chuẩn bị payload giao dịch (Native ETH transfer, ERC-20 transfer/approve/transferFrom, faucet claim) và phát sóng khi có khóa ký.

- **Smart Contracts** ([`contracts/`](file:///d:/DowloadsD/ATI/contracts/)):
  - `AgentToken.sol`: Token ERC-20 với trần cung 10M, Faucet thử nghiệm (100 AGNT, 60s cooldown) và hạn mức bảo vệ giao dịch mặc định (500 AGNT/lần).

- **Integration Tests** ([`backend/tests/test_integration_blockchain.py`](file:///d:/DowloadsD/ATI/backend/tests/test_integration_blockchain.py)):
  - Chạy toàn diện 36 bài kiểm thử trên môi trường EVM thật, kiểm tra toàn bộ vòng đời từ triển khai, kiểm tra sức khỏe RPC, faucet, mô phỏng guardrail đến chuyển token và phân quyền.

---

## 2. Hướng dẫn chạy nhanh

### Cài đặt môi trường Python:
```powershell
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
```

### Chạy toàn bộ Test Suite (36/36 tests - Tự động bật/tắt EVM Node):
```powershell
backend/.venv/Scripts/python.exe backend/run_integration_tests.py
```

### Sử dụng công cụ dòng lệnh CLI:
```powershell
# Danh sách mạng được hỗ trợ
backend/.venv/Scripts/python.exe backend/cli_network.py networks

# Đo độ trễ và kiểm tra sức khỏe các RPC Sepolia
backend/.venv/Scripts/python.exe backend/cli_network.py --chain-id 11155111 health
```

Chi tiết tài liệu API và các luồng kiểm thử xem tại: [docs/BLOCKCHAIN_SERVICE.md](file:///d:/DowloadsD/ATI/docs/BLOCKCHAIN_SERVICE.md).
