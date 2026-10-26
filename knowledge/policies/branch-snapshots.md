# Snapshot policy của hai branch — chưa phải policy chung

Doc-ID: policy-branch-snapshots. Scope: policy_snapshot. Usage: reference_only. Policy-version: agent-470c9c6_backend-51da5de.

Tài liệu ghi nhận code/config để bàn giao, không chọn một policy chung. Không đưa snapshot này vào deployment retrieval; không dùng làm config runtime hoặc cho phép WRITE.

## Snapshot branch ai-agent

Nguồn `config/policy.yaml` và `security/policy.py` tại commit `470c9c66f8867ead99a925e2569414fddfeee8b2`. Config đề xuất Sepolia 11155111; mặc định 0.1 ETH mỗi transaction và 0.5 ETH trong cửa sổ 24 giờ. Đây là cấu hình ở commit đó, không xác nhận cấu hình đang chạy.

PolicyEngine check_transfer chặn nếu address allowlist rỗng hoặc recipient không thuộc allowlist. check_contract_call chặn nếu contract/function allowlist rỗng hoặc không khớp. Config có contract zero placeholder và tên hàm deposit/withdraw; chúng không chứng minh có SampleVault đã deploy hoặc AgentToken có hai hàm này.

Config yêu cầu simulation và block_on_revert; các giá trị config không tự chứng minh mọi đường gọi tool đã thực thi simulation. Daily usage trong PolicyEngine là bộ nhớ của instance, cần record_usage được đường thực thi gọi; không khẳng định đây là tổng mọi giao dịch on-chain của ví.

## Snapshot branch feature/frontend-backend

Nguồn `backend/app/services/guardrail.py` và `backend/app/core/config.py` tại commit `51da5deda3febe1dca04b63cf42bb2ab2a76f9c9`. Default config: 0.1 ETH, 500 token mỗi transfer; require_human_approval và simulation_enabled là true, có thể bị runtime/env thay đổi.

Trong evaluate_transaction, blacklist/địa chỉ không hợp lệ có thể bị chặn; recipient ngoài whitelist được đánh dấu INFO thay vì tự bị chặn. Đây khác deny-by-default của branch agent. Hàm dùng Web3.is_address để kiểm định dạng; không khẳng định mọi mixed-case checksum sai sẽ bị từ chối. Flag simulation_enabled trong report không tự chứng minh có eth_call ở chính hàm này.

## On-chain limit khác policy off-chain

Source AgentToken có maxTransferLimit mặc định 500 AGNT, owner sửa được; source không có daily ETH limit hoặc address allowlist tương ứng backend. Hai lớp có thể cùng áp dụng và cần kiểm tra riêng. Không chọn hạn mức dễ hơn để bỏ qua lớp còn lại.

## Việc còn chờ nhóm

Nhóm cần thống nhất policy runtime và đường ký/xác nhận trước tích hợp WRITE. Phần Việt ở P2 hoàn thành bằng snapshot có provenance và scope tách biệt; không cần sửa engine, merge branch hoặc quyết định policy thay đồng đội.
