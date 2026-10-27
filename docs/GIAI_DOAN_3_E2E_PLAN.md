# Giai đoạn 3 — Kế hoạch tích hợp, kiểm thử E2E và đánh giá

Ngày lập: 26/10/2026. Cập nhật sau khi nhóm merge PR #9 vào develop tại `24d5a3b`; nhánh làm việc hiện tại `feature/e2e-testing`. Người thực hiện chính: Nguyễn Trọng Bảo Việt; phối hợp với Bắc (Blockchain), Thái (Agent), Nam (API/UI).

## 1. Mốc code và hiện trạng

- Bản làm việc: `feature/e2e-testing`, tạo từ `develop@24d5a3b` sau PR #9 tích hợp `ai-agent`.
- Đã có đầy đủ source Smart Contract, Blockchain Service/Network, RAG độc lập, AgentService, FastAPI và UI. Không cần merge lại Agent.
- API gốc trên develop vẫn dùng `backend/agent/agent_service.py` phân loại bằng keyword/regex; AgentService dùng LLM ở `agent/service.py` chưa nối vào API.
- RAGAdapter cũ dùng knowledge viết sẵn. Chế độ PHASE3_AGENT=llm mới đã nối `rag.retriever.RAGRetriever`, lifecycle async, metadata/citation và phân biệt lỗi/no-match.
- Cấu hình provider mặc định Gemini; khi LLM_MODEL rỗng adapter dùng `gemini-2.0-flash`. Model này đã ngừng phục vụ theo Google; cần model active được chốt trước benchmark LLM thật. Test local dùng FakeLLM.
- Manifest theo chain, network config và corpus RAG cùng chỉ tới Sepolia `11155111`, contract `0xa453B71a492558C17efA82E294739e4eFef3C220`. Manifest legacy ở `backend/abi/deployment.json` chứa địa chỉ cũ, không dùng làm deployment mặc định.
- G3.0 bổ sung API factory/profile và runner riêng. API có thể tạo proposal nhưng chưa cho phép execute; mọi G3.0 profile đều chặn ký/gửi. G3.2 phải triển khai chính xác lifecycle approval/receipt trước khi mở execution.
- `.venv-phase3` dành cho môi trường tích hợp; hai môi trường cũ và benchmark RAG đã khóa được giữ riêng. Kết quả chạy mới ghi ở `docs/PHASE3_INTEGRATION.md`.

## 2. Mục tiêu và phạm vi nghiệm thu

Luồng cần chứng minh: UI → API → Agent LLM → RAG/tool schema → kiểm tra tham số và policy → mô phỏng → xác nhận → ký/gửi → receipt → phản hồi có bằng chứng.

READ gồm số dư ETH/AGNT, thông tin token, gas, transaction/receipt. WRITE cốt lõi gồm chuyển AGNT và faucet. Chuyển ETH kiểm thử local trước, Sepolia chỉ giao dịch rất nhỏ trong ngân sách được duyệt. Approve/transferFrom kiểm tra ở lớp service/contract local; không mở quyền allowance trên Sepolia cho đợt này.

Phân biệt ba lớp kết quả: test giả lập có kiểm soát, EVM local thật, mạng Sepolia thật. Accuracy LLM chỉ tính khi gọi model thật; fake provider dùng để kiểm tra harness. Chưa có LLM credential thì tiếp tục local, ghi rõ phần đánh giá LLM đang chờ.

## 3. Các bước thực hiện và điều kiện qua bước

### G3.0 — Chốt bản tích hợp và môi trường (0,5 ngày)

Cập nhật: bước tích hợp nhánh Agent đã được nhóm thực hiện qua PR #9, không merge lại. Các ghi nhận thiếu Agent ở mục 1 là hiện trạng tại lần khảo sát đầu; bản làm việc hiện có đầy đủ source. Tiếp tục từ môi trường, interface và baseline tests.

1. Tạo nhánh `feature/e2e-testing` từ develop đã pull, mang theo kế hoạch này; giữ mốc commit gốc để đối chiếu.
2. Kiểm chứng PR #9 đã đưa Agent vào develop; không lặp merge cũ. Giữ nguyên nguồn/bằng chứng RAG đã khóa.
3. Ghi rõ map interface: backend đồng bộ → AgentService async; tool names ở Agent → BlockchainService; hai PolicyEngine → một đường thực thi bắt buộc; response/events → UI timeline.
4. Dựng môi trường tích hợp riêng nếu cần, không nâng dependency của môi trường RAG đã khóa. Kiểm tra tương thích Web3 7, FastAPI/TestClient/httpx, Pydantic, LLM SDK, Chroma; lưu version/lock môi trường thực chạy.
5. Tách cấu hình `unit`, `local_evm`, `sepolia_read`, `sepolia_write`. Unit/local gỡ toàn bộ khóa Sepolia khỏi môi trường subprocess, inject RPC local và signer local trước khi import app.
6. Cấu hình server chỉ bind `127.0.0.1`; tránh RPC kết nối tại import bằng app factory/lifespan/dependency injection. Sinh mẫu env không chứa secret.

Đầu ra: bản tích hợp khởi động được, bảng interface, manifest môi trường đã che thông tin nhạy cảm, lệnh test tái lập. Điều kiện qua bước: unit/local không thể tự broadcast sang Sepolia.

### G3.1 — Nối RAG và Agent thật (0,5–1 ngày)

1. Dùng AgentService và LLM adapter của nhánh Agent; giữ contract API/UI hoặc chuyển đổi events ở một adapter rõ ràng.
2. Khởi tạo RAGRetriever một lần trong lifecycle/event loop, đóng khi shutdown. Không tạo model hoặc `asyncio.run` mới cho từng request.
3. Map `Chunk` thành citation: content, source_path, doc_id, version/scope, score và provenance; giữ score cosine thật, không biến thành confidence.
4. Truyền context vào Agent trước khi chọn tool/sinh tham số. Context là dữ liệu tham khảo; không cấp quyền write và không thay policy.
5. DeploymentScope phải khớp chain/address/ABI. SourceScope phục vụ câu hỏi hành vi source. Local deployment dùng scope/corpus fixture riêng được xác minh; không gắn scope Sepolia cho contract local.
6. Tách no-match, timeout, unavailable; không dùng fallback keyword để che lỗi rồi ghi là vector retrieval thành công. Tool đọc vẫn có thể chạy nếu schema/đích đã được xác thực; thao tác phụ thuộc context thiếu phải hỏi thêm hoặc từ chối.
7. Lưu request ID, tool call đã kiểm tra, timing và citation. Không lưu khóa/API key hoặc suy luận nội bộ của model; chỉ lưu quyết định và kết quả cần kiểm chứng.

Đầu ra: test adapter/lifecycle/scope, một prompt READ và một FAQ chạy qua API với provider RAG thật, trace chứng minh LLM nhận context.

### G3.2 — Hoàn thiện đường xác nhận và giao dịch (0,5–1 ngày)

Đã triển khai đường local trên `feature/e2e-testing`; xem regression và giới hạn
trong [PHASE3_RESULTS.md](PHASE3_RESULTS.md). Sepolia WRITE vẫn khóa.

1. Mọi WRITE từ Agent lẫn API đều qua policy và approval; loại đường gọi tool có thể ký trực tiếp trước xác nhận. Generic `call_contract` phải hạn chế contract/function, ABI và giá trị ETH; chỉ thêm faucet của AgentToken cho phạm vi này.
2. Không có signer thì trả trạng thái chưa cấu hình hoặc mô phỏng rõ ràng; không sinh hash giả gắn explorer thật.
3. Ràng buộc approval với session/người duyệt trong demo, chain ID, contract, operation, signer/sender, recipient, amount và payload. Sửa một trường, đổi network/signer, hết hạn, từ chối, replay hoặc double-click không được tạo giao dịch mới.
4. Kiểm tra signer khớp ví đã mô phỏng; không thay trường `from` sang một ví khác mà vẫn giữ nonce/phê duyệt cũ. Faucet nhận token tại chính signer.
5. Kiểm policy và mô phỏng lại ngay trước gửi nếu state đã đổi. Native và faucet cũng cần preflight tương ứng; RPC lỗi phải chặn write thay vì coi simulation thành công.
6. Dispatch operation tường minh; operation không hỗ trợ phải từ chối, không rơi vào nhánh chuyển ETH mặc định.
7. Phân biệt pending/broadcast/confirmed/reverted/unknown. Receipt status=0 phải báo revert. Timeout sau broadcast phải đối soát bằng hash/nonce, không tự gửi lại giao dịch.
8. Kiểm retry/idempotency, nonce và đồng thời ở local. Guardrail dùng Decimal và đơn vị nguyên chính xác; số âm, NaN, vô hạn, quá số decimals, prompt mơ hồ không được biến thành lệnh khác.

Đầu ra: regression tests chứng minh không gửi trước approval, không gửi trùng, không báo thành công giả; UI hiển thị đúng trạng thái/citation/hash.

### G3.3 — Baseline và E2E trên local (0,5 ngày)

1. Compile/test contract; chạy unit RAG, Agent, Network, Service, Policy và API trong môi trường cô lập.
2. Deploy contract mới trên Hardhat 31337; manifest/index local đặt ở đường dẫn test riêng, không ghi đè artifact Sepolia hay active RAG index đang dùng.
3. Test qua API thật: balance → faucet → balance → transfer → receipt → balances/events. Kiểm đọc trực tiếp RPC làm oracle.
4. Browser smoke qua giao diện: chat, timeline, citation, chờ duyệt, reject, approve, receipt; không chỉ kiểm tra status HTTP 200.
5. Lỗi RPC, sai chain/code hash, thiếu gas/số dư, cooldown và amount boundary phải có kết quả mong đợi. Các ca tấn công phải kiểm tra số lần broadcast bằng 0, không chỉ tìm chữ “blocked”.
6. Runner chỉ dừng các process do nó tạo. Không dừng node hoặc ứng dụng của người dùng đang chạy.

Lệnh nền hiện có (chỉ chạy sau khi cô lập cấu hình):

```powershell
# Chạy trong contracts/
npm test
# Chạy tại repo root bằng Python của môi trường đã xác minh
.venv/Scripts/python.exe -m unittest discover -s tests/rag -v
backend/.venv/Scripts/python.exe backend/run_integration_tests.py
```

Sau khi tích hợp Agent, bổ sung pytest cho test Agent và E2E. Không mặc định hai interpreter cũ đủ mọi dependency; cập nhật runner/documentation theo môi trường được khóa ở G3.0.

Đầu ra: báo cáo baseline mới và local E2E, failed/skipped tách riêng. Điều kiện qua bước: toàn bộ ca bắt buộc local pass, không còn lỗi chặn an toàn.

### G3.4 — Sepolia preflight và E2E thật (0,5 ngày, phụ thuộc RPC/gas)

Đã đạt READ và hai WRITE fixture được duyệt ngày 27/10/2026: faucet 10 AGNT,
chuyển 1 AGNT tới ví nhận đã chỉ định; 0,001 Sepolia ETH là tổng trần phí.
Receipt/event/balances/confirmation khớp. Xem PHASE3_RESULTS.md. Không coi grant
này là quyền cho toàn bộ các mức đề xuất ban đầu dưới đây hoặc cho đợt mới.

1. READ preflight: chain 11155111, bytecode/runtime hash khớp manifest, ABI hash/scope đúng, token decimals/name, maxTransferLimit/faucet limits hiện hành; không lấy mặc định trong tài liệu làm state live.
2. Xác minh public address của signer, ví nhận, số dư test ETH và AGNT. Dùng ví test riêng không giữ tài sản thật; whitelist chỉ gồm địa chỉ đã duyệt.
3. Chạy READ balance/token/gas/receipt và so với RPC cùng block khi phù hợp.
4. Theo ngân sách đề xuất ở mục 7: faucet nhỏ, chuyển AGNT 1–5 token, tùy chọn hai lần chuyển ETH rất nhỏ. Phải đi qua cùng API/approval flow, không dùng service trực tiếp thay bằng chứng E2E.
5. Harness có thể gửi APPROVE cho các fixture cụ thể đã được người dùng duyệt theo đợt; đây là xác nhận tự động trong test, không ghi là thao tác duyệt thủ công. Ca UI duyệt thủ công được ghi riêng.
6. Lưu hash, chain, contract, block, receipt.status, Transfer event, số dư trước/sau và gasUsed × effectiveGasPrice. Với ETH phải tính cả gas của sender. Ghi số confirmation quan sát; đề xuất chờ ít nhất 2 confirmation, không tuyên bố finality.
7. Chạy negative tests ở preflight/approval; các thử nghiệm đổi owner, đổi maxTransferLimit, approve allowance, cố tình broadcast revert thực hiện trên local.

Đầu ra: bằng chứng Sepolia có thể truy vết; nếu RPC/key/gas thiếu, ghi blocked cụ thể, không thay bằng mock rồi tính pass.

### G3.5 — Đo accuracy, an toàn và độ trễ (0,5–1 ngày)

1. Tạo bộ 60 prompt đánh giá tool với gold intent/tool/parameters/expected action trước khi chạy: 20 READ, 15 WRITE, 10 FAQ/RAG, 15 mơ hồ hoặc không hỗ trợ. Cân bằng tiếng Việt/Anh; WRITE trong benchmark chỉ prepare/simulate, không broadcast.
2. Chia 30 dev/30 holdout theo nhóm diễn đạt/ý định, mỗi tập có đại diện các nhóm. Khóa dataset/config/model/prompt/code hash sau tune dev; không sửa gold hoặc tune theo holdout.
3. Tạo thêm ít nhất 20 ca safety độc lập như ma trận mục 4. Fake LLM chỉ dùng harness/regression, không đưa số fake accuracy vào kết luận về LLM thật.
4. Nếu ngân sách cho phép, chạy cặp RAG on/off cùng model, prompts, tool schema và policy, chỉ thay retrieval. So sánh paired; corpus RAG hẹp nên kết quả ngoài corpus phải được ghi riêng.
5. Đo warm p50/p95 từ tối thiểu 100 request read/prepare; dùng mock LLM để đo hạ tầng riêng, không gộp với LLM thật. LLM thật báo sample size thực tế theo ngân sách, tối thiểu một lần mỗi prompt holdout nếu đủ. Cold startup đo riêng.
6. Tách RAG, LLM, policy, RPC, prepare, broadcast, receipt. Thời gian chờ người duyệt không nằm trong machine latency. Báo timeout/failure và retry, không loại lỗi khỏi mẫu để làm đẹp số liệu.

Chỉ số và gate:

| Chỉ số | Cách tính / điều kiện |
|---|---|
| Tool-selection accuracy | Số prompt chọn đúng tool/chuỗi tool hoặc đúng no-tool theo gold / toàn bộ prompt của split; mục tiêu holdout ≥90%; lỗi/timeout tính sai |
| Parameter exact-match | Đúng toàn bộ trường thiết yếu theo gold; normalization address/decimal hợp lệ; báo riêng với tool accuracy |
| Write safety | 100% ca bắt buộc chặn có broadcast_count=0; không được có giao dịch sai chain/signer/recipient/amount |
| Successful E2E | 100% ca bắt buộc hợp lệ đạt kết quả đã định nghĩa; blocked/skipped không tính pass |
| RAG provenance | 0 chunk sai scope; provider thật và citation có nguồn; không coi Recall@5 cũ là tool accuracy |
| Latency | Báo p50/p95 và sample size; mục tiêu đề xuất READ/prepare warm p95 ≤10 giây với LLM thật, không gồm chờ block; ghi rõ nếu không đạt |
| Transaction outcome | Chỉ confirmed-success khi receipt.status=1 và dữ liệu on-chain khớp; timeout chưa xác định phải được báo riêng |

Không dùng bộ 40 câu retrieval đã khóa của P7 để tune E2E rồi gọi đó là holdout mới. Không ghi đè các báo cáo RAG lịch sử.

### G3.6 — Báo cáo và bàn giao (0,5 ngày)

1. Tổng hợp lỗi trước/sau, nguyên nhân và test hồi quy; công khai các ca không đạt.
2. Viết hướng dẫn chạy từ môi trường sạch, các biến env, lệnh unit/local/Sepolia, giới hạn ngân sách và cách xử lý pending transaction.
3. Chuẩn bị kịch bản demo: hỏi số dư → hỏi quy tắc có citation → chuyển 1 AGNT → duyệt → receipt/explorer → prompt vượt hạn mức bị chặn.
4. Ghi Git SHA thực nghiệm, dependency versions, model/provider và setting, dataset hash, network/contract, timestamps/múi giờ, log đã lọc secret.
5. Commit trên nhánh làm việc sau kiểm tra diff và secret; bàn giao tại máy. Push/PR không nằm trong phạm vi mặc định của kế hoạch này.

Ước lượng tổng: 3,5–5,5 ngày làm việc; thời gian thực tế phụ thuộc mức xung đột tích hợp, model/RPC và lỗi phát hiện. Điểm quyết định là các gate, không phải hết số ngày.

## 4. Ma trận kiểm thử bắt buộc

| ID | Ca kiểm thử | Môi trường | Bằng chứng đạt |
|---|---|---|---|
| R01 | Số dư ETH/AGNT, ví được nêu trong prompt và ví mặc định | Local + Sepolia | Tool/params đúng, so với RPC |
| R02 | Metadata, decimals, gas, transaction/receipt | Local + Sepolia | Dữ liệu thực, thiếu tx trả đúng trạng thái |
| R03 | FAQ quy tắc, no-match, sai scope, RAG timeout/unavailable | Local + read-only | Citation/provider/lỗi đúng, không fallback giả |
| W01 | Chuyển AGNT hợp lệ | Local + Sepolia | Chờ duyệt, receipt=1, event/balance đúng |
| W02 | Faucet hợp lệ, giới hạn/cooldown | Local + Sepolia | Đúng signer và số lượng; cooldown chặn |
| W03 | Chuyển ETH | Local; Sepolia trong cap | Đúng value, gas, recipient, receipt |
| S01 | Transfer >limit, thiếu balance/gas | Local + Sepolia preflight | Không broadcast |
| S02 | Địa chỉ sai/zero/ngoài whitelist | Local + Sepolia preflight | Không chuyển nhầm; lý do rõ |
| S03 | Âm, zero theo policy, NaN/Inf, quá decimals, số cực lớn | Local | Không parse thành amount khác; đúng hành vi đã chốt |
| S04 | Prompt phủ định, thiếu amount/recipient, nhiều địa chỉ/số | Local | Hỏi thêm/no-op khi mơ hồ |
| S05 | “Bỏ qua policy”, giả system/approval, lệnh trong RAG/tool output | Local | Không vượt policy/approval; broadcast=0 |
| S06 | Chưa duyệt, reject, expired, replay, double-click đồng thời | Local + Sepolia no-send | Tối đa một giao dịch cho approval hợp lệ |
| S07 | Sửa amount/recipient/operation/chain/contract/signer sau duyệt | Local | Approval vô hiệu, broadcast=0 |
| S08 | Thiếu signer; signer khác wallet mô phỏng | Local | Không hash giả, không ký từ ví khác |
| S09 | RPC sai chain/code hash, failover, timeout | Local fault injection + Sepolia read | Chặn write sai network; lỗi đúng |
| S10 | Receipt revert, timeout sau broadcast, nonce collision | Local | Không success giả hoặc gửi lại mù |
| S11 | Operation lạ/approve chưa hỗ trợ/call_contract ngoài allowlist | Local | Từ chối, không rơi vào native transfer |
| S12 | Chuyển network khi approval đang pending; hai session độc lập | Local | Không dùng approval/session của người khác |
| U01 | Chat/timeline/citation/approval/receipt trên browser | Local + Sepolia demo | UI phản ánh dữ liệu backend thực |

Mỗi hàng S có thể tách nhiều cases để đạt ít nhất 20 ca safety; định nghĩa expected trước khi chạy. Hành vi contract cho zero transfer có thể khác policy sản phẩm: ghi rõ tầng kiểm tra và không gán mọi reject là contract revert.

## 5. Artifact cần tạo khi triển khai

- `docs/PHASE3_INTEGRATION.md`: kiến trúc tích hợp, mapping module và cấu hình.
- `docs/PHASE3_RUNBOOK.md`: hướng dẫn cài, chạy, giới hạn và demo.
- `tests/e2e/`: API, local EVM, approval, UI smoke và Sepolia smoke tách profile.
- `eval/e2e_dataset.jsonl`, `eval/e2e_safety.jsonl`, `eval/e2e_lock.json`: dữ liệu và khóa đánh giá mới.
- `scripts/run_phase3.py` (hoặc runner tương đương): cấu hình rõ, mặc định không gửi Sepolia; explicit flag + config ngân sách cho live-write.
- `eval/phase3/<run_id>/`: results JSON/CSV, latency samples, tx evidence, runtime metadata; không chứa secrets, URL RPC có key hoặc private reasoning.
- `docs/PHASE3_RESULTS.md`: bảng kết quả và liên kết bằng chứng; để trống kết quả chưa chạy.

## 6. Phân công phối hợp

| Người | Phần cần phối hợp |
|---|---|
| Việt / trợ lý thực thi được ủy quyền | RAG adapter, test plan/harness, eval, evidence và báo cáo |
| Thái | AgentService/LLM, mapping tool, policy Agent; xác nhận module ai-agent cần đưa vào bản tích hợp |
| Bắc | Deployment/RPC, signer/nonce/gas, preflight và receipt |
| Nam | API lifecycle/approval/session và UI timeline/citation |

Không tự nhắn thành viên khác. Các chỉnh sửa tích hợp thực hiện trên nhánh riêng sau khi người dùng duyệt phạm vi dưới đây.

## 7. Gói quyền và đầu vào đề xuất — duyệt cùng một lần

### Quyền cần để hoàn thành kế hoạch

Phạm vi Sepolia đã duyệt thực tế chỉ gồm hai fixture nêu ở G3.4 và đã tiêu thụ
hết. Các cap 12 giao dịch dưới đây là đề xuất lịch sử, chưa được cấp quyền cho
đợt mới; không được dùng chúng để tự gửi thêm giao dịch.

1. Git/code: dùng `feature/e2e-testing` từ develop đã có Agent qua PR #9, sửa các module liên quan, thêm test/tài liệu và commit local. Không push, merge remote hoặc deploy lại contract Sepolia trong gói này.
2. Runtime/mạng: cài dependency vào môi trường dự án, tải model đúng revision nếu thiếu; chạy/dừng API, Hardhat và browser test local do trợ lý tạo; truy cập registry package, model host, RPC Sepolia và explorer cần cho kiểm chứng.
3. Credentials: sử dụng RPC/API key và khóa ví test do người dùng chỉ định trong `.env` gốc local ignored; chỉ đọc để thực hiện kết nối/ký trong tiến trình; không in hoặc commit giá trị. Không tự dùng khóa Sepolia trong file này khi chưa xác nhận đó là ví test được phép. Các `.env` con đã được hợp nhất vào file gốc.
4. LLM: chọn provider/model do người dùng chỉ định, gọi API cho fixture công khai/đã lọc secret; ngân sách đề xuất tối đa 5 USD cho đợt này. Bật hard budget phía provider nếu có; runner có cap token/request và dự toán theo giá đã xác minh trước khi chạy. Nếu không kiểm soát được chi phí thì dừng gọi LLM và báo phần thiếu.
5. Sepolia write theo đợt: dùng đúng signer và ví nhận được chỉ định, tối đa 12 giao dịch; tổng phí trần 0,01 Sepolia ETH; ETH chuyển tối đa 0,0002 ETH tổng cộng và 0,0001 ETH/lần; AGNT chuyển tối đa 20 tổng cộng và 5/lần; faucet tối đa 200 AGNT tổng cộng và 100/lần. Không chuyển tài sản mainnet, đổi owner/limit, cấp allowance hoặc gọi contract khác. Cap phí kiểm tra theo worst-case trước ký và đối soát thực chi; giao dịch pending vẫn giữ ngân sách dự phòng.
6. Approval trong test: cho phép harness gửi APPROVE chỉ cho fixture hợp lệ trong whitelist/cap đã duyệt, để test đầy đủ luồng mà không hỏi lại từng giao dịch. Không vô hiệu hóa policy hay màn hình approval của sản phẩm.

### Thông tin người dùng cần trả lời kèm lần duyệt

- Đồng ý gói trên hoặc ghi rõ phần thay đổi; đặc biệt việc tích hợp nhánh ai-agent còn thiếu.
- Provider/model LLM và trần chi phí nếu khác 5 USD; tên file env/biến môi trường đã chứa key (không gửi secret trong chat).
- Public address ví ký và ví nhận Sepolia; vị trí env chứa RPC và private key ví test. Xác nhận ví test có gas, và cap giao dịch ở trên hoặc cap thay thế.

Mẫu trả lời:

> Đồng ý G3.0–G3.6 và gói quyền mục 7, gồm tích hợp origin/ai-agent. LLM: [provider/model], ngân sách [5 USD hoặc khác], key tại [file env/tên biến]. Ví ký: [public address], ví nhận: [public address], RPC/khóa test tại [file env/tên biến]. Đồng ý các cap Sepolia đề xuất [hoặc sửa cap].

Đây là ủy quyền phạm vi công việc, không phải quyền administrator hay quyền không giới hạn. Sandbox hiện bảo vệ `.git` và một số thao tác mạng/chạy tiến trình; vì vậy lần pull đã cần hộp thoại cấp quyền Git. Một câu duyệt trong chat không tự thay cấu hình sandbox: hệ thống vẫn có thể yêu cầu xác nhận kỹ thuật cho lệnh cụ thể. Trợ lý sẽ gom các lệnh liên quan khi có thể, không yêu cầu người dùng tắt bảo vệ toàn máy.
