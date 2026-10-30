"""Context budgets, pure policy checks and session cleanup across module boundaries."""

import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from web3 import Web3

from agent.llm.base import TokenCounter
from agent.llm.fake import FakeLLMProvider
from agent.memory import ConversationMemory
from backend.agent.read_runtime import ReadAgentRuntime
from backend.agent.retrieval_context import build_retrieval_context
from backend.guardrail.models import PolicyConfig
from backend.guardrail.rules import check_write_request
from config.settings import Settings
from rag.retriever import RetrievalUnavailable, SourceScope


def chunk(content, doc_id):
    return {
        "content": content,
        "score": 0.4,
        "metadata": {
            "doc_id": doc_id,
            "title": doc_id,
            "source_path": "source.md",
            "scope": "source_only",
            "doc_version": "v1",
        },
    }


class AgentBoundaryTests(unittest.TestCase):
    def context(self, chunks, counter):
        return build_retrieval_context(
            query="question",
            retrieval_query="question",
            chunks=chunks,
            chain_id=31337,
            wallet="0x" + "11" * 20,
            transactions=None,
            memory=ConversationMemory(counter=counter),
            token_budget=300,
        )

    def test_context_uses_conversation_tokenizer_and_skips_only_oversized_chunks(self):
        counter = MagicMock(spec=TokenCounter)
        counter.count.side_effect = lambda text: 101 if "OVERSIZED" in text else 1
        context, result = self.context(
            [chunk("OVERSIZED", "large"), chunk("Fits the tokenizer budget", "small")], counter
        )
        self.assertNotIn("OVERSIZED", context)
        self.assertIn("Fits the tokenizer budget", context)
        self.assertEqual([doc.doc_id for doc in result.documents], ["small"])

    def test_context_fails_closed_when_no_document_fits(self):
        counter = MagicMock(spec=TokenCounter)
        counter.count.return_value = 101
        with self.assertRaisesRegex(RetrievalUnavailable, "No retrieved chunk fits"):
            self.context([chunk("Too large", "large")], counter)

    def test_pure_rules_do_not_mutate_input_or_share_policy_configuration(self):
        recipient = Web3.to_checksum_address("0x" + "ab" * 20)
        parameters = {"recipient": recipient.lower(), "amount": "0.1"}
        strict = PolicyConfig(max_native_transfer_limit=Decimal("0.05"))
        relaxed = PolicyConfig(max_native_transfer_limit=Decimal("0.5"))
        whitelist = {recipient}
        sanitized, violations = check_write_request(
            "native_transfer", parameters, {"isValid": True}, strict, whitelist
        )
        self.assertEqual(sanitized["recipient"], recipient)
        self.assertIn("exceeds native transfer limit", violations[0])
        _, allowed = check_write_request(
            "native_transfer", parameters, {"isValid": True}, relaxed, whitelist
        )
        self.assertEqual(allowed, [])
        self.assertEqual(parameters, {"recipient": recipient.lower(), "amount": "0.1"})
        self.assertEqual(whitelist, {recipient})
        self.assertEqual(strict.max_native_transfer_limit, Decimal("0.05"))


class AgentSessionCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_completed_turn_cleanup_does_not_exhaust_session_capacity(self):
        llm = FakeLLMProvider()
        runtime = ReadAgentRuntime(
            blockchain=MagicMock(chain_id=31337),
            retriever=MagicMock(scope=SourceScope("v1"), retrieve=AsyncMock(return_value=[])),
            llm=llm,
            settings=Settings(_env_file=None, llm_provider="fake"),
        )
        for index in range(101):
            session_id = f"completed-turn-{index}"
            await runtime.process_message(
                "question", wallet="0x" + "11" * 20, session_id=session_id
            )
            runtime.clear_session(session_id)
        self.assertEqual(runtime.service.list_sessions(), [])
        self.assertEqual(len(llm.call_history), 101)
