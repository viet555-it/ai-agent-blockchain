# Kết quả Safety v2 offline

Policy và workflow chạy trên SQLite tạm với blockchain fixture. FakeLLM phát tool call theo kịch bản; kết quả không đo khả năng chống injection của LLM thật.

Policy latency gồm kiểm luật và truy vấn usage, không gồm thời gian dựng fixture. Scripted Agent latency không gồm workflow authorize chạy sau đó. Không so sánh độ trễ này với provider LLM thật.

| Lớp | Dự kiến | Hoàn tất | Đạt | Lỗi | N/A |
|---|---:|---:|---:|---:|---:|
| policy | 40 | 36 | 36 | 0 | 4 |
| fake_agent | 40 | 40 | 38 | 0 | 0 |

Tỷ lệ chặn đúng/chặn nhầm chỉ dùng ca có kỳ vọng policy tương ứng. Ca chờ duyệt không bị tính là chặn. Ca đổi payload, bỏ duyệt và đồng thời có kiểm workflow riêng; không gọi việc qua policy là vượt quyền ký.

Lỗi hạ tầng được ghi riêng trong mẫu số hoàn tất; xem cả số dự kiến và số lỗi trước khi diễn giải tỷ lệ. Bộ dữ liệu đang ở trạng thái đề xuất, gồm 20 kịch bản theo cặp Việt/Anh; chưa có holdout hoặc kết quả live.

Chi tiết từng ca, trace công cụ và workflow trong results.json; bảng số liệu trong samples.csv.
