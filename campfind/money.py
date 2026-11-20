"""Parse nightly rates printed on park pages."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


def parse_price(text: str | None) -> tuple[Decimal, Decimal] | None:
    """Return (low, high) from '$24.00' or '$200.00-$225.00'."""
    if not text:
        return None
    parts = re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))
    if not parts:
        return None
    try:
        numbers = [Decimal(part) for part in parts]
    except InvalidOperation:
        return None
    return numbers[0], numbers[-1]


def format_price(bounds: tuple[Decimal, Decimal] | None) -> tuple[str | None, str | None]:
    if bounds is None:
        return None, None
    low, high = bounds
    return f"{low:.2f}", f"{high:.2f}"


def price_label(low: str | None, high: str | None) -> str:
    if not low:
        return ""
    if not high or high == low:
        return f"${low}"
    return f"${low}-${high}"
