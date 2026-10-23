# Dry-run, caller và gas

Doc-ID: web3-simulation. Scope: general. Version: rag-p2-v1.

## Mô phỏng giao dịch token trong dự án

`tool_simulate_transfer` ở `backend/example_contract_usage.py`, commit `28a9a0b6a96f6cbd59cb2ceea264c4d4d562f1d8`, chọn ABI theo RPC chain ID, kiểm chain/code/code hash, đọc decimals và đổi amount bằng helper số nguyên chính xác.

Nếu không truyền spender, helper mô phỏng `transfer(recipient,units)` với from bằng sender. Nếu truyền spender, helper mô phỏng `transferFrom(sender,recipient,units)` với from bằng spender, kể cả khi spender chính là sender. Đổi caller có thể đổi kết quả allowance và quyền truy cập.

Helper dùng `.call`, không ký hoặc broadcast transaction. ContractLogicError trở thành `isValid=False`; lỗi RPC/kết nối không bị đổi thành kết luận contract từ chối. Kết quả true chỉ phản ánh state ở lúc call; balance/allowance/limit có thể đổi trước khi transaction được thực thi.

## eth_call và estimateGas

`eth_call` thực thi lời gọi không ghi thay đổi state lên chain. `eth_estimateGas` ước lượng gas cho transaction trong state được node xem xét; không là receipt hay bảo đảm transaction sẽ thành công. Nên mô phỏng đúng from, to, data và value dự kiến. [Nguồn Ethereum JSON-RPC](https://ethereum.org/developers/docs/apis/json-rpc/).

## Gas limit khác phí gas

Gas limit là số đơn vị gas cho phép, không phải số ETH trả. Với EIP-1559, maxFeePerGas là trần giá gas; phí thực tế dựa trên gasUsed và effectiveGasPrice trong receipt. Ước lượng chi phí và số dư phải dùng dữ liệu mới, không dùng con số cố định từ corpus. [Nguồn Ethereum gas](https://ethereum.org/en/developers/docs/gas/).

## Dry-run không thay thế policy

Mô phỏng thành công không cấp allowance, không giữ chỗ balance, không thực thi giao dịch và không thay sự xác nhận của người dùng. AgentToken validator, policy backend và execution tool là các lớp khác nhau. Tài liệu RAG chỉ giải thích các lớp, không quyết định quyền WRITE.
