from __future__ import annotations

import hashlib
from collections.abc import Callable
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


def generate_demo(
    size: str,
    date_range: DateRange,
    *,
    seed: int = 0,
    report_time: float | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[UsageRecord, ...]:
    """Create deterministic synthetic data for one seeded demo invocation.

    Historical samples are fixed for a seed. Live Monitor samples additionally
    advance from report time, rather than the host's refresh count, so missed or
    coalesced refreshes do not alter the simulated workload.
    """
    try:
        magnitude = _MAGNITUDES[size]
    except KeyError as exc:
        raise ValueError("demo size must be small, medium, or large") from exc
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("demo seed must be an integer")
    records: list[UsageRecord] = []
    for offset in range(date_range.days):
        if cancelled is not None and cancelled():
            break
        day = date_range.since + timedelta(days=offset)
        if offset % 6 == 0:
            continue
        live_increment = _live_increment(
            seed, is_current_day=day == date_range.until, report_time=report_time
        )
        for agent, raw_id, name, model in _PROJECTS:
            base = (
                _base_total(seed, day.isoformat(), agent, raw_id, model) + live_increment
            ) * magnitude
            usage = TokenUsage.from_parts(
                total=base,
                input=base * 3 // 10,
                output=base * 2 // 10,
                cache_read=base * 3 // 10,
                cache_creation=base - (base * 3 // 10 + base * 2 // 10 + base * 3 // 10),
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


def _base_total(seed: int, *identity: str) -> int:
    value = _stable_int(seed, *identity)
    return 700 + value % 900


def _live_increment(seed: int, *, is_current_day: bool, report_time: float | None) -> int:
    """Return the seeded cumulative increment for the current reporting epoch."""
    if report_time is None:
        return 0
    if report_time < 0 or report_time != report_time or report_time == float("inf"):
        raise ValueError("demo report time must be a finite non-negative number")
    # The current live epoch is intentionally independent from host ordinals and
    # refresh cadence. It only affects the current local day, so historical data
    # remains stable during a live invocation.
    if not is_current_day:
        return 0
    epoch = int(report_time // 5)
    return sum(
        1 + _stable_int(seed, "report-epoch", str(index)) % 4
        for index in range(1, epoch + 1)
    )


def _stable_int(seed: int, *parts: str) -> int:
    material = ":".join(("ccusage-viz-demo:v1", str(seed), *parts))
    return int.from_bytes(hashlib.sha256(material.encode("utf-8")).digest()[:8], "big")
