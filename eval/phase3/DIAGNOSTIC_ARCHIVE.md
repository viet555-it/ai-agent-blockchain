# Archive chẩn đoán trước baseline cuối

Hai lượt dưới đây được bổ sung theo yêu cầu commit các file còn lại sau bàn
giao. Giữ nguyên kết quả, kể cả lỗi; không thay evidence baseline hoặc dùng
chúng để nâng điểm Gemini. Cả hai chạy FakeLLM, `generation_requests=0`.

| Thư mục | Nội dung / giới hạn |
|---|---|
| `20261027T112838Z-fake-dev/` | Lượt harness hoàn tất, 30 dev và 20 safety có script. Được thay bằng lượt `20261027T113547Z-fake-dev/` trong báo cáo hạ tầng; không phải accuracy model thật. |
| `20261027T114229Z-fake-dev/` | Lượt preview có trạng thái `INFRASTRUCTURE_FAILURE`: lưu được 30 dev và 2 safety. Không coi là hoàn tất bộ safety. |

`payload-preview.jsonl` có 52 payload dựng local theo định dạng Gemini từ prompt
test, context corpus dự án và kết quả fixture Hardhat. Trường `model` chỉ tên
model dự kiến; các payload này không phải bằng chứng đã gửi Google hoặc model
đã trả lời. File không chứa thought/signature của provider, approval/session ID,
key thật từ root env hoặc raw signed transaction theo kiểm tra trước commit.

Baseline được báo cáo tại [PHASE3_G35_REPORT.md](../../docs/PHASE3_G35_REPORT.md),
hồi quy code sau sửa tại [PHASE3_POST_G35_FIXES.md](../../docs/PHASE3_POST_G35_FIXES.md).
Không gộp các run cũ/lỗi/preview thành mẫu holdout mới hoặc loại lỗi để cải thiện
số liệu. Các ledger/runtime files trong `.phase3/` vẫn giữ local và không thuộc
archive này.
