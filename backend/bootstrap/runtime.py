"""Resolve and validate application configuration without opening runtime resources."""

import os
from dataclasses import dataclass
from typing import Any

from backend.guardrail.policy_engine import PolicyConfig, PolicyEngine
from backend.network.network_manager import NetworkManager
from backend.rag.rag_adapter import RAGAdapter
from backend.runtime_profiles import RuntimeProfile
from backend.wallet_settings import WalletSettings


@dataclass(frozen=True)
class ApplicationRuntime:
    profile: RuntimeProfile
    network_manager: NetworkManager
    policy: PolicyEngine
    rag: RAGAdapter
    wallet: str
    agent_mode: str
    local_writes: bool
    wallet_settings: WalletSettings | None
    sepolia_execution: Any = None

    @property
    def history_enabled(self) -> bool:
        return self.wallet_settings is not None


def resolve_runtime(
    *,
    profile: str | None = None,
    policy: PolicyEngine | None = None,
    rag: RAGAdapter | None = None,
    wallet: str | None = None,
    agent_mode: str | None = None,
    enable_local_writes: bool | None = None,
    sepolia_execution: Any = None,
    wallet_settings: WalletSettings | None = None,
) -> ApplicationRuntime:
    history_enabled = wallet_settings is not None or (
        profile != "unit" and os.environ.get("WALLET_HISTORY_ENABLED", "false").lower() == "true"
    )
    if history_enabled:
        wallet_settings = wallet_settings or WalletSettings.from_environment()
    runtime_profile = RuntimeProfile.load(
        profile, allow_sepolia_write=sepolia_execution is not None
    )
    if sepolia_execution is not None and (
        runtime_profile.name != "sepolia_write" or agent_mode != "llm"
    ):
        raise ValueError("Explicit Sepolia execution requires sepolia_write and llm mode")
    network_manager = NetworkManager({runtime_profile.chain_id: runtime_profile.network()})
    network_manager.set_active_chain_id(runtime_profile.chain_id)
    policy_engine = policy or PolicyEngine(PolicyConfig())
    rag_adapter = rag or RAGAdapter()
    mode = agent_mode or os.environ.get("PHASE3_AGENT", "legacy")
    if mode not in {"legacy", "llm"}:
        raise ValueError("PHASE3_AGENT must be legacy or llm")
    local_writes = enable_local_writes
    if local_writes is None:
        flag = os.environ.get("PHASE3_LOCAL_WRITES", "false").lower()
        if flag not in {"true", "false"}:
            raise ValueError("PHASE3_LOCAL_WRITES must be true or false")
        local_writes = flag == "true"
    if local_writes and (runtime_profile.name != "local_evm" or mode != "llm"):
        raise ValueError("Local writes require local_evm profile and llm agent mode")
    if history_enabled and mode != "llm":
        raise ValueError("Wallet history requires PHASE3_AGENT=llm")
    if history_enabled and sepolia_execution is not None:
        raise ValueError("Browser-wallet history cannot share the legacy Sepolia execution grant")
    demo_wallet = wallet or os.environ.get("DEMO_WALLET_ADDRESS")
    if not demo_wallet:
        if runtime_profile.chain_id == 31337:
            demo_wallet = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
        else:
            _, manifest = network_manager.load_deployment_manifest(runtime_profile.chain_id)
            demo_wallet = manifest["deployer"]
    if local_writes and policy is None:
        policy_engine = PolicyEngine(
            PolicyConfig(
                recipient_whitelist=[demo_wallet, *policy_engine.config.recipient_whitelist]
            )
        )
    if sepolia_execution is not None and policy is None:
        policy_engine = PolicyEngine(
            PolicyConfig(
                recipient_whitelist=[sepolia_execution.sender, sepolia_execution.recipient]
            )
        )
    return ApplicationRuntime(
        profile=runtime_profile,
        network_manager=network_manager,
        policy=policy_engine,
        rag=rag_adapter,
        wallet=demo_wallet,
        agent_mode=mode,
        local_writes=local_writes,
        wallet_settings=wallet_settings,
        sepolia_execution=sepolia_execution,
    )
