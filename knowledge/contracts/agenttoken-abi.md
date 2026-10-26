# AgentToken — danh mục ABI theo repository

Doc-ID: agenttoken-abi-guide. Scope: deployed_contract. Version: repo-28a9a0b6a96f. Verification: repository_only.

Nguồn: `backend/abi/11155111/AgentToken_abi.json` tại commit `28a9a0b6a96f6cbd59cb2ceea264c4d4d562f1d8`. Scope chain 11155111 và address `0xa453B71a492558C17efA82E294739e4eFef3C220` là khai báo trong repo, chưa xác minh RPC.

Danh mục xác định interface; ABI không xác nhận live bytecode, giá trị getter, quyền thực thi hoặc đầy đủ revert conditions. Các mô tả ý nghĩa dựa trên tên hàm và source đã review, không bảo đảm hành vi live. Mọi hàm WRITE ở ABI này là nonpayable; không gửi ETH value khác zero khi gọi.

## constructor(address,uint256)

- Input: `address initialOwner, uint256 initialSupply`.
- Output: `(không có)`.
- Mutability: `nonpayable`.
- Mục đích: Giao diện khởi tạo; đơn vị initialSupply được giải thích theo source, không dùng constructor làm tool gọi contract đã deploy.

## FAUCET_AMOUNT_LIMIT()

- Input: `(không có)`.
- Output: `uint256 (không đặt tên)`.
- Mutability: `view`.
- Mục đích: Getter hạn mức amount của faucet theo interface; giá trị cần đọc bằng tool.

## MAX_TOTAL_SUPPLY()

- Input: `(không có)`.
- Output: `uint256 (không đặt tên)`.
- Mutability: `view`.
- Mục đích: Getter hằng số trần supply trong interface; không suy ra totalSupply hiện tại.

## allowance(address,address)

- Input: `address owner, address spender`.
- Output: `uint256 (không đặt tên)`.
- Mutability: `view`.
- Mục đích: Tra cứu allowance của owner cho spender; output là raw token units.

## approve(address,uint256)

- Input: `address spender, uint256 value`.
- Output: `bool (không đặt tên)`.
- Mutability: `nonpayable`.
- Mục đích: Giao diện cấp allowance cho spender; value là raw token units, không phải ETH.

## balanceOf(address)

- Input: `address account`.
- Output: `uint256 (không đặt tên)`.
- Mutability: `view`.
- Mục đích: Tra cứu balance của account; output là raw token units.

## cap()

- Input: `(không có)`.
- Output: `uint256 (không đặt tên)`.
- Mutability: `view`.
- Mục đích: Getter cap trong interface; khác totalSupply.

## decimals()

- Input: `(không có)`.
- Output: `uint8 (không đặt tên)`.
- Mutability: `view`.
- Mục đích: Getter số chữ số thập phân; ABI chỉ xác định kiểu uint8, không chứa giá trị trả về.

## faucet(uint256)

- Input: `uint256 amount`.
- Output: `(không có)`.
- Mutability: `nonpayable`.
- Mục đích: Giao diện xin token; amount là raw token units. Điều kiện từ source được lưu scope source_only.

## faucetCooldown()

- Input: `(không có)`.
- Output: `uint256 (không đặt tên)`.
- Mutability: `view`.
- Mục đích: Getter cooldown; diễn giải source theo giây ở tài liệu source_only.

## lastFaucetClaim(address)

- Input: `address (không đặt tên)`.
- Output: `uint256 (không đặt tên)`.
- Mutability: `view`.
- Mục đích: Getter theo address; tên tham số có thể trống trong ABI của public mapping.

## maxTransferLimit()

- Input: `(không có)`.
- Output: `uint256 (không đặt tên)`.
- Mutability: `view`.
- Mục đích: Getter hạn mức; không suy ra giá trị hiện tại từ default source.

## mint(address,uint256)

- Input: `address to, uint256 amount`.
- Output: `(không có)`.
- Mutability: `nonpayable`.
- Mục đích: Giao diện mint tới to; amount là raw token units; quyền owner xem tài liệu source_only.

## name()

- Input: `(không có)`.
- Output: `string (không đặt tên)`.
- Mutability: `view`.
- Mục đích: Getter tên token; ABI không chứa giá trị string thực tế.

## owner()

- Input: `(không có)`.
- Output: `address (không đặt tên)`.
- Mutability: `view`.
- Mục đích: Getter owner; ABI không cho biết ví owner hiện tại.

## renounceOwnership()

- Input: `(không có)`.
- Output: `(không có)`.
- Mutability: `nonpayable`.
- Mục đích: Giao diện từ bỏ ownership; không phải thao tác chuyển token.

## setMaxTransferLimit(uint256)

- Input: `uint256 newLimit`.
- Output: `(không có)`.
- Mutability: `nonpayable`.
- Mục đích: Giao diện cập nhật hạn mức; newLimit là raw token units.

## symbol()

- Input: `(không có)`.
- Output: `string (không đặt tên)`.
- Mutability: `view`.
- Mục đích: Getter symbol; ABI không chứa giá trị string thực tế.

## totalSupply()

- Input: `(không có)`.
- Output: `uint256 (không đặt tên)`.
- Mutability: `view`.
- Mục đích: Getter tổng supply tại state truy vấn; raw token units.

## transfer(address,uint256)

- Input: `address to, uint256 value`.
- Output: `bool (không đặt tên)`.
- Mutability: `nonpayable`.
- Mục đích: Giao diện chuyển token từ caller tới to; value là raw token units.

## transferFrom(address,address,uint256)

- Input: `address from, address to, uint256 value`.
- Output: `bool (không đặt tên)`.
- Mutability: `nonpayable`.
- Mục đích: Giao diện chuyển token từ from tới to bởi caller/spender; value là raw token units.

## transferOwnership(address)

- Input: `address newOwner`.
- Output: `(không có)`.
- Mutability: `nonpayable`.
- Mục đích: Giao diện thay owner; newOwner là address.

## validateTransfer(address,address,uint256)

- Input: `address sender, address recipient, uint256 amount`.
- Output: `bool isValid, string reason`.
- Mutability: `view`.
- Mục đích: Giao diện kiểm tra với sender/recipient/amount; bool và reason không phải receipt.

## validateTransferFrom(address,address,uint256,address)

- Input: `address sender, address recipient, uint256 amount, address spender`.
- Output: `bool isValid, string reason`.
- Mutability: `view`.
- Mục đích: Giao diện kiểm tra thêm spender là caller dự kiến; amount là raw token units.

## Events trong ABI

Danh mục dưới đây là interface log, không chứng minh event đã được emit tại deployment.

- `Approval(address,address,uint256)` — indexed: owner, spender.
- `FaucetClaimed(address,uint256,uint256)` — indexed: recipient.
- `MaxTransferLimitUpdated(uint256,uint256)` — indexed: (không có).
- `OwnershipTransferred(address,address)` — indexed: previousOwner, newOwner.
- `TokensMinted(address,uint256)` — indexed: to.
- `Transfer(address,address,uint256)` — indexed: from, to.

## Custom errors trong ABI

Có error trong ABI không cho biết mọi hàm đều có thể phát sinh error đó. Không dùng danh sách này thay eth_call; require string trong source không nhất thiết có entry error riêng.

- `ERC20ExceededCap(uint256,uint256)`.
- `ERC20InsufficientAllowance(address,uint256,uint256)`.
- `ERC20InsufficientBalance(address,uint256,uint256)`.
- `ERC20InvalidApprover(address)`.
- `ERC20InvalidCap(uint256)`.
- `ERC20InvalidReceiver(address)`.
- `ERC20InvalidSender(address)`.
- `ERC20InvalidSpender(address)`.
- `OwnableInvalidOwner(address)`.
- `OwnableUnauthorizedAccount(address)`.

## Ghi chú kết quả trả về

Hàm không output không có nghĩa caller nhận một bool true. Bool từ call không phải transaction hash. Giao dịch thật được theo dõi bằng receipt/tool riêng. Getter và validator view không tự gửi transaction.
