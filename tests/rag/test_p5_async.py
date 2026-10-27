import asyncio
import threading
import unittest
from dataclasses import replace

from rag.models import DeploymentScope
from rag.retriever import (
    InvalidQuery, RAGRetriever, RetrievalOptions, RetrievalTimeout,
    RetrievalUnavailable, SourceScope, explicit_signatures,
)


SCOPE = DeploymentScope(11155111, "0x" + "1" * 40, "sha256:" + "a" * 64, "v1")


class BlockingRetriever(RAGRetriever):
    def __init__(self, **kwargs):
        super().__init__(None, None, SCOPE, **kwargs)
        self.started = threading.Event()
        self.release_worker = threading.Event()
        self.calls = 0

    def _search(self, query, k):
        self.calls += 1
        self.started.set()
        self.release_worker.wait(timeout=2)
        return []


class AsyncRetrieverTest(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_query_and_k_do_not_submit_background_work(self):
        retriever = BlockingRetriever()
        self.addAsyncCleanup(retriever.aclose)
        for query, k in (("", 5), ("  ", 5), (None, 5), ("x" * 2001, 5),
                         ("hello", 0), ("hello", 11), ("hello", True)):
            with self.subTest(query=str(query)[:20], k=k), self.assertRaises(InvalidQuery):
                await retriever.retrieve(query, k)
        self.assertEqual(retriever.calls, 0)

    async def test_work_runs_off_event_loop_and_holds_slot_after_timeout(self):
        retriever = BlockingRetriever(options=RetrievalOptions(timeout_seconds=0.08))
        self.addAsyncCleanup(retriever.aclose)
        self.addCleanup(retriever.release_worker.set)
        first = asyncio.create_task(retriever.retrieve("first"))
        for _ in range(100):
            if retriever.started.is_set():
                break
            await asyncio.sleep(0.001)
        self.assertTrue(retriever.started.is_set())
        # This coroutine continues while the synchronous worker is blocked.
        self.assertFalse(first.done())
        with self.assertRaises(RetrievalTimeout):
            await first
        with self.assertRaises(RetrievalTimeout):
            await retriever.retrieve("must not spawn another worker")
        self.assertEqual(retriever.calls, 1)
        retriever.release_worker.set()
        for _ in range(100):
            if retriever._slots._value == 1:
                break
            await asyncio.sleep(0.002)
        self.assertEqual(await retriever.retrieve("after completion"), [])

    async def test_cancelling_a_request_does_not_release_running_worker_early(self):
        retriever = BlockingRetriever(options=RetrievalOptions(timeout_seconds=0.08))
        self.addAsyncCleanup(retriever.aclose)
        self.addCleanup(retriever.release_worker.set)
        task = asyncio.create_task(retriever.retrieve("cancel me"))
        for _ in range(100):
            if retriever.started.is_set():
                break
            await asyncio.sleep(0.001)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        with self.assertRaises(RetrievalTimeout):
            await retriever.retrieve("still busy")
        self.assertEqual(retriever.calls, 1)
        retriever.release_worker.set()

    async def test_closed_retriever_and_missing_index_are_errors_not_no_match(self):
        retriever = RAGRetriever(None, None, SCOPE)
        await retriever.aclose()
        with self.assertRaises(RetrievalUnavailable):
            await retriever.retrieve("hello")
        live = RAGRetriever(None, None, SCOPE)
        self.addAsyncCleanup(live.aclose)
        with self.assertRaises(RetrievalUnavailable):
            await live.retrieve("hello")


class RetrieverContractTest(unittest.TestCase):
    def test_signature_parser_handles_overloads_and_tuples_not_parameter_values(self):
        self.assertEqual(explicit_signatures("transfer (address, uint256)"), {"transfer(address,uint256)"})
        self.assertEqual(explicit_signatures("foo((address,uint256)[],bytes32)"), {"foo((address,uint256)[],bytes32)"})
        self.assertEqual(explicit_signatures("decimals() and balanceOf(address)"), {"decimals()", "balanceOf(address)"})
        self.assertEqual(explicit_signatures("transfer(0x123,5)"), set())

    def test_options_and_source_scope_validation(self):
        for key, value in (("min_similarity", float("nan")), ("timeout_seconds", 0),
                           ("max_concurrency", True), ("candidate_pool", 1),
                           ("general_categories", "web3")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                replace(RetrievalOptions(), **{key: value})
        source = SourceScope("source-v1", include_general=False)
        self.assertTrue(source.accepts({"scope": "source_only", "doc_version": "source-v1"}))
        self.assertFalse(source.accepts({"scope": "deployed_contract", "doc_version": "source-v1"}))
        self.assertFalse(source.accepts({"scope": "source_only", "doc_version": "source-v2"}))
        self.assertFalse(source.accepts({"scope": "general"}))


if __name__ == "__main__":
    unittest.main()
