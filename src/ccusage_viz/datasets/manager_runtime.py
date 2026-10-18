from __future__ import annotations

import shlex
import sys
from collections.abc import Callable
from shutil import get_terminal_size

from ccusage_viz.datasets.manager_rendering import _descriptor_title, _text, render_dataset_manager
from ccusage_viz.datasets.models import DatasetRegistrationStatus
from ccusage_viz.datasets.service import DatasetService
from ccusage_viz.diagnostics import format_error
from ccusage_viz.formatting import clip_width, display_width, pad_width, wrap_width
from ccusage_viz.i18n import Translator
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.terminal import Frame, FramePainter, compose_frame, emphasize, set_cursor_visible
from ccusage_viz.tui_input import InputDecoder, KeyEvent, PasteEvent, read_event, tui_input_mode


def _read_manager_event(decoder: InputDecoder, read_input: Callable[[], object] | None) -> object:
    """Read one nested-manager event and preserve global Ctrl-C semantics."""

    event = read_input() if read_input is not None else read_event(decoder, 0.1)
    if isinstance(event, KeyEvent) and event.value == "\x03":
        raise KeyboardInterrupt
    return event


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
        if event.value == "\x08":
            _show_manager_help(screen, translator, decoder, read_input=read_input)
            continue
        if event.value == "\x1b":
            return None
        if event.value == "\x7f":
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
            translator.text(
                "status.dataset_registration_conflict", dataset_id=result.registration.dataset_id
            ),
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
    return translator.text(
        f"status.dataset_registration_{result.kind}", dataset_id=result.registration.dataset_id
    )


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
            _manager_help_lines(
                status, translator, details=details, width=max(1, size.columns - 4)
            ),
            translator,
            width=size.columns,
            height=size.lines,
            color=True,
        )
    )
    while True:
        event = _read_manager_event(decoder, read_input)
        if isinstance(event, KeyEvent) and event.value in {"h", "\x08", "\x1b", "\r", "\n"}:
            return


def run_dataset_manager(service: DatasetService, translator: Translator) -> int:
    from ccusage_viz.datasets.manager_installation import _register_github, _register_official

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
                        translator.text(
                            "status.dataset_remove_confirm", dataset_id=current.dataset_id
                        ),
                        title=translator.text("status.dataset_remove_title"),
                        controls=translator.text("status.dataset_remove_controls"),
                    ):
                        service.remove_registration(current.dataset_id)
                        selected = max(0, selected - 1)
                elif key == "r":
                    refreshed = service.refresh_all()
                    unavailable = sum(item.availability == "unavailable" for item in refreshed)
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
                            current=current.source.release_tag,  # ty: ignore[unresolved-attribute]
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
