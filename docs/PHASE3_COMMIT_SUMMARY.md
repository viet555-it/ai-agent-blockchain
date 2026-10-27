# Tổng hợp thay đổi chuẩn bị commit

Nhánh: `feature/e2e-testing`. HEAD hiện tại:
`24d5a3bb25905171befbfa44fabb02b34c706d23` (develop sau tích hợp Agent).
Phạm vi dưới đây tổng hợp toàn bộ thay đổi đang có so với HEAD, gồm code mới
chưa được Git theo dõi. Chưa stage, commit, push hoặc tạo PR trong bước tổng hợp.

## 1. Hợp nhất cấu hình và môi trường

- Thêm `config/environment.py`: xác định root cố định, đọc duy nhất `.env` gốc;
  biến môi trường tiến trình được ưu tiên, kể cả giá trị rỗng dùng cô lập test.
- Cập nhật `config/settings.py`, `rag/settings.py`, `contracts/hardhat.config.js`
  và `scripts/demo_cli.py` dùng cấu hình root; RAG chỉ dùng path overrides cần thiết.
- Mẫu cấu hình duy nhất `.env.example`: provider/model, local profile, RPC,
  WRITE flag, RAG/cache và các biến Sepolia tùy chọn. Xóa `contracts/.env.example`
  và `rag/.env.example`; file `.env` thật không thuộc commit.
- Thêm dependency `filelock`, bộ `requirements-phase3.in`, constraints và lock
  để tái lập môi trường tích hợp. `.gitignore` loại env thật, venv, cache và
  `.phase3/` chứa dữ liệu runtime.

## 2. Tích hợp API, AgentService và RAG

- `backend/api/server.py`: chuyển sang `create_app(...)` với lifespan; import
  module không kết nối RPC. Cho inject dependency trong test, phục vụ frontend,
  chat async và chọn mode `legacy`/`llm` tường minh.
- Thêm `backend/runtime_profiles.py`: tách `unit`, `local_evm`, `sepolia_read`,
  `sepolia_write`; kiểm chain/loopback và ngăn quyền local WRITE lan sang Sepolia.
- Thêm `backend/agent/read_runtime.py`: nối Agent tools tới BlockchainService
  qua thread offload, dùng RAG thật theo SourceScope/DeploymentScope, giới hạn
  context, giữ citation/provenance/cosine score thật và tách session.
- Không fallback giả khi RAG lỗi; phân biệt no-match/timeout/unavailable và
  kiểm scope. Chuẩn hóa từ faucet khi truy xuất, giữ nguyên câu hỏi ban đầu.
- Cập nhật `backend/rag/rag_adapter.py` để nhận similarity thực, kể cả giá trị âm.
- `agent/service.py`, `agent/core.py`, `tools/base.py`: truyền system prompt,
  retrieval context và request context từ lớp tích hợp.

## 3. Sửa Gemini, lịch sử tool và độ chính xác câu trả lời

- `agent/llm/gemini.py`: system instruction native, schema Gemini tương thích,
  bảo toàn native function ID/thought signature trong memory; không đưa thought
  vào câu trả lời hoặc timeline.
- Kiểm history thiếu/sai function call/result trước SDK; gộp response song song;
  giới hạn request/output, timeout và retry. Diagnostic HTTP/reason được lọc,
  không ghi nguyên lỗi có thể chứa URL/key; nhận diện empty/MAX_TOKENS.
- `agent/llm/base.py`, `agent/memory.py`: giữ provider metadata, tính token của
  arguments, cắt trọn turn thay vì bỏ function call còn giữ result. Turn quá lớn
  bị chặn trước lượt gọi tiếp theo bằng `ContextBudgetExceededError`.
- `backend/agent/read_runtime.py`: transaction detail không đưa bytecode input/
  chữ ký quá dài vào model; số dư ETH/AGNT được render từ giá trị RPC chính xác,
  giữ cả hai tài sản khi hỏi chung. Balance đọc phụ trợ không xóa câu hỏi làm rõ.
- Hỏi lại khi yêu cầu chuyển còn phân vân giữa hai số lượng, hỗ trợ Việt/Anh;
  không tự chọn amount. Guard có phạm vi hẹp, prompt xử lý các dạng thiếu trường
  khác; không coi đây là bộ nhận diện mọi yêu cầu mơ hồ.

## 4. Proposal, policy và thực thi local sau approval

- Thêm `backend/agent/proposal_tools.py` cho đúng ba thao tác: chuyển ETH,
  chuyển AGNT và faucet. Tool chỉ đề xuất, không tự ký/gửi hoặc cấp approval.
- Thêm `backend/services/transaction_coordinator.py`: kiểm chain, contract/ABI/
  runtime hash, signer, policy, simulation và gas; bind payload với approval và
  session; kiểm lại trước broadcast.
- Xử lý reject/expired/tamper/replay/double-click/concurrency, nonce thay đổi,
  receipt revert/pending/unknown; đối soát hash thay vì gửi lại mù.
- Cập nhật `backend/guardrail/policy_engine.py` và API proposal/approval/status.
  Dùng amount dạng chuỗi chính xác để tránh mất đơn vị nhỏ khi đi qua JSON/JS.
- Kết thúc Agent sau quyết định proposal và render từ backend; bỏ lượt LLM dư
  sau policy/simulation. Không thay màn hình duyệt hoặc quyền thực thi của user.
- `backend/network/config.py`, `scripts/setup_local_demo.py`: cấu hình Hardhat
  loopback, setup/export deployment local riêng theo chain, giữ artifact Sepolia.

## 5. Sepolia preflight và grant giới hạn

- `scripts/preflight_sepolia.py`: kiểm chain/deployment/code hash/ABI/balances/
  RAG, RPC provider chỉ đọc, kiểm cả đường gọi sau Web3 middleware.
- `backend/services/sepolia_execution.py`: execution grant tường minh cho đúng
  hai fixture đã duyệt; ledger khóa file, reserve fee/hash trước broadcast,
  giữ cap qua restart/unknown và không gửi lại giao dịch đã reserve.
- `scripts/smoke_sepolia_write.py`: mặc định preview, tách thực thi và resume/
  reconcile. Điều chỉnh estimate gas và script FakeLLM cho proposal một lượt.
- Hai fixture faucet 10 AGNT/chuyển 1 AGNT đã có receipt thành công. Grant đã
  dùng hết; commit code không cấp quyền gửi thêm hoặc tự mở Sepolia WRITE.

## 6. Giao diện

- `frontend/app.js`: session theo tab, gắn session khi duyệt/poll; hiển thị citation
  và similarity thật, dữ liệu chain/explorer theo network, amount giữ độ chính xác.
- Hiển thị approval và CONFIRMED/REVERTED/PENDING/UNKNOWN; polling không gửi lại.
- `frontend/index.html`: bỏ thông tin chain cố định không phù hợp local.

## 7. Bộ test và đánh giá E2E

- `scripts/run_phase3.py`, `backend/run_integration_tests.py`: runner unit/RAG/
  contracts/API–EVM, FakeLLM và credentials rỗng; chỉ quản lý node do runner tạo.
- Thêm test môi trường, Gemini/memory protocol, runtime profiles, READ/RAG,
  coordinator/approval và Sepolia grant; sửa API tests để dùng factory/lifespan.
- `eval/e2e_dataset.jsonl`: 60 case mới, chia 30 dev/30 holdout theo nhóm;
  `eval/e2e_safety.jsonl`: 20 ca độc lập. `eval/e2e_metrics.py` chấm tool/params/
  action/source, giữ lỗi trong mẫu số và tách latency model/hạ tầng.
- `eval/e2e_runtime.py`: Hardhat/RAG/RPC thật, fixture tạm, transport chặn mutation
  sau setup; benchmark chỉ READ/prepare, không gọi APPROVE.
- `eval/e2e_budget.py`: sổ request bền vững dev/safety/holdout; các lần chạy lại
  dùng chung cap, không reset khi lỗi/restart.
- `scripts/prepare_e2e_eval.py`, `scripts/evaluate_e2e.py`: tạo gold, dev/freeze/
  holdout/safety, lưu protocol/hash/JSON/CSV. `scripts/smoke_e2e_regressions.py`
  kiểm ca đã quan sát sau sửa, lưu riêng, không nhận là holdout mới.
- `scripts/smoke_live_agent.py`: kiểm tích hợp provider thật với cap request.

## 8. Tài liệu

README/hướng dẫn cấu hình cũ được cập nhật theo root env. Các tài liệu mới gồm
kế hoạch giai đoạn 3, mapping tích hợp, runbook, Sepolia preflight, kết quả baseline
G3.5 và kết quả sửa sau baseline. `eval/E2E_README.md` giải thích dataset/scoring/
budget/freeze và giới hạn diễn giải kết quả.

## Kết quả dùng trong mô tả commit

| Kiểm tra | Kết quả / phạm vi |
|---|---|
| Unit hiện hành | 273 passed, 1 deselected; 68 subtest passed |
| API/EVM hiện hành | 135 tests passed |
| Ruff các file của đợt sửa gần nhất | Passed |
| Diff whitespace và secret audit | Passed; audit cả JSON/JSONL/CSV mới |
| RAG / contract độc lập | Lượt trước: 54 / 34 passed; không chạy lại trong đợt sửa cuối |
| Gemini baseline | Dev 29/30, holdout 28/30; safety 20/20 |
| Gemini hồi quy sau sửa | Lượt trọng điểm 9/10 (một HTTP 504), transaction riêng 2/2 |
| Request lũy kế | 151/200; dev 61/75, safety 42/50, holdout 48/75 |

Không cộng số test trùng giữa runner. Điểm baseline thuộc code trước sửa; lock
được giữ làm bằng chứng lịch sử. Chưa có holdout mới cho code hiện tại hoặc
nghiệm thu lại p95 ≤10 s; baseline READ/prepare holdout p95 là 23,21 s.
Approval/session của demo vẫn lưu RAM, chưa phải hệ thống nhiều người dùng.

## Chọn file trước khi stage

Đưa code, tests, requirements, `.env.example`, thay đổi `.gitignore`, tài liệu,
dataset/safety và lock lịch sử vào tập review. `git diff --stat` thông thường
không hiển thị nội dung các file mới chưa tracked; cần review cả các file đó.

Evidence hoàn chỉnh đang được báo cáo tham chiếu; có thể đưa JSON/CSV tại các
thư mục sau vào commit nếu muốn giữ bằng chứng cùng source:

- `eval/phase3/20261027T113547Z-fake-dev/`: hạ tầng 100 mẫu.
- `eval/phase3/20261027T130553Z-gemini-dev/`: dev baseline.
- `eval/phase3/20261027T132031Z-gemini-dev/`: safety riêng, không phải dev benchmark.
- `eval/phase3/20261027T132507Z-gemini-holdout/`: holdout baseline.
- `eval/phase3/20261027T140114Z-gemini-postfix-regression/`: giữ cả HTTP 504.
- `eval/phase3/20261027T140646Z-gemini-postfix-regression/`: transaction chẩn đoán.

Không thêm toàn bộ `eval/phase3/` một cách tự động: còn fake run cũ trùng và
`20261027T114229Z-fake-dev/` là lượt INFRASTRUCTURE_FAILURE chứa payload preview.
Giữ dữ liệu đó local để chẩn đoán nếu chưa chọn đưa vào review. Không xóa lỗi
504 khỏi lượt hồi quy hoàn chỉnh nhằm cải thiện kết quả.

Không commit `.env` thật, private/API keys, venv, cache, deployment local sinh tự
động hoặc `.phase3/`. Ledger và log `.phase3/` cần được giữ nguyên tại máy.
Evidence Sepolia chi tiết hiện nằm trong `.phase3/` và sẽ không có trong checkout
khác; tài liệu công khai đã có hash/receipt/balance tóm tắt. Nếu cần bàn giao JSON
chi tiết, xuất bản đã lọc secret vào thư mục evidence riêng trước khi stage.

## Commit message đề xuất

```text
feat: integrate agent workflows and phase 3 E2E validation

- connect API lifecycle, AgentService and scoped RAG with root env configuration
- add local ETH/AGNT/faucet proposals with bound approvals and receipt handling
- preserve Gemini tool history, exact balances and clarification responses
- add restricted Sepolia execution grants and durable request/fee ledgers
- add isolated test runners, E2E datasets, protocol locks and regression reports

Validation: 273 unit tests, 68 subtests and 135 API/EVM tests passed.
Baseline holdout tool accuracy: 28/30; latency acceptance remains open.
```

Đây là một tập tích hợp lớn, code backend/Agent/UI/tests phụ thuộc nhau. Nếu tách
commit theo nhóm, cần stage từng hunk và kiểm tra mỗi điểm trung gian; bảng trên
là nhóm để review, không khẳng định mỗi nhóm tự build/test độc lập.
