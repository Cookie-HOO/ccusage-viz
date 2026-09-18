from __future__ import annotations

from datetime import timedelta

from ccusage_viz.core.time import DateRange
from ccusage_viz.domain import ModelBreakdown, SourceKind, TokenUsage, UsageRecord
from ccusage_viz.project_identity import make_project_ref

_MAGNITUDES = {"small": 1, "medium": 1_000, "large": 1_000_000}
_PROJECTS = (
    ("claude", "/demo/alpha", "alpha", "claude-sonnet"),
    ("claude", "/demo/shared/app", "app", "claude-opus"),
    ("codex", "/synthetic/shared/app", "app", "gpt-codex"),
    ("codex", "/synthetic/tools", "tools", "gpt-codex"),
)


def generate_demo(size: str, date_range: DateRange) -> tuple[UsageRecord, ...]:
    """Create synthetic, deterministic data; size changes magnitude only."""
    try:
        magnitude = _MAGNITUDES[size]
    except KeyError as exc:
        raise ValueError("demo size must be small, medium, or large") from exc
    records: list[UsageRecord] = []
    for offset in range(date_range.days):
        day = date_range.since + timedelta(days=offset)
        if offset % 6 == 0:
            continue
        for index, (agent, raw_id, name, model) in enumerate(_PROJECTS):
            base = (700 + ((offset * 137 + index * 211) % 900)) * magnitude
            usage = TokenUsage.from_parts(
                total=base,
                input=base * 3 // 10,
                output=base * 2 // 10,
                cache_read=base * 3 // 10,
                cache_creation=base // 10,
            )
            records.append(
                UsageRecord(
                    day,
                    agent,
                    usage,
                    SourceKind.CLAUDE_DAILY_PROJECTS
                    if agent == "claude"
                    else SourceKind.CODEX_SESSIONS,
                    project=make_project_ref(agent, raw_id, name),
                    models=(ModelBreakdown(model, usage),),
                )
            )
    return tuple(records)
