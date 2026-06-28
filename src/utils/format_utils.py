"""표시용 포맷 함수."""

from __future__ import annotations


def format_count(value: int | float | None) -> str:
    if value is None:
        return "0"

    return f"{int(value):,}"
