# Đổi ví và lịch sử lưu trong database

Luồng browser-wallet đã được tích hợp vào app. Database lưu chat, tool protocol, proposal,
approval, các lần gửi, receipt và audit. Ví trình duyệt giữ quyền ký; API không ký/gửi thay user.

## Chạy trên máy hiện tại

Chạy các lệnh từ root repository. Đã cài dependency Python và frontend trong môi trường hiện tại.
Máy mới dùng dependency đã khóa:

```powershell
.venv-phase3/Scripts/python.exe -m pip install -r requirements-phase3.lock.txt
npm --prefix frontend ci
```

File `.env` root dùng:

```dotenv
PHASE3_PROFILE=local_evm
PHASE3_AGENT=llm
WALLET_HISTORY_ENABLED=true
DATABASE_URL=sqlite:///data/app.db
APP_ORIGIN=http://127.0.0.1:8000
BROWSER_WALLET_WRITES=true
LOCAL_RPC_URL=http://127.0.0.1:8545
```

Giữ cấu hình model/RAG hiện có. `BROWSER_WALLET_WRITES` là quyền chuẩn bị payload để ví user
ký, không bật signer backend. `PHASE3_LOCAL_WRITES` chỉ có tác dụng ở chế độ demo cũ khi
wallet history tắt. File mẫu `.env.example` mặc định tắt tính năng để người dùng máy mới
chạy migration và cấu hình origin trước.

Terminal 1:

```powershell
npm --prefix contracts run compile
npm --prefix contracts run node -- --hostname 127.0.0.1
```

Terminal 2:

```powershell
.venv-phase3/Scripts/python.exe -m scripts.setup_local_demo
.venv-phase3/Scripts/python.exe -m scripts.migrate_app_db
.venv-phase3/Scripts/python.exe -m backend.api.server
```

Mở đúng `http://127.0.0.1:8000`, khớp `APP_ORIGIN`. API phục vụ source frontend trực tiếp,
không cần Vite để chạy demo. Khi dùng hostname/port khác phải đổi `APP_ORIGIN` và khởi động
lại API. HTTPS bắt buộc ngoài localhost. Triển khai SQLite chạy một API instance.

## Kết nối và đổi ví

1. Cấu hình mạng Hardhat trong extension: RPC `http://127.0.0.1:8545`, chain ID `31337`, ETH.
   Nếu extension chưa có mạng này, thêm mạng trong extension trước khi chọn Switch network.
2. Chọn extension ở danh sách provider, bấm **Connect wallet**.
3. Bấm **Sign in to history / Đăng nhập lịch sử**, kiểm message và ký. Chữ ký này xác thực
   quyền đọc lịch sử; không phải giao dịch chuyển tài sản.
4. App tải hoặc tạo hội thoại của ví. Các nút New chat, Rename, Archive quản lý hội thoại;
   Older messages/Load more phân trang lịch sử. Archive không xóa vĩnh viễn dữ liệu.
5. Bấm Change account hoặc chọn tài khoản khác trong extension. App khóa thao tác và dọn
   nội dung cũ. Đăng nhập ví mới để tải lịch sử riêng. Không cần sửa `.env` hoặc restart API.
6. Quay về A và đăng nhập: thấy lại lịch sử A. Việc đăng nhập ví mới được thông báo tới
   các tab cùng browser; các tab cũ phải xác thực lại.

Local test account chỉ dùng cho Hardhat; không dùng cùng khóa/seed này trên mạng có tài sản.
App không có ô nhập private key/seed. Để gửi giao dịch, tài khoản phải có ETH trả gas.

## Giao dịch

- Các thao tác hỗ trợ: chuyển ETH, chuyển AGNT, nhận AGNT faucet.
- Agent tạo proposal; modal hiển thị sender, recipient, mạng, amount, gas và mô phỏng.
- Duyệt ở app xong, extension mới hỏi ký/gửi. API chỉ cấp một submission cho proposal.
- Worker đọc RPC mỗi khoảng 15 giây để kiểm transaction/receipt; có thể bấm Refresh history.
- `MATCHED` nghĩa là giao dịch khớp payload; `MISMATCHED` nghĩa là khác payload/giới hạn.
- `MINED_SUCCESS` / `MINED_REVERTED` là kết quả receipt hiện tại. `FINALIZED` vẫn phải
  xem receipt success/revert; FINALIZED không tự có nghĩa là chuyển tiền thành công.
- Finality dựa trên block tag `finalized` của RPC, không tự gán từ một số confirmation cố định.
- Một ví chỉ có một submission chưa đối soát xong trong cùng deployment. Khóa được giữ tới
  khi nonce của sender được xác nhận finalized hoặc ví từ chối ký rõ ràng.
- Policy whitelist chuyển tiền vẫn giữ; faucet cho phép mint về chính caller, không mở
  thêm quyền chuyển tới mọi địa chỉ.

Các trạng thái không rõ:

- **AWAITING_SIGNATURE / UNKNOWN:** không bấm gửi lại. Kiểm extension và lịch sử on-chain.
- **Có hash nhưng app chưa lưu:** metadata báo hash trong sessionStorage có thể được gửi lại
  khi reload. Nó chỉ cấp quyền báo hash, không cấp quyền đọc lịch sử hay ký.
- **Mất hash:** worker tìm có giới hạn theo sender/nonce trong tối đa 200 block gần đây kể từ
  lúc chuẩn bị. User có thể mở mục giao dịch chưa rõ, nhập hash để backend kiểm tra.
- **Giao dịch thay thế/speed-up/cancel:** worker tạo attempt mới nối với attempt REPLACED;
  giao dịch thay thế vẫn phải khớp payload để được ghi nhận thực thi đúng proposal.
- **Đổi ví khi popup ký còn mở:** app không thể hứa hủy popup hoặc tx. Hash đến muộn vẫn
  ghi dưới A; B không được đọc lịch sử riêng A. Giao dịch đã gửi tiếp tục được worker theo dõi.
- **Reset Hardhat:** instance ID từ `hardhat_metadata` phân biệt chain cũ/mới. Chạy setup
  lại, restart API và reconnect. Lịch sử cũ giữ lại dưới deployment cũ, không ký proposal cũ.

Chủ ví có thể chỉnh giao dịch trong extension hoặc gửi ngoài app. Guardrail kiểm soát payload
do app cấp; không cưỡng chế mọi giao dịch của một EOA. App ghi MISMATCHED và không coi đó
là proposal thực thi hợp lệ. Chưa có smart-account policy enforcement trong phạm vi này.

## Persistence và bảo vệ lịch sử

- Identity xác thực bằng exact server-issued SIWE message; nonce dùng một lần, có expiry và
  browser binding. Chỉ EOA được hỗ trợ.
- Cookie auth HttpOnly; CSRF và Origin kiểm tra mọi thao tác thay đổi trạng thái.
- `wallet_address` từ client không được dùng thay cho kiểm quyền owner từ session.
- Mỗi conversation gắn cố định owner và deployment; chat bị gián đoạn không tự chạy lại tool.
- DB lưu transcript trước khi cache context bị trim; context phục hồi theo nhóm tool call/result
  và token budget. Không lưu text thought của model; chỉ giữ protocol/signature cần thiết.
- Request chat có ID chống ghi trùng; lease trong DB ngăn hai request cùng conversation xử lý
  đồng thời. Cache RAM không phải nguồn chuẩn.
- API `/api/chat`, `/api/approval/*`, `/api/transactions/propose`, `/api/guardrail/audits` cũ bị
  khóa khi bật wallet-history mode. Không có đường tắt bỏ auth qua demo endpoint.
- History trong app chỉ gồm dữ liệu phát sinh từ khi bật tính năng. Không thể phục hồi chat RAM
  đã mất trước đó; chưa có index toàn bộ giao dịch on-chain của ví.

## Migration, backup, phục hồi và rollback

Migration chạy trước API, không tự chạy ở mỗi worker:

```powershell
.venv-phase3/Scripts/python.exe -m scripts.migrate_app_db
```

Backup SQLite nhất quán, kể cả committed WAL:

```powershell
.venv-phase3/Scripts/python.exe -m scripts.backup_app_db --output data/backups/app-20261028.db
```

Lệnh không ghi đè file đã có. Bản backup chứa lịch sử riêng, phải giới hạn người có quyền đọc.
Không copy một mình `app.db` trong lúc đang ghi WAL. Để phục hồi, dừng API, giữ nguyên DB
cũ, trỏ `DATABASE_URL` sang bản sao của backup rồi kiểm migration trước khi chạy API.
Không downgrade hoặc xóa DB để xử lý giao dịch UNKNOWN.

Đối soát thủ công một lượt, không ký/gửi:

```powershell
.venv-phase3/Scripts/python.exe -m scripts.reconcile_app_transactions
```

Tắt `BROWSER_WALLET_WRITES` để ngừng cấp lệnh ký mới nhưng vẫn giữ history và worker.
Để quay lại demo cũ, tắt `WALLET_HISTORY_ENABLED`, cấu hình `PHASE3_LOCAL_WRITES` như runbook
cũ và restart; việc này không xóa DB. Không reset ledger Sepolia grant cũ.

PostgreSQL nhiều instance, smart-contract wallets, WalletConnect, gộp nhiều ví vào một user,
purge/export và retention tự động là phần mở rộng, chưa được bật/kiểm thử trong bản SQLite này.

## Kiểm thử

```powershell
.venv-phase3/Scripts/python.exe -m scripts.run_phase3 --suite unit
.venv-phase3/Scripts/python.exe -m scripts.run_phase3 --suite local_evm
npm --prefix frontend test
npm --prefix frontend run build
node frontend/node_modules/playwright/cli.js install chromium
.venv-phase3/Scripts/python.exe -m scripts.run_wallet_e2e
```

E2E tự tạo RPC/API ở cổng trống, deployment và database tạm; dùng FakeLLM và account local.
Chỉ dừng process do runner tạo. Không dùng API key/khóa từ `.env` thật, không gọi testnet.
Kết quả ở `.phase3/wallet-e2e/results.json`, `api.log`, `history.png`; runner giữ log riêng,
xóa database tạm khi kết thúc. Browser provider test mô phỏng protocol extension; chưa thay
cho smoke thủ công UI của từng extension thật.

Kết quả kiểm tra ngày 28/10/2026: 291 test unit qua (3 ca Hardhat được skip ở suite unit),
156 test trong suite backend/Hardhat qua, 5 test frontend qua và 5 ca Chromium E2E qua
(đổi ví/reload, faucet, response đến muộn, nhiều tab, mobile/tiếng Việt). Frontend build,
lint các module mới, kiểm tra dependency và migration schema 0001 đều qua.
