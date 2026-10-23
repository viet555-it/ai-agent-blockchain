# AgentToken — deployment được ghi nhận trong repository

Doc-ID: agenttoken-deployment-guide. Scope: deployed_contract. Version: repo-28a9a0b6a96f. Verification: repository_only.

## Chain, địa chỉ và ABI được chọn

Manifest `backend/abi/11155111/deployment.json` tại commit `28a9a0b6a96f6cbd59cb2ceea264c4d4d562f1d8` ghi network Sepolia, chain ID `11155111`, contract address `0xa453B71a492558C17efA82E294739e4eFef3C220`. ABI canonical là `backend/abi/11155111/AgentToken_abi.json` cùng commit.

Runtime code hash được manifest khai báo là `0x93baa9b6feec50647d48e313f67e3e7b4dec306061958ffc7a6a29bbc1d8ef42`. Đây là hash bytecode theo manifest; không phải SHA-256 file ABI mà module RAG dùng để xác định phiên bản tài liệu.

Manifest ghi initialSupply là chuỗi `1000000`. Nó mô tả tham số deployment, không phải totalSupply hiện tại. ABI đi kèm có `MAX_TOTAL_SUPPLY()`, `cap()` và `validateTransferFrom(address,address,uint256,address)`. Việc có entry trong ABI không tự chứng minh bytecode tại địa chỉ thực hiện entry đó.

## Đối chiếu tài liệu cũ

README contract đang nhắc địa chỉ `0xDf7B0c367817f97d756441da6047a1Da91cC6Fff` và mô tả ABI cũ. Nó không khớp chain-scoped manifest hiện chọn. Không thay địa chỉ hoặc ABI dựa vào đoạn README này; README không nằm trong allowlist ingest.

Địa chỉ cũ không phải deployment scope của tài liệu này. Source Solidity cũng không tự chứng minh đã được deploy tại địa chỉ mới. Các hướng dẫn hành vi từ source được giữ scope `source_only` riêng.

## Giới hạn xác minh và dữ liệu động

Tập tài liệu này xác nhận artifact trong Git, chưa kiểm tra live RPC. Không dùng nó để khẳng định contract đang hoạt động, owner hiện tại, số dư, allowance hoặc hạn mức hiện tại.

Helper `backend/example_contract_usage.py` chọn artifact theo chain ID của RPC, kiểm tra manifest chainId, code không rỗng và runtimeCodeHash nếu có. Bước xác minh RPC này thuộc lúc dùng tool; việc retrieval tìm được tài liệu không thay thế bước đó.

Nguồn: ABI/manifest canonical và helper Python ở commit `28a9a0b6a96f6cbd59cb2ceea264c4d4d562f1d8`. Các bằng chứng và content hash được ghi trong `knowledge/manifest.json`.
