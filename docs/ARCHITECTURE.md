# Architecture – AI Agent with Blockchain Tools

## API composition và lifecycle hiện tại

`backend/api/server.py` giữ `create_app()` và entry point chạy API. Factory gọi
`backend/bootstrap/runtime.py` để kiểm tra profile, feature flags và lắp cấu hình;
`backend/bootstrap/lifespan.py` khởi tạo các service khi ứng dụng startup.
`backend/bootstrap/retrieval.py` chọn và kiểm tra scope RAG theo chain/deployment.
Factory và module import không kết nối RPC hoặc mở database.

| Module | Trách nhiệm |
|---|---|
| `backend/api/schemas.py` | Request models và validation |
| `backend/api/routes/` | Health/network, chat, approval và proposal endpoints |
| `backend/api/wallet_routes.py` | Xác thực ví, hội thoại và lịch sử có phân quyền |
| `backend/api/dependencies.py` | Kiểm tra quyền dùng legacy endpoints |
| `backend/api/error_handlers.py` | Chuyển lỗi wallet API thành HTTP và chính sách cache |
| `backend/bootstrap/runtime.py` | Cấu hình đã kiểm tra, chưa mở tài nguyên |
| `backend/bootstrap/lifespan.py` | Startup/shutdown, lắp service, receipt worker |

Routes lấy service từ `request.app.state`. Mỗi app có runtime riêng; public
factory vẫn hỗ trợ inject blockchain, policy, LLM, retriever và wallet settings.
LLM/retriever được truyền vào do caller quản lý. Tài nguyên do app tạo được đăng
ký vào `AsyncExitStack` ngay sau khi tạo và được đóng khi startup lỗi hoặc shutdown.
Thứ tự đóng: dừng receipt worker → database → retriever → LLM. Nếu một thao tác
cleanup lỗi, các thao tác cleanup còn lại vẫn được thực hiện.

Các phần dưới mô tả agent core và lớp công cụ hiện tại; flow wallet history và
database xem thêm `WALLET_HISTORY_RUNBOOK.md` và `WALLET_HISTORY_DATABASE_PLAN.md`.

## Frontend composition hiện tại

`frontend/app.js` lắp các view/controller và khởi động dashboard. `state.js` tạo
state cho từng dashboard; dependency được truyền vào factory thay vì view import
state toàn cục. `controllers/` quản lý chat, approval, tải assets và wallet session;
`ui/` render DOM, theme/ngôn ngữ, timeline, modal và bố cục. HTTP của dashboard đi
qua `dashboardApi` trong `api.js`; `WalletController` và `HistoryView` tiếp tục
quản lý tương tác với provider và dữ liệu lịch sử.

Controller chat kiểm tra đồng thời wallet generation, conversation và history
epoch trước khi render response. Tải số dư giữ generation guard; receipt polling
legacy chỉ gọi endpoint đọc trạng thái sau lần review đầu tiên.

`styles.css` là entry point import các file trong `styles/` theo thứ tự cascade
hiện tại. Browser có thể tải trực tiếp các ES module/CSS qua FastAPI; Vite gộp
cùng nguồn này khi build production. Các module và stylesheet vẫn được revalidate
qua `Cache-Control: no-cache` trong chế độ wallet history.

## Transaction preparation và execution hiện tại

`backend/services/transactions/` chứa các phần dùng chung:

| Module | Trách nhiệm |
|---|---|
| `models.py` | Transaction error, proposal đang chờ và kết quả chuẩn bị |
| `serialization.py` | Canonical JSON hash và chuyển receipt thành dữ liệu JSON |
| `preflight.py` | Chain rules, deployment/ABI/bytecode identity, nonce, gas, balance và `eth_call` |
| `preparation.py` | Chuẩn hóa amount/recipient, tạo unsigned transaction và đánh giá policy |
| `transports.py` | Gửi bằng tài khoản local hoặc ký/gửi raw transaction Sepolia |

`TransactionCoordinator` tiếp tục sở hữu lock, proposal binding, approval review,
nonce fence và receipt reconciliation. Nó dùng `TransactionPreparer` qua composition,
rồi gọi transport sau approval và lần preflight cuối. Import cũ của `TransactionError`,
`BoundProposal`, `SUPPORTED`, `digest` và `json_safe` từ coordinator vẫn hoạt động.

`BrowserPreparer` chỉ dùng preparation/preflight, không kế thừa coordinator và không
nhận execution transport. `BrowserWalletService` gọi `preflight()` công khai trước
khi cấp quyền ký; database tiếp tục quản lý context, version, send lock và submission.

Sepolia giữ các fixture và fee/nonce ledger hiện có. Transport ký transaction,
lưu reservation bền vững, gắn expected hash vào pending approval, rồi mới gửi raw
transaction. Không có thay đổi về thứ tự reserve-before-send hoặc xử lý `UNKNOWN`.

## Synchronous blockchain adapters

`backend/services/blockchain_service.py` giữ provider/network configuration và
public facade cho callers hiện có. Các method chuyển việc cho functions trong
`backend/services/blockchain/`:

| Module | Trách nhiệm |
|---|---|
| `abi.py` | Standard ERC-20 ABI, cùng object được re-export qua import cũ |
| `access.py` | Protocol mô tả RPC, contract và unsigned-builder capabilities |
| `reads.py` | Đọc RPC, token metadata/allowance, gas và pending receipt |
| `simulation.py` | Deployment bytecode verification và token dry-run bằng `eth_call` |
| `transaction_builder.py` | Native/ERC-20 transfer, approve và faucet payload chưa ký |
| `signer.py` | Ký bằng key được truyền trực tiếp, gửi raw transaction, đợi receipt |

Các adapter nhận dependency theo protocol và dùng `w3` public; không import ngược
facade. Builder không gọi signer hoặc broadcaster. Các helper `execute_*` cũ vẫn
điều phối prepare → sign/send → receipt qua public methods của facade. Browser
wallet và proposal tools tiếp tục dùng unsigned preparation/preflight; approval,
durable reservation và quyền gửi vẫn thuộc các flow transaction đã mô tả ở trên.

Service sync này có interface khác `services/blockchain.py`, protocol async dùng
bởi agent core; hai interface tiếp tục được giữ riêng.

## Durable browser-wallet workflows

`BrowserWalletService` là facade giữ các method API hiện có. Nó lắp các workflow
trong `backend/services/wallet/` bằng composition:

| Workflow | Trách nhiệm |
|---|---|
| `deployments.py` | Nhận diện RPC/deployment, xác minh bytecode và phát hiện Hardhat reset |
| `contexts.py` | Tạo wallet context và hàng send lock trước authorization |
| `proposals.py` | Policy theo ví, chuẩn bị proposal, đọc và từ chối proposal |
| `submissions.py` | Authorize, report, lịch sử transaction và khôi phục hash theo owner |
| `reconciliation.py` | Claim lease, đọc chain evidence, xử lý replacement/reorg và cập nhật receipt |
| `scope.py` | ContextVar dùng chung giữa history routes và proposal tools |

`backend/db/repositories/` chứa SQL của các workflow trên. Mỗi hàm repository nhận
connection đang mở từ workflow, không tạo session/engine và không tự commit. Đổi
proposal sang `AWAITING_SIGNATURE`, tạo attempt, claim send lock, tạo approval và
ghi audit cùng nằm trong một transaction; lỗi ở bất kỳ bước nào sẽ rollback toàn bộ.

Reconciliation claim lease trước khi gọi RPC, sau đó kiểm tra lại deployment và
lease trước khi ghi chain evidence. Report đến trong lúc worker đọc RPC không bị
ghi đè bằng hash cũ. Các điều kiện version, lease timeout, batch size và status
transitions giữ nguyên.

`backend/db/rows.py` và `pagination.py` chứa row materialization/keyset pagination;
`backend/wallet_values.py` chứa ID, capability hash/token và chuyển RPC scalar.
Các import cũ qua `wallet_common`, `history_service` và `browser_wallet` tiếp tục
trỏ đến cùng helper/ContextVar.

## Wallet domain errors và HTTP adapter

`backend/wallet_errors.py` định nghĩa `WalletError`, `WalletErrorKind` và `fail()`
bằng thư viện chuẩn. Lỗi nghiệp vụ chứa kind, code và message; không chứa HTTP
status hoặc phụ thuộc FastAPI. Workflow, auth, pagination và worker dùng cùng
classification. `fail()` vẫn được re-export qua `wallet_common`; callers truyền
kind như `INVALID_INPUT` hoặc `CONFLICT` thay cho số HTTP status.

`backend/api/error_handlers.py` là nơi duy nhất map kind sang HTTP status. Phản hồi
vẫn có dạng `{"detail": {"code": "...", "message": "..."}}`, kèm cache policy và
request ID như trước. Cùng code `TX_HASH` có thể map sang 400 cho input lỗi hoặc
409 cho xung đột, dựa trên kind thay vì suy luận từ code/message.

Auth phân biệt domain rejection với RPC failure khi kiểm tra loại ví; worker log
code/message và tiếp tục lịch retry 15 giây khi gặp domain error. Các lỗi validation
request của FastAPI, lỗi storage và `TransactionError` vẫn giữ adapter hiện có.

## Agent integration và guardrail boundaries

`backend/agent/models.py` chứa `AgentResponse` và `TimelineStep`; model imports không
kéo theo legacy runtime hoặc mutable policy engine. Các import qua module/package
cũ vẫn trả về cùng model class. Legacy runtime giữ orchestration trong
`agent_service.py`, dùng các helper intent, validation, reads và replies trong `legacy/`.

`ReadAgentRuntime` điều phối retrieval, session lock, context, agent loop và response:

| Module | Trách nhiệm |
|---|---|
| `read_tools.py` | Backend READ adapters và registry riêng, chỉ thêm proposal tools khi được cấu hình |
| `query_rules.py` | Chuẩn hóa query retrieval và yêu cầu làm rõ amount mơ hồ |
| `retrieval_context.py` | Tạo RAG context theo token budget của conversation |
| `prompts.py` | System prompt cho READ hoặc proposal-only mode |
| `response_mapper.py` | Timeline, provider diagnostics, authoritative RPC balances và response; bỏ thought events |

Agent integration dùng `AgentService.get_session()`, `ConversationMemory.count_tokens()`
và public `create_llm()`; provider factory nằm trong `agent/llm/factory.py`. Private
factory alias cũ tiếp tục hỗ trợ injection hook trong test/caller hiện có. History
routes gọi `ReadAgentRuntime.clear_session()` để giải phóng memory và session lock.

`backend/guardrail/models.py` chứa config/decision/approval/audit models.
`rules.py` chứa operation sets, address/amount/simulation checks, parameter hashing
và description formatting. `PolicyEngine` tiếp tục sở hữu `RLock`, normalized
whitelist, pending approvals và audit log. Các check thuần vẫn chạy trong lock của
engine; review, expiration, tamper checks, state mutation và audit không bị tách
sang owner khác. `security/policy.py` của agent core vẫn là implementation riêng.

## RAG retrieval hiện tại

`rag/retriever.py` giữ public `RAGRetriever`, factory offline, query validation,
worker executor/semaphore, deadline, cancellation, cleanup và catalog cache theo
index fingerprint. Tìm kiếm đồng bộ được chuyển sang `rag/retrieval/` với dependency
provider/store/scope/options được truyền trực tiếp:

| Module | Trách nhiệm |
|---|---|
| `contracts.py` | Immutable `SourceScope`, `RetrievalOptions` và ba loại lỗi retrieval |
| `signatures.py` | Canonical ABI type signatures, overloads và tuple/array parsing |
| `metadata.py` | Khôi phục provenance, kiểm scalar filters và stored signatures |
| `candidates.py` | Đọc candidate vectors, tính cosine thực và kiểm provenance |
| `search.py` | Scope/interface filtering, ANN, ranking, parent context và token budget |

Import các contracts/parser qua `rag.retriever` vẫn trả cùng object canonical.
Module contracts có thể được import mà không tải retriever, index hoặc model.
Timeout/cancel tiếp tục giữ slot cho đến khi native worker kết thúc; catalog chỉ
được dùng lại khi index fingerprint khớp. Query không mở rộng scope hoặc tăng giả score.

`eval/rag_eval_lock.json` khóa cả các module vừa tách và ghi `structure_revision`.
Bản khóa cũ nằm ở `eval/locks/rag_eval_pre_structure_refactor.json`; các báo cáo
dev/holdout P7 cũ tiếp tục nhận diện bằng khóa này. `eval/rag_structure_equivalence.json`
ghi kết quả đối chiếu đầy đủ 20 query dev trước/sau bằng model local đã pin; đây là
kiểm tra tương đương của refactor, không phải phép đo holdout mới.

## E2E evaluation hiện tại

`scripts/evaluate_e2e.py` giữ entry point và CLI; `eval/e2e/` chứa immutable
options/validation, protocol freeze/holdout, measured provider, case execution,
JSON/CSV reporting và runner. `eval/e2e_runtime.py` tiếp tục sở hữu Hardhat fixture,
read-only benchmark RPC, RAG view và API lifecycle; request ledger và metrics vẫn
ở các module hiện có. Regression smoke dùng các module này trực tiếp thay vì
import logic từ CLI; các helper imports cũ vẫn được re-export.

Runner giữ checkpoint sau từng case, quota stop, NOT RUN trong mẫu số, báo cáo khi
lỗi hạ tầng và cleanup runtime. Provider tiếp tục reserve request trước khi gọi
LLM, không reset ledger. Protocol hash bao gồm các module mới; khóa lịch sử vẫn
không hợp lệ cho runtime đã thay đổi. Xem `eval/E2E_README.md` để chạy và diễn giải
bằng chứng FakeLLM/latency so với phép đo model thật.

## Agent core và tool interfaces

`AgentService` trong `agent/service.py` quản lý session và gọi `AgentLoop`.
Loop dựng messages/tool schemas, gọi provider, validate Pydantic arguments, chạy
registry tool và ghép tool results vào conversation. Provider trả text, tool calls
hoặc error theo interface chung; ứng dụng quyết định cách trình bày events.

`tools/base.py` cung cấp `BaseTool`, `ToolContext`, `ToolResult` và `RiskLevel`.
Core registry dùng decorator cùng `config/tools.yaml`; backend integration dùng
registry snapshot riêng. Cache context đi qua `cache_get()`/`cache_set()`.
Tool READ gọi service interface; tool WRITE core có policy/dry-run riêng. Browser
proposal tools tiếp tục dùng backend preparation/approval workflow, không sử dụng
core WRITE registry để ký hoặc gửi.

Hai blockchain interfaces phục vụ hai boundary khác nhau:

| Interface | Consumer và kết quả |
|---|---|
| `services/blockchain.py` | Protocol async, Web3 implementation và deterministic mock cho core tools |
| `backend/services/blockchain_service.py` | Facade sync cho API, trả exact decimal strings/raw integers và dùng adapters đã mô tả phía trên |

Retriever protocol hiện tại là `async retrieve(query: str, k: int = 5) -> list[Chunk]`.
`services/retriever.py` có `NullRetriever` để core chạy khi không inject RAG;
LLM backend dùng `rag/retriever.py` với scope/index/model đã kiểm tra. Retriever
không xác nhận state on-chain hoặc cấp quyền thực thi transaction.

`ConversationMemory` giữ system prompt, budget và cặp tool-call/result hợp lệ;
`count_tokens()` dùng counter của conversation. Default settings dành buffer 20%
trên context budget 8.000 tokens; runtime có thể inject settings/counter khác.
Backend tính thêm header/citation khi ghép context và giữ các giá trị RPC chính xác.

## Cấu hình và cài đặt

| Nguồn | Nội dung |
|---|---|
| Root `.env` | Provider keys/model, RPC, profile flags và database/origin; biến process ưu tiên |
| `config/settings.py` | Settings của agent core; không dùng để tự cấp quyền browser/backend execution |
| `config/tools.yaml`, `config/policy.yaml` | Registry và policy cho core tools |
| `config/rag.json`, `knowledge/manifest.json` | Pinned model/index, retrieval options và approved corpus |
| `backend/wallet_settings.py`, runtime configuration | History, browser writes, sessions và network profiles |

Ứng dụng đầy đủ chạy từ source checkout, có editable package mapping và canonical
root requirements. Xem `docs/PACKAGING.md`; code wheel không thay thế frontend,
knowledge và runtime assets của checkout. Ma trận hợp lệ và contract tests nằm
trong `docs/RUNTIME_PROFILES.md`.

## Kiểm chứng hiện tại

Runner `scripts.run_phase3 --suite unit` chạy core và backend unit tests với
FakeLLM/isolated configuration. `--suite rag` chạy RAG/Chroma/CLI/lock tests riêng;
root pytest mặc định không tự bao gồm backend tests. `scripts.check_packaging`
build offline và kiểm archive/editable imports ngoài cwd.

Local-EVM integration kiểm API, exact transaction units, approval/idempotency,
browser authorization và RAG lifecycle. Playwright dùng provider mô phỏng, node,
API và database riêng; vẫn cần thử popup MetaMask thật. Không gọi Gemini hoặc gửi
Sepolia để chứng minh refactor. Kết quả từng bước nằm trong `docs/REFACTOR_PLAN.md`;
coverage/performance không được suy ra từ số test và chưa có phép đo coverage mới.
