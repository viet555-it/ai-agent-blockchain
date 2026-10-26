"""Load only manifest-approved sources; no network, model or database access."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from rag.models import DeploymentScope


class SourceError(ValueError):
    """Invalid manifest, source, hash or provenance. Never silently skip it."""


@dataclass(frozen=True)
class SourceDocument:
    text: str
    source_format: str
    metadata: dict[str, Any]


def content_hash(text: str) -> str:
    """Manifest v2 hash: UTF-8 with CRLF normalized to LF, nothing else."""
    return "sha256:" + hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SourceError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json(text: str, label: str) -> Any:
    def reject_constant(value: str) -> None:
        raise SourceError(f"Non-finite JSON value: {value}")

    try:
        return json.loads(text, object_pairs_hook=_unique_object, parse_constant=reject_constant)
    except (ValueError, RecursionError) as exc:
        raise SourceError(f"{label}: invalid JSON: {exc}") from exc


def _read(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeError) as exc:
        raise SourceError(f"Cannot read UTF-8 source {path}: {exc}") from exc


def _path(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or "\x00" in value:
        raise SourceError("source_path must be a relative POSIX path")
    posix = PurePosixPath(value)
    if posix.is_absolute() or PureWindowsPath(value).drive or ".." in posix.parts:
        raise SourceError(f"Source outside root: {value}")
    if posix.as_posix() != value or value == ".":
        raise SourceError(f"Non-canonical source_path: {value}")
    target = (root / value).resolve()
    if not target.is_relative_to(root):
        raise SourceError(f"Source symlink escapes root: {value}")
    return target


def _hash_field(value: Any, label: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise SourceError(f"{label} must be a lowercase sha256 digest")


def _reference(root: Path, item: Any, verify_git: bool, *, read_workspace: bool) -> None:
    if not isinstance(item, dict):
        raise SourceError("Provenance reference must be an object")
    target = _path(root, item.get("source_path"))
    _hash_field(item.get("content_hash"), "content_hash")
    origin = item.get("source_origin")
    commit = item.get("source_commit")
    if origin == "git":
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise SourceError("Git provenance needs a full 40-character source_commit")
        if verify_git:
            try:
                raw = subprocess.check_output(
                    ["git", "show", f"{commit}:{item['source_path']}"],
                    cwd=root, stderr=subprocess.PIPE, timeout=15,
                )
                text = raw.decode("utf-8")
            except (OSError, UnicodeError, subprocess.SubprocessError) as exc:
                raise SourceError(f"Cannot verify Git evidence: {item['source_path']}") from exc
            if content_hash(text) != item["content_hash"]:
                raise SourceError(f"Git evidence hash mismatch: {item['source_path']}")
    elif origin == "workspace":
        if "source_commit" not in item or commit is not None:
            raise SourceError("Workspace source_commit must explicitly be null")
        if read_workspace and content_hash(_read(target)) != item["content_hash"]:
            raise SourceError(f"Workspace evidence hash mismatch: {item['source_path']}")
    else:
        raise SourceError("source_origin must be git or workspace")


def abi_type(param: Any) -> str:
    """Validate ABI types and expand tuple signatures, preserving array suffixes."""
    if not isinstance(param, dict) or not isinstance(param.get("type"), str):
        raise SourceError("ABI parameter needs a type")
    match = re.fullmatch(r"([A-Za-z][A-Za-z0-9]*)(\[(?:[1-9][0-9]*)?\])*", param["type"])
    if not match:
        raise SourceError(f"Invalid ABI type: {param['type']}")
    base = param["type"].split("[", 1)[0]
    suffix = param["type"][len(base):]
    if base == "tuple":
        components = param.get("components")
        if not isinstance(components, list) or not components:
            raise SourceError("ABI tuple needs components")
        return "(" + ",".join(abi_type(p) for p in components) + ")" + suffix
    integers = {f"{kind}{size}" for kind in ("int", "uint") for size in range(8, 257, 8)}
    fixed_bytes = {f"bytes{size}" for size in range(1, 33)}
    if base not in {"address", "bool", "string", "bytes", "function"} | integers | fixed_bytes:
        raise SourceError(f"Unsupported ABI type: {base}")
    return base + suffix


def abi_signature(entry: dict[str, Any]) -> str:
    name = entry.get("name", entry["type"])
    return name + "(" + ",".join(abi_type(param) for param in entry.get("inputs", [])) + ")"


def validate_abi(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise SourceError("ABI must be a non-empty array")
    seen: set[tuple[str, str]] = set()
    for entry in value:
        if not isinstance(entry, dict):
            raise SourceError("ABI entries must be objects")
        kind = entry.get("type")
        if kind not in {"constructor", "function", "event", "error", "fallback", "receive"}:
            raise SourceError(f"Unknown ABI entry type: {kind}")
        if kind in {"function", "event", "error"}:
            if not isinstance(entry.get("name"), str) or not re.fullmatch(r"[A-Za-z_$][\w$]*", entry["name"]):
                raise SourceError("ABI function/event/error needs a valid name")
        for field in ("inputs", "outputs"):
            required = field == "inputs" and kind in {"constructor", "function", "event", "error"}
            required = required or (field == "outputs" and kind == "function")
            if required or field in entry:
                if not isinstance(entry.get(field), list):
                    raise SourceError(f"ABI {field} must be an array")
                for param in entry[field]:
                    abi_type(param)
                    if "name" in param and not isinstance(param["name"], str):
                        raise SourceError("ABI parameter name must be a string")
                    if kind == "event" and type(param.get("indexed")) is not bool:
                        raise SourceError("Event parameter indexed must be boolean")
        if kind in {"function", "constructor", "fallback", "receive"}:
            allowed = {"view", "pure", "nonpayable", "payable"} if kind == "function" else {"nonpayable", "payable"}
            if entry.get("stateMutability") not in allowed:
                raise SourceError("Missing or invalid ABI stateMutability")
            if kind == "receive" and entry["stateMutability"] != "payable":
                raise SourceError("ABI receive must be payable")
        identity = (kind, abi_signature(entry) if kind not in {"constructor", "fallback", "receive"} else kind)
        if identity in seen:
            raise SourceError(f"Duplicate ABI entry: {identity}")
        seen.add(identity)
    return value


def load_corpus(manifest_path: str | Path, *, root: str | Path, verify_git: bool = False) -> list[SourceDocument]:
    """Load schema v2; reject invalid or stale sources instead of partial results.

    Ingested file hashes are always checked. Optional Git verification checks pinned
    evidence objects offline; it requires a checkout containing those commits.
    Reference-only content is never returned as an ingestion document.
    """
    root = Path(root).resolve()
    path = Path(manifest_path)
    if not path.is_absolute():
        path = root / path
    if not path.resolve().is_relative_to(root):
        raise SourceError("Manifest must be inside root")
    manifest = parse_json(_read(path), str(path))
    if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 2:
        raise SourceError("Expected manifest schema_version 2")
    try:
        deployment = DeploymentScope(**manifest["deployment_scope"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceError(f"Invalid manifest deployment_scope: {exc}") from exc
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise SourceError("Manifest sources must be a non-empty array")
    docs: list[SourceDocument] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    seen_content: set[tuple[Any, ...]] = set()
    for source in sources:
        if not isinstance(source, dict):
            raise SourceError("Each manifest source must be an object")
        for field in ("doc_id", "title", "category", "doc_version", "verification_status"):
            if not isinstance(source.get(field), str) or not source[field].strip():
                raise SourceError(f"Source needs non-empty {field}")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", source["doc_id"]):
            raise SourceError("Invalid doc_id")
        _reference(root, source, verify_git, read_workspace=False)
        source_path = source["source_path"]
        if source["doc_id"] in seen_ids or source_path.casefold() in seen_paths:
            raise SourceError(f"Duplicate source ID/path: {source_path}")
        seen_ids.add(source["doc_id"])
        seen_paths.add(source_path.casefold())
        if source.get("scope") not in {"general", "deployed_contract", "source_only", "policy_snapshot"}:
            raise SourceError(f"Invalid scope: {source_path}")
        if "contract_address" in source and not isinstance(source["contract_address"], str):
            raise SourceError("contract_address must be a string")
        if source["scope"] == "deployed_contract" and not deployment.accepts(source):
            raise SourceError(f"Deployment metadata does not match manifest scope: {source_path}")
        if source["scope"] == "policy_snapshot" and not source.get("policy_version"):
            raise SourceError("policy_snapshot requires policy_version")
        if source.get("usage") not in {"ingest", "reference_only"}:
            raise SourceError("usage must be ingest or reference_only")
        evidence = source.get("derived_from", [])
        if not isinstance(evidence, list):
            raise SourceError("derived_from must be an array")
        if source["source_origin"] == "workspace" and not evidence:
            raise SourceError("Authored source needs derived_from evidence")
        for reference in evidence:
            _reference(root, reference, verify_git, read_workspace=True)
        if source["usage"] == "reference_only":
            continue
        fmt = source.get("source_format")
        expected_suffix = {"markdown": ".md", "abi_json": ".json", "deployment_json": ".json"}
        if fmt not in expected_suffix or PurePosixPath(source_path).suffix != expected_suffix[fmt]:
            raise SourceError(f"Unsupported ingestion format/extension: {source_path}")
        text = _read(_path(root, source_path))
        if not text.strip():
            raise SourceError(f"Empty ingestion source: {source_path}")
        if content_hash(text) != source["content_hash"]:
            raise SourceError(f"Source hash mismatch: {source_path}")
        if fmt == "abi_json":
            validate_abi(parse_json(text, source_path))
            if source.get("abi_hash") != source["content_hash"]:
                raise SourceError("ABI hash must match ABI source content_hash")
        elif fmt == "deployment_json":
            value = parse_json(text, source_path)
            if not isinstance(value, dict) or type(value.get("chainId")) not in (int, str):
                raise SourceError("Deployment requires chainId")
            chain = str(value["chainId"])
            address = value.get("contractAddress")
            if chain != str(deployment.chain_id) or not isinstance(address, str) or address.lower() != deployment.contract_address.lower():
                raise SourceError("Deployment content does not match scope")
        duplicate = (source["content_hash"], source["scope"], source["doc_version"], source.get("chain_id"),
                     source.get("contract_address", "").lower(), source.get("abi_hash"), fmt)
        if duplicate in seen_content:
            raise SourceError(f"Duplicate content in same scope; choose a canonical source: {source_path}")
        seen_content.add(duplicate)
        docs.append(SourceDocument(text=text, source_format=fmt, metadata=copy.deepcopy(source)))
    return docs
