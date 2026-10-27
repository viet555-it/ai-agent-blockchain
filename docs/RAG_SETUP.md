# Cài đặt và vận hành RAG độc lập

Cập nhật 23/10/2026. Bắt đầu tại đây nếu bạn nhận module lần đầu; xem [hợp đồng bàn giao](RAG_HANDOFF.md) khi tích hợp Python. Môi trường đã kiểm tra: **Windows x64, Python 3.12.10, CPU**. Không cần backend, API key, ví, RPC, LLM hoặc Node để chạy RAG. Dependency backend không được thay đổi.

## 1. Cài môi trường riêng

Mở PowerShell tại thư mục gốc repository. Giữ `config/rag.json`, `requirements-rag.lock.txt`, corpus và code đi cùng nhau. Nếu chưa có `.venv`, dùng Python 3.12:

```powershell
python --version
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-rag.lock.txt
.venv/Scripts/python.exe -m pip check
```

`python --version` phải là 3.12.x; nếu máy có nhiều Python, chọn executable 3.12 để tạo môi trường. Không tạo lại `.venv` đang dùng chỉ để chạy các lệnh tiếp theo. Gọi trực tiếp executable như ví dụ nên không cần activate hoặc đổi PowerShell execution policy.

Lockfile giữ 104 phiên bản package của môi trường đã kiểm tra, gồm PyTorch CPU, Sentence Transformers và Chroma. Cài dependency lần đầu cần mạng hoặc wheel cache thích hợp. Chưa xác nhận lockfile này trên mọi OS/Python khác. P8 kiểm tra lại `pip check` trên môi trường đã cài, không cài lại từ đầu qua mạng.

## 2. Tải model đúng revision và tạo index

```powershell
# Lần đầu: cho phép tải đúng model revision trong config rồi ingest.
.venv/Scripts/python.exe -m scripts.ingest_rag --verify-git --allow-download

# Những lần sau mặc định dùng cache offline:
.venv/Scripts/python.exe -m scripts.ingest_rag --verify-git
```

Model `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, revision `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`. Không thay revision sang latest. Model cache ở `.cache/rag/huggingface`; index ở `data/rag`. Snapshot đã đo khoảng 500 MB; smoke trước đây dùng khoảng 1,3 GB RSS, có thể khác theo môi trường. Lần tải đầu cần mạng; query không tự tải model.

`--verify-git` kiểm bằng chứng commit objects có sẵn tại `28a9a0b6a96f6cbd59cb2ceea264c4d4d562f1d8`, không tự fetch GitHub. Nếu clone thiếu lịch sử này, tải commit/branch contract tương ứng từ remote của dự án rồi chạy lại. Không bỏ pin nguồn để làm kiểm tra pass.

Kết quả lần đầu có `status: built`, `doc_count: 9`, `chunk_count: 159`, `max_chunk_tokens: 128`. Chạy lại cùng corpus/model/config chia đoạn phải có `status: unchanged`, giữ collection. Tên collection được sinh mới cho mỗi lần build; dấu vân tay nội dung mới là căn cứ đối chiếu.

Có thể chỉ kiểm corpus và chia đoạn, chưa ghi DB:

```powershell
.venv/Scripts/python.exe -m scripts.ingest_rag --dry-run --verify-git
```

Lệnh dry-run vẫn cần model cached/tokenizer. Công cụ tùy chọn `scripts.prepare_rag_model` tải model và ghi báo cáo smoke P4; nó có thể ghi lại config/report, nên không cần chạy công cụ đó cho luồng cài đặt trên.

## 3. Query và kiểm kết quả

```powershell
.venv/Scripts/python.exe -m scripts.query_rag --query "transfer(address,uint256)" --k 3
.venv/Scripts/python.exe -m scripts.query_rag --query "decimals()" --json
.venv/Scripts/python.exe -m scripts.query_rag --scope source --query "Theo source faucet có giới hạn bao nhiêu và chờ bao lâu?" --json
.venv/Scripts/python.exe -m scripts.query_rag --query "Cách nấu phở bò ngon" --json
.venv/Scripts/python.exe -m examples.rag_retrieve
```

Query cuối ngoài corpus có `status: no_match`, `results: []`, **exit code 3**; đây là kết quả dự kiến. Ví dụ Python trả danh sách chunks JSON, dùng async context manager để đóng retriever. Text giữ tiếng Việt, nguồn/version, score và thời gian; JSON dành cho caller. Log tiến trình thư viện có thể xuất hiện trên stderr; stdout JSON của query là một object.

Default scope là deployment được manifest ghi nhận. Câu hỏi điều kiện hành vi source phải chọn `--scope source`; nguồn repo không chứng minh contract live có cùng hành vi. Query getter chỉ tìm interface trong corpus, không đọc giá trị runtime. Xem toàn bộ cờ bằng `.venv/Scripts/python.exe -m scripts.query_rag --help`; scope và exit codes được mô tả trong [hợp đồng bàn giao](RAG_HANDOFF.md).

## 4. Kiểm thử và tái lập

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests/rag -v
.venv/Scripts/python.exe -m scripts.verify_rag_handoff
```

Suite hiện có 54 tests. Kiểm tra bàn giao tạo index **trống mới** trong thư mục tạm dưới `data/rag`, ingest thật, kiểm fingerprint/số chunk, ingest lặp và chạy query deployment/source/no-match, text CLI, ví dụ async bằng các process mới. Sau khi xong nó bỏ index tạm, kiểm active pointer gốc không đổi và lưu `docs/examples/rag_p8_handoff_check.json`. Dùng model cache hiện có; không cài dependency hoặc tải lại model. Có thể mất vài phút vì nhiều process đều load model riêng.

Đánh giá lại bộ đã khóa, nếu cần xác minh môi trường:

```powershell
.venv/Scripts/python.exe -m eval.run_rag_eval --split dev
.venv/Scripts/python.exe -m eval.run_rag_eval --split holdout
```

Các lệnh ghi đè báo cáo đo tương ứng; muốn giữ lần đo cũ, sao chép báo cáo trước. Evaluator kiểm config/runtime/corpus/model/index fingerprint theo lock P7. Không đổi lock chỉ để né lỗi mismatch, không tune trên holdout đã xem. Kết quả và phương pháp tại [báo cáo P7](../eval/rag_results.md).

## 5. Cấu hình, rebuild và rollback

`config/rag.json` là cấu hình chính. Model/revision, prefix style hoặc corpus thay đổi cần ingest/rebuild phù hợp; thay ngưỡng query/parent context không cần tính lại embedding. Khi thay đầu vào đã khóa, cần quy trình đánh giá phiên bản mới; kết quả P7 không tự áp dụng.

```powershell
# Tạo generation mới, không xóa collection đang dùng:
.venv/Scripts/python.exe -m scripts.ingest_rag --rebuild --verify-git

# Xem các generation còn được giữ:
Get-ChildItem data/rag/generations -Filter '*.json'

# Thay bằng tên generation thực từ danh sách, ví dụ rag_ + 32 ký tự hex:
# .venv/Scripts/python.exe -m scripts.ingest_rag --rollback <GENERATION>
```

Rollback kiểm manifest/count/hash trước khi đổi active pointer. Config/query provider phải khớp model identity của generation được chọn. Writer có lock; không sửa/xóa collection active hoặc xóa DB để rebuild. Nếu build lỗi, generation trước vẫn active. Chưa có tự động dọn các generation cũ.

Cấu hình `RAG_INDEX_PATH` và `RAG_CACHE_PATH` trong `.env` duy nhất ở root dự án.
RAG chỉ đọc hai đường dẫn này, không xuất API key hoặc wallet key ra môi trường.
Biến shell được ưu tiên khi cần override tạm thời:

```powershell
$env:RAG_INDEX_PATH = 'data/rag/another-index'
$env:RAG_CACHE_PATH = '.cache/rag/huggingface'
# Ingest/query trong shell này dùng các đường dẫn trên.
# Gỡ override khi không dùng nữa:
Remove-Item Env:RAG_INDEX_PATH -ErrorAction SilentlyContinue
Remove-Item Env:RAG_CACHE_PATH -ErrorAction SilentlyContinue
```

Đường dẫn tương đối được tính từ repo root. Các công cụ ingest/query và ví dụ dùng RAGSettings; `verify_rag_handoff` chủ động override index cho subprocess. Chỉ dùng thư mục cache/index tin cậy của môi trường chạy.

Khi sửa knowledge, cập nhật danh sách ingest, version, content hash và bằng chứng derived_from trong `knowledge/manifest.json`, rồi ingest và đánh giá lại. Chỉ dùng nguồn được duyệt; policy reference-only không được tự đưa vào ingest. Tài liệu khai báo source_origin=workspace giữ source_commit=null và hash/bằng chứng dẫn xuất, kể cả khi được đóng gói trong commit bàn giao; chỉ chuyển sang provenance Git khi có commit chứa đúng nội dung để đối chiếu, không gán commit source gốc cho tài liệu dẫn xuất mới.

## 6. Lỗi thường gặp

| Triệu chứng | Cách xử lý |
|---|---|
| Thiếu sentence_transformers/chromadb | Dùng `.venv/Scripts/python.exe`; cài lockfile và chạy pip check |
| Model không có trong cache | Chạy ingest với `--allow-download` một lần có mạng, kiểm RAG_CACHE_PATH |
| Index missing/stale hoặc identity mismatch | Kiểm đường dẫn override, corpus/manifest/config; ingest hoặc rebuild theo thay đổi thực |
| Hash/provenance nguồn không khớp | Review file và cập nhật manifest có căn cứ; không tắt kiểm tra hash |
| `--verify-git` không tìm thấy commit | Bổ sung commit objects từ repository nguồn rồi kiểm lại |
| Câu hỏi quá dài/quá 128 token | Rút câu hỏi; retriever không truncate im lặng |
| Không có kết quả cho faucet source | Chọn source scope/version đúng; default deployment không mượn source-only |
| `build.lock` còn sau process bị tắt | Đọc PID/trạng thái writer, chỉ xử lý lock sau khi xác nhận writer đã dừng |
| Query timeout | Phân biệt startup và query deadline; worker native có thể còn chạy sau khi caller timeout |
| Eval báo frozen input/runtime changed | So sánh thay đổi với lock, tạo phiên bản benchmark mới có chủ đích; không tái tune holdout cũ |

Trong phiên Codex Windows đã kiểm tra, asyncio/Chroma cần chạy ngoài sandbox sau khi được cấp quyền; lỗi sandbox không phải lỗi semantic của model. Trong terminal thông thường, dùng các lệnh như trên. Bắt đầu chẩn đoán bằng JSON status/exit code; đừng đổi lỗi model/index thành no-match.

Các thư mục `.venv`, `.cache/rag`, `data/rag` đã được gitignore. Bàn giao source/corpus/config/lockfile/tests/eval/docs; người nhận tự tạo cache/index theo hướng dẫn.
