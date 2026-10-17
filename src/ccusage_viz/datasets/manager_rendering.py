from __future__ import annotations

import shlex
from dataclasses import dataclass

from ccusage_viz.custom_models import V2ProbeDescriptor
from ccusage_viz.datasets.models import (
    DatasetManifest,
    DatasetRegistrationStatus,
    LocalDatasetSource,
)
from ccusage_viz.formatting import clip_width, pad_width, wrap_width
from ccusage_viz.i18n import Translator
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.terminal import Frame, compose_frame, emphasize


@dataclass(frozen=True, slots=True)
class ManagerView:
    frame: Frame
    selected_id: str | None


def _text(value, translator: Translator) -> str:
    return value.zh_cn if translator.language == "zh" else value.en


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


def _detail_rows(
    status: DatasetRegistrationStatus, translator: Translator, width: int
) -> list[str]:
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
            rows.extend((f"{item.name} · {state} · {_text(item.label, translator)}",))
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
    description = _descriptor_description(descriptor, translator) if descriptor is not None else ""

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
        rows.append(
            f"{pad_width(clip_width(left_row, left_width), left_width)} │ {clip_width(right_row, right_width)}"
        )
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
