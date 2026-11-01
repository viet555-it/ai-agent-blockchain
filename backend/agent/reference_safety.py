"""Conservative screening of explicit instruction overrides in retrieved reference data.

This catches known high-risk instruction patterns, not every possible injection.
The wallet policy/approval boundary remains independent of this text screening.
"""

import re
import unicodedata

PATTERNS = {
    "AUTHORITY_OVERRIDE": r"\b(?:new\s+(?:system|developer)\s+(?:command|instruction)|lenh\s+he\s+thong\s+moi)\b",
    "INSTRUCTION_OVERRIDE": r"\b(?:ignore|disregard|override)\b.{0,55}\b(?:previous|user|system|instructions?|polic(?:y|ies))\b|\bbo\s+(?:qua\s+)?(?:yeu\s+cau|chi\s+dan)\b",
    "APPROVAL_BYPASS": r"\b(?:skip|bypass|disable|remove)\b.{0,40}\b(?:confirmation|approval|guardrails?)\b|\bbo\s+(?:qua\s+)?(?:xac\s+nhan|phe\s+duyet)\b",
}


def reference_findings(content):
    normalized = unicodedata.normalize("NFKC", content)
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Cf")
    normalized = "".join(
        char for char in unicodedata.normalize("NFD", normalized) if not unicodedata.combining(char)
    )
    normalized = normalized.casefold().replace("đ", "d")
    findings = []
    for code, pattern in PATTERNS.items():
        for match in re.finditer(pattern, normalized):
            prefix = normalized[max(0, match.start() - 35) : match.start()]
            # Documentation prohibiting an action is not itself an override.
            if re.search(
                r"\b(?:never|do not|must not|khong|dung)\s+(?:ever\s+|bao gio\s+|duoc\s+)?$", prefix
            ):
                continue
            findings.append(code)
            break
    return findings


def blocked_reference_reply(query):
    if re.search(r"[ăâđêôơư]|[\u0300-\u036f]", unicodedata.normalize("NFD", query.casefold())):
        return "Tài liệu truy xuất chứa chỉ dẫn yêu cầu đổi quy tắc hoặc bỏ xác nhận. Mình không sử dụng tài liệu đó để hướng dẫn giao dịch. Bạn có thể nêu trực tiếp tài sản, số tiền và người nhận để chuẩn bị một đề xuất mới."
    return "The retrieved material contains instructions to override rules or bypass confirmation. I will not use it as transfer guidance. You can provide the asset, amount and recipient directly to prepare a new proposal."
