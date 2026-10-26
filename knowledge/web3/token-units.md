# Đơn vị token và chuyển đổi chính xác

Doc-ID: web3-token-units. Scope: general. Version: rag-p2-v1.

## Raw units và decimals

Với token có decimals là d, lượng hiển thị bằng raw_amount / 10^d. Raw amount là số nguyên, decimals mô tả thang hiển thị. Token không nhất thiết dùng 18 decimals; phải đọc decimals từ contract đã xác minh khi cần tính lượng thực thi. ERC-20 định nghĩa decimals là metadata tùy chọn; một token khác có thể không cung cấp nó. [Nguồn chuẩn ERC-20](https://eips.ethereum.org/EIPS/eip-20).

## Quy tắc input trong helper của dự án

`backend/token_amounts.py` tại commit `28a9a0b6a96f6cbd59cb2ceea264c4d4d562f1d8` nhận `str` thập phân không âm hoặc `int` theo đơn vị token hiển thị. Nó từ chối float, bool, số âm, exponent notation, khoảng trắng và phần thập phân dài hơn decimals. Decimals phải là int trong 0..255; raw amount phải không vượt `2**256 - 1`.

Helper này không đọc RPC và không tự biết token nào đang được dùng. Ví dụ `to_token_units("5", 18)` cho `5000000000000000000`; `to_token_units("1.000000000000000001", 18)` cho `1000000000000000001`; `to_token_units("1.5", 6)` cho `1500000`. `to_token_units("0.0000001", 6)` bị từ chối vì không biểu diễn chính xác trong 6 decimals.

`format_token_units(units, decimals)` trả chuỗi thập phân chính xác, bỏ zero dư ở cuối phần lẻ. Với units bằng `1000000000000000001`, decimals 18, kết quả là `"1.000000000000000001"`. Không đổi sang float trước khi hiển thị hoặc tạo tham số ABI.

## Zero amount và điều kiện nghiệp vụ

Chuyển đổi lượng zero thành raw zero là hợp lệ về định dạng. Hàm contract cụ thể quyết định có chấp nhận zero hay không. Không suy ra mọi hàm nhận uint256 đều cho phép hoặc đều từ chối zero; kiểm tra tài liệu đúng scope và mô phỏng hành động cụ thể.

## Native coin và token không cùng đơn vị

ETH dùng wei: 1 ETH = 10^18 wei; gwei = 10^9 wei. `value` trong transaction là native coin, còn amount trong calldata transfer token là raw token units. Dù một token cũng dùng 18 decimals, AGNT không trở thành ETH. Tài liệu gas/wei tham khảo [Ethereum gas](https://ethereum.org/en/developers/docs/gas/); ví dụ token ở trên là tính toán số nguyên theo helper dự án.
