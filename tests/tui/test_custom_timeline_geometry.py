from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from ccusage_viz.bootstrap import build_query_runtime
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.configuration import default_custom_pane
from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_models import CustomComparison, CustomProtocolWarning, LocalizedText
from ccusage_viz.formatting import display_width
from ccusage_viz.i18n import load_translator
from ccusage_viz.lifecycle import FixedIntervalScheduler, LifecycleOperation
from ccusage_viz.options import CustomCommandSource
from ccusage_viz.terminal import Terminal, compose_frame
from ccusage_viz.terminal_ui import notice_lines
from ccusage_viz.tui.custom_rendering import _custom_standalone_render
from ccusage_viz.tui.models import CustomDashboardSummary, TuiCustomPane
from ccusage_viz.tui.pane_lifecycle import _new_pane
from ccusage_viz.tui.rendering import _local_pane_content, _pane_render
from tests.custom_component.helpers import response

from .custom_helpers import custom_summary_response


@pytest.mark.parametrize("density", ("compact", "full", "detailed"))
@pytest.mark.parametrize("language", ("en", "zh"))
@pytest.mark.parametrize("standalone", (False, True))
@pytest.mark.parametrize("height", (16, 22))
def test_custom_timeline_budgets_summary_and_wrapped_unicode_warnings(
    density, language, standalone, height
):
    translator = load_translator(language)
    dashboard = _to_options(build_parser(translator).parse_args(["dashboard", "--empty"]))
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
    assert isinstance(pane, TuiCustomPane)
    config = replace(
        pane.component.candidate,
        date_range=DateRange(date(2026, 9, 1), date(2026, 9, 2)),
        presentation=replace(pane.component.candidate.presentation, density=density),
    )
    pane.component.configure(config, data_affecting=False)
    warning = "Coverage warning 使用部分数据 " * 4
    source = response()
    assert pane.component.accept_response(
        replace(
            source,
            warnings=(
                CustomProtocolWarning("coverage", LocalizedText(warning, warning)),
                CustomProtocolWarning("second", LocalizedText("second notice", "第二条提示")),
            ),
        )
    )
    pane.summary = CustomDashboardSummary(
        config.source,
        FixedIntervalScheduler(60, now=0),
        LifecycleOperation("summary"),
        response=custom_summary_response(
            display="68 pages", year_over_year=CustomComparison("ready", Decimal("34"))
        ),
        accepted_period="month",
        accepted_as_of_date=date(2026, 9, 2),
    )
    terminal = Terminal(58, height, False, True)
    rendered = (
        _custom_standalone_render(
            pane.component, translator, terminal, pending=False, summary=pane.summary
        )
        if standalone
        else _pane_render(pane, translator, terminal)
    )
    assert rendered.notices == (warning, "second notice" if language == "en" else "第二条提示")
    expected_notices = notice_lines(
        rendered.notices, width=terminal.width, color=False, ascii=True, translator=translator
    )
    assert sum(row.startswith("! ") for row in expected_notices) == 2
    if standalone:
        content = "\n".join(
            compose_frame(
                rendered.chart, "status", (), expected_notices, height=terminal.height
            ).rows
        )
        assert len(rendered.chart.splitlines()) + len(expected_notices) + 1 == terminal.height
    else:
        content = _local_pane_content(
            rendered.chart, expected_notices, height=terminal.height, width=terminal.width
        )
        assert len(rendered.chart.splitlines()) + len(expected_notices) == terminal.height
    assert isinstance(content, str)
    assert len(content.splitlines()) == terminal.height
    # The existing short-standalone policy suppresses the summary when it
    # cannot fit alongside detailed audit/legend chrome. Dates still survive.
    if not (height == 16 and standalone and density == "detailed"):
        assert ("68 pages" if language == "en" else "68 页") in content
    assert "09-01" in content and "09-02" in content
    assert content.splitlines()[-len(expected_notices) :] == list(expected_notices)
    assert all(display_width(row) <= terminal.width for row in content.splitlines())
