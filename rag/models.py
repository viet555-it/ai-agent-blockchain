"""P1 data contracts; no model, database, agent or backend dependency."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, NotRequired, Protocol, TypedDict, runtime_checkable

Scope = Literal["general", "deployed_contract", "source_only", "policy_snapshot"]


class SourceMetadata(TypedDict):
    chunk_id: str
    doc_id: str
    title: str
    category: str
    source_path: str
    # Authored workspace documents have no containing Git commit until committed.
    source_commit: str | None
    content_hash: str
    scope: Scope
    doc_version: str
    chain_id: NotRequired[int]
    contract_address: NotRequired[str]
    abi_hash: NotRequired[str]
    function_signature: NotRequired[str]
    policy_version: NotRequired[str]
    verification_status: NotRequired[str]
    source_origin: NotRequired[Literal["git", "workspace"]]


class Chunk(TypedDict):
    """Matches the agent protocol; structured source fields live in metadata.

    ``score`` is ranking relevance (higher is better), not confidence in an
    answer. The retrieval implementation must document its metric in P5.
    """

    content: str
    metadata: dict[str, Any]
    score: float


@runtime_checkable
class Retriever(Protocol):
    async def retrieve(self, query: str, k: int = 5) -> list[Chunk]: ...


@dataclass(frozen=True)
class DeploymentScope:
    """Bind one retriever instance to one repository-declared deployment.

    This validates identifiers, not live RPC state or permission to transact.
    ABI hashes use sha256 of UTF-8 source text with LF line endings.
    """

    chain_id: int
    contract_address: str
    abi_hash: str
    doc_version: str
    include_general: bool = True

    def __post_init__(self) -> None:
        if type(self.chain_id) is not int or self.chain_id <= 0:
            raise ValueError("chain_id must be a positive integer")
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}", self.contract_address):
            raise ValueError("contract_address must be a 20-byte hex address")
        if int(self.contract_address[2:], 16) == 0:
            raise ValueError("contract_address must not be the zero address")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.abi_hash):
            raise ValueError("abi_hash must be a lowercase sha256 digest")
        if not self.doc_version.strip():
            raise ValueError("doc_version must not be empty")
        if type(self.include_general) is not bool:
            raise ValueError("include_general must be a boolean")

    def accepts(self, metadata: dict[str, Any]) -> bool:
        """Fail closed on source-only, policy, unknown or mismatched scopes."""
        if metadata.get("scope") == "general":
            return self.include_general
        address = metadata.get("contract_address")
        return (
            metadata.get("scope") == "deployed_contract"
            and type(metadata.get("chain_id")) is int
            and metadata["chain_id"] == self.chain_id
            and isinstance(address, str)
            and address.lower() == self.contract_address.lower()
            and metadata.get("abi_hash") == self.abi_hash
            and metadata.get("doc_version") == self.doc_version
        )
