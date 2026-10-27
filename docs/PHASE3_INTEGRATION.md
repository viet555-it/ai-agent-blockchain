# G3.0 — Môi trường và bản tích hợp

Tài liệu này giữ nhật ký từ G3.0 qua các bước tích hợp; các đoạn nói về giới hạn
ở G3.0/G3.1 là trạng thái lịch sử. Trạng thái hiện tại, cách chạy và phần còn
thiếu nằm tại [bàn giao G3.6](PHASE3_HANDOFF.md). Local WRITE đã có approval;
Sepolia WRITE chỉ mở bằng execution grant tường minh.

Ngày: 26/10/2026 (Asia/Saigon). Nhánh làm việc: `feature/e2e-testing`.
Nền source: `develop@24d5a3b` sau PR #9 đưa `ai-agent` vào develop.

## Trạng thái

Đã có source của các thành viên trong cùng nhánh. G3.0 chuẩn hóa môi trường, API lifecycle và test baseline. G3.1 đã bổ sung
chế độ READ tích hợp AgentService/RAG thật vào cùng endpoint chat.
Không cần merge lại nhánh Agent hoặc mang commit revert từ main.

API dùng factory `create_app(...)`. Import `backend.api.server` không kết nối RPC;
BlockchainService chỉ được tạo khi ứng dụng khởi động. Unit tests inject service
và policy riêng, dùng TestClient trong lifespan context, không dùng RPC Sepolia.
Server CLI chỉ bind `127.0.0.1`; frontend vẫn được phục vụ cùng API.

## Môi trường Python

- Python đã kiểm tra trên máy: 3.12.10, Windows x64; Node 22.20.0.
- `.venv-phase3/`: môi trường tích hợp riêng, không sửa hai môi trường cũ.
- `requirements-phase3.in`: đầu vào dependency.
- `requirements-phase3-constraints.txt`: giữ pins RAG, điều chỉnh `websockets`
  sang 15.0.1 cho Web3 7 và `tenacity <9.2` cho Google GenAI SDK.
- `requirements-rag.lock.txt`, corpus, model revision và evaluator lock không đổi.
- `requirements-phase3.lock.txt`: phiên bản thực cài, xuất sau khi pip check/test đạt.

Lần cài đầu:

```powershell
# Tại repo root, dùng Python 3.12
python -m venv .venv-phase3
.venv-phase3/Scripts/python.exe -m pip install -r requirements-phase3.in
.venv-phase3/Scripts/python.exe -m pip check
```

Sau khi có lock, dùng `pip install -r requirements-phase3.lock.txt` để tái lập
phiên bản của lần kiểm thử này. Cài dependency có thể cần mạng. Cache embedding
model dùng lại `.cache/rag/huggingface`; query không tự tải model khác revision.

## Profile và ranh giới thực thi

| Profile | Chain | Khởi động / thực thi |
|---|---:|---|
| `unit` | 31337 | Bắt buộc inject BlockchainService; không tự kết nối node |
| `local_evm` (mặc định) | 31337 | Chỉ HTTP loopback RPC; không fallback sang mạng khác |
| `sepolia_read` | 11155111 | Chọn tường minh khi có quyền dùng RPC; đọc và chuẩn bị proposal |
| `sepolia_write` | — | Chưa mở; phải hoàn thành G3.2 và chốt ngân sách/credentials |

API hiện cho tạo pending proposal và reject. APPROVE trả HTTP 403, không tạo hash
giả, không gọi signer, không đổi proposal thành EXECUTED. Đây là giới hạn của
bản chuẩn bị tích hợp; giao dịch local ở bộ Blockchain Service tests vẫn được
thực hiện trên EVM 31337 bằng tài khoản local. Không dùng API G3.0 làm demo
giao dịch Sepolia thành công.

Network switch qua API chỉ chấp nhận chain của profile đã khởi động. Muốn đổi
local/Sepolia phải khởi động lại bằng profile phù hợp, tránh đổi network khi còn
approval dùng policy cũ. Unit/local runner ghi đè credential thành rỗng, chọn
FakeLLM và DRY_RUN=true trước khi import app hoặc gọi subprocess/Hardhat dotenv.

## Model dự án đang chọn

Nguồn xác định:

| Nguồn | Cấu hình |
|---|---|
| `.env.example`, `config/settings.py` | Provider mặc định `gemini` |
| `agent/llm/gemini.py` | Đã cập nhật mặc định `gemini-3.5-flash-lite` |
| `agent/llm/anthropic.py`, `openai_adapter.py` | Provider thay thế, chưa phải lựa chọn mặc định |
| `config/rag.json` | Embedding local `paraphrase-multilingual-MiniLM-L12-v2`, không phải LLM Agent |

Model mặc định cũ `gemini-2.0-flash` đã shutdown ngày 01/06/2026:
[lịch deprecation chính thức](https://ai.google.dev/gemini-api/docs/deprecations).
Vì vậy không xem cấu hình mặc định lịch sử là model có thể chạy benchmark thật.
Người dùng đã chọn Gemini 3.5 Flash-Lite, lưu key tại .env và cho chạy smoke
2 request thành công. Bộ baseline dùng FakeLLM. Live evaluation có context
project cần duyệt phạm vi dữ liệu riêng trước khi chạy.

Không in Settings hoặc nội dung env có secrets. Dùng một `.env` tại root và
một mẫu `.env.example` tại root cho API/Agent/Hardhat/RAG. Các mẫu con và
`.env.phase3.example` đã được hợp nhất. Hardhat vẫn chỉ dùng `PRIVATE_KEY` cho
lệnh deployment tường minh; demo local không đọc private key để gửi giao dịch.

## Mapping interface và phần còn lại của G3.2

| Nối giữa | Khác biệt hiện tại | Cách tích hợp tiếp theo |
|---|---|---|
| UI `/api/chat` ↔ `AgentService.chat(session_id, message)` | API trả AgentResponse/timeline; AgentService trả async list AgentEvent | Endpoint async + adapter response giữ contract UI, session tách biệt |
| Agent tools ↔ backend BlockchainService | Agent chờ async/raw wei; backend dùng sync/dict và lượng human-readable | Adapter async, thread offload RPC đồng bộ; map raw_balance/decimals chính xác |
| `get_erc20_balance` ↔ `get_token_balance` | Khác tool name và schema | Map tường minh, không đổi nhầm số lượng/đơn vị |
| `RAGRetriever` ↔ Agent | Retriever async, có scope/version/provenance | Khởi tạo một lần theo lifespan; context là dữ liệu tham khảo, không cấp quyền WRITE |
| RAG chunks ↔ UI citation | content/metadata/score; cosine có thể âm | Giữ score thật, provenance, provider; sửa schema hiện giới hạn score [0,1] |
| RAG no-match ↔ error | Adapter cũ âm thầm fallback khi provider lỗi | Phân biệt unavailable/timeout/no-match, không ghi keyword là vector retrieval |
| Hai PolicyEngine ↔ signer | Agent tools tự gọi policy/ký; API dùng pending approval riêng | Một đường execution bắt buộc, chặn mọi ký trước approval; G3.2 mới mở |
| Agent generic call_contract ↔ AgentToken | Policy source còn SampleVault placeholder | Allowlist theo manifest AgentToken; không mở generic contract ngoài phạm vi |
| Signer/nonce ↔ approval | Key/wallet/scope có thể không đồng nhất | Bind chain/contract/sender/payload/amount, revalidate trước broadcast |

Địa chỉ deployment theo chain: `0xa453B71a492558C17efA82E294739e4eFef3C220`
trên Sepolia 11155111. Manifest legacy `backend/abi/deployment.json` chứa địa chỉ
cũ; dùng `backend/abi/11155111/` và kiểm bytecode live khi tới G3.4. G3.0 chưa
kiểm chứng deployment/RPC live, không dùng corpus làm state on-chain.

## Chạy kiểm thử

Chuẩn bị tokenizer tiktoken một lần (chỉ tải dữ liệu tokenizer, không gọi LLM):

```powershell
.venv-phase3/Scripts/python.exe -c "from config.environment import load_project_env; load_project_env(); import tiktoken; tiktoken.get_encoding('cl100k_base'); print('tokenizer cached')"
```

Runner tự tạo `.phase3/` và temp dưới đó, dùng FakeLLM, xóa quyền dùng key của
child process, log/summary riêng theo suite:

```powershell
.venv-phase3/Scripts/python.exe -m scripts.run_phase3 --suite unit
.venv-phase3/Scripts/python.exe -m scripts.run_phase3 --suite rag
.venv-phase3/Scripts/python.exe -m scripts.run_phase3 --suite contracts
.venv-phase3/Scripts/python.exe -m scripts.run_phase3 --suite local_evm
```

`--suite all` chạy lần lượt cả bốn và dừng khi suite lỗi. Unit không chạy live
EVM tests; local_evm phải có artifact contract đã compile (`contracts` suite
compile tự động nếu cần). Integration runner dùng Node trực tiếp, bind loopback,
chỉ dừng node do nó tạo. Node đã có sẵn trên 31337 được giữ nguyên.

Log/summary có thể ghi đè khi chạy lại cùng suite; lưu bản cụ thể trước khi dùng
cho benchmark/báo cáo cuối. Kết quả fake/unit/local không được tính là accuracy
LLM thật hoặc giao dịch Sepolia thật.

## Kết quả G3.0

Đã xác minh: 190 unit tests, 54 RAG tests, 34 contract tests và 81 tests trong
suite API/EVM local pass. Chi tiết, phạm vi và phần còn thiếu tại
[PHASE3_RESULTS.md](PHASE3_RESULTS.md).

Regression sau sửa: 273 unit tests/68 subtest và 135 tests API/EVM local pass; browser
smoke với Gemini/RAG thật đạt 6/6 ca sau sửa chuẩn hóa câu FAQ. Các suite
RAG/contract độc lập giữ kết quả baseline; không cộng test trùng giữa các runner.

## G3.1 — Chế độ đọc đã tích hợp

Bật `PHASE3_AGENT=llm` khi khởi động API; `legacy` là mặc định tương thích với
bản demo cũ. Chế độ mới gọi AgentService thay vì regex, truy xuất RAG trước khi
LLM chọn tool, đếm lại context bằng tokenizer LLM và trả citation/score/provenance.
Frontend giữ contract AgentResponse, gửi session ID riêng cho mỗi tab và hiển thị
similarity dạng số thực, không diễn giải thành xác suất.

```powershell
.venv-phase3/Scripts/python.exe -m backend.api.server
```

Cần Hardhat local chạy sẵn. FakeLLM mặc định không tự suy luận prompt; script
trong tests cung cấp các tool calls/final response để kiểm wiring, không đo
accuracy mô hình. Muốn chat tự nhiên thật phải chọn model active và cấu hình
provider/key/budget trước. Source mặc định lịch sử không tự được dùng khi mode
LLM thật chưa có LLM_MODEL tường minh.

- Registry riêng chỉ có 6 READ tools: native balance, ERC20 balance, token info,
  gas, block, transaction. Mọi tool khác, kể cả tool WRITE do model tự gọi, bị
  từ chối trước execution. Agent luôn dry_run và không nhận private key.
- READ wrappers dùng schema Agent nhưng gọi backend qua worker thread, giữ
  chuỗi decimal/raw amount chính xác. Câu trả lời balance được render từ
  backend để tránh model viết lại các chữ số.
- Local dùng SourceScope của các tài liệu `usage=ingest`; không gắn deployment
  Sepolia cho node Hardhat. Sepolia read mode yêu cầu chain/address/ABI hash
  khớp deployment. Nguồn source không chứng minh trạng thái contract local/live.
- Retriever khởi tạo một lần trên lifespan/event loop, đóng khi shutdown; retriever
  inject thuộc quyền quản lý của caller. No-match giữ rỗng; lỗi timeout/unavailable
  không âm thầm fallback và không gọi LLM.
- Session khóa riêng để không chạy đồng thời trên cùng memory; giới hạn 100 session
  cho demo local. Session ID là phân vùng memory, không phải cơ chế đăng nhập hay
  xác thực cho môi trường nhiều người dùng.
- API timeline không trả provider thought events. Kết quả tool lỗi/disabled không
  được biến thành thông báo giao dịch thành công chỉ vì LLM nói thành công.

## G3.2 — WRITE local có xác nhận

Đã thêm coordinator dùng chung cho proposal từ Agent và API. Ba thao tác
native transfer, AGNT transfer và faucet phải qua policy/simulation/approval.
Approval bind session, chain, sender, recipient, amount, ABI/runtime hash và
payload; kiểm lại ngay trước broadcast. Chỉ account unlocked của Hardhat
loopback 31337 được gửi, không đọc private key. Cờ `PHASE3_LOCAL_WRITES` mặc
định false; Sepolia WRITE vẫn khóa.

Frontend gửi session khi duyệt, phân biệt CONFIRMED/REVERTED/PENDING/UNKNOWN
và chỉ poll receipt, không broadcast lại. Double-click/replay được trả kết quả
cũ; nonce đổi thì yêu cầu proposal mới. Kết quả broadcast không rõ sẽ khóa các
đề xuất sau để đối soát thủ công.

Hướng dẫn khởi động node, export fixture, chạy API và thử giao diện tại
[PHASE3_RUNBOOK.md](PHASE3_RUNBOOK.md).

## Bước tiếp theo

Người dùng đã duyệt payload; smoke Gemini + RAG + API + EVM local đã chạy.
Đã sửa lỗi model làm tròn raw wei; ca số dư chạy lại đạt. Xem PHASE3_RESULTS.md.
G3.5 đã đo đủ 60 benchmark/20 safety bằng Gemini thật: baseline holdout tool
accuracy 93,3%, safety 20/20; lỗi đã được sửa và kiểm hồi quy riêng, chưa có
holdout mới/latency acceptance cho code hiện tại. Xem
[bàn giao G3.6](PHASE3_HANDOFF.md) và [báo cáo baseline](PHASE3_G35_REPORT.md).
Sáu ca browser
local đã đạt; G3.4 READ và hai fixture WRITE Sepolia được duyệt đã hoàn thành.
Grant WRITE đã tiêu thụ hết, không được tự lặp lại. Chi tiết
tất cả gate ở [kế hoạch giai đoạn 3](GIAI_DOAN_3_E2E_PLAN.md).
