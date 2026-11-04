"""Context titles remain bounded and readable without losing Unicode text."""

from backend.services.history_service import conversation_title


def test_title_keeps_first_topic_and_unicode():
    assert conversation_title("  Kiểm tra số dư ETH.\nSau đó xem gas. ") == "Kiểm tra số dư ETH"


def test_long_title_uses_word_boundary_and_shortens_wallet_addresses():
    title = conversation_title("Transfer 10 AGNT to 0x" + "12" * 20)
    assert title == "Transfer 10 AGNT to 0x1212…1212"
    long_title = conversation_title("Compare Ethereum gas prices and token balances " * 5)
    assert len(long_title) <= 60
    assert long_title.endswith("…")
