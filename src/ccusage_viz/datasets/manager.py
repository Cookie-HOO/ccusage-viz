from __future__ import annotations

import shlex
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from shutil import get_terminal_size

from ccusage_viz.custom_models import V2ProbeDescriptor
from ccusage_viz.datasets.models import (
    DatasetManifest,
    DatasetRegistrationStatus,
    LocalDatasetSource,
)
from ccusage_viz.datasets.service import DatasetService
from ccusage_viz.diagnostics import format_error
from ccusage_viz.formatting import clip_width, display_width, pad_width, wrap_width
from ccusage_viz.i18n import Translator
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.render.ranking_description import render_ranking_description
from ccusage_viz.terminal import (
    Frame,
    FramePainter,
    compose_frame,
    emphasize,
    set_cursor_visible,
)
from ccusage_viz.tui_input import InputDecoder, KeyEvent, PasteEvent, read_event, tui_input_mode


@dataclass(frozen=True, slots=True)
class ManagerView:
    frame: Frame
    selected_id: str | None


def _text(value, translator: Translator) -> str:
    return value.zh_cn if translator.language == "zh" else value.en


def _read_manager_event(
    decoder: InputDecoder, read_input: Callable[[], object] | None
) -> object:
    """Read one nested-manager event and preserve global Ctrl-C semantics."""

    event = read_input() if read_input is not None else read_event(decoder, 0.1)
    if isinstance(event, KeyEvent) and event.value == "\x03":
        raise KeyboardInterrupt
    return event


def _descriptor_title(descriptor, translator: Translator) -> str:
    return _text(descriptor.dataset.title, translator)


def _descriptor_description(descriptor, translator: Translator) -> str:
    return _text(descriptor.dataset.description, translator)


def _descriptor_metric_rows(descriptor, translator: Translator) -> tuple[str, ...]:
    if not isinstance(descriptor, V2ProbeDescriptor):
        charts = " · ".join(
            translator.text(f"label.pane_{kind}") for kind in descriptor.capabilities.charts
        )
        return (f"{_text(descriptor.dataset.unit.label, translator)} · {charts}",)
    rows = []
    for metric in descriptor.metrics:
        charts = " · ".join(
            translator.text(f"label.pane_{kind}") for kind in metric.capabilities.charts
        )
        rows.append(f"{_text(metric.title, translator)} · {metric.aggregation} · {charts}")
    return tuple(rows)


def _list_rows(
    statuses: tuple[DatasetRegistrationStatus, ...],
    translator: Translator,
    *,
    selected: int,
    width: int,
) -> list[str]:
    rows: list[str] = []
    name_width = max(12, width * 46 // 100)
    version_width = max(7, width * 20 // 100)
    source_width = max(10, width - name_width - version_width - 4)
    rows.extend(
        (
            clip_width(
                f"  {pad_width(translator.text('status.dataset_column_name'), name_width)} "
                f"{pad_width(translator.text('status.dataset_column_version'), version_width)} "
                f"{pad_width(translator.text('status.dataset_column_source'), source_width)}",
                width,
            ),
            "─" * width,
        )
    )
    for availability in ("ready", "setup_required", "unavailable", "disabled"):
        grouped = [item for item in statuses if item.availability == availability]
        if not grouped:
            continue
        rows.extend(("", translator.text(f"status.dataset_group_{availability}")))
        for item in grouped:
            index = statuses.index(item)
            descriptor = item.registration.probe.descriptor
            marker = "›" if index == selected else " "
            title = clip_width(_descriptor_title(descriptor, translator), name_width)
            source = translator.text(
                "label.dataset_source_local"
                if isinstance(item.registration.source, LocalDatasetSource)
                else f"label.dataset_source_{item.registration.source.kind}"
            )
            rows.append(
                clip_width(
                    f"{marker} {pad_width(title, name_width)} "
                    f"{pad_width(descriptor.version, version_width)} "
                    f"{pad_width(source, source_width)}",
                    width,
                )
            )
    return rows or [translator.text("status.dataset_manager_empty")]


def _detail_rows(status: DatasetRegistrationStatus, translator: Translator, width: int) -> list[str]:
    descriptor = status.registration.probe.descriptor
    required = tuple(item for item in descriptor.environment if item.required)
    optional = tuple(item for item in descriptor.environment if not item.required)

    def environment_rows(items, heading: str) -> list[str]:
        if not items:
            return []
        rows = [heading]
        for item in items:
            present = item not in status.missing_environment
            state = translator.text(
                "status.dataset_environment_present"
                if present
                else "status.dataset_environment_missing"
            )
            rows.extend(
                (
                    f"{item.name} · {state} · {_text(item.label, translator)}",
                )
            )
        return rows
    def section(key: str) -> str:
        return emphasize(
            translator.text(key), color=get_color_scheme("classic").highlight, enabled=True
        )
    rows = [
        section("status.dataset_details_dataset"),
        _descriptor_title(descriptor, translator),
        *wrap_width(_descriptor_description(descriptor, translator), width),
        *(_descriptor_metric_rows(descriptor, translator)),
        descriptor.source_timezone or translator.text("status.dataset_timezone_unspecified"),
        "",
        section("status.dataset_details_supports"),
        *(_descriptor_metric_rows(descriptor, translator)),
        "",
        section("status.dataset_details_environment"),
        *environment_rows(required, translator.text("status.dataset_environment_required")),
        *environment_rows(optional, translator.text("status.dataset_environment_optional")),
        "",
        section("status.dataset_details_source"),
        *(
            wrap_width(shlex.join(status.registration.source.command_argv), width)
            if isinstance(status.registration.source, LocalDatasetSource)
            else wrap_width(
                f"{status.registration.source.repository} · "
                f"{status.registration.source.release_tag} · "
                f"{status.registration.source.asset_name}",
                width,
            )
        ),
    ]
    return [clip_width(row, width) for row in rows]


def _manifest_rows(manifest: DatasetManifest, translator: Translator, width: int) -> list[str]:
    required = tuple(item for item in manifest.environment if item.required)
    optional = tuple(item for item in manifest.environment if not item.required)

    def environment_rows(items, heading: str) -> list[str]:
        if not items:
            return []
        rows = [heading]
        rows.extend(f"{item.name} · {_text(item.label, translator)}" for item in items)
        return rows

    descriptor = manifest.descriptor
    title = (
        _descriptor_title(descriptor, translator)
        if descriptor is not None
        else _text(manifest.metric.title, translator)
    )
    description = (
        _descriptor_description(descriptor, translator) if descriptor is not None else ""
    )
    def section(key: str) -> str:
        return emphasize(
            translator.text(key), color=get_color_scheme("classic").highlight, enabled=True
        )
    rows = [
        section("status.dataset_details_dataset"),
        title,
        *wrap_width(description, width),
        f"{translator.text('status.dataset_column_version')}: {manifest.version}",
        "",
        section("status.dataset_details_supports"),
        " · ".join(translator.text(f"label.pane_{kind}") for kind in manifest.charts),
        "",
        section("status.dataset_details_environment"),
        *environment_rows(required, translator.text("status.dataset_environment_required")),
        *environment_rows(optional, translator.text("status.dataset_environment_optional")),
    ]
    return [clip_width(row, width) for row in rows]


def _side_by_side(left: list[str], right: list[str], *, left_width: int, right_width: int) -> str:
    rows: list[str] = []
    count = max(len(left), len(right))
    for index in range(count):
        left_row = left[index] if index < len(left) else ""
        right_row = right[index] if index < len(right) else ""
        rows.append(f"{pad_width(clip_width(left_row, left_width), left_width)} │ {clip_width(right_row, right_width)}")
    return "\n".join(rows)


def render_dataset_manager(
    statuses: tuple[DatasetRegistrationStatus, ...],
    translator: Translator,
    *,
    selected: int = 0,
    details: bool = False,
    width: int = 80,
    height: int = 24,
    notice: str | None = None,
) -> ManagerView:
    selected = min(max(selected, 0), max(0, len(statuses) - 1))
    selected_status = statuses[selected] if statuses else None
    if details and selected_status is not None and width >= 100:
        left_width = max(32, (width - 3) * 42 // 100)
        right_width = width - left_width - 3
        body = _side_by_side(
            _list_rows(statuses, translator, selected=selected, width=left_width),
            _detail_rows(selected_status, translator, right_width),
            left_width=left_width,
            right_width=right_width,
        )
        controls = (
            translator.text("status.dataset_manager_upgrade_controls")
            if selected_status.registration.available_update is not None
            else translator.text("status.dataset_manager_controls")
        )
    elif details and selected_status is not None:
        body = "\n".join(_detail_rows(selected_status, translator, width))
        controls = (
            translator.text("status.dataset_manager_detail_upgrade_controls")
            if selected_status.registration.available_update is not None
            else translator.text("status.dataset_manager_detail_controls")
        )
    else:
        body = "\n".join(_list_rows(statuses, translator, selected=selected, width=width))
        controls = translator.text("status.dataset_manager_controls")
    notices = () if notice is None else (notice,)
    return ManagerView(
        compose_frame(
            body,
            translator.text("status.dataset_manager_title", count=len(statuses)),
            controls,
            notices,
            height=height,
        ),
        selected_status.registration.dataset_id if selected_status is not None else None,
    )


def format_dataset_list(
    statuses: tuple[DatasetRegistrationStatus, ...], translator: Translator
) -> str:
    if not statuses:
        return translator.text("status.dataset_manager_empty")
    labels = {
        "ready": translator.text("status.dataset_ready"),
        "setup_required": translator.text("status.dataset_setup_required"),
        "unavailable": translator.text("status.dataset_unavailable"),
        "disabled": translator.text("status.dataset_disabled"),
    }
    return "\n".join(
        f"{item.registration.dataset_id} {item.registration.probe.descriptor.version} · "
        f"{labels[item.availability]}"
        for item in statuses
    )


def _read_local_command(
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    *,
    read_input: Callable[[], object] | None = None,
) -> tuple[str, ...] | None:
    command = ""
    error: str | None = None
    while True:
        frame = compose_frame(
            f"{translator.text('label.custom_command')}: {command or '—'}",
            translator.text("status.dataset_register_local_title"),
            translator.text("status.dataset_register_local_controls"),
            () if error is None else (error,),
            height=get_terminal_size().lines,
        )
        screen.paint(frame)
        event = _read_manager_event(decoder, read_input)
        if isinstance(event, PasteEvent):
            command += event.value
            continue
        if not isinstance(event, KeyEvent):
            continue
        if event.value == "h":
            _show_manager_help(screen, translator, decoder, read_input=read_input)
            continue
        if event.value == "\x1b":
            return None
        if event.value in {"\x7f", "\b"}:
            command = command[:-1]
            continue
        if event.value in {"\r", "\n"}:
            try:
                argv = tuple(shlex.split(command))
                if not argv:
                    raise ValueError("command is empty")
                return argv
            except ValueError:
                error = translator.text("status.dataset_register_command_invalid")
            continue
        if len(event.value) == 1 and event.value.isprintable():
            command += event.value


def _choose_dataset_source(
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    *,
    read_input: Callable[[], object] | None = None,
) -> str | None:
    sources = ("official", "github", "local")
    labels = {
        "official": translator.text("label.dataset_browse_official"),
        "github": translator.text("label.dataset_github_release"),
        "local": translator.text("label.dataset_local_command"),
    }
    index = 0
    while True:
        body = "\n".join(
            f"{'›' if item_index == index else ' '} {labels[source]}"
            for item_index, source in enumerate(sources)
        )
        screen.paint(
            compose_frame(
                body,
                translator.text("status.dataset_add_source_title"),
                translator.text("status.dataset_add_source_controls"),
                height=get_terminal_size().lines,
            )
        )
        event = _read_manager_event(decoder, read_input)
        if not isinstance(event, KeyEvent):
            continue
        if event.value == "h":
            _show_manager_help(screen, translator, decoder, read_input=read_input)
            continue
        if event.value == "\x1b":
            return None
        if event.value in {"j", "\x1b[B"}:
            index = (index + 1) % len(sources)
        elif event.value in {"k", "\x1b[A"}:
            index = (index - 1) % len(sources)
        elif event.value in {"\r", "\n"}:
            return sources[index]


def _confirm(
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    body: str,
    *,
    title: str,
    controls: str,
    read_input: Callable[[], object] | None = None,
) -> bool:
    while True:
        screen.paint(compose_frame(body, title, controls, height=get_terminal_size().lines))
        event = _read_manager_event(decoder, read_input)
        if not isinstance(event, KeyEvent):
            continue
        if event.value == "h":
            _show_manager_help(screen, translator, decoder, read_input=read_input)
            continue
        if event.value in {"\r", "\n"}:
            return True
        if event.value == "\x1b":
            return False


def _register_local(
    service: DatasetService,
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    *,
    read_input: Callable[[], object] | None = None,
) -> str | None:
    argv = _read_local_command(screen, translator, decoder, read_input=read_input)
    if argv is None:
        return None
    try:
        result = service.register_local_command(argv)
    except Exception as exc:
        return format_error(exc, translator)
    if result.kind == "conflict":
        confirmed = _confirm(
            screen,
            translator,
            decoder,
            translator.text("status.dataset_registration_conflict", dataset_id=result.registration.dataset_id),
            title=translator.text("status.dataset_registration_conflict_title"),
            controls=translator.text("status.dataset_registration_conflict_controls"),
            read_input=read_input,
        )
        if not confirmed:
            return translator.text("status.dataset_registration_cancelled")
        try:
            result = service.register_local_command(argv, replace=True)
        except Exception as exc:
            return format_error(exc, translator)
    return translator.text(f"status.dataset_registration_{result.kind}", dataset_id=result.registration.dataset_id)


def _manager_help_lines(
    status: DatasetRegistrationStatus | None,
    translator: Translator,
    *,
    details: bool,
    width: int,
    statuses: tuple[DatasetRegistrationStatus, ...] = (),
) -> tuple[str, ...]:
    def tree(items: tuple[tuple[str, tuple[str, ...]], ...]) -> list[str]:
        rows: list[str] = []
        for item_index, (label, children) in enumerate(items):
            last_item = item_index == len(items) - 1
            branch = "└─" if last_item else "├─"
            continuation = "   " if last_item else "│  "
            rows.append(f"{branch} {label}")
            for child_index, child in enumerate(children):
                rows.append(
                    f"{continuation}{'└─' if child_index == len(children) - 1 else '├─'} {child}"
                )
        return rows

    if details and status is not None:
        descriptor = status.registration.probe.descriptor
        rows = [
            translator.text("status.dataset_help_section_selecting"),
            *tree(
                (
                    (
                        translator.text(
                            "status.dataset_help_setup_title",
                            name=_descriptor_title(descriptor, translator),
                        ),
                        (),
                    ),
                )
            ),
            "",
        ]
        for required, heading in (
            (True, translator.text("status.dataset_environment_required")),
            (False, translator.text("status.dataset_environment_optional")),
        ):
            variables = tuple(item for item in descriptor.environment if item.required is required)
            if not variables:
                continue
            if rows[-1] != "":
                rows.append("")
            rows.append(heading)
            variables_rows: list[tuple[str, tuple[str, ...]]] = []
            for item in variables:
                present = item not in status.missing_environment
                state = translator.text(
                    "status.dataset_environment_present"
                    if present
                    else "status.dataset_environment_missing"
                )
                variables_rows.append(
                    (
                        f"{item.name} · {state} · {_text(item.label, translator)}",
                        (
                            *wrap_width(_text(item.how_to_get, translator), max(1, width - 6)),
                            *(
                                wrap_width(item.help_url, max(1, width - 6))
                                if item.help_url is not None
                                else ()
                            ),
                        ),
                    )
                )
            rows.extend(tree(tuple(variables_rows)))
        return tuple(rows[:-1] if rows[-1:] == [""] else rows)
    rows = [
        translator.text("status.dataset_help_section_selecting"),
        *tree(((translator.text("status.dataset_help_dynamic_list"), ()),)),
        "",
        translator.text("status.dataset_help_section_actions"),
        *tree(
            (
                (translator.text("status.dataset_help_refresh"), ()),
                (translator.text("status.dataset_help_add"), ()),
                (translator.text("status.dataset_help_details"), ()),
                *(
                    ((translator.text("status.dataset_help_upgrade"), ()),)
                    if status is not None and status.registration.available_update is not None
                    else ()
                ),
                (translator.text("status.dataset_help_enable"), ()),
                (translator.text("status.dataset_help_remove"), ()),
                (translator.text("status.dataset_help_navigation"), ()),
            )
        ),
        "",
        translator.text("status.dataset_help_states"),
        *tree(
            (
                (translator.text("status.dataset_help_ready"), ()),
                (translator.text("status.dataset_help_setup_required"), ()),
                (translator.text("status.dataset_help_unavailable"), ()),
                (translator.text("status.dataset_help_disabled"), ()),
            )
        ),
    ]
    return tuple(rows)


def _manager_help_frame(
    lines: tuple[str, ...], translator: Translator, *, width: int, height: int, color: bool = False
) -> Frame:
    content_width = max(1, min(width - 4, 88))
    headings = {
        translator.text("status.dataset_help_section_selecting"),
        translator.text("status.dataset_help_states"),
        translator.text("status.dataset_help_section_actions"),
        translator.text("status.dataset_environment_required"),
        translator.text("status.dataset_environment_optional"),
    }
    content = tuple(
        clip_width(
            emphasize(line, color=get_color_scheme("classic").highlight, enabled=color)
            if line in headings
            else line,
            content_width,
        )
        for line in lines
    )
    footer = clip_width(translator.text("status.dataset_help_close"), content_width)
    panel_width = min(width, max(*(display_width(line) for line in (*content, footer)), 1) + 4)
    inner_width = max(1, panel_width - 4)
    visible = content[: max(1, height - 5)]
    border = "-" * max(0, panel_width - 2)
    panel = ["+" + border + "+"]
    panel.extend("| " + pad_width(line, inner_width) + " |" for line in visible)
    panel.append("|" + "-" * max(0, panel_width - 2) + "|")
    panel.append("| " + pad_width(footer, inner_width) + " |")
    panel.append("+" + border + "+")
    start_x = max(0, (width - panel_width) // 2)
    start_y = max(0, (height - len(panel)) // 2)
    canvas = ["" for _ in range(height)]
    for index, row in enumerate(panel):
        if start_y + index < height:
            canvas[start_y + index] = " " * start_x + row
    return Frame(tuple(canvas))


def _show_manager_help(
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    *,
    status: DatasetRegistrationStatus | None = None,
    details: bool = False,
    read_input: Callable[[], object] | None = None,
) -> None:
    size = get_terminal_size()
    screen.paint(
        _manager_help_frame(
            _manager_help_lines(status, translator, details=details, width=max(1, size.columns - 4)),
            translator,
            width=size.columns,
            height=size.lines,
            color=True,
        )
    )
    while True:
        event = _read_manager_event(decoder, read_input)
        if isinstance(event, KeyEvent) and event.value in {"h", "\x1b", "\r", "\n"}:
            return


def _register_result(
    service: DatasetService,
    result,
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    *,
    read_input: Callable[[], object] | None = None,
) -> str:
    if result.kind == "conflict":
        confirmed = _confirm(
            screen,
            translator,
            decoder,
            translator.text("status.dataset_registration_conflict", dataset_id=result.registration.dataset_id),
            title=translator.text("status.dataset_registration_conflict_title"),
            controls=translator.text("status.dataset_registration_conflict_controls"),
            read_input=read_input,
        )
        if not confirmed:
            return translator.text("status.dataset_registration_cancelled")
        result = service.register_installed_dataset(result.registration.dataset_id, replace=True)
    return translator.text(f"status.dataset_registration_{result.kind}", dataset_id=result.registration.dataset_id)


def _official_preview(service: DatasetService, dataset_id: str):
    return service.prepare_official_install(dataset_id)


def _load_official_preview(
    service: DatasetService,
    dataset_id: str,
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    *,
    read_input: Callable[[], object] | None = None,
):
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ccuv-dataset-preview")
    future = executor.submit(_official_preview, service, dataset_id)
    try:
        while not future.done():
            screen.paint(
                compose_frame(
                    "",
                    translator.text("status.dataset_browse_title"),
                    translator.text("status.dataset_browse_loading_controls"),
                    (translator.text("status.dataset_browse_loading"),),
                    height=get_terminal_size().lines,
                )
            )
            event = _read_manager_event(decoder, read_input)
            if isinstance(event, KeyEvent) and event.value == "\x1b":
                return None
        return future.result()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _official_catalog_rows(
    entries: tuple[object, ...],
    translator: Translator,
    *,
    selected: int,
    width: int,
    color: bool,
) -> tuple[str, ...]:
    """Render official entries with Custom Ranking's item/description hierarchy."""

    context = RenderContext(width, 1, translator, color=color, color_scheme="classic")
    rows: list[str] = []
    for item_index, entry in enumerate(entries):
        rows.append(
            clip_width(
                f"{'›' if item_index == selected else ' '} "
                f"{_text(entry.title, translator)} · {entry.id}",
                width,
            )
        )
        available = max(1, width - 2)
        description_rows = wrap_width(_text(entry.summary, translator), available)
        for row_index, row in enumerate(description_rows[:2]):
            if row_index == 1 and len(description_rows) > 2:
                row = clip_width(row, max(0, available - 1)) + "…"
            rows.append("  " + render_ranking_description(row, context))
    return tuple(rows)


def _register_official(
    service: DatasetService,
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    *,
    read_input: Callable[[], object] | None = None,
) -> str | None:
    try:
        entries = service.official_entries()
    except Exception as exc:
        return format_error(exc, translator)
    if not entries:
        return translator.text("status.datasets_official_empty")
    index = 0
    while True:
        rows = _official_catalog_rows(
            entries,
            translator,
            selected=index,
            width=get_terminal_size().columns,
            color=True,
        )
        screen.paint(
            compose_frame(
                "\n".join(rows),
                translator.text("status.dataset_browse_title"),
                translator.text("status.dataset_browse_controls"),
                height=get_terminal_size().lines,
            )
        )
        event = _read_manager_event(decoder, read_input)
        if not isinstance(event, KeyEvent):
            continue
        if event.value == "h":
            _show_manager_help(screen, translator, decoder, read_input=read_input)
            continue
        if event.value == "\x1b":
            return None
        if event.value in {"j", "\x1b[B"}:
            index = (index + 1) % len(entries)
            continue
        if event.value in {"k", "\x1b[A"}:
            index = (index - 1) % len(entries)
            continue
        if event.value not in {"\r", "\n"}:
            continue
        selected = entries[index]
        try:
            preview = _load_official_preview(
                service, selected.id, screen, translator, decoder, read_input=read_input
            )
            if preview is None:
                continue
            artifact, archive, manifest = preview
        except Exception as exc:
            return format_error(exc, translator)
        if not _confirm(
            screen,
            translator,
            decoder,
            "\n".join(_manifest_rows(manifest, translator, get_terminal_size().columns)),
            title=translator.text("status.dataset_browse_title"),
            controls=translator.text("status.dataset_browse_confirm_controls"),
            read_input=read_input,
        ):
            continue
        try:
            service.install_artifact(artifact, archive)
            return _register_result(
                service,
                service.register_installed_dataset(selected.id),
                screen,
                translator,
                decoder,
                read_input=read_input,
            )
        except Exception as exc:
            return format_error(exc, translator)


def _read_github_repository(
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    *,
    read_input: Callable[[], object] | None = None,
) -> str | None:
    repository = ""
    while True:
        screen.paint(
            compose_frame(
                "\n".join(
                    (
                        translator.text("status.dataset_github_prompt"),
                        "",
                        repository or "—",
                    )
                ),
                translator.text("status.dataset_github_title"),
                translator.text("status.dataset_github_controls"),
                height=get_terminal_size().lines,
            )
        )
        event = _read_manager_event(decoder, read_input)
        if isinstance(event, PasteEvent):
            repository += event.value
            continue
        if not isinstance(event, KeyEvent):
            continue
        if event.value == "h":
            _show_manager_help(screen, translator, decoder, read_input=read_input)
            continue
        if event.value == "\x1b":
            return None
        if event.value in {"\x7f", "\b"}:
            repository = repository[:-1]
        elif event.value in {"\r", "\n"}:
            return repository.strip() or None
        elif len(event.value) == 1 and event.value.isprintable():
            repository += event.value


def _register_github(
    service: DatasetService,
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    *,
    read_input: Callable[[], object] | None = None,
) -> str | None:
    repository = _read_github_repository(screen, translator, decoder, read_input=read_input)
    if repository is None:
        return None
    try:
        artifact = service.resolve_github_repository(repository)
        archive = service.download_artifact(artifact)
        manifest = service.inspect_artifact(artifact, archive)
    except Exception as exc:
        return format_error(exc, translator)
    if not _confirm(
        screen,
        translator,
        decoder,
        "\n".join(_manifest_rows(manifest, translator, get_terminal_size().columns)),
        title=translator.text("status.dataset_github_title"),
        controls=translator.text("status.dataset_github_confirm_controls"),
        read_input=read_input,
    ):
        return None
    try:
        status = service.install_artifact(artifact, archive)
        assert status.installed is not None
        return _register_result(
            service,
            service.register_installed_dataset(status.installed.dataset_id),
            screen,
            translator,
            decoder,
            read_input=read_input,
        )
    except Exception as exc:
        return format_error(exc, translator)


def run_dataset_manager(service: DatasetService, translator: Translator) -> int:
    screen = FramePainter(sys.stdout)
    selected = 0
    details = False
    notice: str | None = None
    help_open = False
    try:
        set_cursor_visible(sys.stdout, False)
        with tui_input_mode() as decoder:
            while True:
                statuses = service.registrations()
                view = render_dataset_manager(
                    statuses,
                    translator,
                    selected=selected,
                    details=details,
                    width=get_terminal_size().columns,
                    height=get_terminal_size().lines,
                    notice=notice,
                )
                active = statuses[selected] if statuses else None
                screen.paint(
                    _manager_help_frame(
                        _manager_help_lines(
                            active,
                            translator,
                            details=details,
                            width=max(1, get_terminal_size().columns - 4),
                            statuses=statuses,
                        ),
                        translator,
                        width=get_terminal_size().columns,
                        height=get_terminal_size().lines,
                        color=True,
                    )
                    if help_open
                    else view.frame
                )
                event = _read_manager_event(decoder, None)
                if not isinstance(event, KeyEvent):
                    continue
                key = event.value
                if help_open:
                    if key in {"h", "\x1b", "\r", "\n"}:
                        help_open = False
                    continue
                if key == "\x1b":
                    if details:
                        details = False
                    continue
                if key in {"j", "\x1b[B"} and statuses:
                    selected = (selected + 1) % len(statuses)
                elif key in {"k", "\x1b[A"} and statuses:
                    selected = (selected - 1) % len(statuses)
                elif key in {"\r", "\n"} and statuses:
                    details = not details
                elif key == "h":
                    help_open = True
                elif key == "+":
                    source = _choose_dataset_source(screen, translator, decoder)
                    if source == "local":
                        notice = _register_local(service, screen, translator, decoder)
                    elif source == "official":
                        notice = _register_official(service, screen, translator, decoder)
                    elif source == "github":
                        notice = _register_github(service, screen, translator, decoder)
                elif key == "d" and view.selected_id is not None:
                    current = statuses[selected].registration
                    service.set_enabled(current.dataset_id, not current.enabled)
                elif key == "x" and view.selected_id is not None:
                    current = statuses[selected].registration
                    if _confirm(
                        screen,
                        translator,
                        decoder,
                        translator.text("status.dataset_remove_confirm", dataset_id=current.dataset_id),
                        title=translator.text("status.dataset_remove_title"),
                        controls=translator.text("status.dataset_remove_controls"),
                    ):
                        service.remove_registration(current.dataset_id)
                        selected = max(0, selected - 1)
                elif key == "r":
                    refreshed = service.refresh_all()
                    unavailable = sum(
                        item.availability == "unavailable" for item in refreshed
                    )
                    notice = translator.text(
                        "status.dataset_refresh_complete", unavailable=unavailable
                    )
                elif (
                    key == "u"
                    and details
                    and view.selected_id is not None
                    and statuses[selected].registration.available_update is not None
                ):
                    current = statuses[selected].registration
                    candidate = current.available_update
                    assert candidate is not None
                    if _confirm(
                        screen,
                        translator,
                        decoder,
                        translator.text(
                            "status.dataset_upgrade_confirm",
                            dataset_id=current.dataset_id,
                            current=current.source.release_tag,
                            candidate=candidate.release_tag,
                        ),
                        title=translator.text("status.dataset_upgrade_title"),
                        controls=translator.text("status.dataset_upgrade_controls"),
                    ):
                        try:
                            upgraded = service.upgrade(current.dataset_id)
                            notice = translator.text(
                                "status.dataset_upgrade_complete",
                                dataset_id=upgraded.dataset_id,
                                version=upgraded.probe.descriptor.version,
                            )
                        except Exception as exc:
                            notice = format_error(exc, translator)
    except KeyboardInterrupt:
        return 0
    finally:
        screen.finish()
        set_cursor_visible(sys.stdout, True)
