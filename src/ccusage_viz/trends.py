from __future__ import annotations


def trend_glyph(change: float, *, ascii: bool) -> str:
    if change > 0:
        return "^" if ascii else "↑"
    if change < 0:
        return "v" if ascii else "↓"
    return "=" if ascii else "—"
