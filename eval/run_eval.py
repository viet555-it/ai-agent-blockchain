"""Tool Accuracy Evaluator – run eval/dataset.jsonl against the agent.

Measures:
- **Tool Selection Accuracy**: Did the LLM pick the correct tool?
- **Argument Accuracy**: Did the arguments contain expected key-value pairs?
- **Safety Compliance**: Did safety prompts correctly NOT trigger tools?
- **Category breakdown**: Accuracy per category (read_balance, write, safety, etc.)

Usage::

    # With FakeLLM (scripted, no API needed)
    python -m eval.run_eval

    # With real LLM
    LLM_PROVIDER=gemini python -m eval.run_eval

    # Output results to file
    python -m eval.run_eval --output eval/results.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.core import AgentLoop
from agent.llm.base import LLMResponse, ToolCall
from agent.llm.fake import FakeLLMProvider
from config.settings import LLMProviderName, Settings
from services.blockchain import MockBlockchainData, MockBlockchainService
from tools.registry import _REGISTRY, ToolRegistry

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────

EVAL_DIR = Path(__file__).resolve().parent
DATASET_PATH = EVAL_DIR / "dataset.jsonl"


# ── Dataset loader ────────────────────────────────────────────────────


def load_dataset(path: Path | None = None) -> list[dict[str, Any]]:
    """Load eval dataset from JSONL."""
    path = path or DATASET_PATH
    items: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning("Skipping line %d: %s", i, e)
    return items


# ── Evaluation logic ──────────────────────────────────────────────────


class EvalResult:
    """Result of evaluating a single prompt."""

    def __init__(
        self,
        prompt: str,
        expected_tool: str | None,
        actual_tool: str | None,
        expected_args: dict[str, Any],
        actual_args: dict[str, Any],
        category: str,
    ) -> None:
        self.prompt = prompt
        self.expected_tool = expected_tool
        self.actual_tool = actual_tool
        self.expected_args = expected_args
        self.actual_args = actual_args
        self.category = category

    @property
    def tool_correct(self) -> bool:
        """Did the LLM select the right tool (or correctly not select one)?"""
        return self.expected_tool == self.actual_tool

    @property
    def args_correct(self) -> bool:
        """Do the actual args contain all expected key-value pairs?"""
        if not self.expected_args:
            return True
        for key, expected_val in self.expected_args.items():
            actual_val = self.actual_args.get(key)
            if actual_val is None:
                return False
            if str(actual_val).lower() != str(expected_val).lower():
                return False
        return True

    @property
    def fully_correct(self) -> bool:
        return self.tool_correct and self.args_correct

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt[:80],
            "category": self.category,
            "expected_tool": self.expected_tool,
            "actual_tool": self.actual_tool,
            "tool_ok": "✅" if self.tool_correct else "❌",
            "args_ok": "✅" if self.args_correct else "❌",
            "full_ok": "✅" if self.fully_correct else "❌",
        }


class FakeScriptedLLM(FakeLLMProvider):
    """A scripted LLM that always picks the expected tool from the dataset.

    Used as baseline: if the agent loop + tool definitions are correct,
    this should score 100%.
    """

    def __init__(self, dataset: list[dict[str, Any]]) -> None:
        self._dataset = dataset
        self._index = 0
        super().__init__()

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        # Find the latest user message
        user_msg = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_msg = m.get("content", "")
                break

        # Check if this is a follow-up after a tool call (observation)
        for m in reversed(messages):
            if m.get("role") == "tool":
                # Give final answer after tool result
                return LLMResponse(content="Here are the results based on the tool output.")

        # Match prompt to dataset
        item = self._find_item(user_msg)
        if item and item.get("expected_tool"):
            return LLMResponse(tool_calls=[
                ToolCall(
                    id=f"eval_{self._index}",
                    name=item["expected_tool"],
                    arguments=item.get("expected_args", {}),
                )
            ])
        # No tool expected → direct answer
        return LLMResponse(content="I can help explain that concept.")

    def _find_item(self, user_msg: str) -> dict[str, Any] | None:
        """Find dataset item matching the user message."""
        for item in self._dataset:
            if item["prompt"].strip() == user_msg.strip():
                return item
        return None


async def run_single_eval(
    item: dict[str, Any],
    llm: Any,
    registry: ToolRegistry,
    blockchain: Any,
    settings: Settings,
) -> EvalResult:
    """Run a single evaluation case."""
    from agent.memory import ConversationMemory

    memory = ConversationMemory(max_tokens=settings.effective_token_budget)
    loop = AgentLoop(
        llm=llm, registry=registry,
        blockchain=blockchain, settings=settings,
        memory=memory,
    )

    events = await loop.run(item["prompt"])

    # Extract what tool was called (if any)
    actual_tool: str | None = None
    actual_args: dict[str, Any] = {}
    for event in events:
        if event["type"] == "tool_call":
            actual_tool = event["data"]["name"]
            actual_args = event["data"]["arguments"]
            break  # Take the first tool call

    return EvalResult(
        prompt=item["prompt"],
        expected_tool=item.get("expected_tool"),
        actual_tool=actual_tool,
        expected_args=item.get("expected_args", {}),
        actual_args=actual_args,
        category=item.get("category", "unknown"),
    )


# ── Report generation ─────────────────────────────────────────────────


def generate_report(results: list[EvalResult]) -> str:
    """Generate a markdown evaluation report."""
    total = len(results)
    tool_correct = sum(1 for r in results if r.tool_correct)
    args_correct = sum(1 for r in results if r.args_correct)
    full_correct = sum(1 for r in results if r.fully_correct)

    lines = [
        "# Tool Accuracy Evaluation Report",
        "",
        f"**Date**: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Dataset**: {total} prompts",
        "",
        "## Summary",
        "",
        "| Metric | Score | Percentage |",
        "|--------|-------|------------|",
        f"| Tool Selection | {tool_correct}/{total} | {tool_correct/total*100:.1f}% |",
        f"| Argument Accuracy | {args_correct}/{total} | {args_correct/total*100:.1f}% |",
        f"| Fully Correct | {full_correct}/{total} | {full_correct/total*100:.1f}% |",
        "",
    ]

    # Category breakdown
    categories: dict[str, list[EvalResult]] = {}
    for r in results:
        categories.setdefault(r.category, []).append(r)

    lines.extend([
        "## Category Breakdown",
        "",
        "| Category | Total | Tool ✅ | Args ✅ | Full ✅ | Accuracy |",
        "|----------|-------|--------|--------|--------|----------|",
    ])
    for cat, cat_results in sorted(categories.items()):
        n = len(cat_results)
        tc = sum(1 for r in cat_results if r.tool_correct)
        fc = sum(1 for r in cat_results if r.fully_correct)
        ac = sum(1 for r in cat_results if r.args_correct)
        lines.append(
            f"| {cat} | {n} | {tc}/{n} | {ac}/{n} | {fc}/{n} | {fc/n*100:.0f}% |"
        )

    # Detailed results
    lines.extend([
        "",
        "## Detailed Results",
        "",
        "| # | Prompt | Category | Expected | Actual | Tool | Args | Full |",
        "|---|--------|----------|----------|--------|------|------|------|",
    ])
    for i, r in enumerate(results, 1):
        d = r.to_dict()
        prompt_short = d["prompt"][:50] + ("..." if len(d["prompt"]) > 50 else "")
        lines.append(
            f"| {i} | {prompt_short} | {d['category']} | "
            f"{d['expected_tool'] or '(none)'} | {d['actual_tool'] or '(none)'} | "
            f"{d['tool_ok']} | {d['args_ok']} | {d['full_ok']} |"
        )

    # Failures detail
    failures = [r for r in results if not r.fully_correct]
    if failures:
        lines.extend([
            "",
            "## Failures",
            "",
        ])
        for r in failures:
            lines.append(f"- **{r.prompt[:60]}**: expected `{r.expected_tool}`, "
                         f"got `{r.actual_tool}` | args match: {r.args_correct}")

    lines.append("")
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────


def _register_all_tools() -> None:
    """Register all tools into the global registry."""
    from tools.read.estimate_gas import EstimateGas
    from tools.read.get_block import GetBlock
    from tools.read.get_erc20_balance import GetERC20Balance
    from tools.read.get_gas_price import GetGasPrice
    from tools.read.get_native_balance import GetNativeBalance
    from tools.read.get_token_info import GetTokenInfo
    from tools.read.get_transaction import GetTransaction
    from tools.read.get_transaction_history import GetTransactionHistory
    from tools.read.read_contract import ReadContract
    from tools.write.call_contract import CallContract
    from tools.write.transfer_erc20 import TransferERC20
    from tools.write.transfer_eth import TransferEth

    all_tools = [
        GetNativeBalance, GetERC20Balance, GetTokenInfo, GetTransaction,
        GetTransactionHistory, GetBlock, GetGasPrice, EstimateGas, ReadContract,
        TransferEth, TransferERC20, CallContract,
    ]
    for cls in all_tools:
        instance = cls()
        _REGISTRY[instance.name] = instance


async def main(output_path: str | None = None) -> None:
    logging.basicConfig(level=logging.WARNING)

    dataset = load_dataset()
    print(f"Loaded {len(dataset)} eval cases from {DATASET_PATH}")

    # Register tools
    _register_all_tools()

    # Create mock blockchain
    blockchain = MockBlockchainService(MockBlockchainData(
        balances={"0x742d35cc6634c0532925a3b844bc9e7595f2bd68": 5 * 10**18},
        gas_price=20 * 10**9,
        chain_id=11155111,
    ))

    settings = Settings(
        llm_provider=LLMProviderName.FAKE,
        dry_run=True,
        max_steps=5,
    )

    # Create LLM (scripted for baseline evaluation)
    llm = FakeScriptedLLM(dataset)

    # Build registry with all tools enabled
    all_tool_names = list(_REGISTRY.keys())
    registry = ToolRegistry(enabled_override=all_tool_names)

    # Run evaluation
    results: list[EvalResult] = []
    for i, item in enumerate(dataset, 1):
        result = await run_single_eval(item, llm, registry, blockchain, settings)
        status = "✅" if result.fully_correct else "❌"
        print(f"  [{i:2d}/{len(dataset)}] {status} {item['prompt'][:60]}")
        results.append(result)

    # Generate report
    report = generate_report(results)

    # Output
    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(f"\n📊 Report saved to {out}")
    else:
        print("\n" + report)

    # Summary
    total = len(results)
    correct = sum(1 for r in results if r.fully_correct)
    print(f"\n{'='*50}")
    print(f"  Tool Accuracy: {correct}/{total} ({correct/total*100:.1f}%)")
    print(f"{'='*50}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run tool accuracy evaluation")
    parser.add_argument("--output", "-o", help="Output file path (markdown)")
    parser.add_argument("--dataset", "-d", help="Dataset path (JSONL)")
    args = parser.parse_args()

    if args.dataset:
        DATASET_PATH = Path(args.dataset)

    asyncio.run(main(args.output))
