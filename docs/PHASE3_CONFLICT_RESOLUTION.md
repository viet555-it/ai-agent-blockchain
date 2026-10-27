# Xử lý conflict PR #11 với develop — 27/10/2026

PR [#11](https://github.com/viet555-it/ai-agent-blockchain/pull/11) ban đầu nhắm
vào `main`, nơi có các commit revert Agent/frontend/backend. Người dùng xác nhận
chuyển đích sang `develop` để nhóm test. PR bị đóng trong lúc kiểm tra; sau khi
người dùng xác nhận, đã mở lại và đổi base sang `develop`. Không merge PR hoặc
thay đổi nhánh main.

Trong cùng thời gian, develop nhận PR #12 về theme, đa ngôn ngữ và timeline.
Vì vậy cần xử lý conflict thực với base mới, thay vì chỉ đổi đích PR:

- Feature trước xử lý: `708c6ec16d98d799a36115cc46c98d89efce8d2f`.
- Develop đưa vào feature: `491ebc5ddf75bbd35d70a17aa1e498367aa317b2`.
- Chiến lược: merge develop vào feature đã publish, không rebase/force-push.
- File conflict: `frontend/app.js`, `frontend/index.html`.

## Nội dung ghép lại

Giữ theme dark/light, chọn EN/VI, CSS/icon mới và timeline đánh số tuần tự của
PR #12. Giữ session ID khi chat/approval/poll, amount dạng chuỗi chính xác,
phí gas/chain trong preview, polling không gửi lại APPROVE, và thông báo
CONFIRMED/REVERTED/PENDING/UNKNOWN riêng của nhánh tích hợp.

Citation tiếp tục escape dữ liệu RAG, hiển thị cosine similarity có thể âm bằng
số thực; không nhân thành phần trăm/confidence. Nhãn contract phản ánh network
đang chạy, đổi ngôn ngữ không biến Hardhat thành Sepolia. Tool/timeline payload
và nhãn tên bước chưa có bản dịch có fallback an toàn.

Đã điều chỉnh i18n tải JSON locale bằng fetch trước bootstrap vì backend phục
vụ native browser modules trực tiếp, không bắt buộc Vite build. API vẫn phục vụ
được hai file locale qua StaticFiles. Thêm test API cho đường phục vụ này.

## Kiểm chứng

| Kiểm tra | Kết quả |
|---|---|
| JavaScript syntax | app.js / i18n.js / icons.js đạt |
| Unit | 274 passed, 1 deselected, 70 subtests passed |
| API/EVM thật | 136 tests passed |
| Browser frontend + API fixture | 13/13 ca, không JavaScript pageerror |

Browser dùng Chrome headless, asset thật và API mock tại browser; không nối
Gemini/RPC. Các ca gồm bootstrap locale, theme, EN/VI + persistence, dynamic
network label, RAG escaping/similarity, timeline/fallback, số lượng token chính
xác và 1 wei ETH, Reject/session, một APPROVE rồi poll, các trạng thái receipt
và tách session giữa tab. Backend API/EVM thật được kiểm riêng, không diễn giải
browser mock thành giao dịch on-chain thật hay accuracy model mới.

Evidence: [conflict-resolution-20261027.json](evidence/phase3/conflict-resolution-20261027.json).
Budget Gemini giữ 151/200; không có request Gemini hoặc giao dịch Sepolia mới
trong đợt xử lý conflict. Các gate holdout mới và latency của giai đoạn 3 vẫn
chưa nghiệm thu.
