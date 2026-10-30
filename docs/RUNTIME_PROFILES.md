# Runtime profiles và hợp đồng API

Ma trận này mô tả validation tại `create_app()` ngày 30/10/2026. Kiểm tra factory
không chứng minh RPC, model, database hoặc deployment đã sẵn sàng khi startup.

## Các tổ hợp hợp lệ

| Profile | Agent | Local writes | History/browser writes | Sepolia execution grant |
|---|---|---|---|---|
| `unit` | `legacy` | false | off | Không |
| `unit` | `llm` | false | off, read, write | Không |
| `local_evm` | `legacy` | false | off | Không |
| `local_evm` | `llm` | false hoặc true | off, read, write | Không |
| `sepolia_read` | `legacy` | false | off | Không |
| `sepolia_read` | `llm` | false | off, read, write | Không |
| `sepolia_write` | `llm` | false | off | Bắt buộc object được truyền rõ |

`off`: không có wallet history. `read`: history bật, `browser_writes=false`.
`write`: history bật, `browser_writes=true`. Hai chế độ history vẫn lưu hội thoại
vào DB; `read` không có nghĩa database chỉ đọc. Browser writes là quyền chuẩn bị
đề xuất để người dùng ký bằng ví, tách khỏi transport ký/gửi của backend.

Fixture CSV `backend/tests/fixtures/runtime_profile_matrix.csv` liệt kê đủ 16
cấu hình hợp lệ. Test duyệt tích Descartes 4 profiles × 2 agent modes × 2 local
write flags × 3 history states × 2 grant states = 96 trường hợp; 80 trường hợp
còn lại phải bị từ chối. Các tham số profile/mode/flags trong ma trận được truyền
rõ vào factory. Không tạo grant thật hoặc gọi RPC Sepolia để kiểm ma trận.

Khi history bật cùng local writes, factory vẫn chấp nhận cấu hình nhưng health
báo `local_writes_enabled=false`; lifespan chọn browser workflow thay cho local
legacy coordinator. Chỉ bật `BROWSER_WALLET_WRITES` không tự bật history.

## Startup và cấu hình

- `unit` dùng chain 31337 và bắt buộc inject blockchain khi startup. Không tự
  kết nối RPC. LLM/retriever được inject hoặc tạo theo mode và ownership hiện có.
- `local_evm` dùng chain 31337 với HTTP loopback, không credentials/query/fragment
  và không có RPC fallback từ xa. Writes backend đòi `llm` và flag local writes.
- Hai profile Sepolia dùng chain 11155111. `sepolia_write` yêu cầu execution
  object và `agent_mode="llm"` được truyền rõ; đặt tên profile hoặc private key
  trong môi trường không tự tạo quyền gửi. Không dùng chung grant này với history.
- History yêu cầu `llm`, database đã migrate và scope RAG khớp chain/deployment.
  RPC/ABI/bytecode validation và resource initialization được thực hiện ở startup.
- Factory ưu tiên giá trị mode/local-write truyền trực tiếp; khi bỏ trống mới
  đọc `PHASE3_AGENT`/`PHASE3_LOCAL_WRITES`. Profile `unit` truyền rõ bỏ qua flag
  history trong môi trường, nhưng vẫn nhận `wallet_settings` được inject rõ.

Các dependency app tạo được đóng theo ownership: worker → database → retriever →
LLM. Lỗi startup/cleanup không bỏ qua cleanup còn lại. Caller quản lý dependency
LLM/retriever được inject. Xem `backend/tests/test_app_lifespan.py`.

## Hợp đồng và bằng chứng

`test_profile_contracts.py` chặn provider creation, DB creation và retriever
factory, rồi kiểm acceptance matrix và request HTTP không chạy lifespan:

- Health: chain/mode và ba feature flags, shape/status 200 giữ nguyên.
- Legacy audits: status 200 khi history off, 403 khi history bật.
- Chat thiếu query: 422; yêu cầu switch ra ngoài runtime chain: 400.
- History responses: `Cache-Control: no-store` và `X-Request-ID` cho cả lỗi.
- Hai snapshot OpenAPI (legacy và wallet history) khớp bản lưu trước bước tách
  agent: paths/methods, request parameters/body, component schemas và responses.

OpenAPI không khai báo toàn bộ response/error/cookie runtime. Các bộ test hành vi
sau kiểm phần đó thay vì suy luận chỉ từ schema:

| Hành vi | Bộ kiểm chứng |
|---|---|
| Login/session cookies, CSRF, đọc chéo ví, history persistence | `test_wallet_history.py`, wallet Playwright E2E |
| Domain error → HTTP status/code/message/headers | `test_wallet_errors.py`, `test_wallet_history.py` |
| Approval replay, nonce/preflight, không gửi từ proposal | `test_transaction_coordinator.py`, `test_transactions_local_evm.py` |
| Version/CAS, rollback, lease và send locks | `test_wallet_history.py`, `test_browser_wallet_local_evm.py` |
| Scope/token budget, cleanup và LLM integration | `test_read_runtime.py`, `test_agent_boundaries.py`, RAG suite |
| Sepolia gates/fixtures/durable reservation | `test_sepolia_execution.py` với RPC/signer fixture |

Chạy từ root bằng `python -m scripts.run_phase3 --suite unit`; runner dùng
FakeLLM và môi trường cô lập. Root `pytest` mặc định chỉ đọc `tests/`, vì vậy không
thay thế được runner có thêm `backend/tests`. `--suite rag` chạy riêng RAG suite.
Local-EVM integration và E2E cần Hardhat/artifact/model cache thích hợp; dùng
node/database test riêng khi kiểm hồi quy, không dùng node demo đang vận hành.

Các test này không thay phép thử popup MetaMask thật, tải mới model/dependencies
trên OS khác hoặc quyền gửi Sepolia thực tế. Coverage mới chưa được đo.
