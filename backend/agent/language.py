"""Language detection, resolution, and localization support for Agent runtime."""

from __future__ import annotations

import re
from typing import Any

VI_DIACRITICS_PATTERN = re.compile(r"[à-ỹđÀ-ỸĐ]")
VI_KEYWORDS = {
    "là", "gì", "không", "cho", "của", "tôi", "bạn", "giá", "ví", "tiền",
    "số", "dư", "xem", "kiểm", "tra", "bao", "nhiêu", "chào", "xin",
    "gửi", "chuyển", "phí", "thế", "nào", "hôm", "nay", "tuần", "này",
    "tháng", "này", "được", "có", "hãy", "giúp", "với", "nhé", "nào",
    "tài", "khoản", "lệnh", "giao", "dịch", "chặn", "duyệt", "hạn", "mức"
}

CONVERSATIONAL_GREETINGS = {
    "hi", "hello", "hey", "chào", "xin chào", "chào bạn", "hello bạn",
    "good morning", "good afternoon", "good evening", "how are you",
    "bạn khỏe không", "alo", "ê"
}

CONVERSATIONAL_IDENTITY = {
    "who are you", "bạn là ai", "bạn tên gì", "what can you do",
    "bạn làm được gì", "bạn giúp được gì", "what is this", "giới thiệu",
    "giới thiệu bản thân", "introduce yourself", "tell me about yourself"
}

CONVERSATIONAL_COURTESY = {
    "thanks", "thank you", "cảm ơn", "cảm ơn bạn", "cám ơn",
    "bye", "goodbye", "tạm biệt", "ok", "okay", "được rồi", "tốt"
}


def detect_query_language(query: str) -> str:
    """Detect whether user query is primarily Vietnamese or English."""
    text = query.strip().casefold()

    # Explicit language requests inside prompt
    if re.search(r"\b(?:bằng tiếng việt|in vietnamese|tiếng việt)\b", text):
        return "vi"
    if re.search(r"\b(?:in english|bằng tiếng anh|speak english|tiếng anh)\b", text):
        return "en"

    # Vietnamese diacritic check
    if VI_DIACRITICS_PATTERN.search(query):
        return "vi"

    # Word-level keyword frequency check
    words = set(re.findall(r"\w+", text))
    vi_match_count = len(words.intersection(VI_KEYWORDS))
    if vi_match_count >= 2:
        return "vi"

    return "en"


def resolve_language(preference: str | None, query: str) -> str:
    """Resolve active language: explicit setting or auto-detection from query.

    Returns: 'vi' or 'en'.
    """
    pref = (preference or "auto").strip().casefold()

    # Prompt-level override takes precedence over global setting
    text = query.strip().casefold()
    if re.search(r"\b(?:bằng tiếng việt|in vietnamese|tiếng việt)\b", text):
        return "vi"
    if re.search(r"\b(?:in english|bằng tiếng anh|speak english|tiếng anh)\b", text):
        return "en"

    if pref in ("vi", "vietnamese", "tiếng việt"):
        return "vi"
    if pref in ("en", "english", "tiếng anh"):
        return "en"

    # 'auto' or unrecognized preference -> detect from query
    return detect_query_language(query)


def is_conversational_query(query: str) -> bool:
    """Determine if query is purely conversational (greeting, thanks, identity)

    where calling blockchain tools or failing on RAG is unnecessary.
    """
    cleaned = re.sub(r"[^\w\s]", "", query).strip().casefold()

    # Exact phrase matches
    if cleaned in CONVERSATIONAL_GREETINGS or cleaned in CONVERSATIONAL_IDENTITY or cleaned in CONVERSATIONAL_COURTESY:
        return True

    # Identity queries (e.g. "who are you", "bạn là ai", "what can you do")
    if any(q in cleaned for q in CONVERSATIONAL_IDENTITY):
        return True

    # Courtesy queries (e.g. "thank you", "cảm ơn")
    if any(c in cleaned for c in CONVERSATIONAL_COURTESY):
        return True

    # Whole-word greetings for short utterances (<= 5 tokens)
    tokens = set(re.findall(r"\w+", cleaned))
    single_word_greetings = {"hi", "hello", "hey", "chào", "alo", "goodbye", "bye"}
    if tokens.intersection(single_word_greetings) and len(cleaned.split()) <= 5:
        return True

    # Multi-word greeting phrases
    multi_greetings = {"xin chào", "chào bạn", "good morning", "good afternoon", "good evening", "how are you", "bạn khỏe không"}
    if any(g in cleaned for g in multi_greetings):
        return True

    return False


MESSAGES = {
    "NO_FINAL_RESPONSE": {
        "vi": "Không có phản hồi cuối cùng từ Agent.",
        "en": "No final response received from Agent.",
    },
    "AGENT_INCOMPLETE": {
        "vi": "Agent chưa hoàn thành thao tác. Hãy kiểm tra lỗi và các công cụ đang được bật.",
        "en": "Agent did not complete the operation. Please check errors and enabled tools.",
    },
    "LLM_ERROR_400": {
        "vi": "Gemini từ chối nội dung hoặc cấu trúc request (HTTP 400). Cần kiểm tra log API.",
        "en": "Gemini rejected the request content or structure (HTTP 400). Please check API logs.",
    },
    "LLM_ERROR_401": {
        "vi": "API key không được chấp nhận (HTTP 401). Hãy kiểm tra cấu hình provider.",
        "en": "API key not accepted (HTTP 401). Please check provider configuration.",
    },
    "LLM_ERROR_403": {
        "vi": "API key hoặc project chưa có quyền gọi model (HTTP 403).",
        "en": "API key or project lacks permissions to invoke the model (HTTP 403).",
    },
    "LLM_ERROR_404": {
        "vi": "Không tìm thấy model đã cấu hình hoặc endpoint tương ứng (HTTP 404).",
        "en": "Configured model or endpoint not found (HTTP 404).",
    },
    "LLM_ERROR_429": {
        "vi": "Gemini đang giới hạn quota/tốc độ (HTTP 429). Hãy kiểm tra quota trước khi thử lại.",
        "en": "Gemini rate/quota limit exceeded (HTTP 429). Please check quota before retrying.",
    },
    "LLM_ERROR_DEFAULT": {
        "vi": "Lời gọi model thất bại. Xem lỗi ‘LLM call failed’ trong terminal chạy API; chưa có giao dịch nào được gửi.",
        "en": "Model call failed. See 'LLM call failed' error in API server terminal; no transaction has been sent.",
    },
    "DOC_NOT_FOUND": {
        "vi": "Chưa tìm thấy tài liệu phù hợp để trả lời câu hỏi này. Bạn hãy nêu rõ chức năng hoặc tên hàm cần tra cứu.",
        "en": "Chưa tìm thấy tài liệu phù hợp để trả lời câu hỏi này (No matching documentation found). Please specify the contract function or topic to look up.",
    },
    "PROPOSAL_READY": {
        "vi": "Giao dịch đã được chuẩn bị. Hãy kiểm tra và duyệt trong cửa sổ xác nhận; chưa có giao dịch nào được gửi.",
        "en": "Transaction proposal prepared. Please review and approve in the confirmation dialog; no transaction has been sent.",
    },
    "REQUEST_BLOCKED": {
        "vi": "Yêu cầu bị chặn: {violations}",
        "en": "Request blocked by Policy Guardrail: {violations}",
    },
    "RAG_UNAVAILABLE": {
        "vi": "Không thể truy xuất tài liệu; hãy kiểm tra dịch vụ RAG trước khi thử lại.",
        "en": "Unable to retrieve documentation; please verify the RAG service before retrying.",
    },
    "BALANCE_SUMMARY": {
        "vi": "Số dư của ví `{address}`: **{balance} {symbol}**.\nRaw balance: `{raw_balance}`.",
        "en": "Balance of wallet `{address}`: **{balance} {symbol}**.\nRaw balance: `{raw_balance}`.",
    },
    "GREETING_DEFAULT": {
        "vi": "Xin chào! Tôi là trợ lý AI Blockchain của bạn trên mạng Ethereum Sepolia. Tôi có thể giúp bạn kiểm tra số dư ví, tra cứu giao dịch, xem giá thị trường ETH/BTC/LINK và chuẩn bị giao dịch an toàn với Guardrail.",
        "en": "Hello! I am your AI Blockchain Assistant on the Ethereum Sepolia network. I can help you check wallet balances, inspect transactions, monitor market prices (ETH/BTC/LINK), and prepare secure transactions with Guardrail protection.",
    },
}


def get_localized_message(key: str, lang: str = "en", **kwargs: Any) -> str:
    """Retrieve and format a localized message string."""
    lang_key = "vi" if lang == "vi" else "en"
    template = MESSAGES.get(key, {}).get(lang_key, "")
    if not template:
        # Fallback to English if key missing in language
        template = MESSAGES.get(key, {}).get("en", key)
    if kwargs:
        try:
            return template.format(**kwargs)
        except Exception:
            return template
    return template
