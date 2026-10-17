from datetime import datetime

import ccusage_viz.tui.custom_rendering as tui_custom_rendering
import ccusage_viz.tui.models as tui_models
from ccusage_viz.bootstrap import build_query_runtime
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.configuration import default_custom_pane
from ccusage_viz.custom_models import CustomProtocolFailure, LocalizedText
from ccusage_viz.errors import QueryError
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import CustomCommandSource
from ccusage_viz.tui.pane_lifecycle import _new_pane


def test_custom_failure_log_detail_uses_only_validated_protocol_fields() -> None:
    failure = QueryError(
        "error.custom_command_protocol",
        custom_failure=CustomProtocolFailure(
            "source_unavailable",
            LocalizedText("Safe source category", "安全的数据源分类"),
            {"field": "range.period", "value": "1w"},
        ),
    )

    assert (
        tui_custom_rendering._custom_failure_log_detail(failure, load_translator("en"))
        == "source_unavailable: Safe source category (range.period=1w)"
    )
    assert (
        tui_custom_rendering._custom_failure_log_detail(failure, load_translator("zh"))
        == "source_unavailable: 安全的数据源分类 (range.period=1w)"
    )


def test_custom_failure_log_detail_hides_unstructured_exception_text() -> None:
    assert (
        tui_custom_rendering._custom_failure_log_detail(
            RuntimeError("private stderr and credential"), load_translator("en")
        )
        == "error"
    )


def test_custom_log_records_render_localized_statuses() -> None:
    dashboard = _to_options(
        build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
    )
    pane = _new_pane(
        dashboard,
        default_custom_pane(
            "timeline",
            source=CustomCommandSource("reading", ("reader", "ccuv")),
            dashboard=dashboard,
        ),
        "dashboard:pane:0",
        build_query_runtime(),
    )
    assert isinstance(pane, tui_models.TuiCustomPane)
    pane.logs.extend(
        (
            tui_models.CustomLogRecord(datetime(2026, 9, 30, 10, 20), "ok", "done"),
            tui_models.CustomLogRecord(datetime(2026, 9, 30, 10, 21), "error", "failed"),
        )
    )

    rows = tuple(
        f"{load_translator('zh').text(f'status.custom_log_{record.status}')} "
        f"{record.timestamp:%H:%M:%S}: {record.detail}"
        for record in pane.logs
    )

    assert rows == ("成功 10:20:00: done", "错误 10:21:00: failed")
