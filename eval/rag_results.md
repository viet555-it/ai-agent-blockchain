# P7 — Kết quả đánh giá retrieval

Ngày chạy: 22/10/2026. Bộ đánh giá cục bộ có 40 câu, chia 20 dev và 20 holdout. Embedding/Chroma thật; k=5. **Đạt các mục tiêu P7 trên bộ này**: holdout Recall@5 100%, no-match 6/6, không có chunk sai scope và warm p95 dưới 500 ms. Toàn bộ **54 tests pass**, không skip.

## Kết quả

| Chỉ số | Dev trước cải tiến | Dev đã khóa | Holdout lần đầu |
|---|---:|---:|---:|
| Câu có đáp án | 14 | 14 | 14 |
| Recall@5 theo gold chunk | 73,21% | 92,86% | 100% |
| Hit@5 theo gold doc | 100% | 100% | 100% |
| No-match đúng | 6/6 | 6/6 | 6/6 |
| Chunk sai scope | 0 | 0 | 0 |
| Lỗi retrieval | 0 | 0 | 0 |
| Warm p50, 100 query | 37,49 ms | 27,45 ms | 60,98 ms |
| Warm p95, 100 query | 48,80 ms | 56,78 ms | 88,46 ms |

Trong mỗi split: 6 ABI, 4 đơn vị/Web3, 4 hành vi source, 3 sai scope/version, 3 ngoài corpus (gồm một overload không có). Các câu source được chạy trong SourceScope; ABI trong DeploymentScope. No-match 6/6 gồm 3 sai scope và 3 ngoài corpus, không phải 6 câu tự nhiên ngoài lĩnh vực.

Holdout theo nhóm: ABI 6/6, Web3 4/4, source 4/4 có Recall@5=100%; ba ca scope và ba ca ngoài corpus đều trả rỗng. Chi tiết từng câu, score, chunk IDs và latency có trong báo cáo JSON.

## Phương pháp và nguồn chuẩn

`rag_dataset.jsonl` giữ query, split, nhóm ý định, scope/overrides, gold doc IDs, gold chunk IDs, kỳ vọng trả rỗng và lý do gắn nhãn. `rag_gold_catalog.json` giữ nguyên nội dung/metadata của 47 gold chunks để review. Gold được chọn từ ABI/guide hoặc các cụm bằng chứng trong source, trước khi chạy retrieval; không lấy kết quả top-k làm gold.

Recall@5 của một câu có đáp án = số gold chunk IDs xuất hiện trong top-5 / tổng gold chunk IDs của câu đó. Báo cáo lấy trung bình trên 14 câu có đáp án, không thêm các câu no-match vào mẫu số. Hit@5 chỉ cần có một gold doc nên được báo riêng. Nhãn gold là tập bằng chứng được chọn, chưa phải danh sách exhaustive của mọi đoạn có thể liên quan. Một mục ABI có thể có nhiều fragment và bản diễn giải cùng được gắn nhãn.

Các ý đã dùng ở P5/P6 như transfer, decimals, faucet limit/cooldown, source allowance self-spending và các câu calibration được giữ ở dev. Holdout dùng các ý khác như name/symbol/owner, native coin so với token, gas, zero transfer, unlimited allowance và ownership. Đây là chia theo ý định trong cùng corpus nhỏ, do cùng quy trình xây dựng; không phải bộ test bên ngoài hay thử nghiệm mù độc lập.

`rag_eval_lock.json` khóa hash dataset, gold catalog, config, source manifest, runtime retriever/evaluator, model identity và index fingerprint trước khi chạy holdout. Evaluator từ chối input/runtime/index bị thay đổi; holdout yêu cầu báo cáo dev cùng lock. Giữ báo cáo baseline và lịch sử sửa cấu hình dev. Một nhãn sai ABI hash thiếu tiền tố `sha256:` được sửa trong bước kiểm tra schema trước mọi lần chạy holdout; không đổi gold evidence theo output.

## Điều chỉnh chỉ dùng dev

Baseline tìm đúng tài liệu nhưng bỏ sót fragment chứa dữ kiện: chỉ lấy hai đoạn mỗi parent, trong khi cùng một mục có nhiều đoạn liên tiếp. Đã bật `parent_context=true` và tăng `max_per_parent` từ 2 lên 5 trong config query, giữ min_similarity=0.45 và context budget=1024 encoder tokens. Không đổi corpus, model hoặc embedding index.

Khi có seed đúng scope vượt ngưỡng (hoặc lookup interface trực tiếp), retriever bổ sung các fragment cùng parent, vẫn bị giới hạn bởi k, scope, category allowlist, dedup và context budget. Parent được xếp theo seed, fragment trong parent theo cosine. Đoạn bổ sung dưới ngưỡng được ghi `selection_reason=parent_context`, `threshold_applied=false`; score giữ cosine thật. Mở rộng không tạo kết quả khi không có seed phù hợp. Test Chroma kiểm tra score không bị tăng, không mượn sibling sai scope, và budget/no-match vẫn có hiệu lực.

Dev sau cải tiến đạt 92,86%. Câu `dev-16` (“Do I sign and broadcast during an eth_call simulation?”) vẫn tìm đúng tài liệu simulation nhưng chưa lấy đúng fragment nói không ký/broadcast. Giữ nguyên lỗi này trong báo cáo; không sửa nhãn để tăng điểm. Sau đó khóa và chạy holdout một lần, không điều chỉnh theo kết quả holdout.

## Đo thời gian và môi trường

Windows 11 build 26200; CPU Intel64 Family 6 Model 186 Stepping 2, 12 logical CPUs; Python 3.12.10; inference CPU, 2 threads. Model `paraphrase-multilingual-MiniLM-L12-v2`, revision `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`, vector 384 chiều, giới hạn encoder 128 tokens. Corpus index gồm 159 chunks từ 9 nguồn.

Dev khởi tạo 17,19 giây, truy xuất đầu 55,19 ms. Holdout khởi tạo 20,20 giây, truy xuất đầu 115,43 ms. Khởi tạo tính cả import/model/index và kiểm tra gold trước query; model đã cached, OS cache có thể đã ấm. Đây không phải thời gian tải/cài model lần đầu hoặc phép đo disk cold cache có kiểm soát.

Mỗi split đo 100 query tuần tự bằng cách lặp 20 câu 5 lần sau vòng đánh giá accuracy, tái sử dụng model và các instance scope. Có cả lookup, semantic, no-match và scope rỗng. p50/p95 dùng nearest rank; JSON giữ đủ 100 mẫu. Không phải thử tải concurrency hoặc đo riêng semantic-only. Chênh lệch giữa các lần chạy chịu ảnh hưởng của hệ thống; không kết luận cải tiến làm inference nhanh hơn chỉ từ bảng này.

## Chạy lại

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests/rag -v
.venv/Scripts/python.exe -m eval.run_rag_eval --split dev
.venv/Scripts/python.exe -m eval.run_rag_eval --split holdout
```

Hai lệnh eval ghi `rag_results_dev.json` và `rag_results_holdout.json`; exit 0 nếu đạt tất cả gates, exit 1 nếu có gate không đạt. Các gate gồm Recall@5 ≥90%, no-match đúng toàn bộ mẫu, không sai scope, không lỗi và warm p95 ≤500 ms. Lần chạy lại không còn là holdout mới cho việc hiệu chỉnh; muốn phát triển tiếp cần thêm bộ holdout mới.

`scripts/prepare_rag_eval.py` là công cụ tạo benchmark từ quy tắc gắn nhãn đã review; từ chối ghi đè bộ đã khóa. Không chạy lại để thay nhãn sau khi xem output. Kết quả ở đây áp dụng cho cấu hình có parent context; báo cáo baseline giữ lại để đối chiếu thay đổi trên dev.

Artifacts: `rag_results_dev_baseline.json`, `rag_results_dev.json`, `rag_results_holdout.json`, `rag_eval_lock.json`, `rag_dataset.jsonl`, `rag_gold_catalog.json`.

Kết quả chỉ đánh giá tìm đoạn trong corpus hiện tại. Chưa chứng minh chất lượng sinh câu trả lời LLM, tool selection, policy chung, hoặc trạng thái contract on-chain. Hướng dẫn sử dụng tại `docs/RAG_SETUP.md` và `docs/RAG_HANDOFF.md`.
