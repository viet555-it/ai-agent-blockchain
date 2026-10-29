"""Disposable test fixture only: FakeLLM and a loopback Hardhat node owned by the runner."""

import json
import os
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from web3 import Web3

from agent.llm.base import LLMResponse, ToolCall
from agent.llm.fake import FakeLLMProvider
from backend.api.server import create_app
from backend.db.store import Database
from backend.guardrail.policy_engine import PolicyConfig, PolicyEngine
from backend.services.blockchain_service import BlockchainService
from backend.wallet_settings import WalletSettings
from config.settings import Settings
from rag.retriever import SourceScope


class WalletTestLLM(FakeLLMProvider):
    async def chat(self, messages, tools=None):
        query = next(item["content"] for item in reversed(messages) if item["role"] == "user")
        system = next(item["content"] for item in messages if item["role"] == "system")
        wallet = re.search(r'"active_wallet": "(0x[0-9a-fA-F]+)"', system).group(1)
        if messages[-1]["role"] == "tool":
            return LLMResponse(content="Read complete.")
        if "faucet" in query.lower():
            return LLMResponse(
                tool_calls=[ToolCall(id="claim", name="faucet_claim", arguments={"amount": "10"})]
            )
        if "balance" in query.lower():
            return LLMResponse(
                tool_calls=[
                    ToolCall(id="balance", name="get_native_balance", arguments={"address": wallet})
                ]
            )
        return LLMResponse(content="Test response")


def create():
    if os.environ.get("WALLET_E2E_TEST") != "1":
        raise RuntimeError("This fixture is only available to the wallet E2E runner")
    rpc = os.environ["WALLET_E2E_RPC"]
    if not rpc.startswith("http://127.0.0.1:"):
        raise RuntimeError("The fixture requires an owned loopback RPC")
    root = Path(os.environ["WALLET_E2E_DIRECTORY"]).resolve()
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 5}))
    if w3.eth.chain_id != 31337 or "hardhat" not in w3.client_version.lower():
        raise RuntimeError("Only Hardhat local is supported")
    artifact = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "contracts/artifacts/src/AgentToken.sol/AgentToken.json"
        ).read_text()
    )
    receipt = w3.eth.wait_for_transaction_receipt(
        w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])
        .constructor(w3.eth.accounts[0], 1000000)
        .transact({"from": w3.eth.accounts[0]})
    )
    target = root / "abi/31337"
    target.mkdir(parents=True)
    (target / "AgentToken_abi.json").write_text(json.dumps(artifact["abi"]))
    (target / "deployment.json").write_text(
        json.dumps(
            {
                "chainId": "31337",
                "contractAddress": receipt.contractAddress,
                "runtimeCodeHash": Web3.to_hex(w3.keccak(w3.eth.get_code(receipt.contractAddress))),
            }
        )
    )
    import backend.network.network_manager as network

    network.BACKEND_ABI_DIR = root / "abi"
    url = "sqlite:///" + (root / "test.db").as_posix()
    database = Database(url)
    database.migrate()
    database.close()
    blockchain = BlockchainService(w3=w3, chain_id=31337)
    return create_app(
        profile="local_evm",
        blockchain=blockchain,
        agent_mode="llm",
        enable_local_writes=False,
        wallet_settings=WalletSettings(url, origin=os.environ["APP_ORIGIN"], browser_writes=True),
        policy=PolicyEngine(PolicyConfig(recipient_whitelist=w3.eth.accounts[:3])),
        llm=WalletTestLLM(),
        retriever=MagicMock(scope=SourceScope("v1"), retrieve=AsyncMock(return_value=[])),
        agent_settings=Settings(_env_file=None, llm_provider="fake"),
    )
