# Bổ sung lịch sử vào hạn mức 24 giờ

Đã có công cụ offline để đưa các transfer cũ vào sổ hạn mức. Công cụ không gọi LLM, RPC, ký hay gửi giao dịch. Việc kiểm thử chỉ dùng SQLite tạm và chain giả; chưa áp dụng lên dữ liệu cá nhân.

## Quy tắc tính

Phạm vi hạch toán là `wallet_id + deployment_id + asset_id`. Native và từng hợp đồng ERC20 được tính riêng. Số tiền lấy từ raw base units và được đối chiếu với payload đã lưu; không làm tròn số thực hoặc suy ra từ token decimals.

| Bằng chứng đã lưu | Hành động |
| --- | --- |
| Thành công, FINALIZED, MATCHED và có thời gian block do server xác minh | `SPENT`, dùng đúng thời gian block cho cửa sổ 24 giờ |
| Revert, FINALIZED và MATCHED | `REVERTED`, giải phóng phần giá trị transfer |
| Chưa rõ trạng thái, chưa final, payload chưa khớp hoặc thiếu thời gian block xác minh | `RESERVED`, cần kiểm tra chain tiếp |
| Đã có bản ghi cùng phạm vi và số tiền | Bỏ qua; bản ghi RESERVED có thể được settle khi có đủ bằng chứng mới |
| Sai hash, sai payload hoặc xung đột với bản ghi đã có | `INVALID`; từ chối toàn bộ lần áp dụng |

Một proposal chỉ được tính một lần, kể cả có lịch sử replacement. Các attempt đã đánh dấu `REPLACED` không trở thành khoản chi riêng. Chỉ proposal transfer có attempt mới được xét; proposal chưa authorize không bị nhập như khoản chi.

Không dùng thời gian tạo proposal/receipt thay cho thời gian block. `RESERVED` không tự hết hạn sau 24 giờ. Vì vậy lịch sử thiếu bằng chứng có thể làm giảm hạn mức khả dụng cho đến khi được đối soát. Không sửa tay timestamp để giải phóng hạn mức.

Reconciler hiện lưu `_app_verified_block_timestamp` từ block canonical khi giao dịch thành công, final và khớp payload. Trường cùng tên do RPC receipt đưa vào bị loại bỏ. Receipt cũ thiếu trường này phải được đối soát lại bằng quy trình xác minh chain trước khi settle; công cụ offline không tự bổ sung bằng chứng chain.

## Xem trước

Database phải là SQLite đã tồn tại và đã chạy migration `0002_limits` trước khi áp dụng. Công cụ không tự migrate. Thay đường dẫn ví dụ bằng database cần xử lý; các lệnh bên dưới chưa được chạy trên database cá nhân.

```powershell
.venv-phase3\Scripts\python.exe -m scripts.backfill_daily_limits --database <database.db> --output .phase3/backfill-preview.json
```

Có thể thêm `--wallet-id <id>` và/hoặc `--deployment-id <id>` để giới hạn phạm vi. Preview mở database chỉ đọc trong một snapshot ổn định. JSON chứa số tiền, lý do, các proposal cần kiểm tra chain và hash bằng chứng nguồn; không xuất raw payload hay capability.

Đọc `plan.items`, `plan.counts`, `plan.requires_chain_review` và `plan.ledger_available`. Mọi mục `INVALID` phải được xử lý trước khi áp dụng. Các mục `RESERVED` có thể được nhập để giữ hạn mức một cách bảo thủ, nhưng vẫn còn việc đối soát chain.

## Áp dụng đúng preview đã xem

```powershell
.venv-phase3\Scripts\python.exe -m scripts.backfill_daily_limits --database <database.db> --apply-plan .phase3/backfill-preview.json --backup .phase3/backfill-before-01.db --output .phase3/backfill-applied.json
```

Backup bắt buộc là file mới. Công cụ lấy SQLite writer lock, so lại toàn bộ bằng chứng trong phạm vi preview, tạo backup nhất quán rồi mới nhập và ghi audit `LIMIT_BACKFILLED` trong cùng transaction. Lỗi nhập sẽ rollback cả ledger và audit. Dữ liệu thay đổi sau preview sẽ khiến thao tác bị từ chối; phải tạo và xem preview mới.

Không cần truyền lại bộ lọc khi apply: phạm vi nằm trong preview. Nếu truyền lại thì phải trùng với phạm vi đã xem. Hash phát hiện thay đổi nội dung; đây không phải chữ ký chứng thực của người duyệt.

Sau khi áp dụng, tạo preview mới để kiểm tra các mục `SKIP` và danh sách còn cần đối soát. Chạy lại với preview mới không nhập trùng. Preview cũ bị từ chối sau khi ledger thay đổi. Nếu việc ghi file kết quả thất bại sau commit, dùng preview mới và audit để kiểm tra trạng thái thay vì suy ra rằng database chưa thay đổi.

## Bằng chứng kiểm thử

- Toàn bộ unit suite trước hai test bổ sung cuối: 447 passed, 207 subtests passed, 3 skipped, 1 deselected.
- Lượt cuối cho backfill, daily limits và wallet history: 83 passed, không lỗi. Bao gồm backup/apply CLI, rollback, idempotency, stale snapshot, replacement, bộ lọc phạm vi, ERC20 raw units và loại timestamp giả từ RPC receipt.
- Ruff kiểm tra các file Python liên quan.
- Không có API request mới. Chưa áp dụng lên lịch sử thật, và phần cấu hình Guardrail theo ví của Nam vẫn cần tích hợp riêng.

Chi tiết máy đọc được: `eval/safety_v2/backfill-offline/validation.json`.
