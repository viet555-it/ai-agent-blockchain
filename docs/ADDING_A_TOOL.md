# Hướng dẫn thêm Tool mới

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
            # Sử dụng ctx.blockchain để gọi RPC
            result = await ctx.blockchain.get_balance(validated.address)

            # Cache (optional, cho data ít thay đổi)
            cache_key = f"my_tool:{validated.address}"
            if cache_key in ctx.cache:
                return ToolResult.success(ctx.cache[cache_key])
            ctx.cache[cache_key] = {"balance": result}

            return ToolResult.success({"balance": result})
        except Exception as e:
            return ToolResult.failure(f"My tool failed: {e}")
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
from tools.registry import _REGISTRY


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


@pytest.fixture(autouse=True)
def _register():
    from tools.read.my_new_tool import MyNewTool
    _REGISTRY["my_tool_name"] = MyNewTool()


class TestMyNewTool:
    @pytest.mark.asyncio
    async def test_success(self, ctx):
        tool = _REGISTRY["my_tool_name"]
        args = tool.validate_args({"address": "0xABC"})
        result = await tool.run(args, ctx)
        assert result.ok

    @pytest.mark.asyncio
    async def test_error_handling(self, ctx):
        tool = _REGISTRY["my_tool_name"]
        args = tool.validate_args({"address": "invalid"})
        result = await tool.run(args, ctx)
        # Test error case
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
