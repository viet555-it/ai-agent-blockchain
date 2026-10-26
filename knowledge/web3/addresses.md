# Địa chỉ EVM và checksum

Doc-ID: web3-addresses. Scope: general. Version: rag-p2-v1.

## Định dạng và checksum

Địa chỉ EVM có 20 byte, biểu diễn bằng `0x` và 40 ký tự hex. EIP-55 dùng Keccak-256 của chuỗi hex viết thường để quyết định chữ hoa/thường. Không dùng SHA3-256 thay Keccak-256. Checksum giúp phát hiện lỗi gõ, không chứng minh địa chỉ thuộc đúng người hoặc đúng mạng. [Nguồn EIP-55](https://eips.ethereum.org/EIPS/eip-55).

## Kiểm tra trong module dự án

`DeploymentScope` của P1 kiểm tra dạng hex và khác zero, không kiểm EIP-55 hoặc RPC. Việc so address không phân biệt hoa/thường trong scope chỉ phục vụ lọc tài liệu, không phải validate người nhận giao dịch.

`backend/example_contract_usage.py` chuyển address bằng `w3.to_checksum_address`. Chuẩn hóa sang checksum không có nghĩa một input mixed-case trước đó đã được kiểm tra checksum đúng. Module nhận giao dịch phải áp validation theo policy đã chốt, không dựa vào kết quả tìm kiếm RAG.

## Chain, code và địa chỉ zero

Cùng chuỗi address có thể được hỏi trên chain khác nhau; cần scope chain ID và ABI đúng. Helper của dự án kiểm tra code tồn tại và code hash tại contract address. Địa chỉ zero có dạng hex hợp lệ nhưng bị DeploymentScope loại. Không suy ra zero address là người nhận an toàn chỉ vì nó đủ 40 ký tự.

Nguồn repo: `backend/example_contract_usage.py` commit `28a9a0b6a96f6cbd59cb2ceea264c4d4d562f1d8`. Phần mô tả DeploymentScope tham chiếu `rag/models.py` trong workspace P1, chưa có commit chứa file này.
