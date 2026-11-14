"""Money is integer minor units everywhere; formatting is the only place decimals appear."""

from __future__ import annotations

EXPONENT: dict[str, int] = {"BHD": 3, "KWD": 3, "OMR": 3, "SAR": 2, "AED": 2, "USD": 2}


def exponent(currency: str) -> int:
    try:
        return EXPONENT[currency]
    except KeyError as err:
        raise ValueError(f"unsupported currency {currency!r}") from err


def to_minor(units: int, currency: str) -> int:
    return units * 10 ** exponent(currency)


def fmt(amount_minor: int, currency: str) -> str:
    """`fmt(12500, "BHD")` -> `"BHD 12.500"`."""
    exp = exponent(currency)
    sign = "-" if amount_minor < 0 else ""
    whole, frac = divmod(abs(amount_minor), 10**exp)
    return f"{currency} {sign}{whole:,}.{frac:0{exp}d}"


def count_phrase(n: int, key: str, *, adjective: str = "") -> str:
    """`count_phrase(1, "tickets_opened")` -> "1 ticket opened"; plural keys are named in the plural."""
    words = key.replace("_", " ").split(" ")
    if n == 1 and words and words[0].endswith("s"):
        words[0] = words[0][:-1]
    return " ".join(part for part in (str(n), adjective, *words) if part)
