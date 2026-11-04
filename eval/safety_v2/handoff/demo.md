# Demo offline phần Safety của Bảo Việt

Demo này chạy qua workflow thật của backend với SQLite tạm và thành phần blockchain/LLM thay thế. Không mở MetaMask, không gọi API model và không gửi giao dịch. Đây là demo tự động của logic, chưa phải demo giao diện Guardrail theo ví của Nam.

Chạy từ root repository bằng PowerShell sau khi môi trường Python và tokenizer cache đã được chuẩn bị theo README dự án:

```powershell
New-Item -ItemType Directory -Path .phase3/tmp -Force | Out-Null
$env:TEMP = (Resolve-Path -LiteralPath .phase3/tmp).Path
$env:TMP = $env:TEMP
$env:TIKTOKEN_CACHE_DIR = (Resolve-Path -LiteralPath .phase3/tiktoken).Path
$demoCases = @(
  'backend/tests/test_wallet_history.py::WalletHistoryTests::test_preparation_does_not_reserve_and_authorization_does'
  'backend/tests/test_wallet_history.py::WalletHistoryTests::test_daily_limit_changed_usage_blocks_authorization_atomically'
  'backend/tests/test_wallet_history.py::WalletHistoryTests::test_concurrent_authorization_only_grants_one_submission'
  'backend/tests/test_wallet_history.py::WalletHistoryTests::test_policy_change_during_rpc_prevents_authorization'
  'backend/tests/test_reference_safety.py::test_runtime_blocks_reference_before_model_or_tools'
)
.\.venv-phase3\Scripts\python.exe -m pytest @demoCases -v --tb=short
```

| Tình huống | Điều cần giải thích khi demo |
|---|---|
| Chuyển hợp lệ | Tạo proposal chưa giữ chỗ; authorize mới tạo reservation |
| Vượt hạn mức tích lũy | Backend trả DAILY_LIMIT_EXCEEDED; transaction rollback không để lại attempt/approval |
| Hai yêu cầu đồng thời | Cùng một proposal chỉ được cấp quyền một lần; không có reservation trùng |
| Policy đổi trong lúc mô phỏng | Kiểm tra cuối từ chối proposal cũ trước khi trả payload ký |
| Reference độc hại | Cả tiếng Việt/Anh đều bị chặn trước LLM; không gọi tool và không nhắc lại địa chỉ độc hại |

Tình huống reference có hai bộ tham số nên lệnh trên dự kiến chạy 6 test cho 5 nội dung demo. Chống vượt hạn mức giữa hai reservation khác nhau còn được kiểm riêng trong `backend/tests/test_daily_limits.py::test_concurrent_connections_cannot_overreserve`.

Khi trình bày số liệu, dùng báo cáo Gemini gốc, báo cáo chấm lại và nhận xét trace như ba phần riêng. Không trình bày demo provider giả là năng lực LLM thật. Policy hiện là cấu hình runtime; việc lưu/sửa theo ví và gắn version database còn chờ tích hợp với Nam.
