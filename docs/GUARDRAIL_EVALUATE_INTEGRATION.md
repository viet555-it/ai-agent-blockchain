# Hàm Thử chặn để Nam nối API/UI

Đã có `backend.services.guardrail_evaluation.evaluate_transfer_policy`. Hàm đánh giá native/ERC20 transfer bằng cấu hình server và usage trong ledger; không tạo proposal, approval, attempt, audit hay reservation, không gọi RPC/LLM. Chưa tạo endpoint HTTP hoặc UI của Nam.

Luật địa chỉ/zero address/whitelist được dùng chung với `PolicyEngine` qua `check_recipient`. Việc đổi hạn mức sang base units dùng `transfer_limit_request`, giống prepare/authorize; việc đọc cửa sổ 24 giờ dùng `DailyLimitService.evaluate`.

## Đầu vào phía server

```python
from backend.services.daily_limits import LimitScope
from backend.services.guardrail_evaluation import evaluate_transfer_policy

# Sau khi xác thực principal, context, generation và deployment ở API.
# connection thuộc một read transaction ổn định do API sở hữu.
result = evaluate_transfer_policy(
    connection,
    scope=LimitScope(principal.wallet_id, deployment_id, request.asset_id),
    config=server_policy_config,
    policy_version=server_policy_version,
    known_token_decimals=deployment_token_decimals,
    operation=request.operation,
    recipient=request.recipient,
    amount_base_units=request.amount_base_units,
    now=server_utc_timestamp,
)
```

`config`, `policy_version`, token metadata, wallet, deployment và thời gian phải lấy từ server. Không nhận config/usage/version do client tự khai. Client chỉ gửi yêu cầu cần thử; API vẫn kiểm session, quyền sở hữu context, generation và deployment hiện hành. Hàm này không thực hiện xác thực thay API.

Hiện hàm dùng `PolicyConfig` runtime đã có. Native dùng giới hạn native; các token hợp lệ trong map metadata dùng giới hạn token runtime chung, còn usage tách theo contract. `known_token_decimals` dùng key đầy đủ dạng `erc20:0x...` chữ thường; không tìm thấy key thì BLOCK `ASSET_POLICY_MISSING`. Map chỉ chứa token được server cho phép trong deployment. Metadata lỗi là lỗi cấu hình, không phải một quyết định BLOCK thành công.

Khi chưa có policy theo ví đã lưu, truyền `policy_version=None`: không tự tạo version hoặc ngụ ý đã có version trong database. Khi Nam có snapshot, phải chuyển đúng giới hạn tài sản đang thử sang config và truyền version thật cùng snapshot. Hash trả về hiện là hash `PolicyConfig` chuẩn hóa; nếu schema policy mới có thêm trường, cần thống nhất hash/version với luồng proposal/authorize trước khi tích hợp. Hàm không tự cung cấp persistence, CAS hoặc kiểm version tại authorize.

Policy và usage phải được đọc trong cùng snapshot. Với SQLite/pysqlite, API cần mở `BEGIN` tường minh trước khi đọc snapshot policy; chỉ `engine.begin()` có thể chưa tạo read snapshot ở chế độ transaction legacy. Không giữ transaction khi gọi RPC. Hàm chỉ dùng một truy vấn đọc ledger khi đầu vào đủ điều kiện tính.

## Đầu ra và UI

- `decision`: `BLOCK`, `REQUIRE_APPROVAL` hoặc `ALLOW`.
- `reason_code`: mã chính; `violations` gồm các mã vi phạm theo thứ tự cố định.
- Các số tiền là chuỗi integer base units: `per_tx_limit_base_units`, `daily_limit_base_units`, `spent_base_units`, `reserved_base_units`, `requested_base_units`, `remaining_base_units`.
- `remaining` là số còn lại trước yêu cầu thử. Trường chưa tính được trả `null`; không đổi thành 0 trên UI.
- `policy_version`, `policy_hash`, `as_of`, `window_seconds=86400`, `checks_scope="policy_only"` xác định cấu hình và phạm vi kiểm tra.

Thứ tự kiểm tra chính: operation được hỗ trợ → operation khớp loại asset → amount hợp lệ → địa chỉ/whitelist → có cấu hình metadata tài sản → giới hạn từng giao dịch → hạn mức 24 giờ. Một số kiểm tra sau không áp dụng khi đầu vào trước đó không hợp lệ. Nếu vừa vượt từng giao dịch vừa vượt 24 giờ, cả hai mã xuất hiện; mã từng giao dịch là lý do chính.

Các mã: `UNSUPPORTED_OPERATION`, `OPERATION_ASSET_MISMATCH`, `INVALID_AMOUNT`, `INVALID_ADDRESS`, `ZERO_ADDRESS`, `RECIPIENT_NOT_ALLOWED`, `ASSET_POLICY_MISSING`, `PER_TX_LIMIT_EXCEEDED`, `DAILY_LIMIT_EXCEEDED`; ca hợp lệ trả `APP_APPROVAL_REQUIRED` hoặc `POLICY_OK`. Bản đầu chỉ nhận `native_transfer` và `erc20_transfer`; approve/faucet có quy tắc riêng.

API có thể trả HTTP 200 cho một quyết định policy hoàn tất. Lỗi DB/cấu hình được đẩy lên caller, không chuyển thành BLOCK. Request sai cấu trúc hoặc scope sai cần được API kiểm tra và trả lỗi theo hợp đồng API.

UI ghi “Kết quả kiểm tra chính sách”. `ALLOW` chưa phải quyền ký hoặc bảo đảm giao dịch sẽ thành công; `REQUIRE_APPROVAL` chưa tạo yêu cầu duyệt. Kết quả chỉ đúng tại `as_of`: luồng thật vẫn kiểm lại policy, preflight và reserve nguyên tử tại authorize. Việc chọn tắt duyệt trong app còn cần sửa luồng tạo proposal theo đặc tả bàn giao, không chỉ đổi config.

## Kiểm chứng offline

`backend/tests/test_guardrail_evaluation.py` kiểm ngưỡng đúng và vượt 1 wei, spent + reserved, whitelist, zero address, metadata token, uint256, scope/cửa sổ, hạ hạn mức và lỗi DB. Một test chặn mọi câu SQL không phải SELECT trong lúc gọi thử lặp lại, rồi đối chiếu toàn bộ bảng wallet và ledger trước/sau.

Các ca benchmark cố định được đối chiếu với `WalletProposals.prepare` thật trên SQLite tạm và chain giả, gồm native/token hợp lệ, ca biên, vượt từng giao dịch và vượt tổng 24 giờ. Đây là kiểm tra policy/workflow offline, không phải kết quả model hoặc holdout độc lập.
