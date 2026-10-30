# Kế hoạch refactor cấu trúc dự án

Ngày khảo sát: 29/10/2026. Phạm vi khảo sát ban đầu: source, imports, cấu hình và các bộ test. Tiến độ triển khai và kiểm chứng sau khảo sát được ghi ở mục 8.

## 1. Kết luận

Dự án đã có ranh giới tốt ở `tools/read`, `tools/write`, adapter LLM, network, database và các bước ingest RAG. Vấn đề tập trung ở tầng tích hợp: một số module cùng xử lý điều phối, biến đổi dữ liệu, truy cập hạ tầng và trình bày kết quả. Chỉ chia file theo số dòng sẽ không giải quyết được phụ thuộc này.

Hướng đề xuất: refactor tăng dần theo trách nhiệm, giữ public interface và hành vi hiện tại trong từng bước. Chưa cần chuyển toàn bộ repository sang `src/`, đổi framework frontend hoặc hợp nhất mọi service cùng tên.

## 2. Bằng chứng và mức ưu tiên

Số dòng bên dưới tính toàn bộ dòng vật lý, gồm comment và dòng trống, tại thời điểm khảo sát. Đây là tín hiệu để đọc code, không phải tiêu chuẩn chất lượng độc lập.

| File | Dòng | Vấn đề cụ thể | Ưu tiên |
|---|---:|---|---|
| `frontend/app.js` | 1.016 | State, DOM, theme/ngôn ngữ, HTTP, chat, timeline, approval và wallet lifecycle trong một module | P1 |
| `frontend/styles.css` | 1.318 | Styles nhiều khu vực giao diện tập trung một file | P2 |
| `backend/services/browser_wallet.py` | 886 | Deployment identity, context, proposal, authorization, SQL, submission và receipt reconciliation | P1, rủi ro cao |
| `backend/services/blockchain_service.py` | 566 | ABI, đọc RPC, xây dựng transaction, mô phỏng, ký/gửi và đợi receipt | P2 |
| `backend/agent/agent_service.py` | 531 | Models dùng chung nằm cạnh legacy agent; `process_message` dài khoảng 246 dòng | P2 |
| `backend/api/server.py` | 471 | Request schemas, validation cấu hình, dependency wiring, lifespan, worker, routes, static hosting | P1 |
| `backend/guardrail/policy_engine.py` | 470 | Models, đánh giá policy, mutable approval state, khóa và audit cùng một module | P2 |
| `rag/retriever.py` | 434 | Scope/options/errors, signature parsing, metadata phục hồi, ranking và async lifecycle | P3 |
| `backend/services/transaction_coordinator.py` | 413 | Proposal model, serialization, identity/preflight, approval và transport | P1, làm sau API |
| `backend/agent/read_runtime.py` | 371 | Tool adapter/registry, chuẩn hóa query, dựng RAG context/prompt, session lock, event-to-response | P2 |
| `scripts/evaluate_e2e.py` | 672 | CLI và logic đánh giá là ứng viên tách sau runtime | P3 |

Các điểm phụ thuộc đáng chú ý:

- `BrowserPreparer` kế thừa `TransactionCoordinator` để dùng logic chuẩn bị nhưng phải chặn `_broadcast`; `BrowserWalletService.authorize` gọi trực tiếp `_preflight`. Đây là dấu hiệu phần chuẩn bị và phần gửi cần interface riêng.
- `backend/agent/read_runtime.py` import `AgentResponse`/`TimelineStep` từ module legacy, đồng thời gọi `AgentService._get_or_create_session` và `memory._counter`. Tầng tích hợp đang phụ thuộc chi tiết nội bộ.
- `server.py` import factory private `_create_llm` và dựng nhiều tài nguyên trong closure `lifespan`; ownership/cleanup cần được giữ rõ khi tách.
- `wallet_common.fail` ném `FastAPI.HTTPException` từ service. Khi tách domain error phải giữ nguyên HTTP status và `detail={code,message}` cho client.
- `BrowserWalletService` import helper phân trang từ `history_service`; nên đưa quy tắc phân trang dùng chung về module có trách nhiệm rõ.
- `services/blockchain.py` định nghĩa protocol async, implementation và mock; `backend/services/blockchain_service.py` là concrete service sync với shape kết quả khác. Không thể hợp nhất bằng đổi import đơn thuần.
- `security/policy.py` và `backend/guardrail/policy_engine.py` thuộc hai đường thực thi khác nhau. Cần lập bảng quy tắc trước khi cân nhắc dùng chung.
- `pyproject.toml` chỉ đặt `testpaths=["tests"]`; gọi pytest mặc định không tự bao gồm `backend/tests`. Danh sách package build cũng chưa bao gồm `backend` và `rag`; cần xác định sản phẩm chạy từ source hay phân phối wheel trước khi sửa packaging.
- `docs/ARCHITECTURE.md` còn mô tả retriever null và backend của đồng đội, không phản ánh đầy đủ wallet history/LLM runtime hiện tại.

## 3. Ranh giới mục tiêu

Giữ agent core, tools, RAG và backend integration là các vùng có trách nhiệm riêng:

```text
frontend views/controllers -> API clients -> FastAPI routes
                                             |
                                     application services
                                      /              \
                            policy / models       adapters / persistence

backend agent integration -> agent core -> tool / provider interfaces
                         -> RAG interface
```

Quy tắc phụ thuộc:

1. Routes parse request, xác thực, gọi service và map response/error; không chứa SQL hay khởi tạo RPC.
2. App factory/lifespan là nơi lắp dependency và quản lý tài nguyên. Module import không kết nối RPC, mở DB hoặc khởi động worker.
3. Agent core không import `backend.api`; models dùng chung không import legacy runtime.
4. Transaction preparation không có quyền ký/gửi. Browser flow chỉ nhận unsigned transaction; transport local và Sepolia được inject riêng.
5. Repository nhận connection từ service đối với thao tác cần atomicity; không tự commit mỗi câu SQL.
6. Frontend views không gọi `fetch`; controller gọi API client và cập nhật state/view. Inject callback hoặc context nhỏ, tránh tạo module state toàn cục mới cho mọi thành phần.

Các module đích đề xuất, tạo dần khi có nhu cầu thực tế:

```text
backend/
  api/
    server.py                  # giữ create_app/run để tương thích entry point
    schemas.py
    dependencies.py
    error_handlers.py
    routes/
      system.py                # health, network, wallet info
      chat.py
      approvals.py
      wallet.py                # nhóm authenticated routes hiện có
  bootstrap/
    runtime.py                 # validation profile, dependency assembly
    lifespan.py                # startup, resource ownership, shutdown
  agent/
    models.py                  # AgentResponse, TimelineStep
    read_tools.py              # BackendReadTool + BackendReadRegistry
    retrieval_context.py
    response_mapper.py
    prompts.py
    read_runtime.py            # điều phối luồng LLM
    legacy/                    # intent, validation, reply; giữ facade cũ
  services/
    browser_wallet.py          # facade tương thích trong giai đoạn chuyển đổi
    wallet/
      deployment.py
      contexts.py
      proposals.py
      submissions.py
      reconciliation.py
    transactions/
      models.py
      serialization.py
      preparation.py
      preflight.py
      transports.py
    blockchain/
      reads.py
      transaction_builder.py
      signer.py
  db/
    repositories/
      proposals.py
      submissions.py
      deployments.py
  guardrail/
    models.py
    rules.py
    approvals.py
    policy_engine.py           # facade và ownership của lock
frontend/
  app.js                       # bootstrap, lắp controller
  api.js                       # API client hiện có, bổ sung legacy endpoints
  ui/
    theme.js
    language.js
    chat.js
    timeline.js
    approval-modal.js
    assets.js
  controllers/
    chat.js
    approvals.js
    wallet-session.js
  styles/
    tokens.css
    base.css
    layout.css
    chat.css
    wallet.css
    modal.css
```

`wallet.js`, `history.js`, `api.js`, `i18n.js` đã có trách nhiệm riêng: ưu tiên tái sử dụng, không tạo thêm implementation song song. Cây trên là thiết kế đích đề xuất, chưa phải cấu trúc đã triển khai.

## 4. Lộ trình theo PR

### PR 0 — Chốt baseline và hợp đồng hành vi

- Lập ma trận `unit/local_evm/sepolia_read/sepolia_write`, `legacy/llm`, history bật/tắt và các tổ hợp hợp lệ dựa trên validation hiện tại.
- Chạy test hiện có; ghi rõ pass/fail/skip và lỗi có từ trước. Phân biệt root pytest với backend unittest/runner.
- Chụp hợp đồng endpoint: route, HTTP method/status, request/response, error code, header/cookie; bỏ timestamp/id biến thiên khi so sánh.
- Xác định test còn thiếu cho đổi ví giữa request, approve lặp, deployment reset, nonce đổi, receipt chưa xác định và shutdown khi startup thất bại. Chỉ bổ sung test hành vi cho khoảng trống thực sự.
- Nghiệm thu: có baseline tái chạy được và các invariant ở mục 5 được gắn với test cụ thể; chưa thay logic.

### PR 1 — Tách API và composition root

- Chuyển schemas khỏi `server.py`; chuyển endpoint thành `APIRouter` theo nhóm.
- Tách validation/runtime assembly khỏi lifespan; worker reconciliation được inject service, giữ chu kỳ hiện tại.
- Giữ chữ ký `create_app`, entry point `python -m backend.api.server`, injection seams đang dùng trong test, CORS, static serving và các `app.state` cần thiết.
- Giữ re-export tạm thời cho import cũ. Không đổi schema DB hay giao thức frontend trong PR này.
- Nghiệm thu: API unit tests và runtime profile tests qua; hợp đồng endpoint không đổi; import không kết nối RPC; tài nguyên sở hữu bởi app được đóng đúng khi lỗi startup/shutdown.

### PR 2 — Tách frontend theo tính năng

- Chuyển theme/language và render chat/timeline/modal/assets sang module tương ứng.
- Chuyển HTTP rải rác trong `app.js` vào client hiện có. Tách controller chat, approval và wallet-session.
- Giữ generation check khi đổi ví, listener cleanup, session binding, polling chỉ đọc và chống double-submit.
- Tách CSS theo khu vực, giữ thứ tự cascade và đường dẫn CSS hoạt động cả khi FastAPI serve source lẫn Vite build.
- Nghiệm thu: Node tests, build và wallet E2E qua; kiểm theme EN/VI, modal, lịch sử, scroll và responsive. `app.js` chủ yếu bootstrap, mục tiêu khoảng 100–200 dòng.

### PR 3 — Tách transaction preparation khỏi transport

- Đưa `TransactionError`, `BoundProposal`, serialization/hash vào module chuyên trách; giữ canonical JSON/hash hiện tại.
- Extract chuẩn bị và preflight thành component dùng qua composition, thay dần việc browser gọi private method của coordinator.
- `TransactionCoordinator` tiếp tục giữ lock/state và local execution; Sepolia giữ grant/transport validation riêng. Browser không nhận signer/broadcaster.
- Nghiệm thu: test transaction coordinator, Sepolia execution với mock, browser-wallet và local EVM qua; kiểm không phát sinh đường gửi trực tiếp từ proposal tools/browser service.

### PR 4 — Tách durable wallet workflow và persistence

- Extract lần lượt deployment/context → proposal queries/preparation → submission authorization/report → receipt reconciliation.
- Giữ `BrowserWalletService` làm facade, inject các component. Giữ cùng instance `proposal_scope` khi đổi import.
- Chuyển SQL sang repository theo workflow; service vẫn sở hữu transaction boundary, version compare-and-swap, send lock và lease.
- Tách domain error khỏi HTTP trong bước riêng của PR hoặc PR con; API adapter map chính xác mã lỗi cũ. Không vừa đổi lỗi vừa đổi state machine.
- Nghiệm thu: không thay schema/enum/status transitions; test wallet history, concurrency/idempotency, restart/recovery và local EVM qua. Không mất audit hoặc cho phép đọc chéo ví.

### PR 5 — Làm mỏng agent integration và guardrail

- Chuyển response models ra khỏi legacy runtime; giữ re-export để callers chuyển dần.
- Tách read tools, RAG context builder, prompt và event mapper khỏi `ReadAgentRuntime`. Runtime giữ thứ tự các bước và session lock.
- Thêm public API nhỏ để lấy session/token count/provider factory, thay truy cập private đang có.
- Tách legacy intent/validation/reply nhưng giữ chế độ legacy cho tới khi có quyết định loại bỏ riêng.
- Tách guardrail models và pure rules trước; giữ approval mutation và lock ở cùng owner. Không đồng nhất hai policy engine trước khi so sánh semantic/units/defaults.
- Nghiệm thu: agent/read-runtime/policy tests qua; giữ nguyên token budget, source scope, số dư chính xác từ RPC, lọc thought events và yêu cầu UI approval.

### PR 6 — Dọn phần còn lại và tài liệu

- Tách blockchain reads/build/signing sau khi transaction interfaces ổn định; giữ facade cho callers cũ.
- Tách scope/options/errors và signature parsing khỏi `rag/retriever.py` nếu giúp các callers/test độc lập; giữ nguyên ranking, thresholds, cache, timeout và cleanup.
- Chuyển logic đánh giá có thể tái sử dụng từ `scripts/evaluate_e2e.py` vào `eval/`; script chỉ parse args và gọi runner. Giữ CLI flags và output schema.
- Cập nhật `docs/ARCHITECTURE.md`, README và hướng dẫn thêm tool. Xác định package build có cần hỗ trợ backend/RAG hay chỉ source checkout.
- Xóa shim chỉ khi tìm kiếm imports/scripts/tests không còn consumer và các bộ kiểm tra liên quan qua.
- Nghiệm thu: không có vòng import mới; docs phản ánh flow hiện tại; import/entry point và eval fixture outputs tương thích.

Thứ tự: PR 0 → PR 1 → PR 2 → PR 3 → PR 4 → PR 5 → PR 6. Có thể tách PR lớn thành nhiều PR nhỏ; mỗi PR vẫn phải chạy độc lập và có thể revert. PR 2 ít phụ thuộc PR 3–5, nhưng không cần làm song song để đạt mục tiêu.

## 5. Những hành vi bắt buộc giữ nguyên

- Browser backend không ký/gửi transaction; agent chỉ tạo proposal, không tự cấp approval.
- Proposal gắn với wallet/session/context generation/deployment/parameter hash; thay chain, account, policy hoặc payload phải được xử lý như hiện tại.
- Giữ exact integer/token units, nonce, gas, bytecode/ABI verification và thời điểm preflight.
- Approve/report/reconcile lặp không được tạo lần gửi mới; giữ `UNKNOWN`, lease và send lock trong tình huống kết quả chưa chắc chắn.
- Giữ SQL atomicity và thứ tự kiểm tra lại trước mutation; repository không chia nhỏ critical transaction thành nhiều commit.
- Dữ liệu chat/history không rò giữa ví hoặc deployment; request cũ không cập nhật giao diện sau đổi ví.
- Giữ scoped RAG, token budget, protocol tool-call/result và error mapping. Không đổi prompt/ranking để “cải thiện” trong cùng PR di chuyển code.
- Không thay contract/deployment artifacts hoặc migration history chỉ để sắp xếp lại thư mục.

## 6. Kiểm chứng khi triển khai

Các lệnh dưới đây là kế hoạch kiểm chứng, chưa được chạy trong lần khảo sát này. Chạy từ root PowerShell, dùng môi trường đã cài dependency:

```powershell
.\.venv-phase3\Scripts\python.exe -m pytest tests -q
.\.venv-phase3\Scripts\python.exe -m scripts.run_phase3 --suite unit
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
```

Khi thay đổi giao dịch/API tích hợp, bổ sung:

```powershell
.\.venv-phase3\Scripts\python.exe -m scripts.run_phase3 --suite local_evm
npm.cmd --prefix contracts test
.\.venv-phase3\Scripts\python.exe -m scripts.run_wallet_e2e
```

Root RAG tests có thể cần model/index/cache theo `docs/RAG_SETUP.md`; báo thiếu prerequisite thay vì coi skip là pass. Runner local EVM có thể dùng node cổng 8545 và tạo giao dịch test: dùng node/database test độc lập khi ghi baseline. Không cần gọi LLM thật hoặc gửi Sepolia để chứng minh refactor cấu trúc.

Khi chạm RAG/eval, chạy tests tương ứng và so sánh output trên fixture cố định; khi chạm frontend, bổ sung QA trực quan. Test popup MetaMask thực tế vẫn là bước thủ công riêng vì Playwright hiện dùng provider mô phỏng.

Tiêu chí hoàn tất toàn đợt:

- Module có một trách nhiệm có thể mô tả rõ; các facade chỉ điều phối thay vì giữ toàn bộ implementation.
- Ưu tiên function dưới khoảng 50–80 dòng, module thường dưới khoảng 300 dòng khi hợp lý; không chia cơ học state machine hay transaction atomic chỉ để đạt số dòng.
- Không có import private xuyên tầng ở các vùng vừa refactor; dependency được lắp tại boundary rõ ràng.
- Baseline không có regression mới; report nêu rõ tests đã chạy và tests thiếu môi trường.
- API/CLI/DB/frontend behavior tương thích, tài liệu và entry points được cập nhật.

## 7. Phạm vi chưa kết luận từ khảo sát

Chưa đo coverage/complexity thực chạy, hiệu năng, hoặc xác nhận toàn bộ test đang xanh. Đánh giá trên dựa vào đọc source và kiểm tra cấu hình; các điểm như hai service cùng tên là vấn đề ranh giới/khả năng đọc, không tự động là bug. Thay đổi có sẵn ở `docs/PHASE3_DEMO.md` được giữ nguyên.

## 8. Tiến độ triển khai — 29/10/2026

Branch: `refactor-project-structure`.

Đã hoàn thành phần đầu của PR 1:

- Tách request schemas sang `backend/api/schemas.py`, giữ re-export từ `server.py` cho import cũ.
- Tách routes thành `routes/system.py`, `routes/chat.py`, `routes/approvals.py`; dependency lấy từ state của từng app qua `Request`, không giữ singleton service trong router.
- Tách kiểm tra legacy access sang `dependencies.py` và wallet error/cache handlers sang `error_handlers.py`.
- Giữ factory, lifespan, dependency injection, authenticated wallet routes và static mount; `server.py` giảm từ 471 còn 253 dòng.

Kiểm chứng:

- Baseline với `server.py` gốc từ Git HEAD nạp trong bộ nhớ: 296 passed, 3 skipped, 1 deselected, 75 subtests passed. Không ghi đè source để chạy baseline.
- Sau refactor: cùng bộ unit suite đạt 296 passed, 3 skipped, 1 deselected, 75 subtests passed.
- OpenAPI của unit profile trước/sau bằng nhau; kiểm tra toàn bộ schema, paths và operation IDs.
- Ruff cho các module mới đạt; `git diff --check` không có lỗi whitespace.
- Test chạy qua cấu hình cô lập FakeLLM của dự án ngoài sandbox. Các lượt trong sandbox bị treo hoặc lỗi quyền thư mục tạm; lượt pytest trực tiếp còn bị cấu hình `.env` ảnh hưởng, nên không dùng làm baseline.

Phần còn lại sau commit đầu: tách runtime assembly/lifespan, bổ sung ma trận/hợp đồng đầy đủ cho các profile ở PR 0, rồi tiếp tục các PR sau. Chưa chạy local-EVM, RAG, frontend E2E hoặc đo coverage trong commit đầu; chưa thay đổi transaction logic hoặc database schema.

### Tiếp theo — tách runtime và lifespan

- Commit đầu: `b597fb5` (`refactor(api): extract request schemas and route groups`).
- Tách `ApplicationRuntime`/validation sang `backend/bootstrap/runtime.py`; factory không mở tài nguyên.
- Tách startup/shutdown và wallet receipt worker sang `backend/bootstrap/lifespan.py`; scope retrieval được chọn và kiểm tra trong `backend/bootstrap/retrieval.py`.
- `server.py` còn 120 dòng, giữ public factory, injection parameters, `app.state`, static hosting và entry point hiện có.
- Dùng `AsyncExitStack` để đóng tài nguyên theo ownership. Lỗi cleanup của retriever không còn ngăn LLM được đóng; caller vẫn quản lý các dependency inject vào.
- Thêm 7 test lifecycle: shutdown thường, scope sai, retriever tạo lỗi, cleanup lỗi, DB schema lỗi, dependency inject và worker dừng trước khi DB đóng.
- Unit suite: 303 passed, 3 skipped, 1 deselected, 75 subtests passed. OpenAPI unit profile bằng bản trước refactor; Ruff cho source/test thay đổi đạt.
- Wallet Playwright E2E: 9 passed, không skip/flaky; runner tạo Hardhat, API và database riêng và thoát với mã 0.
- Cập nhật `docs/ARCHITECTURE.md` về API composition và thứ tự giải phóng tài nguyên.

### PR 2 — tách frontend theo tính năng

- `app.js` giảm từ 1.016 xuống 91 dòng, tập trung lắp view/controller và bootstrap.
- `controllers/` chia theo assets, chat, approval và wallet session. `ui/` chứa render chat/RAG citation, timeline, modal, wallet gate, theme/ngôn ngữ, DOM bindings và layout observers.
- `state.js` tạo state theo dashboard; mỗi factory nhận state/dependency trực tiếp. Giữ các module `WalletController`, `HistoryView` và i18n hiện có.
- Dashboard HTTP dùng client trong `api.js`, có custom header để giữ session binding của approval polling.
- `styles.css` chỉ import các stylesheet theo khu vực. Ghép các phần lại khớp nguyên nội dung/thứ tự CSS ban đầu; Vite build cho cùng CSS asset `index-2KmgZ_kE.css` trước/sau refactor.
- Thêm 4 test Node cho phản hồi số dư sau đổi ví, chat trả muộn từ hội thoại cũ, receipt polling không submit lại và session header của status request.
- Thêm Playwright test cho legacy chat/timeline/approval và theme; mở rộng backend test kiểm tra serving/cache của `/ui/chat.js` và `/styles/chat.css`.
- Kiểm chứng: 11/11 Node tests, Vite build, 10/10 Playwright E2E, 21/21 backend wallet/history tests. Kiểm tra ảnh mobile tiếng Việt và các viewport trong E2E đạt. Playwright dùng provider mô phỏng trên Hardhat/API/database riêng.

### PR 3 — tách transaction preparation khỏi transport

- Thêm `backend/services/transactions/`: models, canonical serialization, identity/preflight, unsigned preparation và execution transports.
- `TransactionCoordinator` giảm từ 413 còn 305 dòng; giữ lock, approval records, nonce fence, review, trạng thái `UNKNOWN` và receipt reconciliation. Các identity attributes và import helper cũ vẫn được giữ cho callers.
- Browser dùng `BrowserPreparer` theo composition, không kế thừa coordinator thực thi. `BrowserWalletService` gọi public `preflight()` thay cho `_preflight()` của coordinator.
- Local transport giữ `send_transaction`; Sepolia transport giữ ký, reservation, expected hash và `send_raw_transaction`. Sepolia fixture gates, ledger và fee limit không đổi.
- Đối chiếu AST xác nhận `_bound`, `review`, `_reconcile`, `get` của coordinator không đổi; `ExecutionLedger` và các method kiểm fixture/preflight/proposal/reconcile Sepolia không đổi.
- Thêm 3 test: browser preparation với tài khoản không mở khóa tại backend, kiểm tra lại nonce qua public preflight và execution transport chỉ chạy một lần sau approval.
- Kiểm chứng: 306 unit tests passed, 3 skipped, 1 deselected, 75 subtests passed; 13 local-EVM integration tests passed trên Hardhat cổng riêng/deployment tạm; 10/10 wallet Playwright E2E passed. Ruff và kiểm tra format đạt. Các test Sepolia dùng signer fixture và RPC giả; không gửi testnet.

### PR 4a — tách durable wallet workflow và persistence

- `BrowserWalletService` giảm từ 862 còn 95 dòng và giữ public facade cho routes, tools và scripts.
- Tách workflow deployment, context, proposal, submission và reconciliation vào `backend/services/wallet/`. Các dependency được truyền rõ trong constructor, không có workflow tham chiếu ngược về facade.
- Tách SQL sang `backend/db/repositories/` theo workflow. Workflow giữ quyền sở hữu connection/transaction; repository không tự mở/commit transaction.
- Giữ cùng `proposal_scope` ContextVar qua re-export, cùng generation/context/deployment binding, CAS/version predicates, send locks, leases, batch size và status transitions.
- Tách shared scalar/capability helpers, row materialization và pagination; giữ import cũ tương thích. HTTP error mapping và schema/migration giữ nguyên.
- Đối chiếu AST sau khi inline repository calls: 16 method nghiệp vụ khớp bản cũ, bao gồm SQL và các khối transaction.
- Thêm 3 test failure/concurrency: lỗi ghi approval rollback proposal/attempt/lock; lỗi release lock khi từ chối chữ ký rollback state; worker mất lease trong RPC không được ghi receipt hoặc giải phóng send lock.
- Unit suite: 309 passed, 3 skipped, 1 deselected, 75 subtests passed. Ruff và kiểm tra format các module mới đạt.
- Integration: 13/13 local-EVM/API tests passed, gồm RAG thật từ index/cache local; 10/10 Playwright wallet E2E passed. Mỗi runner dùng Hardhat cổng riêng và dữ liệu test tạm, không dùng node demo.

### PR 4b — tách wallet domain error khỏi HTTP

- Thêm `backend/wallet_errors.py`: `WalletError`, semantic `WalletErrorKind` và `fail()`, không phụ thuộc framework và không mang HTTP status.
- Chuyển 51 failure declarations sang semantic kind. `wallet_common.fail` giữ re-export; pagination import lỗi trực tiếp từ domain module, không còn phụ thuộc wallet service helpers.
- HTTP status chỉ được chọn tại API error handler. Giữ nguyên code/message/response shape, cache headers và request ID, kể cả hai nhóm lỗi `TX_HASH` trước đây trả 400/409 khác nhau.
- Wallet auth và receipt worker bắt domain error thay `HTTPException`; lỗi contract wallet không bị biến thành lỗi RPC, còn lỗi RPC không làm challenge bị consumed.
- Đối chiếu 51 declarations sau mapping và OpenAPI wallet trước/sau khớp nhau. Chuẩn hóa AST theo error kind cho thấy logic auth, history, pagination và wallet workflows không đổi ngoài classification.
- Thêm 5 test cho rate limiter ngoài HTTP, mapping đủ 7 nhóm lỗi qua HTTP, worker log/retry và hai nhánh lỗi xác minh loại ví.
- Kiểm chứng: 314 unit tests passed, 3 skipped, 1 deselected, 82 subtests passed; 10/10 wallet Playwright E2E passed. Ruff đạt. Không có import FastAPI/Starlette trong `backend/services/` hoặc `backend/db/`.

### PR 5 — làm mỏng agent integration và guardrail

- Tách `AgentResponse`/`TimelineStep` sang models trung lập; import qua legacy module/package vẫn tương thích. Package exports tải runtime/engine khi cần, nên import models không kéo theo mutable runtime.
- Tách READ adapters/registry, query guards, RAG context builder, system prompt và response mapper. `ReadAgentRuntime` giảm từ 371 xuống 149 dòng, giữ session lock và thứ tự thực thi.
- Bổ sung public `AgentService.get_session()`, `ConversationMemory.count_tokens()` và `create_llm()`; provider factory ở `agent/llm/factory.py`. Giữ private factory hook cũ cho compatibility/injection, không còn import private factory từ bootstrap.
- History routes dùng `ReadAgentRuntime.clear_session()` thay truy cập `_locks` trực tiếp.
- Tách legacy intent/validation/reads/replies; `agent_service.py` giảm từ 531 xuống 338 dòng và giữ nguyên orchestration, facade methods và legacy mode.
- Tách guardrail models và rules thuần. `policy_engine.py` giảm từ 470 xuống 336 dòng; cùng engine tiếp tục giữ lock, whitelist, approvals và audit. Không hợp nhất với `security/policy.py`.
- Kiểm tra hai OpenAPI schemas (unit và wallet) không đổi; model aliases cùng object. Hai system prompts và AST response mapping khớp baseline; 24 policy decision cases khớp baseline.
- Thêm 5 test cho tokenizer riêng của conversation, context không chứa được tài liệu, policy input/config isolation, cleanup 101 session và review approval đồng thời chỉ thành công một lần.
- Kiểm chứng: 319 unit tests passed, 3 skipped, 1 deselected, 82 subtests passed; 13/13 local-EVM integration passed; 10/10 Playwright wallet E2E passed. Các runner dùng FakeLLM và Hardhat/data tạm, RAG integration dùng index/cache local.

### PR 6a — tách synchronous blockchain adapters — 30/10/2026

- `blockchain_service.py` giảm từ 566 xuống 196 dòng; giữ constructor, provider state, public parameters/defaults, method overrides và các helper `execute_*` hiện có.
- Tách `backend/services/blockchain/` thành ABI, capability protocols, RPC reads, simulation, unsigned transaction builder và signer/receipt adapter. Functions dùng public `w3`, không phụ thuộc ngược vào facade.
- Standard ERC-20 ABI được re-export cùng object qua import cũ. Không thay exact token units, metadata fallbacks, nonce, fee modes, bytecode verification, signing payload hoặc dữ liệu receipt.
- Đối chiếu AST xác nhận 17 method được di chuyển giữ nguyên body sau chuẩn hóa dependency access/type annotations; constructor và orchestration còn lại cũng khớp baseline. Toàn bộ public parameters/defaults và ABI khớp baseline.
- Thêm 5 test hành vi cho phí legacy/EIP-1559 và 1 wei, nonce/chain có sẵn khi ký, không retry broadcast chưa rõ kết quả, metadata/pending receipt và simulation với manifest/spender. Cả 5 test cũng chạy đạt với service baseline trước khi tách.
- Kiểm chứng: 324 unit tests passed, 3 skipped, 1 deselected, 87 subtests passed; 20/20 local-EVM integration passed (bổ sung cả bộ blockchain integration hiện có); 10/10 Playwright wallet E2E passed, không skip/flaky. Ruff/format đạt. Hardhat dùng cổng riêng và deployment/database tạm; không gửi transaction lên mạng thật.

### PR 6b — tách RAG contracts và synchronous search — 30/10/2026

- `rag/retriever.py` giảm từ 434 xuống 196 dòng. Runtime giữ factory, worker/semaphore, query validation, deadline, cancellation, cleanup và catalog cache theo fingerprint.
- Tách `rag/retrieval/`: immutable contracts/errors/options, ABI signature parser, metadata/provenance, cosine candidate lookup và scoped search/ranking/context selection. Ba đoạn lookup/cosine giống nhau dùng chung một function; không thay công thức hay ngưỡng.
- Giữ import/re-export cũ cùng object canonical. Module contracts không tải runtime/index/model; async methods và cache logic giữ nguyên AST.
- Đối chiếu AST của contracts, parser, metadata, cosine và toàn bộ search sau khi inline candidate helper khớp baseline. Model local đã pin trả toàn bộ content/metadata/order/scores giống nhau cho 20/20 query dev; báo cáo ở `eval/rag_structure_equivalence.json`.
- Lưu nguyên benchmark lock cũ trong `eval/locks/`, thêm structural development revision và hash cho toàn bộ module mới vào lock hiện tại. Dataset/gold/config/model/corpus và các báo cáo dev/holdout cũ không thay đổi; không chạy lại hoặc tune holdout. Công cụ tạo benchmark mới cũng khóa các module đã tách.
- Thêm 6 test về import độc lập, object aliases, provenance/type spoofing, options input isolation, hash của các runtime dependency và khả năng nhận diện khóa/báo cáo cũ.
- Kiểm chứng: baseline RAG 54/54 passed; sau refactor RAG 60/60 passed. Unit suite 324 passed, 3 skipped, 1 deselected, 87 subtests passed; 20/20 local-EVM integration passed, gồm các flow API dùng RAG thật. Ruff đạt; 8 file runtime/test mới hoặc refactor đạt kiểm tra format. Các test dùng model cache local, FakeLLM và Hardhat/deployment/database tạm.

Tiếp theo: PR 6c — tách E2E eval runner khỏi CLI và hoàn thiện tài liệu/packaging. Ma trận/hợp đồng đầy đủ của các profile ở PR 0 vẫn cần bổ sung; chưa đo coverage mới.

