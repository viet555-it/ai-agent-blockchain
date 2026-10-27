# Chạy demo giai đoạn 3 trên máy local

Máy mới: dùng [hướng dẫn bàn giao](PHASE3_HANDOFF.md) để cài dependency, chuẩn bị
root env và index RAG. Trình diễn cho nhóm theo [checklist demo](PHASE3_DEMO.md).

Mở hai terminal PowerShell. Các lệnh dưới đây chạy từ repository
`D:\study_materials\ATI\Project\ai-agent-blockchain` và dùng môi trường
`.venv-phase3` đã chuẩn bị. Không cần private key: giao dịch chỉ dùng account
unlocked của Hardhat trên loopback, chain 31337.

## Terminal 1: blockchain local

```powershell
Set-Location D:\study_materials\ATI\Project\ai-agent-blockchain\contracts
npm run compile
npm run node -- --hostname 127.0.0.1
```

Giữ terminal này mở. Khi node khởi động lại, dữ liệu blockchain cũ sẽ mất.

## Terminal 2: deploy fixture và chạy app

```powershell
Set-Location D:\study_materials\ATI\Project\ai-agent-blockchain
.venv-phase3/Scripts/python.exe -m scripts.setup_local_demo
.venv-phase3/Scripts/python.exe -m backend.api.server
```

Script setup kiểm chain/client, triển khai hoặc tái sử dụng AgentToken, xuất
manifest/ABI vào `backend/abi/31337` và `contracts/exported/31337`. Chạy lại script
sau mỗi lần reset node, rồi khởi động lại API. Artifact Sepolia không bị sửa.

File `.env` tại root cần có `LLM_PROVIDER=gemini`, `LLM_MODEL` đã chọn và
`GEMINI_API_KEY` của bạn, cùng `PHASE3_PROFILE=local_evm`, `PHASE3_AGENT=llm`,
`PHASE3_LOCAL_WRITES=true`, `LOCAL_RPC_URL=http://127.0.0.1:8545` và
`TIKTOKEN_CACHE_DIR=.phase3/tiktoken`. Cấu hình này đã được hợp nhất vào file gốc.
API, Agent CLI và Hardhat tự đọc đúng file đó; RAG đọc hai đường dẫn RAG trong
file gốc. Không cần tạo `.env` trong thư mục con hoặc truyền `--env-file`.
Biến đã đặt trong terminal được ưu tiên; mở terminal mới nếu muốn chỉ dùng giá
trị trong file. Không dán key vào chat hoặc commit Git. `fake` chỉ phục vụ
test có kịch bản, không tự hiểu yêu cầu chat tự nhiên.

Mở [app local](http://127.0.0.1:8000). Chat với model thật sẽ sử dụng quota API
của bạn, bao gồm prompt và RAG context.

## Thử luồng trên giao diện

1. Hỏi số dư ETH và thông tin AGNT.
2. Yêu cầu nhận 10 AGNT từ faucet. Kiểm số lượng, ví nhận, chain và gas trong
   cửa sổ xác nhận. Chọn Reject lần đầu để kiểm không gửi giao dịch.
3. Gửi lại yêu cầu và chọn Confirm. Chỉ coi thành công khi trạng thái CONFIRMED;
   kiểm hash, số dư AGNT và receipt. Faucet có cooldown 60 giây, tối đa 100 AGNT/lần.
4. Thử chuyển 2 AGNT tới ví local mặc định được whitelist:
   `0x70997970C51812dc3A010C7d01b50e0d17dc79C8`. Kiểm số dư trước/sau.

Giới hạn policy mặc định: 0,5 ETH và 500 AGNT/giao dịch, recipient phải nằm trong
whitelist. Faucet nhận tại chính sender. Chỉ mở ba thao tác: chuyển ETH,
chuyển AGNT, faucet; không có generic contract call hoặc allowance trong API mới.

## Trạng thái và giới hạn demo

- Khi thiếu cờ, code mặc định tắt WRITE. Mẫu demo `.env.example` đặt
  `PHASE3_LOCAL_WRITES=true`, chỉ có hiệu lực với `local_evm` + `llm`;
  profile Sepolia WRITE vẫn cần execution grant riêng.
- Model chỉ tạo đề xuất. Một coordinator chung kiểm policy, mô phỏng, bind
  payload và xử lý duyệt; chỉ sau APPROVE mới gửi giao dịch.
- Pending approval hết hạn sau 10 phút. Session nằm trong tab, không phải đăng
  nhập; app dùng cho demo local một người, chưa phải dịch vụ nhiều người dùng.
- Approval và trạng thái đối soát giữ trong RAM. Restart API làm mất pending
  approval. Không restart để thử lại một giao dịch có kết quả UNKNOWN.
- PENDING: đã broadcast, tiếp tục kiểm bằng hash; polling không gửi lại.
  REVERTED: receipt status=0. UNKNOWN: kiểm chain/nonce thủ công; coordinator
  chặn đề xuất mới khi kết quả broadcast chưa rõ.
- `DRY_RUN` của Agent vẫn bật; bộ proposal local dùng cờ riêng bên trên và
  nút duyệt để cho phép gửi bằng account Hardhat. Không dùng wallet key từ `.env`.

## Kiểm thử tự động

```powershell
.venv-phase3/Scripts/python.exe -m scripts.run_phase3 --suite unit
.venv-phase3/Scripts/python.exe -m scripts.run_phase3 --suite local_evm
```

Các runner dùng FakeLLM, loại key khỏi môi trường con, không gọi Gemini hoặc
Sepolia. Integration dùng deployment tạm riêng; chỉ dừng Hardhat do runner tạo.

## G3.5: đánh giá model và hệ thống

Dataset, quy tắc chấm, lệnh dev/freeze/safety/holdout và giới hạn request được
ghi tại [E2E_README.md](../eval/E2E_README.md). Runner benchmark tự tạo Hardhat
ở cổng trống và deployment tạm; không cần chạy app hay reset node demo. WRITE
chỉ prepare/simulate; không gọi APPROVE hoặc sử dụng private key trong `.env`.

Lệnh FakeLLM dùng để kiểm harness và đo hạ tầng:

```powershell
.venv-phase3/Scripts/python.exe -m scripts.evaluate_e2e --mode fake --split dev --safety --latency-samples 100
```

Các lệnh Gemini gửi prompt/context/tool result tới Google và dùng quota thật.
Phạm vi ngày 27/10/2026 giới hạn tổng 200 request, chia dev 75 / safety 50 /
holdout 75; sổ `.phase3/g35-gemini-budget.json` giữ reservation qua restart.
Không xóa sổ hoặc chạy lại holdout để thay kết quả chưa đạt. Khi đổi code/model/
gold/config, cần một vòng dev và protocol mới; báo cáo cũ giữ nguyên làm bằng
chứng lịch sử. Các cap này không mở thêm quyền gửi giao dịch Sepolia.

## G3.4: kiểm tra Sepolia chỉ đọc

```powershell
.venv-phase3/Scripts/python.exe -m scripts.preflight_sepolia --api-smoke
```

Lệnh riêng này gọi RPC Sepolia trong `.env` gốc, dùng FakeLLM và RAG thật,
không ký/gửi. Không nằm trong runner `--suite all` để baseline luôn cô lập.
Xem kết quả và điều kiện trước WRITE tại
[PHASE3_SEPOLIA_PREFLIGHT.md](PHASE3_SEPOLIA_PREFLIGHT.md).

Đợt WRITE được người dùng duyệt ngày 27/10/2026 đã hoàn tất cả hai fixture.
Ledger `.phase3/sepolia-approved-20261027-ledger.json` giữ ngân sách đã tiêu thụ;
không xóa/reset để lặp lại. Harness chỉ preview mặc định:

```powershell
.venv-phase3/Scripts/python.exe -m scripts.smoke_sepolia_write
```

Việc gửi thêm thuộc đợt cấp quyền mới. API thường vẫn dùng cấu hình root `.env`;
profile `sepolia_write` yêu cầu execution grant tường minh, không tự dùng key chỉ
vì đổi tên profile. Grant cũ chỉ cho faucet 10 AGNT và chuyển 1 AGNT tới đúng ví
đã duyệt, không có generic call, native transfer, allowance hoặc owner operation.
