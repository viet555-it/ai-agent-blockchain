"""Deterministic, scope-preserving chunks with an explicitly supplied token budget."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from rag.loaders import SourceDocument, abi_signature, content_hash, parse_json, validate_abi

SPLITTER_VERSION = "rag-semantic-v2"


class ChunkingError(ValueError):
    """The supplied budget cannot represent a complete protected text unit."""


@dataclass(frozen=True)
class TokenBudget:
    """Count the exact text passed to the encoder, including special tokens.

    P4 supplies the model tokenizer, e.g. a callback returning the length of
    tokenizer.encode(text, add_special_tokens=True, truncation=False), and the
    model's actual max sequence length. There is no implicit token estimator.
    """

    count_tokens: Callable[[str], int]
    max_tokens: int
    tokenizer_id: str
    unit: str = "tokens"

    def __post_init__(self) -> None:
        if not callable(self.count_tokens):
            raise ValueError("count_tokens must be callable")
        if type(self.max_tokens) is not int or self.max_tokens <= 0:
            raise ValueError("max_tokens must be a positive integer")
        if not isinstance(self.tokenizer_id, str) or not self.tokenizer_id.strip():
            raise ValueError("tokenizer_id must identify the counter/model revision")
        if self.unit not in {"tokens", "utf8_bytes"}:
            raise ValueError("Unsupported budget unit")

    def count(self, text: str) -> int:
        count = self.count_tokens(text)
        if type(count) is not int or count < 0:
            raise ChunkingError("Token counter must return a non-negative integer")
        return count


@dataclass(frozen=True)
class PreparedChunk:
    """Index input, not a scored retrieval result. Score is assigned in P5."""

    content: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"content": self.content, "metadata": copy.deepcopy(self.metadata)}


@dataclass(frozen=True)
class _Section:
    heading: str
    body: str
    signatures: tuple[str, ...] = ()
    entry_type: str | None = None


def _markdown_sections(text: str) -> list[_Section]:
    """ATX headings, preserving fenced code verbatim and nested heading context."""
    result: list[_Section] = []
    headings: list[tuple[int, str]] = []
    body: list[str] = []
    fence: tuple[str, int] | None = None

    def flush() -> None:
        if "".join(body).strip():
            heading = " > ".join(label for _, label in headings) or "Document"
            signatures = tuple(dict.fromkeys(re.findall(r"[A-Za-z_$][\w$]*\([^()\n]*\)", heading)))
            result.append(_Section(heading, "".join(body), signatures))
        body.clear()

    for line in text.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*?)(?:\n)?$", line)
        if fence is not None:
            body.append(line)
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= fence[1] and not marker[2].strip():
                fence = None
            continue
        if marker:
            fence = (marker[1][0], len(marker[1]))
            body.append(line)
            continue
        heading = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*(?:\n)?$", line)
        if heading:
            flush()
            level, title = len(heading[1]), heading[2]
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, title))
        else:
            body.append(line)
    if fence:
        raise ChunkingError("Unclosed Markdown code fence")
    flush()
    return result


def _sections(document: SourceDocument) -> list[_Section]:
    if document.source_format == "markdown":
        return _markdown_sections(document.text)
    if document.source_format == "abi_json":
        abi = validate_abi(parse_json(document.text, document.metadata["source_path"]))
        return [
            _Section(
                entry["type"] + " " + abi_signature(entry),
                json.dumps(entry, ensure_ascii=False, sort_keys=True, indent=2),
                (abi_signature(entry),), entry["type"],
            )
            for entry in abi
        ]
    if document.source_format == "deployment_json":
        value = parse_json(document.text, document.metadata["source_path"])
        return [_Section("Deployment manifest", json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))]
    raise ChunkingError(f"Unsupported source format: {document.source_format}")


def _text_units(text: str) -> list[str]:
    """Keep code fences, inline code and signatures atomic; never split a number/address.

    Whitespace units are retained so joining fragments recovers the complete
    section body. Oversized protected units raise an error rather than truncate.
    """
    blocks: list[str] = []
    pending: list[str] = []
    fence: tuple[str, int] | None = None
    pattern = re.compile(r"`[^`\n]+`|[A-Za-z_$][\w$]*\([^()\n]*\)|[^\s]+|\s+")

    def plain() -> None:
        blocks.extend(match[0] for match in pattern.finditer("".join(pending)))
        pending.clear()

    fenced_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*?)(?:\n)?$", line)
        if fence is not None:
            fenced_lines.append(line)
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= fence[1] and not marker[2].strip():
                blocks.append("".join(fenced_lines))
                fenced_lines.clear()
                fence = None
        elif marker:
            plain()
            fence = (marker[1][0], len(marker[1]))
            fenced_lines.append(line)
        else:
            pending.append(line)
    if fence:
        raise ChunkingError("Unclosed Markdown code fence")
    plain()
    return blocks


def _split_body(body: str, prefix: str, budget: TokenBudget) -> list[str]:
    if budget.count(prefix) >= budget.max_tokens:
        raise ChunkingError("Context prefix leaves no body budget; increase budget or shorten headings")
    if budget.count(prefix + body) <= budget.max_tokens:
        return [body]
    # Prefer whole paragraphs; only an oversized paragraph is broken at safe units.
    paragraphs: list[str] = []
    pending = ""
    for unit in _text_units(body):
        pending += unit
        if unit.isspace() and "\n\n" in unit:
            paragraphs.append(pending)
            pending = ""
    if pending:
        paragraphs.append(pending)
    fragments: list[str] = []
    current = ""
    for paragraph in paragraphs:
        units = [paragraph] if budget.count(prefix + paragraph) <= budget.max_tokens else _text_units(paragraph)
        for unit in units:
            if budget.count(prefix + current + unit) <= budget.max_tokens:
                current += unit
                continue
            if current:
                fragments.append(current)
                current = ""
            if budget.count(prefix + unit) > budget.max_tokens:
                raise ChunkingError("Protected text unit exceeds budget; increase budget or restructure source")
            current = unit
    if current:
        fragments.append(current)
    if "".join(fragments) != body:
        raise ChunkingError("Internal error: splitter did not preserve all section text")
    return fragments


def chunk_documents(
    documents: list[SourceDocument], *, budget: TokenBudget, prefix_style: str = "verbose",
) -> list[PreparedChunk]:
    if prefix_style not in {"verbose", "compact"}:
        raise ValueError("prefix_style must be verbose or compact")
    chunks: list[PreparedChunk] = []
    seen: set[str] = set()
    for document in documents:
        meta = document.metadata
        sections = _sections(document)
        if not sections:
            raise ChunkingError(f"No chunkable content: {meta['source_path']}")
        for section_index, section in enumerate(sections):
            prefix = (
                f"Tài liệu: {meta['title']}\n"
                f"Scope: {meta['scope']}; version: {meta['doc_version']}; "
                f"verification: {meta['verification_status']}\n"
                f"Mục: {section.heading}\n\n"
            )
            if prefix_style == "compact":
                # Keep full provenance in metadata; reserve short encoder windows
                # for the leaf heading and actual content instead of duplicate titles.
                prefix = (
                    f"[{meta['scope']}; {meta['verification_status']}]\n"
                    f"{section.heading.rsplit(' > ', 1)[-1]}\n\n"
                )
            fragments = _split_body(section.body, prefix, budget)
            parent_key = json.dumps(
                [meta["doc_id"], meta["content_hash"], meta["scope"], meta["doc_version"],
                 meta.get("chain_id"), meta.get("contract_address"), meta.get("abi_hash"),
                 section_index, section.heading], ensure_ascii=False,
            )
            parent_id = content_hash(parent_key)
            for part_index, fragment in enumerate(fragments):
                content = prefix + fragment
                metadata = copy.deepcopy(meta)
                chunk_hash = content_hash(content)
                key = json.dumps(
                    [parent_id, part_index, chunk_hash, SPLITTER_VERSION, budget.tokenizer_id,
                     budget.max_tokens, budget.unit, prefix_style], ensure_ascii=False,
                )
                chunk_id = meta["doc_id"] + ":" + content_hash(key).split(":", 1)[1]
                if chunk_id in seen:
                    raise ChunkingError(f"Duplicate chunk ID: {chunk_id}")
                seen.add(chunk_id)
                metadata.update(
                    chunk_id=chunk_id, chunk_hash=chunk_hash, parent_id=parent_id,
                    section_index=section_index, heading_path=section.heading,
                    part_index=part_index, part_count=len(fragments),
                    splitter_version=SPLITTER_VERSION, tokenizer_id=budget.tokenizer_id,
                    budget_unit=budget.unit, budget_limit=budget.max_tokens,
                    measured_length=budget.count(content), context_prefix=prefix,
                    prefix_style=prefix_style,
                )
                if budget.unit == "tokens":
                    metadata["token_count"] = metadata["measured_length"]
                if len(section.signatures) == 1:
                    metadata["function_signature"] = section.signatures[0]
                elif section.signatures:
                    metadata["function_signatures_json"] = json.dumps(section.signatures)
                if section.entry_type:
                    metadata["abi_entry_type"] = section.entry_type
                if metadata["measured_length"] > budget.max_tokens:
                    raise ChunkingError("Chunk exceeds budget after rendering")
                chunks.append(PreparedChunk(content, metadata))
    return chunks
