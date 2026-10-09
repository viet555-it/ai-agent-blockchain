# Smart Contracts (AgentToken)

ERC-20 AGNT, 18 decimals, supply ban đầu 1 triệu token. Phiên bản source mới có trần 10 triệu token, được OpenZeppelin ERC20Capped áp dụng cho constructor, owner mint và faucet. Faucet tối đa 100 AGNT/lần/ví, cooldown cố định 60 giây. Hạn mức chuyển mặc định 500 AGNT/lần gọi; không phải ngân sách theo ngày hoặc cơ chế chống nhiều ví.

## Kiểm thử

Trong `contracts/`:

```sh
npm install
npm test
npm run compile
```

Từ root dự án, cài requirements trong môi trường Python riêng rồi chạy:

```sh
python -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
backend/.venv/Scripts/python.exe -m unittest discover -s backend/tests -v
```

## Deploy local

Chạy một node lâu dài trong terminal thứ nhất:

```sh
npm run node
```

Terminal thứ hai, cũng trong `contracts/`:

```sh
npm run deploy:local
```

Backend dùng RPC `http://127.0.0.1:8545`. Có thể đặt `LOCAL_RPC_URL` để dùng cổng local khác; artifact chain 31337 được ignore trong Git. `npm run deploy:ephemeral` chỉ dùng thử: blockchain của lệnh đó kết thúc khi script thoát.

## Deployment theo chain ID

Script xuất ABI và manifest vào `contracts/exported/<chainId>/` và `backend/abi/<chainId>/`. Manifest chứa chain ID, địa chỉ và hash runtime bytecode. Deploy local chain 31337 không ghi đè chain Sepolia 11155111. Backend chọn manifest theo chain ID thực tế của RPC, từ chối chain mismatch, địa chỉ không có code và bytecode khác hash đã lưu.

Các file ở gốc `backend/abi/` và `contracts/exported/` là bản lưu deployment cũ; backend mới không đọc chúng. Thư mục `11155111/` giữ ABI của **contract cũ** tại `0xDf7B0c367817f97d756441da6047a1Da91cC6Fff`. Bản cũ chưa có supply cap hoặc validateTransferFrom. Không thay ABI source mới vào địa chỉ cũ. Cap và validator mới chỉ có hiệu lực sau khi deploy phiên bản mới.

Để deploy Sepolia, dùng ví testnet mới và giữ key trong `.env` cục bộ, không chép key vào chat, báo cáo hoặc commit:

```sh
npm run deploy:sepolia
```

Script ước tính gas và phí, cộng biên gas 20%, kiểm tra số dư trước khi gửi. Đây là ước tính tại thời điểm gọi; phí mạng có thể thay đổi. Script không tự verify trên explorer.

## Read tools và dry-run

`validateTransfer(sender, recipient, amount)` giữ nguyên chữ ký 3 tham số. `validateTransferFrom(sender, recipient, amount, spender)` kiểm tra allowance kể cả khi spender chính là sender. Validator và ERC-20 đều cho phép zero transfer.

Backend mô phỏng **giao dịch thực** qua eth_call với đúng caller, nên hỗ trợ cả deployment cũ và mới. Input lượng token là chuỗi thập phân hoặc int theo đơn vị token, không nhận float. Balance trả về chuỗi chính xác và số nguyên raw_balance. Ví dụ từ root dự án:

```python
from web3 import Web3
from backend.example_contract_usage import tool_check_balance, tool_simulate_transfer

w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:8545"))
print(tool_check_balance(w3, sender))
print(tool_simulate_transfer(w3, sender, recipient, "1.000000000000000001"))
print(tool_simulate_transfer(w3, sender, recipient, "1.1", spender=backend_wallet))
```

Truyền spender cho mọi transferFrom, kể cả self-spending. Contract revert trả isValid=False; lỗi kết nối RPC được ném lên caller. Dry-run phản ánh trạng thái hiện tại, không bảo đảm trạng thái khi giao dịch được thực thi. Backend không ký hoặc gửi giao dịch trong các helper này.

## Xử lý key đã lộ

Key trong báo cáo cũ cần được thay bằng key của ví mới. Việc thêm tiền tố 0x không khắc phục lộ key. Nếu ví cũ vẫn là owner, có thể chuyển quyền quản trị trên contract cũ trước khi bỏ key cũ:

1. Tạo ví mới trong ví của bạn; xác nhận địa chỉ public và giữ private key riêng.
2. Đặt NEW_OWNER trong `.env` thành địa chỉ public của ví mới; để PRIVATE_KEY tạm thời là key của owner hiện tại cho bước chuyển quyền.
3. Chạy `npm run ownership:check`: chỉ kiểm tra chain, owner và mô phỏng, chưa gửi giao dịch.
4. Sau khi xác nhận địa chỉ đích, đặt `SEND_OWNERSHIP_TRANSFER=true` rồi chạy lại lệnh để gửi giao dịch chuyển quyền. Xóa flag sau khi xong.
5. Cập nhật PRIVATE_KEY cục bộ sang key mới; xử lý tài sản còn ở ví cũ bằng ví của bạn. Chuyển ownership không chuyển ETH hoặc token balance.

Công cụ chuyển owner tương thích contract cũ và không sửa manifest địa chỉ. Không gửi key mới qua chat.

## Test tích hợp backend trên node local

Sau khi node local chạy và contract đã compile, từ root dự án trong PowerShell:

```powershell
$env:LOCAL_TEST_RPC = "http://127.0.0.1:8545"
backend/.venv/Scripts/python.exe -m unittest discover -s backend/tests -v
```

Test tích hợp tự deploy token riêng và chỉ chấp nhận chain 31337. Khi không đặt LOCAL_TEST_RPC, chỉ test tích hợp đó bị skip; các test backend khác vẫn chạy.
