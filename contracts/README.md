# Smart Contracts (AgentToken)

Thư mục chứa Smart Contract cho đồ án **AI Agent with Blockchain Tools**.

## 1. Tổng quan Smart Contract (`AgentToken.sol`)
Hợp đồng chuẩn **ERC-20** (OpenZeppelin v5) được thiết kế chuyên biệt cho AI Agent tương tác:
- **Ký hiệu**: `AGNT` (18 decimals), tổng cung ban đầu: 1,000,000 AGNT.
- **Tính năng cho AI Agent Read Tools**:
  - `balanceOf(address)`: Truy vấn số dư token của ví.
  - `name()`, `symbol()`, `totalSupply()`: Truy vấn thông tin token.
  - `maxTransferLimit()`: Lấy hạn mức chuyển tối đa cho phép.
  - `validateTransfer(sender, recipient, amount)`: Hàm view hỗ trợ AI Agent / Guardrail **mô phỏng trước giao dịch (dry-run/simulation)** trước khi ký broadcast lên blockchain.
- **Tính năng cho AI Agent Write Tools**:
  - `faucet(amount)`: Cho phép ví xin cấp token test miễn phí (tối đa 100 AGNT/lần, cooldown 60 giây). Phục vụ test prompt *"Cấp cho tôi 50 token"*.
  - `transfer(recipient, amount)`: Chuyển token, tự động kiểm tra Guardrail `maxTransferLimit` (mặc định 500 AGNT/tx).
- **Tính năng Quản trị & Guardrail**:
  - `setMaxTransferLimit(newLimit)`: Chủ sở hữu có thể cập nhật hạn mức an toàn.
  - `mint(to, amount)`: Chủ sở hữu cấp thêm token khi cần.

---

## 2. Hướng dẫn chạy và kiểm thử

### Cài đặt thư viện:
```bash
npm install
```

### Biên dịch contract:
```bash
npx hardhat compile
```

### Chạy toàn bộ Unit Tests (18 test cases):
```bash
npx hardhat test
```

### Thử nghiệm deploy trên mạng cục bộ (Hardhat local network):
```bash
npx hardhat run scripts/deploy.js --network hardhat
```

---

## 3. Deploy lên mạng Ethereum Sepolia Testnet

1. Copy file cấu hình môi trường:
   ```bash
   cp .env.example .env
   ```
2. Điền thông tin vào file `.env`:
   - `SEPOLIA_RPC_URL`: Endpoint RPC từ Alchemy hoặc Infura (ví dụ: `https://eth-sepolia.g.alchemy.com/v2/...`)
   - `PRIVATE_KEY`: Khóa riêng của ví testnet (không có tiền thật, có sẵn chút Sepolia ETH để trả gas).
   - `ETHERSCAN_API_KEY`: API Key Etherscan (dùng để verify contract).

3. Chạy lệnh deploy:
   ```bash
   npx hardhat run scripts/deploy.js --network sepolia
   ```

Khi deploy xong, script sẽ **tự động xuất 2 file** sang thư mục `backend/abi/`:
- `AgentToken_abi.json`: File ABI chuẩn JSON.
- `deployment.json`: Chứa địa chỉ contract vừa deploy và thông tin mạng.

---

## 4. Hướng dẫn dành cho Python Backend / AI Agent

Đồng đội phụ trách Python Backend / AI Agent có thể sử dụng trực tiếp file ABI bằng thư viện `web3.py`:

```python
import json
from web3 import Web3

# 1. Kết nối RPC
RPC_URL = "https://rpc.sepolia.org" # hoặc Alchemy URL
w3 = Web3(Web3.HTTPProvider(RPC_URL))

# 2. Đọc ABI và địa chỉ Contract
with open("backend/abi/AgentToken_abi.json", "r") as f:
    abi = json.load(f)

with open("backend/abi/deployment.json", "r") as f:
    deploy_info = json.load(f)
    contract_address = deploy_info["contractAddress"]

contract = w3.eth.contract(address=contract_address, abi=abi)

# 3. Read Tool Example: Kiểm tra số dư
def check_token_balance(wallet_address: str) -> float:
    raw_balance = contract.functions.balanceOf(w3.to_checksum_address(wallet_address)).call()
    return raw_balance / (10 ** 18)

# 4. Guardrail Dry-Run Example: Giả lập kiểm tra giao dịch trước khi gửi
def simulate_transfer(sender: str, recipient: str, amount_token: float):
    amount_wei = int(amount_token * (10 ** 18))
    is_valid, reason = contract.functions.validateTransfer(
        w3.to_checksum_address(sender),
        w3.to_checksum_address(recipient),
        amount_wei
    ).call()
    return is_valid, reason
```
