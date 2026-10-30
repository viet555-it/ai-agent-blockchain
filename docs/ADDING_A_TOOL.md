# Hướng dẫn thêm Tool mới

Ví dụ dưới đây dành cho core async (`tools/`, `services/blockchain.py`). Tích hợp
API dùng `BackendReadRegistry` riêng trong `backend/agent/read_tools.py`; thêm
tool vào registry global hoặc YAML chưa làm tool đó xuất hiện trong browser flow.

Với READ tool cho API, thêm template vào registry riêng và mapping sang public
method của blockchain facade; giữ đúng kwargs, integer/decimal units và xử lý
RPC ngoài event loop. Với thao tác transaction, thêm proposal/preparation thay vì
gọi signer trong tool; UI approval, wallet scope, preflight và transport tiếp tục
thuộc workflow hiện có. Xem [kiến trúc](ARCHITECTURE.md).

## 1. Tạo file tool

Tạo file trong `tools/read/` (READ) hoặc `tools/write/` (WRITE):

```python
# tools/read/my_new_tool.py
from __future__ import annotations

from pydantic import BaseModel, Field

from tools.base import BaseTool, RiskLevel, ToolContext, ToolResult
from tools.registry import register_tool


class MyToolInput(BaseModel):
    """Input schema – Pydantic model."""
    address: str = Field(description="Ethereum address (0x-prefixed)")
    # Thêm fields tùy ý. Field description hiển thị cho LLM.


@register_tool
class MyNewTool(BaseTool):
    name = "my_tool_name"          # unique, snake_case
    description = (
        "Mô tả ngắn gọn tool làm gì. "
        "LLM đọc description này để quyết định có gọi tool không."
    )
    risk_level = RiskLevel.READ    # READ hoặc WRITE
    args_schema = MyToolInput

    async def run(self, validated: MyToolInput, ctx: ToolContext) -> ToolResult:
        try:
            # Cache (optional, cho data ít thay đổi)
            cache_key = f"my_tool:{validated.address}"
            cached = ctx.cache_get(cache_key)
            if cached is not None:
                return ToolResult.success(cached)
            result = await ctx.blockchain.get_balance(validated.address)
            data = {"balance": result}
            ctx.cache_set(cache_key, data)
            return ToolResult.success(data)
        except Exception:
            return ToolResult.failure("Blockchain read failed; check RPC and parameters.")
```

## 2. Đăng ký trong `config/tools.yaml`

```yaml
enabled:
  # ... existing tools ...
  - my_tool_name    # ← thêm dòng này
```

## 3. Viết test

```python
# tests/test_my_tool.py
import pytest
from services.blockchain import MockBlockchainData, MockBlockchainService
from tools.base import ToolContext
from tools.read.my_new_tool import MyNewTool
from unittest.mock import patch


class FakeSettings:
    etherscan_api_key = ""
    sepolia_rpc_url = "https://rpc.sepolia.org"
    dry_run = True
    # ... các field cần thiết


@pytest.fixture()
def ctx():
    data = MockBlockchainData(
        balances={"0xabc": 10**18},
    )
    return ToolContext(
        blockchain=MockBlockchainService(data),
        settings=FakeSettings(),
    )


class TestMyNewTool:
    @pytest.mark.asyncio
    async def test_success(self, ctx):
        tool = MyNewTool()
        args = tool.validate_args({"address": "0xABC"})
        result = await tool.run(args, ctx)
        assert result.ok

    @pytest.mark.asyncio
    async def test_error_handling(self, ctx):
        tool = MyNewTool()
        args = tool.validate_args({"address": "0xabc"})
        with patch.object(ctx.blockchain, "get_balance", side_effect=RuntimeError("test RPC")):
            result = await tool.run(args, ctx)
        assert not result.ok
```

## 4. Thêm eval prompts

Thêm vào `eval/dataset.jsonl`:

```jsonl
{"prompt": "Use my tool on address 0xABC", "expected_tool": "my_tool_name", "expected_args": {"address": "0xABC"}, "category": "read_custom"}
```

## 5. WRITE tool – thêm PolicyEngine

Nếu tool là WRITE, thêm policy check bên trong `run()`:

```python
async def run(self, validated, ctx: ToolContext) -> ToolResult:
    from security.policy import PolicyEngine

    policy = PolicyEngine()
    decision = policy.check_transfer(validated.to, float(validated.value_eth))
    if not decision.allowed:
        return ToolResult.failure(
            f"Policy blocked: {decision.reason}",
            code="POLICY_DENIED",
        )

    if ctx.settings.dry_run:
        return ToolResult.success({"status": "DRY_RUN", ...})

    # ... real transaction logic ...
```

## 6. Checklist

- [ ] File tool trong `tools/read/` hoặc `tools/write/`
- [ ] `@register_tool` decorator
- [ ] Pydantic `args_schema` với Field descriptions
- [ ] `run()` returns `ToolResult.success()` hoặc `ToolResult.failure()`
- [ ] Try/except bao bọc toàn bộ logic
- [ ] Tool name thêm vào `config/tools.yaml`
- [ ] Test file trong `tests/`
- [ ] Eval prompts trong `eval/dataset.jsonl`
- [ ] WRITE tools: PolicyEngine check inside `run()`
- [ ] `ruff check` pass
- [ ] `pytest` pass
