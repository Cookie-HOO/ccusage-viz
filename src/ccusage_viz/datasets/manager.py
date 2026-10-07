from __future__ import annotations

import shlex
import sys
from collections.abc import Callable
from dataclasses import dataclass
from shutil import get_terminal_size

from ccusage_viz.datasets.models import DatasetRegistrationStatus
from ccusage_viz.datasets.service import DatasetService
from ccusage_viz.diagnostics import format_error
from ccusage_viz.formatting import clip_width, pad_width, wrap_width
from ccusage_viz.i18n import Translator
from ccusage_viz.terminal import Frame, FramePainter, compose_frame, set_cursor_visible
from ccusage_viz.tui_input import InputDecoder, KeyEvent, PasteEvent, read_event, tui_input_mode


@dataclass(frozen=True, slots=True)
class ManagerView:
    frame: Frame
    selected_id: str | None


def _text(value, translator: Translator) -> str:
    return value.zh_cn if translator.language == "zh" else value.en


def _list_rows(
    statuses: tuple[DatasetRegistrationStatus, ...],
    translator: Translator,
    *,
    selected: int,
    width: int,
) -> list[str]:
    rows: list[str] = []
    labels = {
        "ready": translator.text("status.dataset_ready"),
        "setup_required": translator.text("status.dataset_setup_required"),
        "unavailable": translator.text("status.dataset_unavailable"),
        "disabled": translator.text("status.dataset_disabled"),
    }
    for availability in ("ready", "setup_required", "unavailable", "disabled"):
        grouped = [item for item in statuses if item.availability == availability]
        if not grouped:
            continue
        rows.extend(("", translator.text(f"status.dataset_group_{availability}")))
        for item in grouped:
            index = statuses.index(item)
            descriptor = item.registration.probe.descriptor
            marker = "›" if index == selected else " "
            rows.append(
                clip_width(
                    f"{marker} {_text(descriptor.dataset.title, translator)}  "
                    f"{descriptor.version}  {translator.text('label.dataset_source_local')} · "
                    f"{labels[item.availability]}",
                    width,
                )
            )
    return rows or [translator.text("status.dataset_manager_empty")]


def _detail_rows(status: DatasetRegistrationStatus, translator: Translator, width: int) -> list[str]:
    descriptor = status.registration.probe.descriptor
    rows = [
        _text(descriptor.dataset.title, translator),
        *wrap_width(_text(descriptor.dataset.description, translator), width),
        f"{_text(descriptor.dataset.unit.label, translator)} · "
        f"{descriptor.source_timezone or translator.text('status.dataset_timezone_unspecified')}",
        "",
        translator.text("status.dataset_details_supports"),
        " · ".join(
            translator.text(f"label.pane_{kind}") for kind in descriptor.capabilities.charts
        ),
        "",
        translator.text("status.dataset_details_environment"),
        *(
            f"{item.name} · "
            f"{translator.text('status.dataset_environment_present') if item not in status.missing_environment else translator.text('status.dataset_environment_missing')}"
            for item in descriptor.environment
        ),
        "",
        translator.text("status.dataset_details_source"),
        *wrap_width(shlex.join(status.registration.source.command_argv), width),
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
        controls = translator.text("status.dataset_manager_controls")
    elif details and selected_status is not None:
        body = "\n".join(_detail_rows(selected_status, translator, width))
        controls = translator.text("status.dataset_manager_detail_controls")
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
        event = read_input() if read_input is not None else read_event(decoder, 0.1)
        if isinstance(event, PasteEvent):
            command += event.value
            continue
        if not isinstance(event, KeyEvent):
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
        event = read_input() if read_input is not None else read_event(decoder, 0.1)
        if not isinstance(event, KeyEvent):
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
        event = read_input() if read_input is not None else read_event(decoder, 0.1)
        if not isinstance(event, KeyEvent):
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
        rows = [
            f"{'›' if item_index == index else ' '} "
            f"{_text(entry.title, translator)} · {entry.id}"
            for item_index, entry in enumerate(entries)
        ]
        screen.paint(
            compose_frame(
                "\n".join(rows),
                translator.text("status.dataset_browse_title"),
                translator.text("status.dataset_browse_controls"),
                height=get_terminal_size().lines,
            )
        )
        event = read_input() if read_input is not None else read_event(decoder, 0.1)
        if not isinstance(event, KeyEvent):
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
        if not _confirm(
            screen,
            translator,
            decoder,
            translator.text("status.dataset_browse_confirm", dataset_id=selected.id, repository=selected.artifacts[0].repository),
            title=translator.text("status.dataset_browse_title"),
            controls=translator.text("status.dataset_browse_confirm_controls"),
            read_input=read_input,
        ):
            continue
        try:
            service.install_official(selected.id)
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
                repository or "—",
                translator.text("status.dataset_github_title"),
                translator.text("status.dataset_github_controls"),
                height=get_terminal_size().lines,
            )
        )
        event = read_input() if read_input is not None else read_event(decoder, 0.1)
        if isinstance(event, PasteEvent):
            repository += event.value
            continue
        if not isinstance(event, KeyEvent):
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
    except Exception as exc:
        return format_error(exc, translator)
    if not _confirm(
        screen,
        translator,
        decoder,
        translator.text("status.dataset_github_confirm", repository=artifact.repository),
        title=translator.text("status.dataset_github_title"),
        controls=translator.text("status.dataset_github_confirm_controls"),
        read_input=read_input,
    ):
        return None
    try:
        status = service.install_resolved_github_artifact(artifact)
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
                screen.paint(view.frame)
                event = read_event(decoder, 0.1)
                if not isinstance(event, KeyEvent):
                    continue
                key = event.value
                if key == "q":
                    return 0
                if key == "\x1b":
                    if details:
                        details = False
                    else:
                        return 0
                if key in {"j", "\x1b[B"} and statuses:
                    selected = (selected + 1) % len(statuses)
                elif key in {"k", "\x1b[A"} and statuses:
                    selected = (selected - 1) % len(statuses)
                elif key == "i" and statuses:
                    details = not details
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
    finally:
        screen.finish()
        set_cursor_visible(sys.stdout, True)
