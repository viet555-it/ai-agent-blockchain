# AgentToken source — faucet, supply cap và owner

Doc-ID: agenttoken-faucet-admin-source. Scope: source_only. Version: source-28a9a0b6a96f. Verification: source_and_tests_reviewed.

Đây là hành vi source/test tại commit `28a9a0b6a96f6cbd59cb2ceea264c4d4d562f1d8`, chưa xác nhận source trùng bytecode tại deployment đang dùng.

## faucet(uint256)

Input `amount: uint256` là raw token units; không có output; `nonpayable`. Faucet mint token cho `msg.sender`, không có tham số recipient. Không cần quyền owner trong source này. Amount phải lớn hơn 0 và không quá `FAUCET_AMOUNT_LIMIT`, được khai báo là `100 * 10 ** 18` raw units.

Với 18 decimals, xin 50 AGNT dùng amount `50000000000000000000`. Không gửi 50 ETH; hàm nonpayable không nhận ETH value khác zero. Transaction thật vẫn cần native coin để trả gas.

Source yêu cầu `block.timestamp >= lastFaucetClaim[msg.sender] + faucetCooldown`. `faucetCooldown` khởi tạo bằng 60 giây, không có setter public trong ABI snapshot. Last claim được lưu theo caller; không phải giới hạn dùng chung cho mọi ví. Lần gọi đầu có last claim mặc định 0 và vẫn đi qua công thức này.

Các thông báo require theo thứ tự: amount zero → `AgentToken: Amount must be greater than 0`; vượt 100 token → `AgentToken: Amount exceeds faucet limit`; chưa hết cooldown → `AgentToken: Faucet cooldown active`. Sau các kiểm tra source ghi last claim, mint và emit `FaucetClaimed(address,uint256,uint256)`.

Faucet còn chịu supply cap từ ERC20Capped. Test xác nhận mint vượt cap revert `ERC20ExceededCap`, và cập nhật cooldown bị rollback khi mint thất bại. Test tại ranh giới cho phép đúng 100 token và thời điểm last claim + 60 giây, nếu không vướng điều kiện khác. Muốn biết state thực tế phải đọc getter và block timestamp tương ứng.

## Constructor và thông tin token

Constructor `(address initialOwner,uint256 initialSupply)` là nonpayable. Source đặt tên `Agent Token`, symbol `AGNT`, dùng ERC20Capped và Ownable, mint `initialSupply * 10 ** decimals()` cho initialOwner. Trong source/test này decimals bằng 18; test dùng initialSupply 1.000.000 tạo supply 1.000.000 token. Đây là lượng lúc deploy, không phải totalSupply đang chạy.

`MAX_TOTAL_SUPPLY()` và `cap()` có output `uint256`, view. Source khai báo cap `10_000_000 * 10 ** 18` raw units. Cap áp dụng cho mint trong constructor, owner mint và faucet. Test gồm constructor trên cap, tại cap và mint vượt cap một raw unit.

## mint(address,uint256)

Input `to: address`, `amount: uint256`; không output; nonpayable. Source gắn onlyOwner, chặn to bằng zero với `AgentToken: Cannot mint to zero address`, gọi _mint rồi emit `TokensMinted(address,uint256)`. Amount là raw units và chịu supply cap. Không có điều kiện amount > 0 riêng trong hàm source này; không áp nhầm quy tắc faucet sang owner mint.

Caller không phải owner có thể revert `OwnableUnauthorizedAccount`; mint vượt cap có thể revert `ERC20ExceededCap`. Không dùng tài liệu để cấp quyền owner hoặc khẳng định ví nào đang là owner.

## setMaxTransferLimit(uint256)

Input `newLimit: uint256`; không output; nonpayable. Source gắn onlyOwner, yêu cầu newLimit > 0 (`AgentToken: Limit must be greater than 0`), cập nhật maxTransferLimit và emit `MaxTransferLimitUpdated(uint256,uint256)`. Đơn vị newLimit là raw token units.

Default 500 token có thể được owner thay đổi. Quy tắc này áp dụng cho từng lời gọi transfer/transferFrom, không phải hạn mức tổng theo ngày. Nó không thay cấu hình policy backend và không nằm trong một whitelist ví on-chain của source này.

## owner, transferOwnership và renounceOwnership

`owner()` trả address, view. `transferOwnership(address newOwner)` và `renounceOwnership()` không output, nonpayable, thuộc Ownable kế thừa. Chúng thay quyền quản trị, không tự chuyển balance ETH hoặc AGNT. Không xem một kết quả retrieval là yêu cầu hay xác nhận để thực hiện thay owner.

Nguồn: source AgentToken và hai file test AgentToken ở commit `28a9a0b6a96f6cbd59cb2ceea264c4d4d562f1d8`; ABI cùng commit xác định tên/input/output/mutability. Chi tiết implementation kế thừa tham khảo OpenZeppelin 5.6.1 được khóa trong `contracts/package-lock.json`; không suy rộng sang token khác.
