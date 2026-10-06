# 🤖 Web3 AI Agent - Autonomous Blockchain & Smart Contract Executor

Hệ thống AI Agent thông minh tích hợp Blockchain, cho phép người dùng tương tác với Smart Contract, tra cứu dữ liệu on-chain, soạn thảo giao dịch chuyển tiền (ETH & Token ERC-20), và Mint NFT bằng **ngôn ngữ tự nhiên (Natural Language)**.

---

## 🌟 Tính Năng Nổi Bật

1. **AI Natural Language Web3 Executor**:
   - Tự động hiểu ý định người dùng (Intent Recognition) và gọi công cụ (Tool Calling).
   - Tra cứu số dư native (ETH, Sepolia ETH, Polygon...) và token ERC-20 (USDC, USDT, LINK, WETH...).
   - Soạn thảo giao dịch gửi tiền on-chain an toàn với đầy đủ tham số (to, value, gas limit, data).
   - Soạn thảo giao dịch Mint NFT đại diện (ERC-721).
   - Tra cứu trạng thái giao dịch (Transaction Hash status) trực tiếp trên Blockchain Explorer.

2. **Bảo Mật & Phê Duyệt Phân Tán (Decentralized Approval)**:
   - Private key của người dùng **không bao giờ** gửi lên AI hoặc Backend.
   - AI Agent chỉ đóng vai trò chuẩn bị payload giao dịch (Transaction Proposal).
   - Người dùng trực tiếp kiểm tra và bấm **"Xác nhận & Ký trên Ví"** qua MetaMask / Web3 Wallet.

3. **Giao Diện Hiện Đại (Modern Web3 UI)**:
   - Chatbot trực quan thời gian thực với định dạng Markdown và thẻ giao dịch tương tác (Interactive Transaction Cards).
   - Dashboard theo dõi ví, mạng lưới (Sepolia Testnet, Mainnet, Hardhat/Local), số dư tức thời.
   - Thao tác nhanh (Quick Actions) 1-click.
   - Tùy chỉnh OpenAI API Key trực tiếp trong cài đặt hoặc sử dụng bộ điều hướng Heuristic thông minh sẵn có.

---

## 🏗️ Cấu Trúc Dự Án

```
ai-agent-blockchain/
├── backend/                  # FastAPI Backend Server (Python)
│   ├── app/
│   │   ├── agent/            # AI Agent Engine & Web3 Tools definition
│   │   │   ├── engine.py     # OpenAI Tool Calling & Fallback Processor
│   │   │   └── tools.py      # Blockchain Tool execution logic
│   │   ├── api/              # API Routes
│   │   │   ├── routes_chat.py
│   │   │   └── routes_wallet.py
│   │   ├── core/             # Configuration & Environment settings
│   │   │   └── config.py
│   │   ├── models/           # Pydantic Request/Response Schemas
│   │   │   └── schemas.py
│   │   ├── services/         # Web3.py Blockchain wrapper & ABI
│   │   │   └── blockchain.py
│   │   └── main.py           # FastAPI entrypoint & CORS
│   ├── .env.example
│   ├── requirements.txt
│   └── test_agent.py         # Test script for backend verification
├── frontend/                 # Next.js 14 (App Router) + Tailwind CSS + Ethers.js
│   ├── src/
│   │   ├── app/              # Next.js App routes & Layout
│   │   ├── components/       # UI Components
│   │   │   ├── Navbar.tsx
│   │   │   ├── ChatInterface.tsx
│   │   │   ├── TransactionCard.tsx
│   │   │   ├── WalletOverview.tsx
│   │   │   ├── QuickActions.tsx
│   │   │   └── SettingsModal.tsx
│   │   ├── context/          # Web3 Wallet Provider (MetaMask/Browser)
│   │   │   └── WalletContext.tsx
│   │   └── services/         # API Service
│   │       └── api.ts
│   ├── package.json
│   └── tailwind.config.js
└── contracts/                # Smart Contracts (Solidity)
    ├── MockERC20.sol         # Test Token ERC-20
    └── MockNFT.sol           # Test NFT ERC-721
```

---

## 🚀 Hướng Dẫn Khởi Chạy

### 1. Khởi chạy Backend (FastAPI)

Mở một cửa sổ Terminal:

```powershell
# Di chuyển vào thư mục backend
cd backend

# Kích hoạt môi trường ảo Python
.venv\Scripts\activate

# Cài đặt thư viện (nếu chưa cài)
pip install -r requirements.txt

# (Tùy chọn) Cấu hình file .env nếu có OpenAI API Key
# Sao chép .env.example thành .env và điền OPENAI_API_KEY=...

# Chạy server FastAPI tại cổng 8000
uvicorn app.main:app --reload --port 8000
```

> **API Documentation (Swagger UI)**: Truy cập `http://127.0.0.1:8000/docs`

---

### 2. Khởi chạy Frontend (Next.js)

Mở một cửa sổ Terminal khác:

```powershell
# Di chuyển vào thư mục frontend
cd frontend

# Cài đặt dependencies (nếu chưa cài)
npm install

# Khởi chạy Next.js development server
npm run dev
```

> **Giao diện Web App**: Mở trình duyệt và truy cập `http://localhost:3000`

---

## 💬 Ví Dụ Câu Lệnh Tương Tác Với AI Agent

| Yêu Cầu | Câu Lệnh Mẫu | Hành Động Của AI Agent |
|---|---|---|
| **Kiểm tra số dư** | *"Kiểm tra số dư ví của tôi"* hoặc *"Xem số dư ví 0xd8dA6BF..."* | Gọi tool `get_native_balance` và trả về số dư ETH hiện có |
| **Gửi ETH** | *"Gửi 0.01 ETH tới 0x71C9491133502447972423423719011234567890"* | Tạo thẻ xác nhận giao dịch `transfer_native`, ước tính Gas và chuẩn bị payload cho MetaMask |
| **Chuyển Token** | *"Chuyển 50 USDC cho 0x71C949..."* | Gọi `prepare_transfer_erc20`, mã hóa hàm `transfer(to, amount)` |
| **Mint NFT** | *"Mint 1 NFT về địa chỉ ví của tôi"* | Soạn thảo giao dịch `mintNFT` trên Smart Contract ERC-721 |
| **Tra cứu Tx** | *"Kiểm tra trạng thái giao dịch 0x..."* | Truy vấn receipt on-chain và báo cáo trạng thái thành công/thất bại kèm link Etherscan |
| **Mạng lưới** | *"Cho tôi biết thông tin mạng blockchain hiện tại"* | Lấy block number mới nhất và trạng thái kết nối RPC |