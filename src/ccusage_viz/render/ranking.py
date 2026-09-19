from __future__ import annotations

from ccusage_viz.chart_models import RankingEntry, RankingModel, ScalarRankingEntry
from ccusage_viz.formatting import (
    center_text,
    display_width,
    format_percent,
    format_tokens,
    pad_width,
    truncate_middle_width,
    truncate_width,
)
from ccusage_viz.render.base import (
    RenderContext,
    colored_mark,
    content_heading,
    date_range_heading,
    styled_text,
)
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.render.summary import render_summary
from ccusage_viz.trends import trend_glyph


def _observed_heading(model: RankingModel, context: RenderContext) -> str:
    scope = model.observed_scope
    if scope is None:
        raise ValueError("observed ranking is missing its scope")
    window = (
        f"{scope.window_seconds // 3600}h"
        if scope.window_seconds % 3600 == 0
        else f"{scope.window_seconds // 60}m"
    )
    mode = context.translator.text(f"label.monitor_{scope.mode}_mode")
    unit = "TPM" if model.metric.unit == "tpm" else context.translator.text("label.tokens")
    return center_text(f"{mode} · {unit} · {window}", context.width)


def _entry_value(entry: RankingEntry | ScalarRankingEntry) -> int | float:
    return entry.value if isinstance(entry, ScalarRankingEntry) else entry.usage.total


def _compact_labels(labels: list[str], width: int) -> list[str]:
    if len(labels) < 2:
        return labels
    candidates: set[str] = set()
    for left_index, left in enumerate(labels):
        for right in labels[left_index + 1 :]:
            common = left
            while common and not right.startswith(common):
                common = common[:-1]
            boundaries = [index for index, character in enumerate(common) if character in "-/\\"]
            meaningful = [index for index in boundaries if len(common) - index >= 4]
            boundary = max(meaningful, default=max(boundaries, default=-1))
            if boundary >= 3:
                candidates.add(common[: boundary + 1])

    best: tuple[int, str, list[int]] | None = None
    for prefix in candidates:
        indexes = [index for index, label in enumerate(labels) if label.startswith(prefix)]
        remainders = [labels[index][len(prefix) :] for index in indexes]
        if len(indexes) < 2 or any(not remainder for remainder in remainders):
            continue
        compact = [f"…{remainder}" for remainder in remainders]
        if len(set(compact)) != len(compact):
            continue
        saving = sum(
            display_width(labels[index]) - display_width(label)
            for index, label in zip(indexes, compact, strict=True)
        )
        candidate = (saving, prefix, indexes)
        if best is None or candidate[0] > best[0]:
            best = candidate
    if best is None or best[0] <= 0:
        return labels

    _, prefix, indexes = best
    output = list(labels)
    for index in indexes:
        output[index] = truncate_middle_width(f"…{labels[index][len(prefix) :]}", width)
    return output


def render_ranking(model: RankingModel, context: RenderContext) -> str:
    title = context.translator.text("label.ranking")
    scope = model.observed_scope
    if scope is not None:
        heading = _observed_heading(model, context)
    else:
        date_range = model.date_range
        if date_range is None:
            raise ValueError("historical ranking is missing its date range")
        heading = center_text(
            content_heading(title, date_range.since, date_range.until, context)
            if context.title_content
            else date_range_heading(title, date_range.since, date_range.until, context),
            context.width,
        )
    summary = render_summary(model.summary, context) if model.summary else ""
    entries: tuple[RankingEntry | ScalarRankingEntry, ...] = (
        model.observed_entries if model.is_observed else model.entries
    )
    if not entries:
        message = "message.monitor_empty" if model.is_observed else "message.no_data"
        return "\n".join(line for line in (summary, heading, context.translator.text(message)) if line)
    total = None if model.is_observed else model.percentage_total.total
    label_width = max(12, min(28, context.width // 3))
    bar_width = max(8, context.width - label_width - 25)
    maximum = max(_entry_value(entry) for entry in entries) or 1
    full, empty = ("█", "░") if not context.ascii else ("#", ".")
    dot, track = ("●", "·") if not context.ascii else ("o", ".")
    scheme = get_color_scheme(context.color_scheme)
    mark_color = scheme.highlight
    growth = context.deltas or {}
    rank_growth = context.rank_deltas or {}
    raw_labels = [
        context.translator.text("label.other") if entry.is_other else entry.label
        for entry in entries
    ]
    regular_indexes = [index for index, entry in enumerate(entries) if not entry.is_other]
    compact = _compact_labels([raw_labels[index] for index in regular_indexes], label_width)
    labels = list(raw_labels)
    for index, label in zip(regular_indexes, compact, strict=True):
        labels[index] = label

    lines = [line for line in (summary, heading) if line]
    for rank, (entry, label) in enumerate(zip(entries, labels, strict=True), start=1):
        value = _entry_value(entry)
        length = round(value / maximum * bar_width)
        if context.style == "dot":
            mark = (
                track * max(0, length - 1)
                + colored_mark(dot, mark_color, context)
                + track * (bar_width - length)
            )
        elif context.style == "dots":
            mark = colored_mark(dot * length, mark_color, context) + track * (bar_width - length)
        else:
            mark = colored_mark(full * length, mark_color, context) + empty * (bar_width - length)
        rank_change = rank_growth.get(entry.key, 0)
        rank_marker = " "
        if not entry.is_other and rank_change:
            rank_color = scheme.trend_increase if rank_change > 0 else scheme.trend_decrease
            rank_marker = styled_text(
                trend_glyph(rank_change, ascii=context.ascii), rank_color, context, bold=True
            )
        activity = " "
        value_marker = " "
        if entry.key in growth:
            change = growth[entry.key]
            color = (
                scheme.trend_increase
                if change > 0
                else scheme.trend_decrease
                if change < 0
                else scheme.trend_neutral
            )
            value_marker = styled_text(
                trend_glyph(change, ascii=context.ascii), color, context, bold=change != 0
            )
            if change:
                activity = styled_text(
                    "*" if context.ascii else "●", scheme.highlight, context, bold=True
                )
        formatted = format_tokens(round(value))
        percentage = f" {format_percent(round(value), total):>6}" if total is not None else ""
        lines.append(
            f"{rank:>2} {rank_marker} {activity} "
            f"{pad_width(truncate_width(label, label_width), label_width)} {mark} "
            f"{formatted:>6} {value_marker}{percentage}"
        )
    return "\n".join(lines)
