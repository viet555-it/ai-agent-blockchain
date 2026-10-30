# AI Agent with Blockchain Tools

Ứng dụng web cho phép tương tác với blockchain bằng ngôn ngữ tự nhiên: tra cứu
số dư, thông tin token, phí gas và chuẩn bị giao dịch. Agent kết hợp LLM, RAG và
công cụ Web3; giao dịch được kiểm tra chính sách, mô phỏng và yêu cầu người dùng
phê duyệt trước khi ký bằng MetaMask.

Lịch sử hội thoại và giao dịch được lưu trong SQLite theo từng ví và deployment.
Luồng demo chính sử dụng **Hardhat Local**, token **AGNT** và **MetaMask**.

## Tính năng

- Chat tiếng Việt/Anh, xem tiến trình gọi công cụ và kết quả blockchain.
- Đọc số dư ETH/AGNT, thông tin contract, phí gas và trạng thái giao dịch.
- Chuẩn bị chuyển ETH, chuyển AGNT và nhận AGNT từ faucet.
- Kiểm tra policy, mô phỏng và yêu cầu phê duyệt trước khi gửi giao dịch.
- Kết nối và ký đăng nhập qua một nút; đổi tài khoản và tải lịch sử riêng của mỗi ví.
- Lưu hội thoại, proposal, approval, transaction hash, receipt và audit trong database.
- Giao diện sáng/tối, EN/VI và bố cục thích ứng với màn hình nhỏ.

## Kiến trúc

```text
Browser UI + MetaMask
        |
        v
FastAPI: xác thực ví, hội thoại, proposal và lịch sử
        |
        +-- Agent + LLM + RAG --> công cụ đọc blockchain
        |
        +-- Policy + mô phỏng --> phê duyệt trên UI --> ký bằng MetaMask
        |
        +-- SQLite <-- worker đối soát transaction/receipt <-- RPC
```

Kết nối extension cung cấp địa chỉ ví. Chữ ký đăng nhập xác thực quyền truy cập
lịch sử của ví đó. Giao dịch cần xác nhận riêng trong MetaMask; backend ở chế độ
browser-wallet không giữ khóa riêng hoặc ký thay người dùng.

| Thành phần | Công nghệ / vị trí |
|---|---|
| Frontend | JavaScript ES modules, CSS, Vite — `frontend/` |
| API và Web3 | FastAPI, Web3.py — `backend/` |
| Agent và LLM | `agent/`, `tools/`, `services/` |
| RAG | Sentence Transformers, Chroma — `rag/`, `knowledge/` |
| Database | SQLite, SQLAlchemy, Alembic — `backend/db/` |
| Smart contract | Solidity, OpenZeppelin, Hardhat — `contracts/` |
| Kiểm thử | pytest/unittest, Node test runner, Playwright |

Chi tiết dependency boundaries nằm trong [kiến trúc](docs/ARCHITECTURE.md).
Factory/lifespan, agent integration, wallet workflows/repositories, blockchain
adapters và evaluator đã được chia theo trách nhiệm; các facade/import cũ vẫn
được giữ cho callers. Xem [ma trận runtime/API](docs/RUNTIME_PROFILES.md) và
[quy ước cài đặt/đóng gói](docs/PACKAGING.md).

## Cài đặt

Các lệnh dành cho **Windows PowerShell**, chạy tại root repository. Môi trường
đã kiểm tra: **Python 3.12 x64**, **Node.js 22**, npm và MetaMask trên Chrome/Edge.
`requirements.txt` khóa dependency của môi trường Windows/CPU; chưa xác nhận
cài mới trên mọi hệ điều hành khác.

### 1. Cài dependency

Nếu đã có repository hoặc môi trường Python, bỏ qua bước clone/tạo môi trường
tương ứng. Nhánh tích hợp hiện tại là `feature/e2e-testing`.

```powershell
git clone --branch feature/e2e-testing https://github.com/viet555-it/ai-agent-blockchain.git
Set-Location ai-agent-blockchain

python -m venv .venv-phase3
.\.venv-phase3\Scripts\python.exe -m pip install -r requirements.txt
.\.venv-phase3\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv-phase3\Scripts\python.exe -m pip check

npm.cmd --prefix contracts ci
npm.cmd --prefix contracts run compile
npm.cmd --prefix frontend ci
```

Dùng `npm.cmd` để tránh PowerShell chặn `npm.ps1`. Không cần activate môi trường
vì các lệnh gọi trực tiếp Python bên trong virtual environment.

### 2. Cấu hình

Tạo `.env` từ mẫu nếu chưa tồn tại:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Sửa các biến sau trong `.env` ở root; giữ các cấu hình RAG còn lại từ mẫu:

```dotenv
LLM_PROVIDER=gemini
GEMINI_API_KEY=<API key của bạn>
LLM_MODEL=gemini-3.5-flash-lite

PHASE3_PROFILE=local_evm
PHASE3_AGENT=llm
PHASE3_LOCAL_WRITES=false
LOCAL_RPC_URL=http://127.0.0.1:8545
DEFAULT_CHAIN_ID=31337
PORT=8000

WALLET_HISTORY_ENABLED=true
BROWSER_WALLET_WRITES=true
DATABASE_URL=sqlite:///data/app.db
APP_ORIGIN=http://127.0.0.1:8000
```

Model trên là cấu hình mẫu của dự án; chọn model mà API key của bạn có quyền
truy cập. Dự án cũng có adapter OpenAI/Anthropic; đổi provider, model và key tương
ứng. Provider `fake` dành cho test có kịch bản, không thay LLM cho chat tự do.
Biến môi trường trong terminal được ưu tiên hơn `.env`.

`PHASE3_LOCAL_WRITES` dành cho luồng demo cũ. Luồng MetaMask dùng
`BROWSER_WALLET_WRITES`; không cần điền private key vào `.env`.
Không commit `.env` hoặc database cá nhân.

### 3. Chuẩn bị RAG và database

Lần đầu cần mạng để tải model embedding và tokenizer:

```powershell
.\.venv-phase3\Scripts\python.exe -m scripts.ingest_rag --verify-git --allow-download
.\.venv-phase3\Scripts\python.exe -c "from config.environment import load_project_env; load_project_env(); import tiktoken; tiktoken.get_encoding('cl100k_base'); print('tokenizer cached')"
.\.venv-phase3\Scripts\python.exe -m scripts.migrate_app_db
```

RAG dùng `config/rag.json`, cache tại `.cache/rag/huggingface` và index tại
`data/rag`. Các lần ingest sau có thể bỏ `--allow-download` để dùng cache.
Nếu thiếu commit nguồn khi kiểm `--verify-git`, xem [hướng dẫn RAG](docs/RAG_SETUP.md).

## Chạy ứng dụng

**Terminal 1 — blockchain local:**

```powershell
npm.cmd --prefix contracts run node -- --hostname 127.0.0.1
```

**Terminal 2 — deploy/kiểm tra contract rồi chạy API:**

```powershell
.\.venv-phase3\Scripts\python.exe -m scripts.setup_local_demo
.\.venv-phase3\Scripts\python.exe -m backend.api.server
```

Mở **[http://127.0.0.1:8000](http://127.0.0.1:8000)** trong browser có MetaMask.
API phục vụ frontend trực tiếp, không cần chạy Vite để demo. Giữ hai terminal
chạy và dùng đúng địa chỉ khớp `APP_ORIGIN`.

Hardhat lưu trạng thái node trong bộ nhớ. Sau khi restart/reset node, chạy lại
`scripts.setup_local_demo`, restart API và kết nối lại ví. Script kiểm bytecode
và receipt trước khi tái sử dụng deployment. Lịch sử SQLite của deployment cũ
vẫn được giữ; Agent mở hội thoại thuộc deployment hiện tại.

## Kết nối ví và nhận AGNT

Thêm mạng local vào MetaMask:

| Trường | Giá trị |
|---|---|
| Tên mạng | Hardhat Local |
| RPC URL | `http://127.0.0.1:8545` |
| Chain ID | `31337` |
| Currency symbol | `ETH` |

1. Import một tài khoản test từ terminal Hardhat vào MetaMask. Khóa này chỉ dùng
   trên mạng local; không nhập khóa vào giao diện chat.
2. Chọn **Hardhat Local**, mở ứng dụng và bấm **Kết nối ví**.
3. Xác nhận quyền tài khoản và ký thông điệp đăng nhập khi MetaMask yêu cầu.
4. Khi hiện **Agent sẵn sàng**, nhập yêu cầu vào chat. Đổi ví qua menu địa chỉ ví
   hoặc MetaMask, rồi xác thực ví mới để tải lịch sử tương ứng.

Hardhat cấp sẵn ETH cho tài khoản test. Khi deploy, **1.000.000 AGNT được cấp cho
Account #0**; các tài khoản khác ban đầu có 0 AGNT. Thử các câu lệnh:

```text
Kiểm tra số dư ETH của ví tôi.
Nhận 50 AGNT từ faucet vào ví hiện tại của tôi.
Kiểm tra số dư AGNT của ví tôi.
```

Để nhận token: duyệt đề xuất trên app, xác nhận giao dịch trong MetaMask rồi chờ
receipt. Faucet cho tối đa **100 AGNT/lần**, cooldown **60 giây**. Contract có
hạn mức chuyển mặc định **500 AGNT/lần**; policy của app có thể giới hạn thêm.

Muốn hiển thị AGNT trong MetaMask, thêm token tùy chỉnh với `contractAddress`
trong `backend/abi/31337/deployment.json`, symbol **AGNT**, decimals **18**.
Thêm token vào MetaMask chỉ thay đổi hiển thị, không cấp token cho ví.

## Giao dịch và lịch sử

```text
Yêu cầu → proposal → policy + mô phỏng → duyệt trên app → MetaMask ký/gửi
→ backend đối soát transaction/receipt → lưu kết quả vào SQLite
```

Hội thoại thuộc ví đã xác thực và deployment đang dùng. Đổi ví không chuyển
lịch sử sang ví khác; tải lại trang khôi phục lịch sử đã lưu.
`MINED_SUCCESS`/`MINED_REVERTED` phản ánh receipt; `MATCHED` cho biết giao dịch
khớp payload đã duyệt. Nếu trạng thái `UNKNOWN` hoặc đang chờ ký, kiểm tra
MetaMask/lịch sử trước khi thử tiếp để tránh gửi trùng.

Lịch sử chỉ gồm thao tác qua ứng dụng, chưa index toàn bộ hoạt động của ví.
Backup database đang dùng bằng tên file mới cho mỗi lần chạy:

```powershell
.\.venv-phase3\Scripts\python.exe -m scripts.backup_app_db --output data/backups/app-demo.db
```

Xem [runbook ví và database](docs/WALLET_HISTORY_RUNBOOK.md) để phục hồi, đối soát
hash và xử lý các trạng thái chưa rõ.

## Kiểm thử

Cài Chromium một lần sau khi cài dependency frontend:

```powershell
node frontend/node_modules/playwright/cli.js install chromium
```

Chạy backend, local EVM, frontend, build và Chromium E2E:

```powershell
.\scripts\test_wallet.cmd
```

Hoặc chạy từng nhóm:

```powershell
.\.venv-phase3\Scripts\python.exe -m scripts.run_phase3 --suite unit
.\.venv-phase3\Scripts\python.exe -m scripts.run_phase3 --suite rag
.\.venv-phase3\Scripts\python.exe -m scripts.check_packaging
.\.venv-phase3\Scripts\python.exe -m scripts.run_phase3 --suite local_evm
npm.cmd --prefix contracts test
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
.\.venv-phase3\Scripts\python.exe -m scripts.run_wallet_e2e
```

Runner backend/E2E dùng FakeLLM và Hardhat, không gọi model hoặc testnet thật.
Suite `local_evm` có thể tái sử dụng node cổng 8545 và tạo giao dịch test, nên chạy
trước buổi demo. Wallet E2E tạo RPC/API/database riêng và mô phỏng provider ví;
vẫn cần thử thủ công popup MetaMask. Log runtime nằm trong `.phase3/`, được Git bỏ qua.

## Xử lý lỗi thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| PowerShell chặn `npm.ps1` | Dùng `npm.cmd`. |
| MetaMask không nhận RPC | Nhập đủ `http://127.0.0.1:8545`, kiểm tra Hardhat đang chạy. |
| Extension connected nhưng Agent chưa sẵn sàng | Bấm **Kết nối ví**, ký đăng nhập và mở chat trên deployment hiện tại. |
| Auth 200 nhưng wallet-contexts 503, `TransactionNotFound` | Giữ node chạy, chạy lại setup local, restart API rồi reconnect; giữ nguyên database. |
| Không có AGNT | Nhận token qua faucet; thêm token tùy chỉnh nếu MetaMask chưa hiển thị. |
| Giao diện vẫn là bản cũ | Restart API sau cập nhật, nhấn **Ctrl+F5**. |
| Lỗi Origin/CSRF | Mở URL khớp `APP_ORIGIN`; xác thực lại khi phiên hết hạn. |
| Thiếu model/index RAG | Chạy bước chuẩn bị RAG; lần tải đầu cần mạng. |

## Tài liệu và phạm vi

- [Ví, lịch sử và database](docs/WALLET_HISTORY_RUNBOOK.md)
- [Thiết kế lưu trữ và đổi ví](docs/WALLET_HISTORY_DATABASE_PLAN.md)
- [Blockchain Service](docs/BLOCKCHAIN_SERVICE.md)
- [Cài đặt RAG](docs/RAG_SETUP.md)
- [Thêm công cụ cho Agent](docs/ADDING_A_TOOL.md)

Hardhat Local là môi trường demo chính. Dự án có cấu hình/tài liệu Sepolia;
muốn dùng cần RPC, deployment, ETH test và policy tương ứng. Không dùng khóa
Hardhat trên mạng có tài sản giá trị.

Chế độ history hiện dùng SQLite với một API instance và ví EOA. WalletConnect,
smart-contract wallet, PostgreSQL nhiều instance và index toàn bộ lịch sử
on-chain chưa thuộc phạm vi triển khai hiện tại.
