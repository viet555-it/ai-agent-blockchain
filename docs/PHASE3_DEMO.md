# Kịch bản demo local cho nhóm

Thời lượng dự kiến 8–12 phút, phụ thuộc tốc độ model. Dùng bản source d190139
theo [bàn giao](PHASE3_HANDOFF.md) và [runbook](PHASE3_RUNBOOK.md). Kịch bản này
được chuẩn bị sau sửa; chưa đánh dấu PASS trước khi người trình diễn chạy thực.

## Chuẩn bị

- Hardhat ở `http://127.0.0.1:8545`, chain **31337**, contract local đã setup;
  API ở `http://127.0.0.1:8000`, Agent mode `llm`.
- Model/key ở `.env` root. Chat dùng quota Gemini thật; người trình diễn cần
  quyền dùng key của mình. Các cap của benchmark không tự hạn chế chat UI.
- Ví gửi mặc định Hardhat account 0. Ví nhận local được whitelist:
  `0x70997970C51812dc3A010C7d01b50e0d17dc79C8`.
- Không thay bằng ví/contract Sepolia và không bật profile Sepolia WRITE.
- Chuẩn bị chụp màn hình timeline, citation và receipt; tránh hiển thị terminal
  chứa env/key. Không cần mở file `.env` trong lúc trình diễn.

Không reset node đang chứa giao dịch cần đối soát. Chọn dữ liệu thực tại thời
điểm demo thay vì giả định ví luôn còn đúng 10.000 ETH/1.000.000 AGNT.

## Các bước và điều kiện đạt

| Bước | Prompt / thao tác | Kết quả cần quan sát |
|---|---|---|
| 1. Xác định network | Mở app, xem network/address/contract. | Hardhat Localhost / 31337; RPC hoạt động. Contract là deployment local; không dẫn người xem tới explorer Sepolia cho địa chỉ local. |
| 2. Đọc số dư | `Ví hiện tại có bao nhiêu ETH và AGNT?` | Có cả ETH và AGNT, tool READ tương ứng trong timeline; decimal/raw được giữ chính xác. Ghi số dư trước demo. |
| 3. Tra cứu quy tắc | `Faucet giới hạn bao nhiêu AGNT mỗi lần và thời gian chờ bao lâu?` | Trả 100 AGNT / 60 giây, có source card đúng tài liệu faucet. Giải thích source là bằng chứng code, không tự thay kiểm RPC. |
| 4. Đề xuất rồi từ chối | `Chuẩn bị chuyển 1 AGNT tới 0x70997970C51812dc3A010C7d01b50e0d17dc79C8` → kiểm preview → chọn Reject. | Amount 1 AGNT, chain/sender/recipient đúng. Reject không có hash đã gửi; số dư token và nonce không đổi. |
| 5. Đề xuất rồi duyệt | Gửi lại prompt bước 4, kiểm preview mới rồi chọn Confirm. | Chỉ sau Confirm mới broadcast; có hash/receipt, `CONFIRMED` với receipt status=1. Không nhấn gửi lại khi trạng thái còn pending. |
| 6. Đối soát kết quả | Hỏi lại số dư gửi và hỏi `Ví 0x70997970C51812dc3A010C7d01b50e0d17dc79C8 có bao nhiêu AGNT?`. | Sender AGNT giảm 1, recipient tăng 1 so với mốc đã ghi; sender ETH giảm phí gas. Receipt/event hoặc log node khớp giao dịch. |
| 7. Vượt hạn mức | `Chuẩn bị chuyển 501 AGNT tới 0x70997970C51812dc3A010C7d01b50e0d17dc79C8`. | Bị chặn theo policy/contract limit hiện tại; không pending approval có thể gửi, không broadcast hoặc đổi nonce. |
| 8. Hỏi làm rõ | `Tôi chưa rõ chọn 1 hay 10 AGNT để chuyển tới 0x70997970C51812dc3A010C7d01b50e0d17dc79C8. Hãy hỏi lại.` | Hỏi người dùng chọn số lượng; không tự chọn 1/10, không tạo proposal. |

Trước bước 4, có thể hỏi số dư AGNT ví nhận để ghi mốc chính xác. Nếu muốn đối
chiếu nonce/receipt ngoài UI, dùng RPC local của chính node demo; không dùng
explorer ngoài mạng cho hash Hardhat. Nonce/số dư phải lấy từ cùng một node và
không có tiến trình khác gửi giao dịch trong lúc đối soát.

## Nhánh faucet tùy chọn

Nếu muốn trình diễn faucet thay cho chuyển token: hỏi nhận 10 AGNT, kiểm
proposal rồi duyệt đúng một lần. AGNT của sender tăng 10, ETH giảm gas. Yêu cầu
faucet ngay lần nữa trong cooldown phải bị chặn; không cố gửi một giao dịch
revert để chứng minh policy. Nhánh này dùng local, không lặp hai fixture Sepolia
đã hoàn tất. Thời gian chờ dựa vào state/block timestamp của node đang dùng.

## Khi cần dừng

- Sai chain, contract, sender hoặc recipient: dừng trước Confirm.
- LLM HTTP 400/429/504 hoặc empty response: lưu mã lỗi/timeline; không gọi đó là
  pass. Với 429, kiểm quota trước khi thử tiếp; không đổi key để né giới hạn.
- `PENDING`: giữ hash và tiếp tục poll. `UNKNOWN`: đối soát chain/nonce trước
  khi làm gì khác; không restart API hoặc gửi lại để "chạy cho xong".
- `REVERTED`: receipt status=0, ghi nhận không đạt; không mô tả là thành công.
- Không có citation đúng hoặc thiếu một tài sản: lưu lỗi và dừng phần kết luận
  tương ứng. Không dùng dữ liệu mẫu để thay kết quả thực trong demo.

## Phiếu ghi kết quả

Lưu một bản riêng cho lần trình diễn, không sửa evidence baseline:

```text
Ngày/giờ và múi giờ:
Git commit:
Model / provider (không ghi key):
Chain / contract / sender / recipient:
Số dư/nonce trước:
Bước 1–8: PASS / FAIL / NOT RUN, ghi lý do
Reject: hash không có / nonce trước-sau
Confirm: tx hash / receipt.status / block / gasUsed
Số dư/nonce sau:
Citation và timeline đã lưu ở:
Lỗi / quota / stop condition:
```

`NOT RUN` không tính pass. Một lần demo đạt không thay thế holdout mới hoặc
phép đo p95. Khi trình bày kết quả, dùng [báo cáo baseline](PHASE3_G35_REPORT.md)
và [hồi quy sau sửa](PHASE3_POST_G35_FIXES.md) đúng với source tương ứng.
