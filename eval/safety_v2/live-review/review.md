# Phạm vi đề xuất cho đánh giá LLM thật

Model lấy từ cấu hình dự án: `gemini-3.5-flash-lite`.

Gửi tối đa 80 request cho 40 ca Việt/Anh; tối đa 4 request/ca, 512 output token/request, tổng trần output 40960 token. Temperature 0, không tự retry. Đây là giới hạn request/token, không phải báo giá hoặc cam kết miễn phí.

Nội dung gồm system prompt, prompt benchmark, 9 schema công cụ, địa chỉ ví/contract thử nghiệm, policy và trạng thái hạn mức giả lập. Hai ca có tài liệu RAG độc hại được chèn vào retrieval context. Các lượt sau có thể chứa phản hồi model và kết quả fixture tool được liệt kê; không gửi gold/kỳ vọng chấm điểm.

Không gửi API key, private key, lịch sử ví thật, database cá nhân hoặc RPC URL chứa key trong payload. API key chỉ được dùng làm credential khi có live runner được cấp quyền. Không ký hoặc gửi giao dịch; phần blockchain dùng mock.

Bản này chỉ là xem trước cục bộ. Chưa gọi provider, chưa tạo ledger ngân sách và chưa có kết quả live. Ngân sách G3.5 không được tái sử dụng.

Review hash: `3d05116c23136cd225115f228787ef0899a6dad4d47b48a1215444a0d75df69a`.
