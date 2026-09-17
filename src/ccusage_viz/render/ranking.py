from __future__ import annotations

from ccusage_viz.chart_models import RankingModel
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
    heading = center_text(
        content_heading(title, model.date_range.since, model.date_range.until, context)
        if context.title_content
        else date_range_heading(title, model.date_range.since, model.date_range.until, context),
        context.width,
    )
    summary = render_summary(model.summary, context) if model.summary else ""
    if not model.entries:
        return "\n".join(
            line for line in (summary, heading, context.translator.text("message.no_data")) if line
        )
    total = model.percentage_total.total
    label_width = max(12, min(28, context.width // 3))
    bar_width = max(8, context.width - label_width - 25)
    maximum = max(entry.usage.total for entry in model.entries) or 1
    full, empty = ("█", "░") if not context.ascii else ("#", ".")
    dot, track = ("●", "·") if not context.ascii else ("o", ".")
    scheme = get_color_scheme(context.color_scheme)
    mark_color = scheme.highlight
    growth = context.deltas or {}
    rank_growth = context.rank_deltas or {}
    raw_labels = [
        context.translator.text("label.other") if entry.is_other else entry.label
        for entry in model.entries
    ]
    regular_indexes = [index for index, entry in enumerate(model.entries) if not entry.is_other]
    compact = _compact_labels([raw_labels[index] for index in regular_indexes], label_width)
    labels = list(raw_labels)
    for index, label in zip(regular_indexes, compact, strict=True):
        labels[index] = label

    lines = [line for line in (summary, heading) if line]
    for rank, (entry, label) in enumerate(zip(model.entries, labels, strict=True), start=1):
        length = round(entry.usage.total / maximum * bar_width)
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
        lines.append(
            f"{rank:>2} {rank_marker} {activity} "
            f"{pad_width(truncate_width(label, label_width), label_width)} {mark} "
            f"{format_tokens(entry.usage.total):>6} {value_marker} "
            f"{format_percent(entry.usage.total, total):>6}"
        )
    return "\n".join(lines)
