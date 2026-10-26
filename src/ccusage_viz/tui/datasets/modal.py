from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ccusage_viz.datasets.service import DatasetService
    from ccusage_viz.tui.session import TuiSession

import shlex
from collections.abc import Callable
from functools import partial
from shutil import get_terminal_size
from typing import cast

from ccusage_viz.command_copy import copy_command
from ccusage_viz.configuration import default_custom_pane
from ccusage_viz.custom_models import V2MetricDescriptor, V2ProbeDescriptor
from ccusage_viz.datasets.models import (
    CatalogEntry,
    DatasetManifest,
    DatasetRegistrationStatus,
    DatasetStatus,
    ReleaseArtifact,
)
from ccusage_viz.diagnostics import format_error
from ccusage_viz.errors import QueryError, UsageError
from ccusage_viz.i18n import Translator
from ccusage_viz.options import CustomChartConfig, CustomChartPaneConfig, CustomCommandSource
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.terminal import Terminal, compose_frame, emphasize
from ccusage_viz.terminal_ui import dimmed
from ccusage_viz.terminal_ui import notice_lines as format_notice_lines
from ccusage_viz.tui.adjustments import _CUSTOM_PANE_KINDS
from ccusage_viz.tui.datasets.catalog import _official_catalog_viewport, _official_preview_rows
from ccusage_viz.tui.datasets.chooser import (
    _PANE_COMMANDS,
    _chooser_viewport,
    _dataset_metric_chooser_chrome,
    _dataset_metric_chooser_rows,
    _dataset_title,
    _metric_chooser_display_rows,
    _metric_chooser_previous_offset,
    _pane_chooser_rows,
)
from ccusage_viz.tui.header import (
    _custom_source_conflict,
    _custom_source_conflict_message,
    _header_lines,
)
from ccusage_viz.tui.models import (
    CustomPaneDraft,
    DashboardDatasetModalState,
    _custom_metric_periods,
)
from ccusage_viz.tui.pane_lifecycle import _insert_pane, _replace_pane
from ccusage_viz.tui_input import KeyEvent, PasteEvent


def _dashboard_registration_statuses(
    service: DatasetService,
) -> tuple[DatasetRegistrationStatus, ...]:
    """Include unavailable registrations while tolerating legacy service collaborators."""

    registrations = getattr(service, "registrations", None)
    statuses = tuple(
        registrations() if registrations is not None else service.ready_registered_sources()
    )
    order = {"ready": 0, "setup_required": 1, "unavailable": 2, "disabled": 3}
    return tuple(
        sorted(
            statuses,
            key=lambda status: (
                order.get(getattr(status, "availability", "ready"), 99),
                status.registration.dataset_id,
            ),
        )
    )


def _dataset_registration_availability(
    status: DatasetRegistrationStatus, translator: Translator
) -> str:
    availability_key = getattr(status, "availability", "ready")
    missing_environment = getattr(status, "missing_environment", ())
    if missing_environment:
        return translator.text(
            "status.dataset_setup_required_names",
            names=", ".join(item.name for item in missing_environment),
        )
    return translator.text(f"status.dataset_{availability_key}")


def open_dataset_modal(
    session: TuiSession, action: str, pane_index: int, *, initial: CustomChartConfig | None = None
) -> None:
    """Start a Dataset chooser without taking ownership of the event loop."""
    from ccusage_viz.datasets.service import DatasetService

    service = DatasetService()
    try:
        statuses = _dashboard_registration_statuses(service)
        error = None
    except UsageError as exc:
        statuses = ()
        error = format_error(exc, session.translator)
    draft = CustomPaneDraft(
        kind=initial.kind if initial is not None else "timeline",
        dataset_id=initial.source.dataset_id if initial is not None else "",
        command=shlex.join(initial.source.command_argv) if initial is not None else "",
    )
    session.dataset_modal = DashboardDatasetModalState(
        action, pane_index, initial, statuses, service, draft=draft, error=error
    )


def _dataset_modal_size(session: TuiSession, pane_index: int) -> tuple[int, int]:
    from ccusage_viz.tui.painting import grid_geometry

    """Return the target pane's content dimensions for its Dataset modal."""
    size = get_terminal_size()
    header_rows = len(
        _header_lines(
            session.header,
            session.header_style,
            session.translator,
            Terminal(
                size.columns, 4, session.dashboard_theme != "no-color", session.options.host.ascii
            ),
            session.last_successful_update,
        )
    )
    rect = grid_geometry(session, size.columns, size.lines, header_rows, 0).pane(pane_index)
    framed = session.frame_style != "none" or pane_index == session.focused
    return (
        max(1, rect.width - 2 if framed else rect.width),
        max(1, rect.height - 2 if framed else rect.height),
    )


def _dataset_modal_height(session: TuiSession, pane_index: int) -> int:
    return _dataset_modal_size(session, pane_index)[1]


def _paint_dataset_modal(session: TuiSession) -> None:
    """Render the active Dataset state in its target pane."""
    assert session.dataset_modal is not None
    modal = session.dataset_modal
    width, height = _dataset_modal_size(session, modal.pane_index)
    notices = () if modal.error is None else (modal.error,)
    if modal.stage == "pane":
        rows, positions = _pane_chooser_rows(session.translator, modal.index)
        body, modal.offset = _chooser_viewport(
            rows, index=positions[_PANE_COMMANDS[modal.index]], offset=modal.offset, height=height
        )
        title = session.translator.text(f"status.tui_{modal.action}_title")
        controls = session.translator.text(f"status.tui_{modal.action}_controls")
    elif modal.stage == "source":
        entries = modal.statuses
        if not entries:
            body = session.translator.text("status.datasets_empty")
        else:
            modal.index %= len(entries)
            rows = []
            for item_index, status in enumerate(entries):
                selected = "›" if item_index == modal.index else " "
                descriptor = status.registration.probe.descriptor
                availability = _dataset_registration_availability(status, session.translator)
                rows.append(
                    f"{selected} {_dataset_title(descriptor.dataset.title, session.translator)} {descriptor.version} · {availability}"
                )
            body, modal.offset = _chooser_viewport(
                rows,
                index=modal.index,
                offset=modal.offset,
                height=height,
                reserved_rows=2 + len(notices),
            )
        title = session.translator.text("status.dataset_chooser_title")
        controls = session.translator.text("status.dataset_chooser_controls")
    elif modal.stage == "source_loading":
        body = ""
        title = session.translator.text("status.dataset_chooser_title")
        controls = session.translator.text("status.dataset_chooser_controls")
        notices = (session.translator.text("status.loading"),)
    elif modal.stage == "browse":
        if modal.future is not None:
            body = ""
            title = session.translator.text("status.dataset_browse_title")
            controls = session.translator.text("status.dataset_browse_controls")
            notices = (session.translator.text("status.dataset_catalog_loading"),)
        elif not modal.entries:
            body = ""
            title = session.translator.text("status.dataset_browse_title")
            controls = session.translator.text("status.dataset_browse_controls")
            notices = (session.translator.text("status.datasets_official_empty"),)
        else:
            body, modal.offset = _official_catalog_viewport(
                modal.entries,
                session.translator,
                index=modal.index,
                offset=modal.offset,
                width=get_terminal_size().columns,
                height=height,
                color=session.dashboard_theme != "no-color",
                color_scheme=session.dashboard_theme,
            )
            title = session.translator.text("status.dataset_browse_title")
            controls = session.translator.text("status.dataset_browse_controls")
    elif modal.stage == "browse_loading":
        body = ""
        title = session.translator.text("status.dataset_browse_title")
        controls = session.translator.text("status.dataset_browse_loading_controls")
        notices = (session.translator.text("status.dataset_browse_loading"),)
    elif modal.stage == "github":
        body = modal.draft.command or "—"
        title = session.translator.text("status.dataset_github_title")
        if modal.future is not None:
            controls = session.translator.text("status.dataset_github_loading_controls")
            notices = (session.translator.text("status.dataset_github_resolving"),)
        elif modal.artifact is not None:
            body = "\n".join(
                (
                    modal.draft.command,
                    "",
                    f"{modal.artifact.release_tag} · {modal.artifact.asset_name}",
                    modal.artifact.sha256,
                    session.translator.text(
                        "status.dataset_github_confirm", repository=modal.artifact.repository
                    ),
                )
            )
            controls = session.translator.text("status.dataset_github_confirm_controls")
        else:
            controls = session.translator.text("status.dataset_github_controls")
    elif modal.stage == "github_installing":
        body = modal.draft.command
        title = session.translator.text("status.dataset_github_title")
        controls = session.translator.text("status.dataset_github_loading_controls")
        notices = (session.translator.text("status.dataset_github_installing"),)
    elif modal.stage == "browse_confirm":
        assert modal.official_preview is not None
        body = "\n".join(_official_preview_rows(modal.official_preview, session.translator))
        title = session.translator.text("status.dataset_browse_title")
        controls = session.translator.text("status.dataset_browse_confirm_controls")
    elif modal.stage == "installing":
        body = modal.selected_dataset_id or ""
        title = session.translator.text("status.dataset_browse_title")
        controls = session.translator.text("status.dataset_browse_confirm_controls")
        notices = (
            session.translator.text(
                "status.dataset_browse_installing", dataset_id=modal.selected_dataset_id
            ),
        )
    elif modal.stage == "installed":
        rows = [
            f"{('›' if item_index == modal.index else ' ')} {session.translator.text(f'label.pane_{kind}')}"
            for item_index, kind in enumerate(modal.chart_kinds)
        ]
        body, modal.offset = _chooser_viewport(
            rows, index=modal.index, offset=modal.offset, height=height
        )
        title = session.translator.text("status.dataset_chooser_title")
        controls = session.translator.text("status.dataset_chooser_controls")
    elif modal.stage == "metric":
        selected = next(
            status.registration.probe.descriptor
            for status in modal.statuses
            if status.registration.dataset_id == modal.draft.dataset_id
        )
        assert isinstance(selected, V2ProbeDescriptor)
        metric_rows = _metric_chooser_display_rows(
            _dataset_metric_chooser_rows(selected, session.translator),
            width=width,
            ascii=session.options.host.ascii,
        )
        metric_row_index = next(
            (index for index, row in enumerate(metric_rows) if row.metric_index == modal.index)
        )
        scheme = get_color_scheme(session.dashboard_theme)
        rows = [
            f"{('›' if row.metric_index == modal.index else ' ')} "
            + (
                emphasize(
                    row.text, color=scheme.highlight, enabled=session.dashboard_theme != "no-color"
                )
                if row.kind == "group"
                else dimmed(row.text, color=session.dashboard_theme != "no-color")
                if row.kind == "description"
                else row.text
            )
            for row in metric_rows
        ]
        metric_body, modal.offset = _chooser_viewport(
            rows, index=metric_row_index, offset=modal.offset, height=height, reserved_rows=4
        )
        title, prompt = _dataset_metric_chooser_chrome(selected, session.translator)
        body = "\n".join((prompt, metric_body))
        controls = session.translator.text("status.dataset_chooser_controls")
    else:
        fields = (
            session.translator.text("label.custom_kind"),
            session.translator.text("label.custom_dataset"),
            session.translator.text("label.custom_command"),
        )
        values = (modal.draft.kind, modal.draft.dataset_id, modal.draft.command)
        body = "\n".join(
            (
                f"{('›' if index == modal.draft.field else ' ')} {label}: {value or '—'}"
                for index, (label, value) in enumerate(zip(fields, values, strict=True))
            )
        )
        title = session.translator.text("status.custom_pane_title")
        controls = session.translator.text("status.custom_pane_controls")
    formatted_notices = format_notice_lines(
        notices,
        width=width,
        color=session.dashboard_theme != "no-color",
        ascii=session.options.host.ascii,
        translator=session.translator,
        color_scheme=session.dashboard_theme,
    )
    session.chooser_overlay = (
        modal.pane_index,
        "\n".join(compose_frame(body, title, controls, formatted_notices, height=height).rows),
    )


def finish_dataset_modal(session: TuiSession, choice: CustomChartPaneConfig | str | None) -> None:
    from ccusage_viz.tui.history import reconcile_topology_after_pane_change, record_mutation
    from ccusage_viz.tui.queries import start_new_pane
    from ccusage_viz.tui.structure import create_pane

    """Apply one completed modal choice through the normal history transaction."""
    assert session.dataset_modal is not None
    modal = session.dataset_modal
    if isinstance(choice, CustomChartPaneConfig):
        source = choice.chart.source
        conflict = _custom_source_conflict(
            session.panes,
            source,
            replacing_index=modal.pane_index if modal.action == "replace" else None,
        )
        if conflict is not None:
            modal.error = _custom_source_conflict_message(conflict, session.translator)
            return
    session.dataset_modal = None
    session.chooser_overlay = None
    if choice is None:
        return
    if modal.action == "replace":
        record_mutation(
            session,
            ("pane", modal.pane_index, "replace"),
            lambda choice=choice, index=modal.pane_index: _replace_pane(
                session.panes,
                index,
                create_pane(session, choice),
                start=partial(start_new_pane, session),
            ),
        )
        return
    insert_at = modal.pane_index if modal.action == "insert_before" else modal.pane_index + 1

    def insert(choice: CustomChartPaneConfig | str = choice, insert_at: int = insert_at) -> None:
        previous_count = len(session.panes)
        _insert_pane(
            session.panes,
            insert_at,
            create_pane(session, choice),
            start=partial(start_new_pane, session),
        )
        reconcile_topology_after_pane_change(session, previous_count)
        session.focused = insert_at

    record_mutation(session, ("pane", modal.pane_index, modal.action), insert)


def advance_dataset_modal(session: TuiSession, status: DatasetRegistrationStatus) -> bool:
    """Apply a refreshed source descriptor and report whether it advances the modal."""
    assert session.dataset_modal is not None
    modal = session.dataset_modal
    modal.draft.dataset_id = status.registration.dataset_id
    modal.metrics = ()
    modal.metric_id = None
    modal.metric_summary = "comparisons"
    modal.metric_periods = ()
    modal.metric_titles = None
    modal.chart_kinds = ()
    descriptor = status.registration.probe.descriptor
    if isinstance(descriptor, V2ProbeDescriptor):
        modal.metrics = descriptor.metrics
        selectable = tuple(
            row.metric_index
            for row in _dataset_metric_chooser_rows(descriptor, session.translator)
            if row.metric_index is not None
        )
        if not selectable:
            modal.stage, modal.offset = ("source", 0)
            modal.error = session.translator.text("status.dataset_unavailable")
            return False
        modal.index = next(
            (
                position
                for position in selectable
                if descriptor.metrics[position].id == descriptor.default_metric_id
            ),
            selectable[0],
        )
        modal.offset = 0
        modal.stage = "metric"
        return True
    modal.chart_kinds = tuple(descriptor.capabilities.charts)
    if not modal.chart_kinds:
        modal.stage, modal.offset = ("source", 0)
        modal.error = session.translator.text("status.dataset_unavailable")
        return False
    modal.stage, modal.index, modal.offset = ("installed", 0, 0)
    return True


def collect_dataset_modal(session: TuiSession) -> bool:
    """Consume a completed Dataset modal future without blocking the Dashboard."""
    assert session.dataset_modal is not None
    modal = session.dataset_modal
    if modal.future is None or not modal.future.done():
        return False
    if modal.stage == "source_loading":
        selected_index = modal.index
        selected_dataset_id = modal.pending_dataset_id
        try:
            refreshed = cast(DatasetRegistrationStatus, modal.future.result())
            refreshed_id = refreshed.registration.dataset_id
            if refreshed_id != selected_dataset_id:
                raise UsageError("error.dataset_corrupt", dataset_id=selected_dataset_id)
            modal.statuses = tuple(
                refreshed if item.registration.dataset_id == selected_dataset_id else item
                for item in modal.statuses
            )
            advanced = advance_dataset_modal(session, refreshed)
            if advanced:
                modal.error = None
        except (UsageError, QueryError) as exc:
            modal.stage, modal.index, modal.offset = ("source", selected_index, 0)
            modal.error = format_error(exc, session.translator)
        except Exception as exc:
            modal.stage, modal.index, modal.offset = ("source", selected_index, 0)
            modal.error = str(exc)
        modal.future = None
        modal.pending_dataset_id = None
        return True
    if modal.stage == "browse":
        try:
            modal.entries = cast(tuple[CatalogEntry, ...], modal.future.result())
            modal.error = None
        except UsageError as exc:
            modal.error = format_error(exc, session.translator)
        except Exception:
            modal.error = session.translator.text("status.dataset_catalog_unavailable")
        modal.future = None
        return True
    if modal.stage == "installing":
        try:
            modal.future.result()
            modal.statuses = _dashboard_registration_statuses(modal.service)
            modal.draft.dataset_id = modal.selected_dataset_id or ""
            modal.stage, modal.index, modal.offset = ("installed", 0, 0)
            modal.error = None
        except UsageError as exc:
            modal.stage = "browse_confirm"
            modal.error = format_error(exc, session.translator)
        except Exception:
            modal.stage = "browse_confirm"
            modal.error = session.translator.text("error.dataset_download_failed")
        modal.future = None
        return True
    if modal.stage == "browse_loading":
        try:
            modal.official_preview = cast(
                tuple[ReleaseArtifact, bytes, DatasetManifest], modal.future.result()
            )
            modal.stage = "browse_confirm"
            modal.error = None
        except UsageError as exc:
            modal.stage = "browse"
            modal.error = format_error(exc, session.translator)
        except Exception:
            modal.stage = "browse"
            modal.error = session.translator.text("error.dataset_download_failed")
        modal.future = None
        return True
    if modal.stage == "github":
        try:
            modal.artifact = cast(ReleaseArtifact, modal.future.result())
            modal.error = None
        except UsageError as exc:
            modal.error = format_error(exc, session.translator)
        except Exception:
            modal.error = session.translator.text("error.dataset_download_failed")
        modal.future = None
        return True
    if modal.stage == "github_installing":
        try:
            status = cast(DatasetStatus, modal.future.result())
            installed = status.installed
            if installed is None:
                raise UsageError("error.dataset_corrupt")
            modal.draft.dataset_id = installed.dataset_id
            modal.statuses = _dashboard_registration_statuses(modal.service)
            modal.stage, modal.index, modal.offset = ("installed", 0, 0)
            modal.error = None
        except UsageError as exc:
            modal.stage = "github"
            modal.error = format_error(exc, session.translator)
        except Exception:
            modal.stage = "github"
            modal.error = session.translator.text("error.dataset_download_failed")
        modal.future = None
        return True
    return False


def handle_dataset_modal(session: TuiSession, event: object) -> None:
    from ccusage_viz.tui.help import open_help

    """Apply one event to the active Dataset modal without blocking Dashboard work."""
    assert session.dataset_modal is not None
    modal = session.dataset_modal
    if not isinstance(event, (KeyEvent, PasteEvent)):
        return
    if isinstance(event, PasteEvent):
        if modal.stage == "local" and modal.draft.field in {1, 2}:
            if modal.draft.field == 1:
                modal.draft.dataset_id += event.value
            else:
                modal.draft.command += event.value
        return
    key = event.value
    if key == "\x03":
        raise KeyboardInterrupt
    if modal.stage == "pane":
        if key == "h":
            open_help(
                session,
                context="chooser",
                action=modal.action,
                selected=_PANE_COMMANDS[modal.index],
            )
            return
        if key == "\x1b":
            finish_dataset_modal(session, None)
        elif key in {"j", "\x1b[B"}:
            modal.index = (modal.index + 1) % len(_PANE_COMMANDS)
        elif key in {"k", "\x1b[A"}:
            modal.index = (modal.index - 1) % len(_PANE_COMMANDS)
        elif key in {"\r", "\n"}:
            choice = _PANE_COMMANDS[modal.index]
            if choice == "datasets":
                modal.stage, modal.index, modal.offset = ("source", 0, 0)
            else:
                finish_dataset_modal(session, choice)
        return
    if modal.stage == "source_loading":
        if key == "\x1b":
            if modal.future is not None:
                modal.future.cancel()
            modal.future = None
            modal.pending_dataset_id = None
            modal.stage, modal.offset = ("source", 0)
        return
    if modal.stage == "source":
        entries = modal.statuses
        if key == "h" and entries:
            open_help(
                session,
                context="dataset-chooser",
                dataset_id=entries[modal.index].registration.dataset_id,
            )
            return
        if key == "\x1b":
            modal.stage, modal.index, modal.offset = ("pane", 0, 0)
        elif key in {"j", "\x1b[B"} and entries:
            modal.index = (modal.index + 1) % len(entries)
        elif key in {"k", "\x1b[A"} and entries:
            modal.index = (modal.index - 1) % len(entries)
        elif key in {"\r", "\n"} and entries:
            status = entries[modal.index]
            if not getattr(status, "ready", True):
                modal.error = _dataset_registration_availability(status, session.translator)
                return
            modal.draft.dataset_id = status.registration.dataset_id
            modal.metrics = ()
            modal.metric_id = None
            modal.metric_summary = "comparisons"
            modal.metric_periods = ()
            modal.metric_titles = None
            modal.chart_kinds = ()
            modal.error = None
            modal.pending_dataset_id = modal.draft.dataset_id
            modal.stage = "source_loading"
            modal.future = session.executor.submit(modal.service.refresh, modal.pending_dataset_id)
            if modal.future.done():
                collect_dataset_modal(session)
        return
    if modal.stage == "metric":
        selected = next(
            status.registration.probe.descriptor
            for status in modal.statuses
            if status.registration.dataset_id == modal.draft.dataset_id
        )
        assert isinstance(selected, V2ProbeDescriptor)
        selectable = tuple(
            row.metric_index
            for row in _dataset_metric_chooser_rows(selected, session.translator)
            if row.metric_index is not None
        )
        if key == "\x1b":
            modal.stage, modal.index, modal.offset = ("source", 0, 0)
        elif key in {"j", "\x1b[B"}:
            modal.index = selectable[(selectable.index(modal.index) + 1) % len(selectable)]
        elif key in {"k", "\x1b[A"}:
            width, _height = _dataset_modal_size(session, modal.pane_index)
            metric_display_rows = _metric_chooser_display_rows(
                _dataset_metric_chooser_rows(selected, session.translator),
                width=width,
                ascii=session.options.host.ascii,
            )
            reveal_offset = _metric_chooser_previous_offset(
                metric_display_rows, selected_metric_index=modal.index, offset=modal.offset
            )
            if reveal_offset is not None:
                modal.offset = reveal_offset
            else:
                modal.index = selectable[(selectable.index(modal.index) - 1) % len(selectable)]
        elif key in {"\r", "\n"}:
            metric = modal.metrics[modal.index]
            modal.metric_id = metric.id
            modal.metric_summary = metric.summary
            modal.metric_titles = (metric.title.en, metric.title.zh_cn)
            modal.metric_periods = ()
            modal.chart_kinds = tuple(metric.capabilities.charts)
            if modal.chart_kinds:
                modal.stage, modal.index, modal.offset = ("installed", 0, 0)
        return
    if modal.stage == "github":
        if key == "\x08" and modal.future is None and modal.artifact is None:
            open_help(session, context="dataset-input")
        elif key == "\x1b":
            if modal.future is not None:
                return
            if modal.artifact is not None:
                modal.artifact = None
                modal.error = None
            else:
                modal.stage, modal.index, modal.offset = ("source", 0, 0)
        elif modal.future is not None:
            return
        elif modal.artifact is not None:
            if key in {"\r", "\n"}:
                modal.stage = "github_installing"
                modal.future = session.executor.submit(
                    modal.service.install_resolved_github_artifact,
                    modal.artifact,
                )
        elif key in {"\r", "\n"}:
            if modal.draft.command.strip():
                modal.future = session.executor.submit(
                    cast(Callable[[str], object], modal.service.resolve_github_repository),
                    modal.draft.command,
                )
                modal.error = None
        elif key == "\x7f":
            modal.draft.command = modal.draft.command[:-1]
            modal.error = None
        elif len(key) == 1 and key.isprintable():
            modal.draft.command += key
            modal.error = None
        return
    if modal.stage == "github_installing":
        return
    if modal.stage == "browse":
        if key == "h" and modal.future is None and modal.entries:
            open_help(session, context="catalog-browser")
        elif key == "\x1b":
            if modal.future is not None:
                modal.future.cancel()
            modal.future = None
            modal.stage, modal.index, modal.offset = ("source", 0, 0)
        elif modal.future is None and modal.entries:
            if key in {"j", "\x1b[B"}:
                modal.index = (modal.index + 1) % len(modal.entries)
            elif key in {"k", "\x1b[A"}:
                modal.index = (modal.index - 1) % len(modal.entries)
            elif key in {"\r", "\n"}:
                selected = modal.entries[modal.index]
                host_os, host_arch = modal.service.platform
                if not any(
                    artifact.os == host_os and artifact.arch == host_arch
                    for artifact in selected.artifacts
                ):
                    modal.error = session.translator.text(
                        "status.dataset_catalog_unavailable_platform",
                        platform=f"{host_os}/{host_arch}",
                    )
                else:
                    modal.selected_dataset_id = selected.id
                    modal.stage = "browse_loading"
                    modal.future = session.executor.submit(
                        cast(Callable[[str], object], modal.service.prepare_official_install),
                        selected.id,
                    )
        return
    if modal.stage == "browse_loading":
        return
    if modal.stage == "browse_confirm":
        if key == "\x1b":
            modal.stage = "browse"
            modal.error = None
        elif key in {"\r", "\n"}:
            assert modal.selected_dataset_id is not None
            assert modal.official_preview is not None
            modal.stage = "installing"
            modal.future = session.executor.submit(
                cast(Callable[[object, bytes], object], modal.service.install_artifact),
                modal.official_preview[0],
                modal.official_preview[1],
            )
        return
    if modal.stage == "installing":
        return
    if modal.stage == "installed":
        if key == "h":
            open_help(
                session,
                context="dataset-chooser",
                dataset_id=modal.draft.dataset_id,
                chart_kind=modal.chart_kinds[modal.index],
            )
            return
        if key == "\x1b":
            if modal.metrics:
                modal.index = next(
                    (
                        position
                        for position, metric in enumerate(modal.metrics)
                        if metric.id == modal.metric_id
                    ),
                    0,
                )
                modal.offset = 0
                modal.stage = "metric"
            else:
                modal.stage, modal.index, modal.offset = ("source", 0, 0)
        elif key in {"j", "\x1b[B"}:
            modal.index = (modal.index + 1) % len(modal.chart_kinds)
        elif key in {"k", "\x1b[A"}:
            modal.index = (modal.index - 1) % len(modal.chart_kinds)
        elif key in {"\r", "\n"}:
            try:
                source = modal.service.registered_command_source(modal.draft.dataset_id)
            except UsageError as exc:
                modal.error = format_error(exc, session.translator)
            else:
                kind = modal.chart_kinds[modal.index]
                metric_periods = modal.metric_periods
                if modal.metric_id is not None:
                    metric = next(
                        item
                        for item in modal.metrics
                        if isinstance(item, V2MetricDescriptor) and item.id == modal.metric_id
                    )
                    metric_periods = _custom_metric_periods(metric, kind)
                finish_dataset_modal(
                    session,
                    default_custom_pane(
                        kind,
                        source=source,
                        dashboard=session.options,
                        metric_id=modal.metric_id,
                        metric_summary=modal.metric_summary,
                        metric_periods=metric_periods,
                        metric_titles=modal.metric_titles,
                    ),
                )
        return
    if key == "\x08" and modal.draft.field in {1, 2}:
        open_help(session, context="dataset-input")
    elif key == "\x1b":
        modal.stage, modal.index, modal.offset = ("source", 0, 0)
    elif key in {"\t", "\x1b[B"}:
        modal.draft.field = (modal.draft.field + 1) % 3
    elif key == "\x1b[A":
        modal.draft.field = (modal.draft.field - 1) % 3
    elif modal.draft.field == 0 and key in {"j", "\x1b[C"}:
        kinds = _CUSTOM_PANE_KINDS
        modal.draft.kind = kinds[(kinds.index(modal.draft.kind) + 1) % len(kinds)]
    elif modal.draft.field == 0 and key in {"k", "\x1b[D"}:
        kinds = _CUSTOM_PANE_KINDS
        modal.draft.kind = kinds[(kinds.index(modal.draft.kind) - 1) % len(kinds)]
    elif key == "\x19":
        value = (modal.draft.kind, modal.draft.dataset_id, modal.draft.command)[modal.draft.field]
        modal.error = session.translator.text(
            "status.command_copied" if copy_command(value) else "status.command_copy_failed"
        )
    elif key == "\x15":
        if modal.draft.field == 0:
            modal.error = session.translator.text("status.custom_pane_kind_required")
        elif modal.draft.field == 1:
            modal.draft.dataset_id = ""
            modal.error = session.translator.text("status.custom_pane_field_cleared")
        else:
            modal.draft.command = ""
            modal.error = session.translator.text("status.custom_pane_field_cleared")
    elif key in {"\r", "\n"}:
        try:
            source = CustomCommandSource(
                modal.draft.dataset_id.strip(), tuple(shlex.split(modal.draft.command))
            )
            finish_dataset_modal(
                session,
                default_custom_pane(modal.draft.kind, source=source, dashboard=session.options),
            )
        except ValueError as exc:
            modal.error = str(exc)
    elif modal.draft.field in {1, 2}:
        value = modal.draft.dataset_id if modal.draft.field == 1 else modal.draft.command
        if key == "\x7f":
            value = value[:-1]
        elif len(key) == 1 and key.isprintable():
            value += key
        else:
            return
        if modal.draft.field == 1:
            modal.draft.dataset_id = value
        else:
            modal.draft.command = value
