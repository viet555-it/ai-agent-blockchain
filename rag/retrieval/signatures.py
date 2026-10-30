"""Extract canonical ABI type signatures without interpreting transaction values."""

from __future__ import annotations

import re

from rag.loaders import abi_type


def _type_signature(text: str) -> str:
    text = text.strip()
    if text.startswith("("):
        depth, close = 0, None
        for index, character in enumerate(text):
            depth += character == "("
            depth -= character == ")"
            if depth == 0:
                close = index
                break
        if close is None or not re.fullmatch(r"(?:\[(?:[1-9][0-9]*)?\])*", text[close + 1 :]):
            raise ValueError("Invalid tuple signature")
        return (
            "("
            + ",".join(_type_signature(p) for p in _parameters(text[1:close]))
            + ")"
            + text[close + 1 :]
        )
    return abi_type({"type": text})


def _parameters(text: str) -> list[str]:
    if not text.strip():
        return []
    depth, start, result = 0, 0, []
    for index, character in enumerate(text):
        depth += character == "("
        depth -= character == ")"
        if character == "," and depth == 0:
            result.append(text[start:index])
            start = index + 1
    result.append(text[start:])
    return result


def explicit_signatures(query: str) -> set[str]:
    """Extract ABI type signatures, not calls containing addresses/amount values."""
    found: set[str] = set()
    for match in re.finditer(r"\b([A-Za-z_$][\w$]*)\s*\(", query):
        start, depth, end = match.end(), 1, None
        for index in range(start, len(query)):
            depth += query[index] == "("
            depth -= query[index] == ")"
            if depth == 0:
                end = index
                break
        if end is None:
            continue
        try:
            params = ",".join(_type_signature(p) for p in _parameters(query[start:end]))
        except ValueError:
            continue
        found.add(match[1] + "(" + params + ")")
    return found
