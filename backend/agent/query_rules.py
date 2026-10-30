"""Query normalization and explicit amount clarification guards."""

import re

from rag.retriever import explicit_signatures


def normalize_retrieval_query(query: str) -> str:
    """Canonicalize the product term in prose, preserving explicit ABI lookups.

    The pinned multilingual encoder is sensitive to sentence-initial `Faucet`.
    Do not lowercase code/signatures or add facts to the retrieval query.
    """
    if explicit_signatures(query):
        return query
    return re.sub(r"(?<![\w$`])faucet(?![\w$`])", "faucet", query, flags=re.IGNORECASE)


def amount_clarification(query: str) -> str | None:
    """Handle explicitly undecided transfer amounts before any tool selection.

    This narrow guard never selects an amount or interprets numbers in wallet
    addresses. Other ambiguities remain the language model's responsibility.
    """
    text = re.sub(r"0x[0-9a-fA-F]+", "<address>", query).casefold()
    if not re.search(r"\b(?:chuyển|gửi|transfer|send)\b", text):
        return None
    uncertain = re.search(
        r"chưa (?:rõ|chắc|biết|chọn|quyết|xác định)|phân vân|không (?:rõ|chắc|biết)"
        r"|not sure|unsure|undecided|haven['’]t (?:decided|chosen)|don['’]t know"
        r"|hỏi lại|ask me|ask (?:for )?clarification",
        text,
    )
    alternatives = re.search(
        r"\b\d+(?:[.,]\d+)?\s*(?:agnt|eth)?\s*(?:hay|hoặc|or)\s*\d+(?:[.,]\d+)?\b",
        text,
    )
    if not uncertain or not alternatives:
        return None
    if re.search(r"[à-ỹđ]", text):
        return "Bạn muốn chuyển số lượng cụ thể bao nhiêu? Hãy xác nhận một số lượng và loại tài sản; chưa có đề xuất hay giao dịch nào được tạo."
    return "What exact amount and asset would you like to transfer? Please choose one amount; no proposal or transaction has been created."
