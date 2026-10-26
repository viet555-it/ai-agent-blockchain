# AgentToken source — transfer, allowance và validator

Doc-ID: agenttoken-transfers-source. Scope: source_only. Version: source-28a9a0b6a96f. Verification: source_and_tests_reviewed.

Tài liệu mô tả source/test tại commit `28a9a0b6a96f6cbd59cb2ceea264c4d4d562f1d8`, không phải xác nhận hành vi live của một địa chỉ. Không đưa các đoạn này vào deployment retrieval như thể đã xác minh on-chain.

## transfer(address,uint256)

Input: `to: address`, `value: uint256`; output `bool`; mutability `nonpayable`. Trong source, caller gửi token của mình đến `to`; `value` tính bằng raw token units, không phải ETH. Với decimals bằng 18, 5 token tương ứng `5000000000000000000` raw units.

Source kiểm tra `value <= maxTransferLimit` trước khi gọi ERC-20 kế thừa. Vượt hạn mức revert với `AgentToken: Transfer exceeds max limit`. Thiếu balance có thể revert `ERC20InsufficientBalance`. Recipient zero bị implementation ERC-20 từ chối. Zero transfer với sender/recipient hợp lệ được test cho phép.

`maxTransferLimit` mặc định trong constructor là 500 token với 18 decimals, không phải ngân sách theo ngày. Owner có thể thay đổi; phải đọc `maxTransferLimit()` để biết giá trị hiện tại trên contract đã xác minh. Một giao dịch đúng 500 token chỉ nằm trong giới hạn mặc định, vẫn cần đủ balance và các điều kiện khác.

## approve(address,uint256) và allowance(address,address)

`approve(address spender,uint256 value)` trả `bool`, `nonpayable`; thiết lập allowance cho spender trên token của caller. `allowance(address owner,address spender)` trả `uint256`, `view`. Lượng allowance là raw token units. Approve không tự chuyển token và không làm thay đổi balance.

Tests source có trường hợp unlimited allowance (`uint256` tối đa) không giảm sau transferFrom. Không khẳng định mọi ERC-20 khác có cùng chi tiết implementation. Việc cấp allowance không bỏ giới hạn transfer của AgentToken.

## transferFrom(address,address,uint256)

Input `from: address`, `to: address`, `value: uint256`; output `bool`; `nonpayable`. Caller là spender, khác vai trò owner của balance (`from`) và người nhận (`to`). Source kiểm tra hạn mức, sau đó dùng ERC-20 kế thừa để chi tiêu allowance và chuyển token.

Thiếu allowance có thể revert `ERC20InsufficientAllowance`; thiếu balance có thể revert `ERC20InsufficientBalance`. Test xác nhận self-spending vẫn cần allowance: nếu caller cũng chính là `from`, gọi transferFrom không được tự miễn kiểm tra allowance. Có thể dùng transfer cho chuyển trực tiếp từ caller theo luồng phù hợp.

Khi giao dịch revert, state thay đổi trong giao dịch bị rollback; test vượt hạn mức không tiêu allowance. Không mô tả thứ tự tất cả lỗi của implementation kế thừa như một cam kết API ổn định.

## validateTransfer(address,address,uint256)

Input `sender: address`, `recipient: address`, `amount: uint256`; output `(bool isValid,string reason)`; `view`. Source kiểm tra theo thứ tự:

1. Sender zero → `(false,"Invalid sender address")`.
2. Recipient zero → `(false,"Invalid recipient address")`.
3. Amount lớn hơn maxTransferLimit → `(false,"Amount exceeds guardrail maxTransferLimit")`.
4. Balance sender nhỏ hơn amount → `(false,"Insufficient balance")`.
5. Nếu qua các kiểm tra trên → `(true,"Valid")`.

Hàm này không kiểm tra allowance; không dùng riêng nó để kết luận transferFrom hợp lệ. Nó không ký hoặc gửi transaction, không giữ chỗ balance, không xác nhận policy backend. Zero amount không bị validator từ chối nếu các địa chỉ hợp lệ.

## validateTransferFrom(address,address,uint256,address)

Input `sender: address`, `recipient: address`, `amount: uint256`, `spender: address`; output `(bool isValid,string reason)`; `view`. Spender là caller dự kiến của transferFrom, không phải recipient.

Source từ chối spender zero với `Invalid spender address`; gọi validateTransfer và giữ kết quả lỗi nếu có; sau đó kiểm tra `allowance(sender,spender) < amount`, trả `Insufficient allowance for spender` nếu thiếu. Qua mọi bước trả `(true,"Valid")`. Test có cả caller/spender bằng sender và zero amount.

## Validator khác mô phỏng giao dịch thực

Validator chỉ bao phủ các điều kiện được viết trong source đó. Helper backend mô phỏng đúng `transfer` hoặc `transferFrom` bằng eth_call với caller dự kiến, thay vì yêu cầu mọi deployment có validator mới. Kết quả mô phỏng chỉ phản ánh state tại lúc gọi; state khi gửi transaction có thể khác.

Nguồn: `contracts/src/AgentToken.sol`, `contracts/test/AgentToken.test.js`, `contracts/test/AgentToken.security.test.js`, `backend/example_contract_usage.py`, ABI canonical — đều pin ở commit `28a9a0b6a96f6cbd59cb2ceea264c4d4d562f1d8`. Đã đọc đối chiếu source và test; P2 chưa chạy lại test Hardhat hoặc RPC.
