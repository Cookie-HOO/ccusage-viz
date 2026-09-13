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
from ccusage_viz.render.base import RenderContext, colored_mark, date_range_heading
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.render.summary import render_summary


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
    heading = center_text(
        date_range_heading(
            context.translator.text("label.ranking"),
            model.date_range.since,
            model.date_range.until,
            context,
        ),
        context.width,
    )
    summary = render_summary(model.summary, context) if model.summary else ""
    if not model.entries:
        return "\n".join(
            line for line in (summary, heading, context.translator.text("message.no_data")) if line
        )
    total = model.percentage_total.total
    label_width = max(12, min(28, context.width // 3))
    suffix_width = 14
    bar_width = max(8, context.width - label_width - suffix_width - 7)
    maximum = max(entry.usage.total for entry in model.entries) or 1
    full, empty = ("█", "░") if not context.ascii else ("#", ".")
    dot, track = ("●", "·") if not context.ascii else ("o", ".")
    mark_color = get_color_scheme(context.color_scheme).highlight
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
        lines.append(
            f"{rank:>2} {pad_width(truncate_width(label, label_width), label_width)} "
            f"{mark} {format_tokens(entry.usage.total):>6} "
            f"{format_percent(entry.usage.total, total):>6}"
        )
    return "\n".join(lines)
