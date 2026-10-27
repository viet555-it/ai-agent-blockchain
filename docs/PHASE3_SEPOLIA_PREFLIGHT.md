# G3.4 — Sepolia preflight chỉ đọc

Đã chạy ngày 27/10/2026, bắt đầu 17:30:49 (Asia/Saigon). Kết quả PASS cho
READ preflight và API/RAG/READ smoke. Chưa cho phép hoặc gửi giao dịch Sepolia.

Evidence local: `.phase3/sepolia-preflight-20261027T103123Z.json`.
Script: `scripts/preflight_sepolia.py`; regression: `tests/test_sepolia_preflight.py`.

## Kết quả quan sát

| Kiểm tra | Kết quả |
|---|---|
| RPC chain | 11155111, đúng Sepolia |
| Contract | `0xa453B71a492558C17efA82E294739e4eFef3C220` |
| Bytecode runtime | Khớp hash manifest `0x93baa9b6…1d8ef42` |
| ABI/RAG scope | Đúng chain, address và ABI hash; index scoped khởi tạo thành công |
| Snapshot preflight | Block 12004537; các getter và balance pin theo block này |
| Token | Agent Token / AGNT / 18 decimals |
| Total supply / cap | 1.000.000 / 10.000.000 AGNT |
| Transfer limit live | 500 AGNT |
| Faucet live | 100 AGNT/lần, cooldown 60 giây |
| Owner / observer | `0x59c6f777551a5Bd19d73d8a47499F21fb53dCbe5` |
| Observer balance | 0,04999228468698713 Sepolia ETH; 1.000.000 AGNT |
| API reads | Native balance, AGNT balance, token metadata đều thành công |
| API WRITE probe | Tool không có trong READ registry; bị chặn |
| Nonce / broadcast | Pending nonce 1 → 1; 0 broadcast |

API smoke dùng FakeLLM để kiểm wiring trên RPC/index thật; không phải đánh giá
Gemini trên Sepolia. HTTP provider riêng chỉ cho phép RPC READ ngay từ lúc tạo,
trước khi Web3 cache middleware. Lượt API ghi nhận 2 `eth_getTransactionCount`,
1 `eth_getBalance`, 14 `eth_chainId`, 7 `eth_call`; không có phương thức bị cấm.
Regression kiểm cả việc chặn `eth_sendRawTransaction` sau khi middleware đã cache.

Địa chỉ observer lấy từ manifest, không được coi là public address đã xác minh
từ private key. Chưa dùng key để suy ra signer hoặc ký. Chưa đánh giá ví nhận.
Giá trị quan sát có thể thay đổi; phải kiểm lại trước giao dịch.

## Chạy lại

Chỉ cần RPC trong `.env` gốc; không cần private key cho các lệnh này:

```powershell
.venv-phase3/Scripts/python.exe -m scripts.preflight_sepolia
.venv-phase3/Scripts/python.exe -m scripts.preflight_sepolia --api-smoke
```

`--wallet 0x...` đổi public address chỉ để đọc. Script không đổi profile trong
`.env`, không deploy, không tạo approval và không có nhánh broadcast. Lỗi RPC
chỉ lưu stage/type, không lưu exception text hoặc URL chứa key.

## Đợt WRITE đã được cấp quyền và hoàn tất

Đợt nhỏ đầu tiên: tối đa 2 giao dịch trên contract trên, qua API/approval:

1. Faucet 10 AGNT cho chính signer đã xác minh.
2. Chuyển 1 AGNT tới public address ví nhận do người dùng chỉ định.

Trần tổng phí đề xuất 0,001 Sepolia ETH; không chuyển ETH, không đổi owner/limit,
không cấp allowance, không deploy lại. Kiểm worst-case gas trước ký, đối soát
receipt/event/balance sau gửi; không gửi lại mù khi trạng thái chưa rõ.

Người dùng đã duyệt sender ở trên, recipient
`0xeF9F53B00B069782256fC20697E7cf6a3136F9BC`, key qua `PRIVATE_KEY` trong `.env`,
cap 2 giao dịch / 0,001 Sepolia ETH và APPROVE bằng harness cho hai fixture.
Public address suy ra từ key khớp sender. Cả hai giao dịch đã thành công:

- [Faucet 10 AGNT](https://sepolia.etherscan.io/tx/0x68e8cad3e05fdae35067a4b6dcc3ce9a3b2cc2982bf479c39c5fe8c002604211).
- [Transfer 1 AGNT](https://sepolia.etherscan.io/tx/0x53fec2ab9b58202da36955d4f8e6b2212ef345857a1fd7c2b0fc910dbbb495b9).

Tổng phí 0,000000000005395392 Sepolia ETH; receipt/event/balances và ít nhất
hai confirmation đều khớp. Xem [PHASE3_RESULTS.md](PHASE3_RESULTS.md) để biết
chi tiết, lỗi đã sửa và đường dẫn evidence. Script
`python -m scripts.smoke_sepolia_write` chỉ preview nếu không có flag execute.
Grant hiện đã tiêu thụ cả hai fixture; không xóa/reset ledger để chạy lại.
Resume chỉ tái sử dụng receipt đã confirmed của cùng grant và gửi fixture chưa
tiêu thụ, không cấp lại ngân sách. Profile write vẫn yêu cầu execution config
tường minh trong factory, không tự mở bằng biến `.env`.
