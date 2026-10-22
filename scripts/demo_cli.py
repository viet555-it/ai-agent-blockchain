"""Interactive CLI demo for the AI Agent.

Usage:
    python -m scripts.demo_cli
    # or
    .venv/Scripts/python -m scripts.demo_cli

Supports hot-swapping LLM provider via env vars:
    LLM_PROVIDER=gemini python -m scripts.demo_cli
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()


BANNER = """
╔══════════════════════════════════════════════════════════╗
║       🤖 AI Agent with Blockchain Tools (Sepolia)        ║
║          Hanoi University – ATI Project                   ║
╚══════════════════════════════════════════════════════════╝
Type your question (or 'exit'/'quit' to stop).
Example queries:
  • "What is the ETH balance of 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045?"
  • "Get the current gas price"
  • "Show me transaction 0x..."
"""


async def main() -> None:
    from agent.service import AgentService
    from config.settings import get_settings

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    # Quiet noisy loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    settings = get_settings()
    print(BANNER)
    print(f"  LLM Provider: {settings.llm_provider.value}")
    print(f"  Model: {settings.llm_model or '(default)'}")
    print(f"  Network: Sepolia (RPC: {settings.sepolia_rpc_url[:40]}...)")
    print(f"  Dry Run: {settings.dry_run}")
    print()

    try:
        service = AgentService.create(settings)
    except Exception as e:
        print(f"\n❌ Failed to initialize agent: {e}")
        print("   Check your .env file (API keys, RPC URL).")
        return

    session_id = "cli-session-1"

    while True:
        try:
            user_input = input("\n🧑 You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Bye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "q"):
            print("👋 Bye!")
            break
        if user_input.lower() == "clear":
            service.clear_session(session_id)
            print("🔄 Conversation cleared.")
            continue

        print()
        try:
            events = await service.chat(session_id, user_input)
        except Exception as e:
            print(f"❌ Error: {e}")
            continue

        for event in events:
            match event.type:
                case "thought":
                    print(f"  💭 Thought: {event.data['content']}")
                case "tool_call":
                    print(
                        f"  🔧 Calling: {event.data['name']}"
                        f"({json.dumps(event.data['arguments'], ensure_ascii=False)})"
                    )
                case "tool_result":
                    result = event.data.get("result", {})
                    status = "✅" if result.get("ok") else "❌"
                    duration = event.data.get("duration_ms")
                    dur_str = f" [{duration:.0f}ms]" if duration else ""
                    if result.get("ok"):
                        print(f"  {status}{dur_str} → {json.dumps(result.get('data'), indent=2, ensure_ascii=False)}")
                    else:
                        print(f"  {status}{dur_str} → Error: {result.get('error')}")
                case "final":
                    print(f"\n🤖 Agent: {event.data['content']}")
                case "error":
                    print(f"\n❌ Agent error: {event.data['error']}")


if __name__ == "__main__":
    asyncio.run(main())
