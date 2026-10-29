"""Select retrieval scope and verify it against the active deployment."""

import hashlib
import json
from pathlib import Path
from typing import Any

from backend.bootstrap.runtime import ApplicationRuntime
from rag.models import DeploymentScope
from rag.retriever import RAGRetriever, SourceScope


async def create_retriever(runtime: ApplicationRuntime, root: Path) -> RAGRetriever:
    manifest = json.loads((root / "knowledge/manifest.json").read_text(encoding="utf-8"))
    if runtime.profile.chain_id == 31337:
        versions = {
            source["doc_version"]
            for source in manifest["sources"]
            if source["scope"] == "source_only" and source["usage"] == "ingest"
        }
        if len(versions) != 1:
            raise ValueError("Select an explicit source version for local retrieval")
        scope = SourceScope(versions.pop(), include_general=True)
    else:
        scope = DeploymentScope(**manifest["deployment_scope"])
    return await RAGRetriever.create(root=root, scope=scope)


def validate_retriever(runtime: ApplicationRuntime, retriever: Any, root: Path) -> None:
    scope = retriever.scope
    if runtime.profile.chain_id == 31337:
        if not isinstance(scope, SourceScope):
            raise ValueError("Local LLM runtime requires SourceScope, not a Sepolia deployment")
        return
    chain_id = runtime.profile.chain_id
    _, deployment = runtime.network_manager.load_deployment_manifest(chain_id)
    abi_text = (root / f"backend/abi/{chain_id}/AgentToken_abi.json").read_text(encoding="utf-8")
    abi_hash = "sha256:" + hashlib.sha256(abi_text.encode("utf-8")).hexdigest()
    if (
        not isinstance(scope, DeploymentScope)
        or scope.chain_id != chain_id
        or scope.contract_address.lower() != deployment["contractAddress"].lower()
        or scope.abi_hash != abi_hash
    ):
        raise ValueError("RAG deployment scope does not match the active chain/contract/ABI")
