from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from shutil import get_terminal_size

from ccusage_viz.datasets.models import (
    CatalogEntry,
    DatasetManifest,
    DatasetStatus,
    ReleaseArtifact,
)
from ccusage_viz.datasets.service import DatasetService
from ccusage_viz.diagnostics import format_error
from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import clip_width, truncate_width, wrap_width
from ccusage_viz.i18n import Translator
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.ranking_description import render_ranking_description
from ccusage_viz.terminal import FramePainter, compose_frame
from ccusage_viz.tui_input import InputDecoder, KeyEvent, PasteEvent, read_event


def _official_catalog_item_rows(
    entry: CatalogEntry,
    translator: Translator,
    *,
    selected: bool,
    width: int,
    color: bool = False,
    color_scheme: str = "classic",
) -> tuple[str, ...]:
    """Render one catalog item with its description as subordinate rows."""

    width = max(1, width)
    content_width = max(1, width - 2)
    name = entry.title.zh_cn if translator.language == "zh" else entry.title.en
    summary = entry.summary.zh_cn if translator.language == "zh" else entry.summary.en
    primary = clip_width(f"{'›' if selected else ' '} {name} · {entry.id}", width)
    wrapped = list(wrap_width(summary, content_width))
    if len(wrapped) > 2:
        wrapped = [wrapped[0], truncate_width(wrapped[1], max(0, content_width - 1)) + "…"]
    context = RenderContext(width, 1, translator, color=color, color_scheme=color_scheme)
    descriptions = tuple("  " + render_ranking_description(row, context) for row in wrapped[:2])
    return (primary, *descriptions)


def _official_catalog_rows(
    entries: tuple[CatalogEntry, ...],
    translator: Translator,
    *,
    index: int,
    width: int,
    color: bool = False,
    color_scheme: str = "classic",
) -> list[str]:
    """Render catalog entries as primary items with subordinate descriptions."""

    return [
        row
        for item_index, entry in enumerate(entries)
        for row in _official_catalog_item_rows(
            entry,
            translator,
            selected=item_index == index,
            width=width,
            color=color,
            color_scheme=color_scheme,
        )
    ]


def _official_catalog_viewport(
    entries: tuple[CatalogEntry, ...],
    translator: Translator,
    *,
    index: int,
    offset: int,
    width: int,
    height: int,
    color: bool = False,
    color_scheme: str = "classic",
) -> tuple[str, int]:
    blocks = tuple(
        _official_catalog_item_rows(
            entry,
            translator,
            selected=item_index == index,
            width=width,
            color=color,
            color_scheme=color_scheme,
        )
        for item_index, entry in enumerate(entries)
    )
    rows = [row for block in blocks for row in block]
    visible_rows = max(1, height - 2)
    maximum_offset = max(0, len(rows) - visible_rows)
    offset = min(max(0, offset), maximum_offset)
    selected_start = sum(len(block) for block in blocks[:index])
    selected_end = selected_start + len(blocks[index])
    if selected_start < offset:
        offset = selected_start
    elif selected_end > offset + visible_rows:
        offset = (
            selected_start if len(blocks[index]) > visible_rows else selected_end - visible_rows
        )
    offset = min(max(0, offset), maximum_offset)
    return "\n".join(rows[offset : offset + visible_rows]), offset


def _official_preview_rows(
    preview: tuple[ReleaseArtifact, bytes, DatasetManifest], translator: Translator
) -> tuple[str, ...]:
    _artifact, _archive, manifest = preview
    descriptor = manifest.descriptor
    if descriptor is None:
        return (
            manifest.metric.title.zh_cn
            if translator.language == "zh"
            else manifest.metric.title.en,
        )
    title = (
        descriptor.dataset.title.zh_cn
        if translator.language == "zh"
        else descriptor.dataset.title.en
    )
    description = (
        descriptor.dataset.description.zh_cn
        if translator.language == "zh"
        else descriptor.dataset.description.en
    )
    charts = " · ".join(
        translator.text(f"label.pane_{kind}")
        for kind in descriptor.capabilities.charts  # ty: ignore[unresolved-attribute]
    )
    required = tuple(item.name for item in descriptor.environment if item.required)
    optional = tuple(item.name for item in descriptor.environment if not item.required)
    return (  # ty: ignore[invalid-return-type]
        title,
        description,
        f"{translator.text('status.dataset_column_version')}: {descriptor.version}",
        f"{translator.text('status.dataset_details_supports')}: {charts}",
        translator.text("status.dataset_details_environment"),
        *(
            f"{translator.text('status.dataset_environment_required')}: {' · '.join(required)}"
            if required
            else (),
        ),
        *(
            f"{translator.text('status.dataset_environment_optional')}: {' · '.join(optional)}"
            if optional
            else (),
        ),
    )


def _browse_dataset_catalog(
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    *,
    service: DatasetService,
    height: int,
    paint_choices: Callable[[str, str, str, tuple[str, ...]], None] | None = None,
    read_input: Callable[[], object] | None = None,
) -> str | None:
    """Fetch and present verified official datasets without blocking the dashboard."""

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ccusage-viz-catalog")
    future = executor.submit(service.official_entries)
    entries: tuple[CatalogEntry, ...] | None = None
    error: str | None = None
    try:
        while entries is None and error is None:
            title = translator.text("status.dataset_browse_title")
            controls = translator.text("status.dataset_browse_controls")
            notices = (translator.text("status.dataset_catalog_loading"),)
            if paint_choices is None:
                screen.paint(compose_frame("", title, controls, notices, height=height))
            else:
                paint_choices("", title, controls, notices)
            if future.done():
                try:
                    entries = future.result()
                except UsageError as exc:
                    error = format_error(exc, translator)
                except Exception:
                    error = translator.text("status.dataset_catalog_unavailable")
                continue
            event = read_input() if read_input is not None else read_event(decoder, 0.1)
            if isinstance(event, KeyEvent) and event.value == "\x1b":
                future.cancel()
                return None
            if not future.done():
                continue
            try:
                entries = future.result()
            except UsageError as exc:
                error = format_error(exc, translator)
            except Exception:
                error = translator.text("status.dataset_catalog_unavailable")
        if error is not None:
            while True:
                title = translator.text("status.dataset_browse_title")
                controls = translator.text("status.dataset_browse_controls")
                if paint_choices is None:
                    screen.paint(compose_frame("", title, controls, (error,), height=height))
                else:
                    paint_choices("", title, controls, (error,))
                event = read_input() if read_input is not None else read_event(decoder, 0.1)
                if isinstance(event, KeyEvent) and event.value == "\x1b":
                    return None
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    assert entries is not None
    index = 0
    offset = 0
    confirming = False
    notice: str | None = None
    host_os, host_arch = service.platform
    platform_name = f"{host_os}/{host_arch}"
    while True:
        choices, offset = (
            _official_catalog_viewport(
                entries,
                translator,
                index=index,
                offset=offset,
                width=get_terminal_size().columns,
                height=height,
            )
            if entries
            else (translator.text("status.datasets_official_empty"), 0)
        )
        selected = entries[index] if entries else None
        available = selected is not None and any(
            artifact.os == host_os and artifact.arch == host_arch for artifact in selected.artifacts
        )
        title = translator.text("status.dataset_browse_title")
        controls = translator.text(
            "status.dataset_browse_confirm_controls"
            if confirming
            else "status.dataset_browse_controls"
        )
        notices = () if notice is None else (notice,)
        if confirming and selected is not None:
            artifact = next(
                artifact
                for artifact in selected.artifacts
                if artifact.os == host_os and artifact.arch == host_arch
            )
            detail = "\n".join(
                (
                    choices,
                    "",
                    selected.summary.zh_cn if translator.language == "zh" else selected.summary.en,
                    f"{artifact.repository} · {artifact.release_tag} · {platform_name}",
                    translator.text(
                        "status.dataset_browse_confirm",
                        dataset_id=selected.id,
                        repository=artifact.repository,
                    ),
                )
            )
        else:
            detail = choices
        if paint_choices is None:
            screen.paint(compose_frame(detail, title, controls, notices, height=height))
        else:
            paint_choices(detail, title, controls, notices)
        event = read_input() if read_input is not None else read_event(decoder, 0.1)
        if not isinstance(event, KeyEvent):
            continue
        key = event.value
        if key == "\x1b":
            if confirming:
                confirming = False
                notice = None
                continue
            return None
        if key == "h":
            notice = translator.text("status.dataset_catalog_help_hint")
            continue
        if not entries:
            continue
        if not confirming and key in {"j", "\x1b[B"}:
            index = (index + 1) % len(entries)
            notice = None
            continue
        if not confirming and key in {"k", "\x1b[A"}:
            index = (index - 1) % len(entries)
            notice = None
            continue
        if key not in {"\r", "\n"}:
            continue
        if not available:
            notice = translator.text(
                "status.dataset_catalog_unavailable_platform", platform=platform_name
            )
            continue
        if not confirming:
            confirming = True
            notice = None
            continue
        notice = translator.text("status.dataset_browse_installing", dataset_id=selected.id)
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ccusage-viz-install")
        install = executor.submit(service.install_official, selected.id)
        try:
            while not install.done():
                if paint_choices is None:
                    screen.paint(compose_frame(detail, title, controls, (notice,), height=height))
                else:
                    paint_choices(detail, title, controls, (notice,))
                event = read_input() if read_input is not None else read_event(decoder, 0.1)
                if isinstance(event, KeyEvent) and event.value == "\x1b":
                    # A started installation is transactional and cannot be safely cancelled.
                    continue
            install.result()
        except UsageError as exc:
            confirming = False
            notice = format_error(exc, translator)
            continue
        except Exception:
            confirming = False
            notice = translator.text("error.dataset_download_failed")
            continue
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        return selected.id


def _install_github_dataset(
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    *,
    service: DatasetService,
    height: int,
    paint_choices: Callable[[str, str, str, tuple[str, ...]], None] | None = None,
    read_input: Callable[[], object] | None = None,
) -> str | None:
    """Install a verified GitHub dataset from one repository input."""

    repository = ""
    artifact: ReleaseArtifact | None = None
    error: str | None = None
    resolving: Future[ReleaseArtifact] | None = None
    installing: Future[DatasetStatus] | None = None
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ccusage-viz-github")
    try:
        while True:
            if resolving is not None and resolving.done():
                try:
                    artifact = resolving.result()
                    error = None
                except UsageError as exc:
                    error = format_error(exc, translator)
                except Exception:
                    error = translator.text("error.dataset_download_failed")
                resolving = None
            if installing is not None and installing.done():
                try:
                    status = installing.result()
                    installed = status.installed
                    if installed is None:
                        raise UsageError("error.dataset_corrupt")
                    return installed.dataset_id
                except UsageError as exc:
                    error = format_error(exc, translator)
                except Exception:
                    error = translator.text("error.dataset_download_failed")
                artifact = None
                installing = None

            title = translator.text("status.dataset_github_title")
            if resolving is not None:
                body = repository or "—"
                controls = translator.text("status.dataset_github_loading_controls")
                notices = (translator.text("status.dataset_github_resolving"),)
            elif installing is not None:
                body = repository
                controls = translator.text("status.dataset_github_loading_controls")
                notices = (translator.text("status.dataset_github_installing"),)
            elif artifact is not None:
                body = "\n".join(
                    (
                        repository,
                        "",
                        f"{artifact.release_tag} · {artifact.asset_name}",
                        artifact.sha256,
                        translator.text(
                            "status.dataset_github_confirm", repository=artifact.repository
                        ),
                    )
                )
                controls = translator.text("status.dataset_github_confirm_controls")
                notices = () if error is None else (error,)
            else:
                body = repository or "—"
                controls = translator.text("status.dataset_github_controls")
                notices = () if error is None else (error,)
            if paint_choices is None:
                screen.paint(compose_frame(body, title, controls, notices, height=height))
            else:
                paint_choices(body, title, controls, notices)

            event = read_input() if read_input is not None else read_event(decoder, 0.1)
            if (
                isinstance(event, PasteEvent)
                and artifact is None
                and resolving is None
                and installing is None
            ):
                repository += event.value
                error = None
                continue
            if not isinstance(event, KeyEvent):
                continue
            key = event.value
            if key == "\x1b":
                if resolving is not None or installing is not None:
                    continue
                if artifact is not None:
                    artifact = None
                    error = None
                    continue
                return None
            if resolving is not None or installing is not None:
                continue
            if artifact is not None:
                if key in {"\r", "\n"}:
                    installing = executor.submit(service.install_resolved_github_artifact, artifact)
                continue
            if key in {"\r", "\n"}:
                if repository.strip():
                    resolving = executor.submit(service.resolve_github_repository, repository)
                    error = None
                continue
            if key in {"\x7f", "\b"}:
                repository = repository[:-1]
                error = None
            elif len(key) == 1 and key.isprintable():
                repository += key
                error = None
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
