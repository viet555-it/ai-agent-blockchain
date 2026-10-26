"""Exact ERC-20 amounts without binary floating point or Decimal context rounding."""
import re

UINT256_MAX = 2**256 - 1


def to_token_units(amount: str | int, decimals: int) -> int:
    if type(decimals) is not int or not 0 <= decimals <= 255:
        raise ValueError("Invalid token decimals")
    if type(amount) not in (str, int):
        raise TypeError("Token amount must be a decimal string or integer; floats are rejected")
    text = str(amount)
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", text):
        raise ValueError("Amount must be a finite non-negative decimal without exponent notation")
    whole, _, fraction = text.partition(".")
    if len(fraction) > decimals:
        raise ValueError("Amount has more fractional digits than the token supports")
    units = int(whole) * 10**decimals + int(fraction.ljust(decimals, "0") or "0")
    if units > UINT256_MAX:
        raise ValueError("Amount exceeds uint256")
    return units


def format_token_units(units: int, decimals: int) -> str:
    if type(units) is not int or not 0 <= units <= UINT256_MAX:
        raise ValueError("Invalid raw token balance")
    if type(decimals) is not int or not 0 <= decimals <= 255:
        raise ValueError("Invalid token decimals")
    if decimals == 0:
        return str(units)
    whole, fraction = divmod(units, 10**decimals)
    tail = str(fraction).zfill(decimals).rstrip("0")
    return f"{whole}.{tail}" if tail else str(whole)
