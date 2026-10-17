from __future__ import annotations

import shlex
from collections.abc import Callable
from dataclasses import replace
from shutil import get_terminal_size

from ccusage_viz.command_copy import copy_command
from ccusage_viz.configuration import default_custom_pane
from ccusage_viz.custom_models import V2ProbeDescriptor
from ccusage_viz.diagnostics import format_error
from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import display_width, wrap_width
from ccusage_viz.i18n import Translator
from ccusage_viz.options import (
    CustomChartConfig,
    CustomChartPaneConfig,
    CustomCommandSource,
    DashboardLaunch,
)
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.terminal import FramePainter, compose_frame, emphasize
from ccusage_viz.terminal_ui import dimmed
from ccusage_viz.tui.adjustments import _CUSTOM_PANE_KINDS
from ccusage_viz.tui.models import CustomPaneDraft, MetricChooserRow, _custom_metric_periods
from ccusage_viz.tui_input import InputDecoder, KeyEvent, PasteEvent, read_event

_PANE_GROUPS = (
    (
        "status.tui_pane_group_ccusage",
        ("timeline", "calendar", "stack", "ranking", "monitor"),
    ),
    ("status.tui_pane_group_custom", ("datasets",)),
    ("status.tui_pane_group_other", ("animate", "empty")),
)

_PANE_COMMANDS = tuple(command for _, commands in _PANE_GROUPS for command in commands)

def _pane_chooser_rows(translator: Translator, selected: int) -> tuple[list[str], dict[str, int]]:
    current = _PANE_COMMANDS[selected]
    rows: list[str] = []
    positions: dict[str, int] = {}
    for heading, commands in _PANE_GROUPS:
        if rows:
            rows.append("")
        rows.append(translator.text(heading))
        for command in commands:
            positions[command] = len(rows)
            rows.append(
                f"{'›' if command == current else ' '} {translator.text(f'label.pane_{command}')}"
            )
    return rows, positions

def _dataset_title(value, translator: Translator) -> str:
    return value.zh_cn if translator.language == "zh" else value.en

def _dataset_metric_chooser_rows(
    descriptor: V2ProbeDescriptor, translator: Translator
) -> tuple[MetricChooserRow, ...]:
    """Return grouped, selectable Metric rows with explanatory children."""

    rows: list[MetricChooserRow] = []
    for group in descriptor.metric_groups:
        members = [
            (index, metric)
            for index, metric in enumerate(descriptor.metrics)
            if metric.group_id == group.id
        ]
        if not members:
            continue
        rows.append(MetricChooserRow("group", _dataset_title(group.title, translator)))
        for member_index, (index, metric) in enumerate(members):
            is_last = member_index == len(members) - 1
            branch = "└─" if is_last else "├─"
            continuation = "   " if is_last else "│  "
            rows.extend(
                (
                    MetricChooserRow(
                        "metric", f"{branch} {_dataset_title(metric.title, translator)}", index
                    ),
                    MetricChooserRow(
                        "description",
                        f"{continuation}└─ {_dataset_title(metric.description, translator)}",
                    ),
                )
            )
    rows.extend(
        row
        for index, metric in enumerate(descriptor.metrics)
        if metric.group_id is None
        for row in (
            MetricChooserRow("metric", _dataset_title(metric.title, translator), index),
            MetricChooserRow(
                "description", f"  └─ {_dataset_title(metric.description, translator)}"
            ),
        )
    )
    return tuple(rows)

def _metric_chooser_row_text(row: MetricChooserRow, *, ascii: bool) -> str:
    """Adapt tree connectors for an ASCII terminal without changing row identity."""

    if not ascii:
        return row.text
    return row.text.translate(str.maketrans({"├": "|", "└": "\\", "│": "|", "─": "-"}))

def _metric_chooser_display_rows(
    rows: tuple[MetricChooserRow, ...], *, width: int, ascii: bool
) -> tuple[MetricChooserRow, ...]:
    """Wrap descriptive tree children within the chooser's marker-safe width."""

    content_width = max(1, width - 2)  # selection marker and its following space
    connector = "\\- " if ascii else "└─ "
    display_rows: list[MetricChooserRow] = []
    for row in rows:
        text = _metric_chooser_row_text(row, ascii=ascii)
        if row.kind != "description":
            display_rows.append(replace(row, text=text))
            continue
        prefix, description = text.rsplit(connector, 1)
        prefix = f"{prefix}{connector}"
        wrapped = wrap_width(description, max(1, content_width - display_width(prefix)))
        continuation = prefix[: -len(connector)] + " " * display_width(connector)
        display_rows.extend(
            MetricChooserRow("description", f"{line_prefix}{line}")
            for line_prefix, line in zip(
                (prefix, *(continuation for _ in wrapped[1:])), wrapped, strict=True
            )
        )
    return tuple(display_rows)

def _metric_chooser_previous_offset(
    rows: tuple[MetricChooserRow, ...], *, selected_metric_index: int, offset: int
) -> int | None:
    """Reveal rows before the first Metric before wrapping its selection."""

    selectable_positions = tuple(
        position for position, row in enumerate(rows) if row.metric_index is not None
    )
    if (
        not selectable_positions
        or rows[selectable_positions[0]].metric_index != selected_metric_index
    ):
        return None
    first_position = selectable_positions[0]
    return first_position - 1 if offset == first_position and first_position > 0 else None

def _dataset_metric_chooser_chrome(
    descriptor: V2ProbeDescriptor, translator: Translator
) -> tuple[str, str]:
    """Give the metric chooser a selected-Dataset title and next action."""

    return (
        translator.text(
            "status.dataset_metric_chooser_title",
            name=_dataset_title(descriptor.dataset.title, translator),
            version=descriptor.version,
        ),
        translator.text("status.dataset_metric_choose"),
    )

def _choose_custom_pane_config(
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    *,
    height: int,
    dashboard: DashboardLaunch,
    paint_choices: Callable[[str, str, str, tuple[str, ...]], None] | None = None,
    read_input: Callable[[], object] | None = None,
    initial: CustomChartConfig | None = None,
) -> CustomChartPaneConfig | None:
    if initial is not None and initial.source.source_kind == "installed":
        return _choose_installed_pane_config(
            screen,
            translator,
            decoder,
            height=height,
            dashboard=dashboard,
            initial=initial,
            paint_choices=paint_choices,
            read_input=read_input,
        )
    draft = CustomPaneDraft(
        kind=initial.kind if initial is not None else "timeline",
        dataset_id=initial.source.dataset_id if initial is not None else "",
        command=shlex.join(initial.source.command_argv) if initial is not None else "",
    )
    error: str | None = None
    while True:
        fields = (
            translator.text("label.custom_kind"),
            translator.text("label.custom_dataset"),
            translator.text("label.custom_command"),
        )
        values = (draft.kind, draft.dataset_id, draft.command)
        choices = "\n".join(
            f"{'›' if index == draft.field else ' '} {field}: {value or '—'}"
            for index, (field, value) in enumerate(zip(fields, values, strict=True))
        )
        controls = translator.text("status.custom_pane_controls")
        notices = () if error is None else (error,)
        if paint_choices is None:
            screen.paint(
                compose_frame(
                    choices,
                    translator.text("status.custom_pane_title"),
                    controls,
                    notices,
                    height=height,
                )
            )
        else:
            paint_choices(choices, translator.text("status.custom_pane_title"), controls, notices)
        event = read_input() if read_input is not None else read_event(decoder, 0.1)
        if isinstance(event, PasteEvent):
            if draft.field == 1:
                draft.dataset_id += event.value
            elif draft.field == 2:
                draft.command += event.value
            continue
        if not isinstance(event, KeyEvent):
            continue
        key = event.value
        if key == "\x1b":
            return None
        if key in {"\t", "\x1b[B"}:
            draft.field = (draft.field + 1) % len(fields)
            continue
        if key == "\x1b[A":
            draft.field = (draft.field - 1) % len(fields)
            continue
        if draft.field == 0 and key in {"j", "\x1b[C"}:
            draft.kind = _CUSTOM_PANE_KINDS[(_CUSTOM_PANE_KINDS.index(draft.kind) + 1) % 4]
            continue
        if draft.field == 0 and key in {"k", "\x1b[D"}:
            draft.kind = _CUSTOM_PANE_KINDS[(_CUSTOM_PANE_KINDS.index(draft.kind) - 1) % 4]
            continue
        if key == "\x19":
            value = (draft.kind, draft.dataset_id, draft.command)[draft.field]
            error = translator.text(
                "status.command_copied" if copy_command(value) else "status.command_copy_failed"
            )
            continue
        if key == "\x15":
            if draft.field == 0:
                error = translator.text("status.custom_pane_kind_required")
            elif draft.field == 1:
                draft.dataset_id = ""
                error = translator.text("status.custom_pane_field_cleared")
            else:
                draft.command = ""
                error = translator.text("status.custom_pane_field_cleared")
            continue
        if key in {"\r", "\n"}:
            try:
                argv = tuple(shlex.split(draft.command))
                source = CustomCommandSource(draft.dataset_id.strip(), argv)
                return default_custom_pane(draft.kind, source=source, dashboard=dashboard)
            except ValueError as exc:
                error = str(exc)
            continue
        if draft.field in {1, 2}:
            value = draft.dataset_id if draft.field == 1 else draft.command
            if key in {"\x7f", "\b"}:
                value = value[:-1]
            elif len(key) == 1 and key.isprintable():
                value += key
            else:
                continue
            if draft.field == 1:
                draft.dataset_id = value
            else:
                draft.command = value

def _choose_installed_pane_config(
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    *,
    height: int,
    dashboard: DashboardLaunch,
    initial: CustomChartConfig,
    paint_choices: Callable[[str, str, str, tuple[str, ...]], None] | None = None,
    read_input: Callable[[], object] | None = None,
) -> CustomChartPaneConfig | None:
    """Edit an installed Dataset pane without exposing its resolved command."""

    from ccusage_viz.datasets.service import DatasetService

    kind = initial.kind
    dataset_id = initial.source.dataset_id
    field = 0
    error: str | None = None
    while True:
        fields = (translator.text("label.custom_kind"), translator.text("label.custom_dataset"))
        values = (kind, dataset_id)
        choices = "\n".join(
            f"{'›' if index == field else ' '} {label}: {value or '—'}"
            for index, (label, value) in enumerate(zip(fields, values, strict=True))
        )
        controls = translator.text("status.custom_pane_controls")
        notices = () if error is None else (error,)
        if paint_choices is None:
            screen.paint(
                compose_frame(
                    choices,
                    translator.text("status.custom_pane_title"),
                    controls,
                    notices,
                    height=height,
                )
            )
        else:
            paint_choices(choices, translator.text("status.custom_pane_title"), controls, notices)
        event = read_input() if read_input is not None else read_event(decoder, 0.1)
        if isinstance(event, PasteEvent) and field == 1:
            dataset_id += event.value
            continue
        if not isinstance(event, KeyEvent):
            continue
        key = event.value
        if key == "\x1b":
            return None
        if key in {"\t", "\x1b[B"}:
            field = (field + 1) % len(fields)
            continue
        if key == "\x1b[A":
            field = (field - 1) % len(fields)
            continue
        if field == 0 and key in {"j", "\x1b[C"}:
            kind = _CUSTOM_PANE_KINDS[
                (_CUSTOM_PANE_KINDS.index(kind) + 1) % len(_CUSTOM_PANE_KINDS)
            ]
            continue
        if field == 0 and key in {"k", "\x1b[D"}:
            kind = _CUSTOM_PANE_KINDS[
                (_CUSTOM_PANE_KINDS.index(kind) - 1) % len(_CUSTOM_PANE_KINDS)
            ]
            continue
        if key == "\x19":
            value = (kind, dataset_id)[field]
            error = translator.text(
                "status.command_copied" if copy_command(value) else "status.command_copy_failed"
            )
            continue
        if key == "\x15":
            if field == 0:
                error = translator.text("status.custom_pane_kind_required")
            else:
                dataset_id = ""
                error = translator.text("status.custom_pane_field_cleared")
            continue
        if key in {"\r", "\n"}:
            try:
                source = DatasetService().installed_command_source(dataset_id.strip())
                return default_custom_pane(kind, source=source, dashboard=dashboard)
            except (UsageError, ValueError) as exc:
                error = format_error(exc, translator) if isinstance(exc, UsageError) else str(exc)
            continue
        if field != 1:
            continue
        if key in {"\x7f", "\b"}:
            dataset_id = dataset_id[:-1]
        elif len(key) == 1 and key.isprintable():
            dataset_id += key

_DATASET_VIEW_KINDS = ("timeline", "calendar", "stack", "ranking")

def _chooser_viewport(
    rows: list[str], *, index: int, offset: int, height: int, reserved_rows: int = 2
) -> tuple[str, int]:
    """Keep the selected chooser row visible in the available frame body."""

    visible_rows = max(1, height - reserved_rows)
    maximum_offset = max(0, len(rows) - visible_rows)
    offset = min(max(0, offset), maximum_offset)
    if index < offset:
        offset = index
    elif index >= offset + visible_rows:
        offset = index - visible_rows + 1
    return "\n".join(rows[offset : offset + visible_rows]), offset

def _choose_dataset_view(
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    *,
    kinds: tuple[str, ...] = _DATASET_VIEW_KINDS,
    height: int,
    paint_choices: Callable[[str, str, str, tuple[str, ...]], None] | None = None,
    read_input: Callable[[], object] | None = None,
) -> str | None:
    index = 0
    offset = 0
    while True:
        rows = [
            f"{'›' if item_index == index else ' '} {translator.text(f'label.pane_{kind}')}"
            for item_index, kind in enumerate(kinds)
        ]
        title = translator.text("status.dataset_chooser_title")
        controls = translator.text("status.dataset_chooser_controls")
        choices, offset = _chooser_viewport(rows, index=index, offset=offset, height=height)
        if paint_choices is None:
            screen.paint(compose_frame(choices, title, controls, height=height))
        else:
            paint_choices(choices, title, controls, ())
        event = read_input() if read_input is not None else read_event(decoder, 0.1)
        if not isinstance(event, KeyEvent):
            continue
        if event.value == "\x1b":
            return None
        if event.value in {"j", "\x1b[B"}:
            index = (index + 1) % len(kinds)
        elif event.value in {"k", "\x1b[A"}:
            index = (index - 1) % len(kinds)
        elif event.value in {"\r", "\n"}:
            return kinds[index]

def _choose_dataset_pane_config(
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    *,
    height: int,
    dashboard: DashboardLaunch,
    initial: CustomChartConfig | None = None,
    paint_choices: Callable[[str, str, str, tuple[str, ...]], None] | None = None,
    read_input: Callable[[], object] | None = None,
) -> CustomChartPaneConfig | None:
    """Select a ready Dataset, then Metric and chart kind for V2 sources."""

    from ccusage_viz.datasets.service import DatasetService

    service = DatasetService()
    try:
        statuses = service.ready_registered_sources()
    except UsageError as exc:
        statuses = ()
        error: str | None = format_error(exc, translator)
    else:
        error = None
    index = 0
    offset = 0
    while True:
        entries = list(statuses)
        if not entries:
            return None
        index %= len(entries)
        choices: list[str] = []
        for item_index, status in enumerate(entries):
            selected = "›" if item_index == index else " "
            descriptor = status.registration.probe.descriptor
            choices.append(
                f"{selected} {_dataset_title(descriptor.dataset.title, translator)} "
                f"{descriptor.version} · {translator.text('status.dataset_ready')}"
            )
        title = translator.text("status.dataset_chooser_title")
        controls = translator.text("status.dataset_chooser_controls")
        notices = () if error is None else (error,)
        body, offset = _chooser_viewport(
            choices,
            index=index,
            offset=offset,
            height=height,
            reserved_rows=2 + len(notices),
        )
        if paint_choices is None:
            screen.paint(compose_frame(body, title, controls, notices, height=height))
        else:
            paint_choices(body, title, controls, notices)
        event = read_input() if read_input is not None else read_event(decoder, 0.1)
        if not isinstance(event, KeyEvent):
            continue
        key = event.value
        if key == "\x1b":
            return None
        if key in {"j", "\x1b[B"}:
            index = (index + 1) % len(entries)
            continue
        if key in {"k", "\x1b[A"}:
            index = (index - 1) % len(entries)
            continue
        if key not in {"\r", "\n"}:
            continue
        status = entries[index]
        descriptor = status.registration.probe.descriptor
        metric_id: str | None = None
        metric_summary = "comparisons"
        metric_periods: tuple[str, ...] = ()
        metric_titles: tuple[str, str] | None = None
        if isinstance(descriptor, V2ProbeDescriptor):
            metric_rows = _dataset_metric_chooser_rows(descriptor, translator)
            selectable = tuple(
                row.metric_index for row in metric_rows if row.metric_index is not None
            )
            metric_index = next(
                (
                    index
                    for index in selectable
                    if descriptor.metrics[index].id == descriptor.default_metric_id
                ),
                selectable[0],
            )
            metric_offset = 0
            while True:
                metric = descriptor.metrics[metric_index]
                metric_display_rows = _metric_chooser_display_rows(
                    metric_rows, width=get_terminal_size().columns, ascii=dashboard.host.ascii
                )
                metric_row_index = next(
                    index
                    for index, row in enumerate(metric_display_rows)
                    if row.metric_index == metric_index
                )
                scheme = get_color_scheme(dashboard.host.theme)
                metric_choices = [
                    f"{'›' if row.metric_index == metric_index else ' '} "
                    + (
                        emphasize(
                            row.text,
                            color=scheme.highlight,
                            enabled=dashboard.host.theme != "no-color",
                        )
                        if row.kind == "group"
                        else dimmed(row.text, color=dashboard.host.theme != "no-color")
                        if row.kind == "description"
                        else row.text
                    )
                    for row in metric_display_rows
                ]
                metric_body, metric_offset = _chooser_viewport(
                    metric_choices,
                    index=metric_row_index,
                    offset=metric_offset,
                    height=height,
                    reserved_rows=4,
                )
                title, prompt = _dataset_metric_chooser_chrome(descriptor, translator)
                body = "\n".join((prompt, metric_body))
                if paint_choices is None:
                    screen.paint(
                        compose_frame(
                            body,
                            title,
                            translator.text("status.dataset_chooser_controls"),
                            (),
                            height=height,
                        )
                    )
                else:
                    paint_choices(
                        body,
                        title,
                        translator.text("status.dataset_chooser_controls"),
                        (),
                    )
                event = read_input() if read_input is not None else read_event(decoder, 0.1)
                if not isinstance(event, KeyEvent):
                    continue
                if event.value == "\x1b":
                    break
                if event.value in {"j", "\x1b[B"}:
                    metric_index = selectable[
                        (selectable.index(metric_index) + 1) % len(selectable)
                    ]
                    continue
                if event.value in {"k", "\x1b[A"}:
                    reveal_offset = _metric_chooser_previous_offset(
                        metric_display_rows,
                        selected_metric_index=metric_index,
                        offset=metric_offset,
                    )
                    if reveal_offset is not None:
                        metric_offset = reveal_offset
                    else:
                        metric_index = selectable[
                            (selectable.index(metric_index) - 1) % len(selectable)
                        ]
                    continue
                if event.value in {"\r", "\n"}:
                    metric_id = metric.id
                    metric_summary = metric.summary
                    metric_titles = (metric.title.en, metric.title.zh_cn)
                    break
            if metric_id is None:
                continue
            kinds = tuple(metric.capabilities.charts)
        else:
            kinds = tuple(descriptor.capabilities.charts)
        if not kinds:
            continue
        view = _choose_dataset_view(
            screen,
            translator,
            decoder,
            height=height,
            kinds=kinds,
            paint_choices=paint_choices,
            read_input=read_input,
        )
        if view is None:
            continue
        if isinstance(descriptor, V2ProbeDescriptor):
            metric_periods = _custom_metric_periods(metric, view)
        try:
            source = service.registered_command_source(status.registration.dataset_id)
        except UsageError as exc:
            error = format_error(exc, translator)
            continue
        return default_custom_pane(
            view,
            source=source,
            dashboard=dashboard,
            metric_id=metric_id,
            metric_summary=metric_summary,
            metric_periods=metric_periods,
            metric_titles=metric_titles,
        )

def _choose_pane_type(
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    *,
    height: int,
    action: str = "add",
    paint_choices: Callable[[str, str, str, tuple[str, ...]], None] | None = None,
    read_input: Callable[[], object] | None = None,
    on_help: Callable[[str], None] | None = None,
) -> str | None:
    index = 0
    offset = 0
    while True:
        rows, positions = _pane_chooser_rows(translator, index)
        title = translator.text(f"status.tui_{action}_title")
        controls = translator.text(f"status.tui_{action}_controls")
        choices, offset = _chooser_viewport(
            rows,
            index=positions[_PANE_COMMANDS[index]],
            offset=offset,
            height=height,
        )
        if paint_choices is None:
            screen.paint(compose_frame(choices, title, controls, height=height))
        else:
            paint_choices(choices, title, controls, ())
        event = read_input() if read_input is not None else read_event(decoder, 0.1)
        if not isinstance(event, KeyEvent):
            continue
        key = event.value
        if key == "h" and on_help is not None:
            on_help(_PANE_COMMANDS[index])
        elif key in {"j", "\x1b[B"}:
            index = (index + 1) % len(_PANE_COMMANDS)
        elif key in {"k", "\x1b[A"}:
            index = (index - 1) % len(_PANE_COMMANDS)
        elif key in {"\r", "\n"}:
            return _PANE_COMMANDS[index]
        elif key == "\x1b":
            return None
