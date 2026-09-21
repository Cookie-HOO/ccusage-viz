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
from ccusage_viz.project_identity import exact_project_agent
from ccusage_viz.render.base import (
    RenderContext,
    colored_mark,
    content_heading,
    date_range_heading,
    styled_text,
    title_with_querying,
)
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.render.summary import render_summary, render_summary_placeholder
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
    state = (
        f" · {context.translator.text(f'label.monitor_{scope.state}')}"
        if scope.state != "ready"
        else ""
    )
    heading = title_with_querying(
        context.translator.text(
            "label.monitor_ranking_tokens"
            if model.metric.unit == "tokens"
            else "label.monitor_ranking_tpm",
            mode=mode,
            window=window,
            state=state,
        ),
        context,
    )
    return center_text(heading, context.width)


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


def _observed_dimensions(
    labels: list[str], values: list[str], context: RenderContext
) -> tuple[int, int, int]:
    """Allocate observed ranking columns from content while retaining a useful bar."""
    label_size = max(display_width(label) for label in labels)
    value_size = max(6, *(display_width(value) for value in values))
    available = max(1, context.width - value_size - 11)
    if context.style == "list":
        return min(label_size, available), 0, value_size
    label_width = min(label_size, max(1, available - 8))
    return label_width, available - label_width, value_size


def _entry_agent(entry: RankingEntry | ScalarRankingEntry) -> str | None:
    if isinstance(entry, ScalarRankingEntry) and entry.agent is not None:
        return entry.agent
    return exact_project_agent(entry.key)


def _historical_title(model: RankingModel, context: RenderContext) -> str:
    return (
        context.translator.text("label.ranking_agent_project")
        if model.project_aggregation == "exact"
        else context.translator.text("label.ranking")
    )


def render_ranking(model: RankingModel, context: RenderContext) -> str:
    title = _historical_title(model, context)
    scope = model.observed_scope
    if scope is not None:
        heading = _observed_heading(model, context)
    else:
        date_range = model.date_range
        if date_range is None:
            raise ValueError("historical ranking is missing its date range")
        heading_text = (
            date_range_heading(title, date_range.since, date_range.until, context)
            if model.project_aggregation == "exact"
            else content_heading(title, date_range.since, date_range.until, context)
            if context.title_content
            else date_range_heading(title, date_range.since, date_range.until, context)
        )
        if not context.pending and model.top is not None and model.top_share is not None:
            heading_text = context.translator.text(
                "label.ranking_top_share",
                heading=heading_text,
                top=model.top,
                share=f"{model.top_share:.1%}",
            )
        heading = center_text(heading_text, context.width)
    pending = context.pending and not model.is_observed
    summary = (
        render_summary_placeholder(
            model.summary.period,
            model.summary.day,
            context,
            all_agents=model.summary.all_agents,
        )
        if pending and model.summary is not None
        else render_summary(model.summary, context)
        if model.summary
        else ""
    )
    entries: tuple[RankingEntry | ScalarRankingEntry, ...] = (
        model.observed_entries if model.is_observed else model.entries
    )
    if not entries:
        message = "message.monitor_empty" if model.is_observed else "message.no_data"
        return "\n".join(
            line for line in (summary, heading, context.translator.text(message)) if line
        )
    total = None if model.is_observed or pending else model.percentage_total.total
    formatted_values = [
        "??" if pending else format_tokens(round(_entry_value(entry))) for entry in entries
    ]
    agents = [_entry_agent(entry) for entry in entries]
    separate_fields = (model.project_aggregation == "exact" and not model.is_observed) or (
        model.is_observed and scope is not None and scope.mode == "project"
    )
    projects = [
        context.translator.text("label.other") if entry.is_other else entry.label
        for entry in entries
    ]
    combined_labels = [
        f"{agent} {project}"
        if separate_fields and agent is not None and not entry.is_other
        else project
        for entry, agent, project in zip(entries, agents, projects, strict=True)
    ]
    if model.is_observed:
        label_width, bar_width, value_width = _observed_dimensions(
            combined_labels if separate_fields else projects, formatted_values, context
        )
    else:
        label_width = min(28, max(8, context.width // 3))
        bar_width = max(8, context.width - label_width - 24)
        value_width = 6
    regular_indexes = [index for index, entry in enumerate(entries) if not entry.is_other]
    labels = list(projects)
    if not model.is_observed:
        compact_source = projects if separate_fields else combined_labels
        compact = _compact_labels([compact_source[index] for index in regular_indexes], label_width)
        for index, label in zip(regular_indexes, compact, strict=True):
            labels[index] = label
    agent_width = 0
    project_width = label_width
    if separate_fields:
        agent_width = min(
            max((display_width(agent) for agent in agents if agent is not None), default=0),
            max(1, label_width - 1),
        )
        project_width = max(1, label_width - agent_width - 1)
    maximum = max(_entry_value(entry) for entry in entries) or 1
    full, empty = ("█", "░") if not context.ascii else ("#", ".")
    dot, track = ("●", "·") if not context.ascii else ("o", ".")
    scheme = get_color_scheme(context.color_scheme)
    mark_color = scheme.highlight
    growth = context.deltas or {}
    rank_growth = context.rank_deltas or {}
    lines = [line for line in (summary, heading) if line]
    for rank, (entry, label, agent, formatted) in enumerate(
        zip(entries, labels, agents, formatted_values, strict=True), start=1
    ):
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
        percentage = f" {format_percent(round(value), total):>6}" if total is not None else ""
        rank_marker = " " if pending else rank_marker
        activity = " " if pending else activity
        value_marker = " " if pending else value_marker
        prefix = f"{rank:>2} {rank_marker} {activity} "
        if separate_fields:
            agent_text = "" if entry.is_other or agent is None else agent
            label_text = (
                f"{pad_width(truncate_width(agent_text, agent_width), agent_width)} "
                f"{pad_width(truncate_width(label, project_width), project_width)}"
            )
        else:
            label_text = pad_width(truncate_width(label, label_width), label_width)
        if model.is_observed and context.style == "list":
            row = (
                f"{rank_marker} {activity} {label_text} "
                f"{pad_width(formatted, value_width, align='right')} {value_marker}"
            )
            lines.append(center_text(row, context.width))
        else:
            lines.append(
                f"{prefix}{label_text} {mark} "
                f"{pad_width(formatted, value_width, align='right')} {value_marker}{percentage}"
            )
    return "\n".join(lines)
