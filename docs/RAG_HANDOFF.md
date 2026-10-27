# Bàn giao module RAG cá nhân

Cập nhật 23/10/2026, branch `feature/rag_context`. Module độc lập nhận query và trả các đoạn liên quan có nguồn, scope/version và score. [Hướng dẫn cài và chạy](RAG_SETUP.md). Công việc tích hợp agent/API/UI thuộc bước tiếp theo của nhóm; không phải điều kiện để chạy module này.

## Interface và vòng đời

```python
import asyncio
from pathlib import Path

from rag.retriever import (
    RAGRetriever, RetrievalOptions, SourceScope,
    InvalidQuery, RetrievalUnavailable, RetrievalTimeout,
)

async def main():
    async with await RAGRetriever.create(root=Path.cwd()) as retriever:
        chunks = await retriever.retrieve("transfer(address,uint256)", k=5)
        for chunk in chunks:
            print(chunk["content"])
            print(chunk["metadata"]["source_path"], chunk["score"])

asyncio.run(main())
```

`root` phải trỏ tới repo chứa config/corpus/index. Ví dụ chạy nguyên file ở `examples/rag_retrieve.py` tự tính root từ vị trí file. Factory mặc định load offline, đọc config và kiểm index khớp model/manifest. Khởi tạo một lần cho mỗi vòng đời/scope, tái sử dụng trong cùng event loop; không load lại model cho từng query. Async context manager gọi `aclose()` khi xong. Khi đã ở event loop của ứng dụng, gọi `await`, không thêm `asyncio.run` lồng nhau.

Chữ ký công khai: `async retrieve(query: str, k: int = 5) -> list[Chunk]`. Query không rỗng, tối đa 2000 ký tự và 128 token encoder; k là integer 1–10. Constructor cũng cho phép inject provider/store/scope/options; khi tự inject cần tự quản lý tài nguyên và pin `expected_manifest_hash` để phát hiện corpus stale. `RetrievalOptions()` dùng default của class (parent_context=false/max_per_parent=2); **factory không truyền options đọc config hiện tại** với parent_context=true/max_per_parent=5. Khi override options, truyền một bộ đầy đủ theo ý định vì nó thay toàn bộ options config.

Model/tokenizer/Chroma chạy qua worker thread, mặc định một query đang xử lý trên mỗi instance. Timeout 15 giây tính cả chờ slot/query, không tính factory startup. Cancel/timeout không giết native inference đang chạy; slot chỉ được nhả khi worker kết thúc. `aclose` ngừng nhận query, không bảo đảm dừng ngay inference đang chạy hoặc giải phóng mọi cache PyTorch.

## Schema kết quả

`Chunk` là TypedDict trong `rag/models.py`; `Retriever` là Protocol tương thích interface ở branch agent:

```python
{
    "content": str,
    "metadata": dict,
    "score": float,
}
```

| Metadata | Ý nghĩa |
|---|---|
| chunk_id, parent_id, doc_id, title, category | Định danh đoạn, mục cha và tài liệu |
| source_path, source_origin, source_commit | Nguồn Git hoặc workspace; workspace chưa commit giữ null |
| content_hash, chunk_hash, derived_from | Hash nguồn/đoạn và bằng chứng dẫn xuất khi có |
| scope, doc_version, verification_status, usage | Phạm vi, phiên bản, mức xác minh và quyền ingest |
| chain_id, contract_address, abi_hash | Ràng buộc deployment khi áp dụng |
| function_signature hoặc function_signatures_json | Signature ABI khi đoạn có interface tương ứng |
| score_metric, selection_reason, threshold_applied | Ý nghĩa score và cách chọn |
| index_collection, index_fingerprint, retrieval_config_hash | Phiên bản dữ liệu và cấu hình query |
| context_budget_unit, context_max_tokens, context_tokens_total | Đơn vị/giới hạn context thực tế |

Không phải mọi field tùy chọn đều có ở mọi scope. `source_commit=null` không có nghĩa không có nguồn: tài liệu khai báo workspace có hash và bằng chứng dẫn xuất; không đổi null thành một commit cũ giả. Provenance nested được giữ đầy đủ trong DB qua record_json và khôi phục ở retriever. Mẫu kết quả thật xem `docs/examples/rag_p8_handoff_check.json`; fixture trong tests chỉ minh họa shape, score fixture không phải phép đo.

Score là **cosine similarity [-1,1]**, không phải confidence hay xác suất đúng. Ngưỡng prose hiện 0.45. Lookup đúng full signature/bare symbol có thể dưới ngưỡng. Config P7 còn bổ sung fragment cùng parent của một seed phù hợp; fragment dưới ngưỡng ghi `selection_reason=parent_context`, `threshold_applied=false`. Score không bị tăng giả. Nhóm parent/signature được ưu tiên nên danh sách không nhất thiết giảm dần cosine toàn cục.

Kết quả tối đa k, loại trùng nội dung, tối đa 5 đoạn cùng parent theo config hiện tại, context tối đa 1024 **encoder tokens** trên nội dung ghép. Không cắt một chunk để nhét vừa. Agent tích hợp cần đếm lại bằng tokenizer LLM, cộng header/citation và system prompt; 1024 encoder tokens không đồng nghĩa 1024 LLM tokens.

## Scope và lỗi

Deployment mặc định lấy nguyên từ `knowledge/manifest.json`: chain **11155111**, address **0xa453B71a492558C17efA82E294739e4eFef3C220**, version `repo-28a9a0b6a96f`, ABI hash `sha256:2b3ca413594b0ed56a5271910b3c98028ea2a2ceed8bd8ffe34ea357e6c90497`. Nguồn được xác minh trong repository, chưa đối chiếu RPC/bytecode live. Address cũ trong README không thuộc scope này.

Lọc chain/address/ABI hash/version trước ANN; mở rộng parent cũng chỉ trong tập được phép. Query text không thể thay scope bất biến. General chỉ được thêm khi include_general=true và category nằm trong allowlist `web3`. Policy snapshot hiện reference-only, không được dùng làm policy chung.

Đọc hành vi source bằng instance riêng:

```python
async with await RAGRetriever.create(
    root=Path.cwd(),
    scope=SourceScope("source-28a9a0b6a96f", include_general=True),
) as source_retriever:
    chunks = await source_retriever.retrieve("Theo source faucet có giới hạn gì?")
```

SourceScope nhận source_only cùng version và general được phép; không mượn ABI deployment. Nếu mở rộng nhiều contract, cần thiết kế phạm vi source rõ hơn, không coi mọi source cùng tên version là cùng contract. Muốn query một deployment khác, tạo DeploymentScope mới và corpus được duyệt cho scope đó; không đổi address của instance đang phục vụ request.

| Kết quả API | Caller nên làm |
|---|---|
| `[]` | Không có đoạn phù hợp trong scope/budget; diễn đạt thiếu nguồn, không lấy tài liệu đầu danh sách |
| `InvalidQuery` | Yêu cầu input ngắn/hợp lệ hơn |
| `RetrievalUnavailable` | Báo lỗi dữ liệu/model/index; kiểm setup/provenance, không coi là không có kiến thức |
| `RetrievalTimeout` | Báo truy xuất quá hạn; quản lý retry có giới hạn theo ứng dụng |

CLI có mã 0 thành công, 3 no-match, 2 input sai, 4 unavailable, 5 timeout, 130 hủy, 1 lỗi chưa phân loại. Nội dung truy xuất là dữ liệu tham khảo; không phải lệnh cho agent, quyền WRITE, xác nhận người dùng hoặc kết luận state hiện tại.

## Phiên bản và bằng chứng bàn giao

| Thành phần | Bản đang bàn giao |
|---|---|
| Corpus | Manifest schema 2; 11 nguồn, 9 ingest, 2 reference-only; 8 tài liệu Markdown |
| Artifact contract gốc | Commit 28a9a0b6a96f6cbd59cb2ceea264c4d4d562f1d8 |
| Doc versions | repo-28a9a0b6a96f / source-28a9a0b6a96f / rag-p2-v1 |
| Splitter | rag-semantic-v2, compact prefix, tối đa 128 token mỗi đoạn |
| Model | paraphrase-multilingual-MiniLM-L12-v2 @ e8f8c211226b894fcb81acc59f3b34ba3efd5f42 |
| Vector/index | CPU normalized float32, 384 chiều, Chroma 1.5.9 cosine; 159 chunks |
| Index fingerprint | sha256:fac5405f38d38b19252b95d5b91021dc509a8d9357aaf82e6145afa5a2152e8f |
| Runtime config | min_similarity=.45, candidate_pool=32, parent_context=true, max_per_parent=5, context_max_tokens=1024, timeout=15s, max_concurrency=1 |

Fingerprint nội dung ổn định khi rebuild đúng đầu vào; UUID collection và thời điểm build có thể khác. Lockfile dependency, config, corpus, source manifest và evaluator lock phải đi cùng phiên bản code. Tài liệu dẫn xuất vẫn khai báo source_origin=workspace với source_commit=null và hash/bằng chứng tương ứng; commit bàn giao không tự đổi provenance hoặc fingerprint đã đánh giá.

P7 có 54 tests pass, 40 câu chia 20 dev/20 holdout. Holdout lần đầu Recall@5 100% trên 14 câu có đáp án; no-match đúng 6/6; không chunk sai scope; warm p95 88,46 ms trên 100 query tuần tự. Dev còn một câu chưa lấy đúng fragment ký/broadcast. Xem [báo cáo đầy đủ](../eval/rag_results.md) để biết gold labels, mẫu nhỏ, cách tính và giới hạn. Không diễn giải các số này thành chất lượng trả lời LLM hay độ chính xác trên mọi câu hỏi.

Kiểm tra P8 ngày 23/10/2026 tại `docs/examples/rag_p8_handoff_check.json` pass 7/7 bước, dựng lại đúng fingerprint với 9 nguồn/159 chunks, ingest lặp giữ collection, chạy CLI deployment/source/no-match/text và ví dụ async thành công. Index tạm được dọn, active pointer gốc không đổi; 54 tests pass lại và pip check sạch. Dùng cache model/môi trường đã cài; không phải một lần cài môi trường mới từ mạng hoặc một holdout mới. Hướng dẫn tái lập nằm trong setup.

## Giới hạn tích hợp

Module chưa nối agent/API/UI, chưa hợp nhất policy, chưa sinh câu trả lời LLM hoặc ký/gửi transaction. Khi tích hợp, bên gọi quản lý lifecycle và scope, kiểm lại context theo tokenizer LLM, hiển thị citation và xử lý no-match/lỗi theo interface trên. Kiểm chứng deployment/RPC và thực thi giao dịch thuộc lớp ứng dụng.

Danh sách bàn giao: `rag/`, `knowledge/`, `config/rag.json`, `scripts/`, `examples/`, `tests/rag/`, `eval/`, hai requirements RAG và tài liệu/báo cáo liên quan. `.venv`, cache model và DB không đưa vào Git. Người nhận bắt đầu từ RAG_SETUP, chạy ingest/query/test trước khi nối sản phẩm.
