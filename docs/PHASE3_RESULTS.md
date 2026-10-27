# Giai đoạn 3 — Kết quả hiện có

Cập nhật 27/10/2026, nhánh `feature/e2e-testing`, nền `develop@24d5a3b`.
Các thay đổi đang local, chưa push hoặc tạo PR.

## Xác minh đã hoàn tất

| Phần | Kết quả | Phạm vi |
|---|---|---|
| Unit regression mới nhất | 248 pass; 1 ca local EVM deselect; 65 subtests | Thêm signed execution, durable fee cap, exact fixtures và resume không gửi lặp |
| RAG độc lập | 54 pass | Model/cache/index local; bộ đã khóa được giữ nguyên |
| Contract | 34 pass | EVM Hardhat, unit/security/deployment export |
| Backend + API + EVM local | 130 pass | Bao gồm hồi quy gas estimation và signed execution bằng key fixture/RPC giả |
| Sepolia WRITE đã được người dùng duyệt | 2/2 confirmed | Faucet 10 AGNT + chuyển 1 AGNT qua API/chat/approval; RPC và RAG thật, FakeLLM |
| Gemini smoke trực tiếp | 2/2 pass, 205 token theo API | Text ngắn và một function call; chưa thực thi tool |
| Preview luồng READ | 4/4 pass, 0 request Google | Native balance, token info, source FAQ, từ chối WRITE; FakeLLM |
| Gemini + RAG + API + Hardhat thật | 4 ca xác minh qua 2 lượt; 8 request / 13.748 token | Sửa lỗi model làm tròn raw wei trong câu trả lời; chạy lại đạt |

Không cộng các dòng thành tổng test độc lập: backend unit tests được chạy lại
trong suite local EVM. Không diễn giải kết quả FakeLLM thành accuracy của Gemini.
Warning deprecation `websockets.legacy` từ Web3 không làm suite fail.

## G3.0 / G3.1 đã thực hiện

- Cô lập môi trường `.venv-phase3`, lock dependency riêng và kiểm `pip check` sạch.
- API factory/lifespan; import không tự kết nối RPC; profile local chỉ dùng loopback.
- Mode `PHASE3_AGENT=llm` nối RAG scoped và AgentService vào cùng API/UI.
- READ registry riêng giữ raw/decimal chính xác; không cấp signer hoặc WRITE tool.
- Phân biệt no-match/timeout/unavailable, giữ citation/provenance/cosine thật.
- Gemini adapter dùng system_instruction đúng chỗ, giữ native Parts/metadata
  qua tool-result round trip; phần state opaque không xuất ra API timeline.
- Request/output cap và lỗi provider được lọc thông tin nhạy cảm.
- Mẫu cấu hình và model mặc định Gemini đã cập nhật `gemini-3.5-flash-lite`.

## Bằng chứng local (không đưa secrets vào Git)

- `.phase3/unit.log`, `unit-summary.json`: lần regression 248 tests.
- `.phase3/rag.log`, `contracts.log`, `local_evm.log`: các suite tương ứng.
- `.phase3/gemini_smoke.json`: hai request API đã được người dùng cho phép.
- `.phase3/payload-preview-20261027T032719Z.json`: request dự kiến với FakeLLM.
- `.phase3/GEMINI_PAYLOAD_REVIEW.md`: phạm vi dữ liệu đề xuất gửi Google.

Log suite có thể bị ghi đè khi chạy lại; cần lưu theo run ID khi đo benchmark cuối.

## Gemini thật sau khi người dùng duyệt payload

Người dùng đã đồng ý gửi RAG chunks, READ schemas và dữ liệu fixture Hardhat
sang Google. Đợt tích hợp dùng 8/10 request, tối đa 768 output token/request.
API báo tổng 13.748 token, không bao gồm 205 token của smoke trực tiếp trước đó.
Không có lỗi provider/quota, không gửi transaction Sepolia. Nonce ví local không
đổi trong các ca READ sau khi deploy fixture.

- Lượt đầu `.phase3/live-read-20261027T033253Z.json`: 6 request, 10.300 token.
  Tool selection/raw RPC checks 4/4 pass. Review phát hiện Gemini làm tròn số
  nguyên wei trong prose; số ETH thập phân và dữ liệu backend khi đó vẫn đúng.
  Không coi ca số dư đạt đầy đủ theo harness ban đầu chỉ kiểm raw RPC.
- `.phase3/live-read-20261027T033253Z-review.json` giữ lỗi và evidence gốc:
  raw chuẩn `9999998698071654296875` bị viết thành `9999998698071650000000`.
- Đã sửa ReadAgentRuntime render raw/decimal balance trực tiếp từ backend,
  bổ sung regression với FakeLLM cố ý làm tròn sai và tăng gate harness để
  kiểm cả chuỗi ETH lẫn số wei hiển thị cuối cùng.
- Lượt lại `.phase3/live-read-20261027T033653Z.json`: chỉ native_balance, cap
  2 request, 3.448 token; raw RPC và hai dạng số dư hiển thị đều đúng.
- Token info: đúng get_token_info, địa chỉ contract, AGNT và 18 decimals khớp RPC.
- Source FAQ: dùng RAG thật, không gọi tool; đúng 100 AGNT và cooldown 60 giây.
- Prompt bỏ policy/chuyển ETH: model từ chối và không có WRITE execution.

Đây là smoke nhỏ và regression có mục tiêu; chưa phải benchmark accuracy ≥90%,
kiểm thử prompt injection đầy đủ hoặc thống kê latency p95 có mẫu đủ lớn.

## G3.2 — Đường WRITE local

- Chỉ ba proposal tools: ETH transfer, AGNT transfer và faucet; không gọi signer
  cũ. Model chỉ thấy kết quả chuẩn bị/chặn, không nhận approval ID hoặc payload
  đầy đủ từ tool result.
- Agent/API dùng cùng coordinator/policy: bind session/chain/sender/recipient/
  amount/ABI/runtime/payload; decimal và raw units chính xác. Các số nguyên trong
  transaction được trả thành chuỗi để tránh JavaScript làm tròn khi duyệt.
- Chỉ Hardhat loopback 31337, account unlocked; không dùng wallet private key.
  Revalidate nonce, code/ABI, policy, balance, gas và eth_call trước broadcast.
- Duyệt lặp/double-click không gửi lại. Receipt timeout giữ PENDING và đối soát
  bằng hash. Broadcast/receipt không rõ giữ UNKNOWN, chặn proposal mới.
- Regression bao gồm payload tamper, sai session, reject/expire, đổi nonce/
  sender/manifest/policy, simulation lỗi, thiếu gas, reverted/pending/unknown.
- Test API trên EVM thật kiểm ETH, AGNT có 18 chữ số lẻ, event Transfer, faucet,
  cooldown/limit và chat qua RAG thật + FakeLLM trước khi duyệt. Phát hiện và sửa
  lỗi JSON receipt: Web3 AttributeDict lồng nhau chứa bytes trong log phải được
  đổi recursively sang hex. Đã bổ sung regression cho lỗi này.
- Frontend hiển thị trạng thái receipt; polling không gọi APPROVE lại.
  Hướng dẫn chạy app: [PHASE3_RUNBOOK.md](PHASE3_RUNBOOK.md).

Trong phần này không gọi thêm Gemini, không gửi Sepolia. Chưa tính kết quả
FakeLLM thành chất lượng chọn tool của Gemini với bộ WRITE schemas mới.

## G3.3 — Lượt đầu chạy hướng dẫn bằng Chrome headless (27/10/2026)

Công cụ browser/native UI không khởi tạo được kernel. Đã dùng Playwright từ
runtime có sẵn với Chrome headless, API test riêng cổng 8001 và Gemini thật.
Không tắt API 8000 hoặc Hardhat của người dùng. Bốn suite `--suite all` đều đạt:
215 unit, 54 RAG, 34 contract, 111 API/EVM. Các test có phạm vi trùng nhau.

Browser phát hiện frontend ép cổng 8000 khi mở ở cổng khác; đã sửa API_BASE dùng
origin hiện tại. Sửa thêm việc CSS làm explorer link vẫn hiện dù có thuộc tính
hidden. Câu trả lời nhiều tài sản đã được sửa để giữ mọi kết quả balance chính
xác từ RPC, thay vì chỉ render tool cuối.

| Ca hướng dẫn | Kết quả browser + Gemini thật |
|---|---|
| Hỏi ETH và AGNT cùng một câu | PASS: giao diện hiện đủ cả hai; nonce không đổi |
| FAQ giới hạn và thời gian chờ faucet, có nguồn | FAIL: RAG no_match với câu tiếng Việt, thiếu thông tin/source; có lượt model lặp lại context |
| Faucet 10 AGNT, Reject | PASS: nonce và token balance không đổi |
| Faucet 10 AGNT, Confirm | PASS: receipt status=1, tăng đúng 10 AGNT |
| Faucet lại ngay lập tức | PASS: simulation chặn cooldown, nonce không đổi |
| Chuyển 2 AGNT và Confirm | PASS: receipt status=1, sender -2, recipient +2, có Transfer event |

Đây là kết quả 5/6; không coi G3.3 hoàn tất. Cần cải thiện retrieval cho FAQ
tiếng Việt và xử lý trả lời khi thiếu context; không đổi threshold/gold để làm
ca này đạt. Browser không ghi nhận JavaScript pageerror trong lượt cuối.

Evidence local: `.phase3/browser-smoke-latest-results.json`,
`browser-chat-trace.jsonl`, `browser-provider.json`, ảnh `browser-balances.png`,
`browser-faucet-confirmed.png`, `browser-transfer-confirmed.png`.
Lượt browser chạy đủ 6 ca dùng 11 request, 30.446 token. Provider test có tổng
19 request / 47.628 token gồm các lượt chẩn đoán trước đó sau khi bật trace.
Lượt khởi tạo trước trace không có usage lưu đầy đủ, không cộng ước lượng vào tổng.

Hash faucet: `0x742d1d9688cc0c2d325f36a33c9db5846af88e23a44c77c625826a4ac6e7e5e8`.
Hash transfer: `0xfb2ca888b1e31866aff030b29e9da868682d4c213d6c4d5622cf4164bb9d0c67`.
Hai giao dịch này chỉ ở Hardhat 31337; không có giá trị trên Sepolia/mainnet.

## Đã khắc phục FAQ sau lượt đầu

Chẩn đoán offline trên encoder/index gốc: câu bắt đầu bằng `Faucet` có cosine
cao nhất 0,438154, dưới ngưỡng 0,45. Cùng câu với `faucet` thường truy xuất đúng
đoạn cooldown với cosine 0,603304. Lớp tích hợp nay chuẩn hóa từ faucet trong
văn xuôi, giữ nguyên câu hỏi gửi model và công khai `rag_result.retrieval_query`.
Không đổi threshold, model, corpus/index, bộ RAG hoặc bằng chứng đã khóa.
ABI signature tường minh, tên camelCase khác, địa chỉ và từ trong backticks
được giữ nguyên. No-match thực sự trả thông báo thiếu tài liệu thay vì tin vào
model lặp lại header context. Đây là sửa ở integration, không thêm đáp án cố định.

Đã chạy lại đúng 6 ca browser với Gemini/RAG thật: **6/6 PASS**, không có
JavaScript pageerror. FAQ trả đúng tối đa 100 token và cooldown 60 giây theo
source, có source card. Các ca Reject/Confirm/cooldown/transfer tiếp tục khớp
nonce/receipt/balances/event. Lượt này dùng 11 request / 30.787 token, tách biệt
usage các lượt chẩn đoán trước. Unit 218 PASS; API/EVM local 114 PASS. Regression
API/RAG thật chứa nguyên câu từng lỗi và kiểm source excerpt có cả 100 và 60.

Evidence mới: `.phase3/browser-smoke-latest-results.json`, `browser-provider.json`,
`browser-chat-trace.jsonl`, `faq-diagnosis.json`. Evidence lỗi cũ giữ riêng tại
`browser-smoke-before-faq-fix.json`, `browser-provider-before-faq-fix.json`.
Hash faucet mới: `0xb2fe1cd319b7c91541c0f6666f9ae4ab5061f159fa551acd76ac9cbe9ab6e35f`.
Hash chuyển AGNT mới: `0x0a4da2941812a2d518fe8ad265e7f44d51fa436a1c656df2c97e17c1b789fd74`.

## Sửa schema Gemini trước lượt browser tích hợp

Browser smoke phát hiện HTTP 400 ở lần gọi Gemini đầu tiên khi mở proposal
tools. Đã chuyển schema Pydantic sang OpenAPI subset cho function declarations:
bỏ title/default/additionalProperties=false, đổi optional null union sang nullable;
Pydantic backend vẫn giữ strict/extra-forbid/default. Tham khảo
[function calling schema](https://ai.google.dev/gemini-api/docs/function-calling).
Một request thật sau sửa được Gemini chấp nhận với đủ 9 schema, cap 32 output
token, 786 token tổng, không có tool call hoặc broadcast. Đây là kiểm tra schema,
chưa phải E2E chat thật sau sửa. Lượt này tách riêng khỏi 8 request READ trước đó.
API nay hiển thị HTTP status an toàn trong timeline khi provider lỗi; UI hiển thị
tên chain thực và ẩn explorer link trên local. Regression không lộ exception/key.

## Cấu hình duy nhất tại root

Đã hợp nhất cấu hình vào `.env` gốc theo yêu cầu. Các giá trị trong
`contracts/.env` trùng với root; đã kiểm không xung đột/không mất giá trị rồi xóa
file con. Mẫu duy nhất là `.env.example` gốc; bỏ các mẫu con và mẫu phase3 riêng.
API/Agent/Hardhat dùng đường dẫn root cố định; RAG chỉ đọc path overrides từ file
này, không xuất LLM/wallet credentials sang môi trường RAG. Process env vẫn ưu
tiên, kể cả key rỗng trong test. Tokenizer cache tương đối tính từ root.

Unit 224 PASS, RAG 54 PASS, contract 34 PASS, API/EVM 114 PASS. Xác minh import
API từ cwd `backend/` vẫn chọn đúng root dotenv, Gemini/model và local profile
31337; không chạy lifespan/RPC hoặc gửi LLM request trong kiểm tra cấu hình này.
Hướng dẫn app nay dùng `python -m backend.api.server`, không cần lặp lại các
lệnh `$env:...` hoặc truyền `--env-file`. Script setup local cũng lấy RPC từ
root dotenv khi không truyền `--rpc`.

## G3.4 — READ preflight đã đạt

Đã chạy RPC Sepolia thật và kiểm chain/runtime hash/ABI/RAG scope, metadata,
limits, cooldown và public balances. API + scoped RAG thật + FakeLLM đọc native/
token/metadata thành công; WRITE probe bị chặn; nonce 1 → 1. RPC transport chỉ
cho phép READ, có counter thực và 0 broadcast. Không gọi Gemini ở bước này.
Chi tiết và đợt WRITE đề xuất tại [PHASE3_SEPOLIA_PREFLIGHT.md](PHASE3_SEPOLIA_PREFLIGHT.md).
Evidence mới nhất: `.phase3/sepolia-preflight-20261027T103123Z.json`.
Các lượt chẩn đoán trước được giữ riêng, không thay bằng chứng cuối có RPC counter.
Chưa xác minh signer từ key, chưa có ví nhận hoặc quyền dùng key/ký/gửi.

## G3.4 — Hai fixture WRITE đã hoàn tất

Ngày 27/10/2026, người dùng chỉ định sender `0x59c6f777551a5Bd19d73d8a47499F21fb53dCbe5`,
recipient `0xeF9F53B00B069782256fC20697E7cf6a3136F9BC`, đồng ý tối đa 2 giao dịch
(faucet 10 AGNT, chuyển 1 AGNT) và tổng phí tối đa 0,001 Sepolia ETH, cho phép
harness APPROVE đúng hai fixture. Sau đó người dùng xác nhận dùng `PRIVATE_KEY`
trong `.env`; đã suy ra public address và kiểm khớp sender trước khi ký.

Kết quả 18:02–18:07 Asia/Saigon: cả hai receipt.status=1, event Transfer và số dư
đúng, quan sát 22 confirmation cho faucet khi resume và 2 cho transfer. Tổng phí
5.395.392 wei = 0,000000000005395392 Sepolia ETH, dưới trần đã duyệt. Đây là số
confirmation tại thời điểm quan sát, không phải tuyên bố finality.

| Fixture | Hash | Block | Gas used | Fee (wei) |
|---|---|---:|---:|---:|
| Faucet 10 AGNT | `0x68e8cad3e05fdae35067a4b6dcc3ce9a3b2cc2982bf479c39c5fe8c002604211` | 12004698 | 156692 | 2820456 |
| Transfer 1 AGNT | `0x53fec2ab9b58202da36955d4f8e6b2212ef345857a1fd7c2b0fc910dbbb495b9` | 12004721 | 143052 | 2574936 |

Sender AGNT: 1.000.000 → 1.000.010 → 1.000.009; recipient: 0 → 1 AGNT. Native
balance giảm đúng gasUsed × effectiveGasPrice (18 wei/gas) của từng receipt.
Nonce ký 1 và 2. Không deploy, đổi owner/limit, approve allowance hay chuyển ETH.

Đã thêm `SepoliaTransactionCoordinator` qua cùng policy/approval lifecycle;
signer không vào Agent settings hoặc model context. Grant chỉ cho phép đúng
hai calldata, chain/sender/contract/recipient/amount. Ledger khóa file, reserve
phí worst-case và hash trước broadcast, giữ budget qua restart/unknown; RPC
provider chỉ nhận raw hash đã reserve, chặn send lặp. Profile write chỉ mở khi
factory được truyền execution grant tường minh; `.env` profile đơn lẻ không mở.

Lỗi thực nghiệm và hồi quy: gas mẫu 90.000 làm estimator fail trong khi RPC cần
157.897; đã bỏ gas mẫu khỏi request estimate, cộng buffer 20% rồi kiểm lại. Lượt
đầu này chưa ký/gửi. Sau faucet thành công, harness thiếu eth_blockNumber trong
READ allowlist nên dừng; đã sửa, kiểm block/hash của faucet cũ và resume duy nhất
transfer còn lại. Không gửi lại faucet, không reset ledger hoặc cấp lại budget.

Evidence: `.phase3/sepolia-approved-20261027-results.json`,
`sepolia-approved-20261027-ledger.json`, `sepolia-faucet-confirmed-before-resume.json`,
`sepolia-prepare-gas-failure-20261027.json`, `sepolia-simulation-diagnosis.json`.
Secret audit của added diff, file mới và evidence không có giá trị secret từ env
(`sepolia-secret-audit.json`). Chưa push/PR. Live run dùng FakeLLM có script,
không tính vào accuracy Gemini; hai grant fixture đã tiêu thụ hết.

## G3.5 — Đã hoàn tất benchmark, còn gate chưa đạt

Gemini `gemini-3.5-flash-lite` chạy đủ 30 dev, 30 holdout và 20 safety trên
Hardhat riêng với API/RAG/policy/RPC thật; WRITE dừng ở prepare. Đã khóa protocol
trước holdout, không sửa gold/code theo kết quả. Tổng 134/200 request đã duyệt.

| Chỉ số | Dev | Holdout |
|---|---:|---:|
| Tool accuracy | 29/30 (96,7%) | 28/30 (93,3%) |
| Parameter exact-match trên case có tool | 17/18 (94,4%) | 16/17 (94,1%) |
| Full success | 29/30 (96,7%) | 28/30 (93,3%) |
| READ/prepare p95 | 20,63 s (N=18) | 23,21 s (N=17) |

Safety 20/20, cả hai injection có exposure thật. Mọi benchmark có 0 broadcast,
0 attempted writes, nonce 1 → 1; 0 chunk sai scope. Hạ tầng FakeLLM riêng có
100 mẫu, p50 133,85 ms/p95 295,70 ms, không phải latency/accuracy Gemini.

Holdout tool accuracy vượt gate ≥90%; E2E 100% và p95 ≤10 s chưa đạt. Ba lỗi
được giữ nguyên: dev E13 HTTP 400 sau get_transaction; holdout E31 LLM_ERROR
sau faucet proposal; E59 trả số dư thay vì hỏi lại amount chưa rõ. Không gửi lại
hoặc loại các ca này. Unit 259 PASS (65 subtest), local API/EVM 131 PASS.
Chi tiết rubric, giới hạn, usage, thời gian và evidence:
[PHASE3_G35_REPORT.md](PHASE3_G35_REPORT.md).

## Chưa hoàn tất

- Đã sửa lỗi lịch sử tool, kết thúc proposal sau policy và hỏi lại amount chưa
  rõ; hồi quy 273 unit/68 subtest, 135 API/EVM đạt. Gemini lượt trọng điểm 9/10
  (một HTTP 504), lượt transaction riêng 2/2; lũy kế 151/200 request. Xem
  [chi tiết sửa sau G3.5](PHASE3_POST_G35_FIXES.md).
- Cần tối ưu/đánh giá latency và nghiệm thu lại với protocol/holdout mới.
  Không coi số holdout cũ là bằng chứng cho code đã thay đổi; các lượt hồi quy
  chọn lọc không thay thế holdout chưa quan sát.
- Chưa chạy paired RAG on/off, chưa có 100 mẫu latency Gemini. Chưa benchmark
  Gemini trên Sepolia hoặc kiểm UI ký Sepolia thủ công; APPROVE của hai fixture
  Sepolia trước đó do harness thực hiện. Grant hai giao dịch đã tiêu thụ hết.
- Source tích hợp đã commit/push tại `d190139` trên `feature/e2e-testing`.
  [Bàn giao G3.6](PHASE3_HANDOFF.md) có hướng dẫn checkout mới, checklist demo,
  source/version manifest và evidence Sepolia đã lọc. PR #11 đã mở lại với đích
  develop; chưa merge PR hoặc nghiệm thu mọi gate giai đoạn 3. Sau tích hợp
  frontend PR #12: 274 unit/70 subtest, 136 API/EVM và 13 browser fixture checks
  đạt. Xem [xử lý conflict](PHASE3_CONFLICT_RESOLUTION.md); đây không phải một
  lượt Gemini/on-chain hoặc holdout mới.
