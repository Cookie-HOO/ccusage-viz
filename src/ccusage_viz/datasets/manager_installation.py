from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from shutil import get_terminal_size

from ccusage_viz.datasets.manager_rendering import _manifest_rows, _text
from ccusage_viz.datasets.manager_runtime import _confirm, _read_manager_event, _show_manager_help
from ccusage_viz.datasets.service import DatasetService
from ccusage_viz.diagnostics import format_error
from ccusage_viz.formatting import clip_width, wrap_width
from ccusage_viz.i18n import Translator
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.ranking_description import render_ranking_description
from ccusage_viz.terminal import FramePainter, compose_frame
from ccusage_viz.tui_input import InputDecoder, KeyEvent, PasteEvent


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
            translator.text(
                "status.dataset_registration_conflict", dataset_id=result.registration.dataset_id
            ),
            title=translator.text("status.dataset_registration_conflict_title"),
            controls=translator.text("status.dataset_registration_conflict_controls"),
            read_input=read_input,
        )
        if not confirmed:
            return translator.text("status.dataset_registration_cancelled")
        result = service.register_installed_dataset(result.registration.dataset_id, replace=True)
    return translator.text(
        f"status.dataset_registration_{result.kind}", dataset_id=result.registration.dataset_id
    )


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
