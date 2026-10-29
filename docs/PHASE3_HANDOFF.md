# Bàn giao giai đoạn 3 để nhóm kiểm thử

Backend/Agent tích hợp tại [`d190139`](https://github.com/viet555-it/ai-agent-blockchain/commit/d190139d68d97f536103ba094387e9c0000338be).
Nhánh `feature/e2e-testing` sau đó tích hợp frontend theme/EN–VI/timeline từ
develop `491ebc5` và xử lý conflict theo [báo cáo merge](PHASE3_CONFLICT_RESOLUTION.md).
[PR #11](https://github.com/viet555-it/ai-agent-blockchain/pull/11) đã mở lại và
đổi đích sang develop theo xác nhận của người dùng; chưa merge PR vào develop/main.

Ứng dụng local đã tích hợp AgentService, Gemini, RAG, policy, proposal/approval
và receipt. Có thể bàn giao để thử sản phẩm; **chưa nghiệm thu hết gate giai
đoạn 3**. Đặc biệt, code sau sửa chưa có holdout mới và chưa chứng minh p95
READ/prepare ≤10 giây. Đây không phải bản phát hành production.

## Bắt đầu từ đâu

| Việc cần làm | Tài liệu / evidence |
|---|---|
| Cài và chạy từ checkout mới | Mục tiếp theo và [runbook](PHASE3_RUNBOOK.md) |
| Trình diễn cho nhóm | [Kịch bản demo](PHASE3_DEMO.md) |
| Xem phần đã thay đổi | [Tổng hợp commit](PHASE3_COMMIT_SUMMARY.md) |
| Xem baseline trước sửa | [G3.5](PHASE3_G35_REPORT.md) |
| Xem lỗi đã sửa và giới hạn kết luận | [Hồi quy sau G3.5](PHASE3_POST_G35_FIXES.md) |
| Kiểm phiên bản, Git SHA và hash file | [Handoff manifest](evidence/phase3/handoff-manifest-20261027.json) |
| Kiểm hai giao dịch Sepolia lịch sử | [Evidence đã lọc](evidence/phase3/sepolia-20261027.json) |
| Kiểm corpus/tokenizer cho bàn giao | [RAG dry-run](evidence/phase3/rag-dry-run-20261027.json) |

## Cài từ checkout mới trên Windows

Môi trường đã dùng: Windows x64, Python **3.12.10**, Node **22.20.0**. Các lệnh
dưới đây dành cho PowerShell tại repository root. Đây là quy trình tái lập từ
source/lock; chưa được chạy cài mới toàn bộ trên một máy sạch trong đợt bàn giao.
Không tạo lại môi trường hoặc chép đè `.env` của máy đã cấu hình.

```powershell
# Sau khi clone repository, chọn đúng nhánh đã bàn giao:
git switch feature/e2e-testing
python --version
node --version

python -m venv .venv-phase3
.venv-phase3/Scripts/python.exe -m pip install -r requirements.txt
.venv-phase3/Scripts/python.exe -m pip check

# Chỉ chạy lần đầu khi checkout chưa có .env:
Copy-Item .env.example .env

Push-Location contracts
npm ci
npm run compile
Pop-Location
```

Sửa `.env` duy nhất ở root: điền `GEMINI_API_KEY`, giữ model được nhóm chọn
(`gemini-3.5-flash-lite` trong bản đã kiểm), `PHASE3_PROFILE=local_evm`,
`PHASE3_AGENT=llm`, `PHASE3_LOCAL_WRITES=true`,
`LOCAL_RPC_URL=http://127.0.0.1:8545`, `TIKTOKEN_CACHE_DIR=.phase3/tiktoken`.
Demo local không cần private key. Biến đã đặt trong terminal được ưu tiên hơn
file; dùng terminal mới nếu còn override từ lần chạy khác. Không gửi key vào chat.

Tải model embedding được pin và dựng index local; việc này cần mạng lần đầu:

```powershell
.venv-phase3/Scripts/python.exe -m scripts.ingest_rag --verify-git --allow-download
.venv-phase3/Scripts/python.exe -c "from config.environment import load_project_env; load_project_env(); import tiktoken; tiktoken.get_encoding('cl100k_base'); print('tokenizer cached')"
```

Không đổi embedding revision/corpus/config để làm kiểm tra pass. Nếu clone thiếu
commit nguồn contract mà `--verify-git` yêu cầu, bổ sung lịch sử từ remote dự án
theo [RAG_SETUP.md](RAG_SETUP.md). Lần sau có cache dùng ingest không có
`--allow-download`. Corpus hiện có 9 tài liệu / 159 chunk, tối đa 128 token/chunk.
Handoff đã kiểm dry-run với model cache thật và `--verify-git`, không ghi index.

Sau đó mở hai terminal theo [runbook](PHASE3_RUNBOOK.md): terminal 1 chạy node
Hardhat loopback; terminal 2 chạy setup local rồi API. Mở
[http://127.0.0.1:8000](http://127.0.0.1:8000). Chain phải là **31337**, không phải
Sepolia. Chạy lại setup sau mỗi lần reset node; giữ node đang dùng nếu muốn giữ
deployment/số dư. Không restart backend để thử lại giao dịch đang UNKNOWN.

## Kiểm thử trước khi trình diễn

```powershell
.venv-phase3/Scripts/python.exe -m scripts.run_phase3 --suite unit
.venv-phase3/Scripts/python.exe -m scripts.run_phase3 --suite local_evm
```

Các lệnh dùng FakeLLM, xóa credentials trong tiến trình con và không gọi Gemini/
Sepolia. FakeLLM kiểm wiring/hành vi có kịch bản, không thay phép đo model thật.
Runner ghi đè log/summary cùng suite trong `.phase3/`; giữ bản cũ nếu cần đối soát.
Không dùng `--suite all` chỉ để trình diễn nếu không cần chạy lại các suite khác.

Kết quả sau xử lý conflict: **274 unit PASS + 70 subtest PASS**, **136 API/EVM PASS**.
`pip check` trong môi trường tích hợp đạt. Suite RAG 54/contract 34 là kết quả
trước đó; không chạy lại hai suite này trong đợt sửa cuối. Không cộng các runner
có test trùng thành một tổng test độc lập.

## Các bằng chứng và giới hạn

- Gemini baseline: dev 29/30, holdout 28/30, safety 20/20. Baseline tool accuracy
  đạt 93,3% holdout; full success 100% và latency p95 10 s chưa đạt.
- Code sau sửa: lượt ca trọng điểm 9/10 (HTTP 504 giữ nguyên), lượt transaction
  riêng 2/2. Đây là các câu đã quan sát, không phải holdout mới.
- Browser sau merge frontend đạt 13/13 với API fixture, không lỗi JavaScript;
  đây là kiểm giao diện, không phải lượt Gemini/on-chain mới. Six-case browser
  smoke với model/RPC thật trước các sửa cuối đã đạt 6/6. Checklist demo đầy đủ
  vẫn cần người trình diễn chạy với runtime và model của mình.
- Hai giao dịch Sepolia đã có receipt status=1/event/balance đúng, nhưng smoke
  dùng FakeLLM có script với RAG/RPC thật. Không tính là accuracy Gemini hoặc
  demo UI ký Sepolia bằng người.
- Grant Sepolia đã tiêu thụ hết. Evidence công khai là lịch sử; số confirmation
  là số quan sát lúc kiểm, không phải xác nhận lại trạng thái chain hiện tại.
- Budget Gemini lũy kế **151/200**: dev 61/75, safety 42/50, holdout 48/75.
  Bước bàn giao không gọi thêm Gemini/RPC Sepolia. Sổ `.phase3/` giữ local;
  một checkout mới không kế thừa ngân sách hay quyền dùng key của máy này.
- Approval/session lưu RAM và session ID không phải đăng nhập. Demo dành cho
  local một người; chưa mở thành dịch vụ public nhiều người dùng.

Không dùng lock G3.5 cũ để chạy code mới. Source, dataset, config và model phải
được khóa cho một vòng đánh giá mới; bộ holdout đã xem chỉ còn dùng chẩn đoán/
hồi quy. Không xóa ledger để tăng quota hoặc cấp lại grant giao dịch.

## Trạng thái G3.6 và phần tiếp theo

| Mục | Trạng thái |
|---|---|
| Báo cáo lỗi trước/sau và test hồi quy | Có báo cáo và evidence |
| Hướng dẫn cài/chạy từ checkout mới | Đã viết; pip check/RAG dry-run đã kiểm trên máy hiện tại; chưa cài lại máy sạch |
| Kịch bản demo | Đã chuẩn bị với expected/stop conditions; chờ người trình diễn chạy checklist |
| Metadata và evidence có thể chia sẻ | Có manifest source SHA/versions/hashes và Sepolia summary đã lọc |
| Commit/push bản tích hợp | d190139 đã push lên feature/e2e-testing |
| PR / merge / nghiệm thu toàn giai đoạn | PR #11 nhắm develop; chưa merge PR, còn gate mở |

Nhóm có thể review và kiểm thử trên nhánh feature. Trước khi nhận là bản hoàn
thiện, cần chốt bộ holdout chưa dùng cho code hiện tại và ngân sách mới phù hợp,
đo lại latency theo stage, chạy checklist UI, rồi mới quyết định merge. Bàn giao
tài liệu không tự mở quyền gửi thêm Sepolia, đổi model hoặc tăng request cap.
