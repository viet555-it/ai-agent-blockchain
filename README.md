# AI Agent with Blockchain Tools

Bắt đầu bàn giao/kiểm thử nhóm tại [PHASE3_HANDOFF.md](docs/PHASE3_HANDOFF.md):
cài từ checkout mới, kịch bản demo, metadata và evidence đã lọc. Source tích hợp
đã push trên `feature/e2e-testing`; các gate holdout mới và latency vẫn còn mở.

Môi trường tích hợp và kiểm thử giai đoạn 3: [PHASE3_INTEGRATION.md](docs/PHASE3_INTEGRATION.md).

Chạy app với proposal/approval trên Hardhat local: [PHASE3_RUNBOOK.md](docs/PHASE3_RUNBOOK.md).

Cấu hình duy nhất: `.env` tại root dự án (mẫu `.env.example`). API, Agent CLI,
Hardhat và đường dẫn RAG đều dùng file này; không cần `.env` trong thư mục con.
API trên nhánh kiểm thử dùng profile local; chuyển ETH/AGNT và faucet đi qua
proposal → policy/simulation → UI approval → receipt. Sepolia WRITE cần grant
tường minh; grant hai fixture lịch sử đã dùng hết.

Dự án phát triển Hệ thống **AI Agent** tích hợp các công cụ **Blockchain (Web3 Tools)** và hệ thống rào chắn an toàn (**Guardrail & Policy Engine**).

---

## 1. Phân hệ Blockchain Service & Network

Phân hệ này đảm nhiệm toàn bộ việc kết nối mạng blockchain, quản lý RPC, các công cụ tương tác On-chain (Read & Write tools cho AI Agent), kiểm tra an toàn Dry-run và bộ kiểm thử tích hợp (Integration Tests):

- **Network Manager** ([backend/network](backend/network/)):
  - Hỗ trợ đa mạng: Local Hardhat Node (Chain 31337) và Sepolia Testnet (Chain 11155111).
  - Tự động chuyển đổi RPC dự phòng (**RPC Failover**) khi có endpoint bị gián đoạn hoặc quá tải.
  - Kiểm tra sức khỏe RPC (**Health Check**) & đo độ trễ (latency ms).
  - Xác thực bytecode runtime và chống xung đột chain ID.

- **Blockchain Service** ([blockchain_service.py](backend/services/blockchain_service.py)):
  - **Read Tools**: Truy vấn số dư ETH, số dư Token ERC-20 (`AgentToken`), thông tin token, trạng thái giao dịch, phí gas EIP-1559.
  - **Pre-flight Simulation (Dry-Run)**: Sử dụng `eth_call` để giả lập giao dịch trước khi phát sóng, bắt trọn các lỗi vượt hạn mức chuyển nhượng (Guardrail 500 AGNT), thiếu số dư hay vi phạm thời gian hồi faucet.
  - **Write Tools**: Chuẩn bị payload giao dịch (Native ETH transfer, ERC-20 transfer/approve/transferFrom, faucet claim) và phát sóng khi có khóa ký.

- **Smart Contracts** ([contracts](contracts/)):
  - `AgentToken.sol`: Token ERC-20 với trần cung 10M, Faucet thử nghiệm (100 AGNT, 60s cooldown) và hạn mức bảo vệ giao dịch mặc định (500 AGNT/lần).

- **Integration Tests** ([backend/tests](backend/tests/)):
  - Runner hiện tại kiểm API và EVM thật, gồm vòng đời deployment, RPC, faucet,
    simulation, approval, token transfer và receipt. Sau merge frontend đạt 136 test;
    unit riêng đạt 274 test và 70 subtest, không cộng các test trùng giữa runner.

---

## 2. Hướng dẫn chạy nhanh

### Cài đặt môi trường tích hợp:
```powershell
python -m venv .venv-phase3
.venv-phase3/Scripts/python.exe -m pip install -r requirements-phase3.lock.txt
.venv-phase3/Scripts/python.exe -m pip check
```

Chi tiết chuẩn bị root env, Node dependencies, tokenizer và index RAG tại
[hướng dẫn bàn giao](docs/PHASE3_HANDOFF.md). Không tạo lại môi trường đã có.

### Chạy test (FakeLLM, không gọi Gemini/Sepolia):
```powershell
.venv-phase3/Scripts/python.exe -m scripts.run_phase3 --suite unit
.venv-phase3/Scripts/python.exe -m scripts.run_phase3 --suite local_evm
```

### Sử dụng công cụ dòng lệnh CLI:
```powershell
# Danh sách mạng được hỗ trợ
.venv-phase3/Scripts/python.exe backend/cli_network.py networks

# Đo độ trễ và kiểm tra sức khỏe các RPC Sepolia
.venv-phase3/Scripts/python.exe backend/cli_network.py --chain-id 11155111 health
```

Chi tiết API và các luồng kiểm thử: [BLOCKCHAIN_SERVICE.md](docs/BLOCKCHAIN_SERVICE.md).
