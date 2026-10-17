import shlex

import ccusage_viz.tui.models as tui_models
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_copy import (
    format_command,
    format_dashboard_pane_command,
    format_full_command,
    format_full_dashboard_command,
)
from ccusage_viz.command_parsing.panes import parse_pane_fragment as parse_dashboard_pane
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.configuration import standalone_from_chart_pane
from ccusage_viz.formatting import display_width
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import (
    AnimationPaneConfig,
)
from ccusage_viz.terminal import Terminal
from ccusage_viz.tui.adjustments import (
    _adjustment_footer,
)
from ccusage_viz.tui.controls import _pane_content_actions
from ccusage_viz.tui.custom_rendering import _pane_copy_payload
from ccusage_viz.tui.header import _header_options
from ccusage_viz.tui.pane_lifecycle import _new_pane
from ccusage_viz.tui.rendering import (
    _pane_render,
)


def test_full_dashboard_command_copies_and_round_trips_custom_partition() -> None:
    parser = build_parser(load_translator("en"))
    dashboard = _to_options(
        parser.parse_args(
            [
                "dashboard",
                "--pane",
                "chart ranking --dataset router --command router --metric tokens --partition-by logical_model --group-by real_model --top 3",
            ]
        )
    )

    command = format_full_dashboard_command(dashboard)
    copied = _to_options(parser.parse_args(shlex.split(command)[1:]))

    fragment = shlex.split(command)[shlex.split(command).index("--pane") + 1]
    assert "--partition-by logical_model --group-by real_model" in fragment
    pane = copied.panes[0]
    assert isinstance(pane, tui_models.CustomChartPaneConfig)
    assert (pane.chart.partition_by, pane.chart.group_by) == ("logical_model", "real_model")


def test_dashboard_command_copy_preserves_custom_legend() -> None:
    parser = build_parser(load_translator("en"))
    dashboard = _to_options(
        parser.parse_args(
            [
                "dashboard",
                "--pane",
                "custom timeline --dataset reading --command 'reader ccuv' --legend inside",
            ]
        )
    )

    command = format_full_dashboard_command(dashboard)
    copied = _to_options(parser.parse_args(shlex.split(command)[1:]))

    assert "--legend inside" in command
    pane = copied.panes[0]
    assert isinstance(pane, tui_models.CustomChartPaneConfig)
    assert pane.chart.presentation.legend == "inside"


def test_dashboard_commands_preserve_local_date_context_and_timezone() -> None:
    parser = build_parser(load_translator("en"))
    dashboard = _to_options(parser.parse_args(["dashboard"]))

    full = format_full_dashboard_command(dashboard)
    reparsed = _to_options(parser.parse_args(shlex.split(full)[1:]))

    assert shlex.split(full)[:2] == ["ccuv", "dashboard"]
    assert f"--timezone {dashboard.host.timezone}" in full
    assert (
        _header_options(reparsed).chart.date_range.since
        <= _header_options(reparsed).chart.date_range.until
    )
    explicit = _to_options(parser.parse_args(["dashboard", "--timezone", "UTC"]))
    assert explicit.host.timezone == "UTC"


def test_full_dashboard_command_preserves_local_launcher_for_clock_overlay() -> None:
    parser = build_parser(load_translator("en"))
    dashboard = _to_options(parser.parse_args(["dashboard"]), launcher="ccuv-local")

    command = format_full_dashboard_command(dashboard)
    tokens = shlex.split(command)
    reparsed = _to_options(parser.parse_args(tokens[1:]), launcher=tokens[0])

    assert tokens[:2] == ["ccuv-local", "dashboard"]
    assert "--overlay-command" in tokens[tokens.index("--pane") + 1]
    assert reparsed.launcher == "ccuv-local"
    assert isinstance(reparsed.panes[0], AnimationPaneConfig)
    assert reparsed.panes[0].overlay.command == "ccuv-local text time-state --run"


def test_full_dashboard_command_preserves_animation_pane_style() -> None:
    parser = build_parser(load_translator("en"))
    dashboard = _to_options(
        parser.parse_args(["dashboard", "--pane", "timeline", "--pane", "animate rain"])
    )

    command = format_full_dashboard_command(dashboard)
    reparsed = _to_options(parser.parse_args(shlex.split(command)[1:]))

    assert "animate rain" in command
    assert reparsed.panes[1] == dashboard.panes[1]


def test_dashboard_layout_weights_round_trip_through_full_command() -> None:
    parser = build_parser(load_translator("en"))
    dashboard = _to_options(
        parser.parse_args(
            [
                "dashboard",
                "--pane",
                "timeline",
                "--pane",
                "ranking",
                "--grid",
                "1x2",
                "--column-weight",
                "2",
                "--column-weight",
                "1",
                "--row-weight",
                "3",
            ]
        )
    )

    full = format_full_dashboard_command(dashboard)
    reparsed = _to_options(parser.parse_args(shlex.split(full)[1:]))

    assert "--column-weight 16 --column-weight 8" in full
    assert "--row-weight 24" in full
    assert reparsed.host.grid == "1x2"
    assert reparsed.host.column_weights == (16, 8)
    assert reparsed.host.row_weights == (24,)


def test_full_dashboard_command_explicit_grid_overrides_source_named_layout() -> None:
    parser = build_parser(load_translator("en"))
    dashboard = _to_options(parser.parse_args(["dashboard", "spotlight-wide"]))

    full = format_full_dashboard_command(dashboard, grid="2x2")
    reparsed = _to_options(parser.parse_args(shlex.split(full)[1:]))

    assert "--grid 2x2" in full
    assert "--layout" not in full
    assert reparsed.host.grid == "2x2"
    assert reparsed.host.layout is None


def test_full_dashboard_command_serializes_runtime_layout_weight_overrides() -> None:
    parser = build_parser(load_translator("en"))
    dashboard = _to_options(parser.parse_args(["dashboard"]))

    full = format_full_dashboard_command(
        dashboard,
        column_weights=(2, 1),
        row_weights=(3, 1, 1),
    )
    reparsed = _to_options(parser.parse_args(shlex.split(full)[1:]))

    assert reparsed.host.column_weights == (16, 8)
    assert reparsed.host.row_weights == (15, 5, 5)


def test_full_dashboard_command_includes_private_and_runtime_configuration() -> None:
    parser = build_parser(load_translator("en"))
    dashboard = _to_options(
        parser.parse_args(
            [
                "dashboard",
                "--ccusage-bin",
                "/opt/ccusage",
                "--query-timeout",
                "42",
                "--pane",
                "timeline --project /private/project --density minimal",
            ]
        )
    )
    full = format_full_dashboard_command(
        dashboard,
        dashboard.panes,
        layout="auto",
        header_style="compact",
        header_summary="month",
        dashboard_style="split",
    )

    tokens = shlex.split(full)
    assert "/private/project" in full
    assert "--ccusage-bin /opt/ccusage" in full
    assert "--query-timeout 42" in full
    assert "--pane" in tokens
    assert "--interval" not in tokens
    reparsed = _to_options(parser.parse_args(tokens[1:]))
    assert reparsed.panes[0].chart.filters.projects == ("/private/project",)
    assert reparsed.panes[0].chart.presentation.density == "minimal"
    assert "--density minimal" in tokens[tokens.index("--pane") + 1]


def test_dashboard_pane_copy_materializes_canonical_standalone_interval() -> None:
    parser = build_parser(load_translator("en"))
    base = _to_options(parser.parse_args(["dashboard"]))
    timeline = parse_dashboard_pane("timeline --period 7d", host=base)
    stack = parse_dashboard_pane("stack", host=base)
    monitor = parse_dashboard_pane("monitor --by model", host=base)

    assert format_dashboard_pane_command(
        standalone_from_chart_pane(base, timeline), refresh_interval=30
    ) == (
        f"ccuv chart timeline --period 7d --timezone {base.host.timezone} "
        "--interval 30 --density compact"
    )
    assert format_dashboard_pane_command(
        standalone_from_chart_pane(base, stack), refresh_interval=30
    ) == (f"ccuv chart stack --timezone {base.host.timezone} --interval 30 --density compact")
    assert format_dashboard_pane_command(
        standalone_from_chart_pane(base, monitor), refresh_interval=30, sampling_interval=15
    ) == (f"ccuv chart monitor --by model --timezone {base.host.timezone} --density compact")


def test_dashboard_pane_command_views_wrap_without_affecting_copy_payload() -> None:
    parser = build_parser(load_translator("en"))
    dashboard = _to_options(
        parser.parse_args(
            [
                "dashboard",
                "--ccusage-bin",
                "/private/bin/ccusage",
                "--pane",
                "timeline --period 7d --by model --top 4 --agent claude --model sonnet --project project --density minimal",
            ]
        )
    )
    pane = _new_pane(standalone_from_chart_pane(dashboard, dashboard.panes[0]), "pane:command")
    terminal = Terminal(24, 16, False, True)
    active = pane.component.candidate

    pane.body_view = "command"
    concise = _pane_render(pane, load_translator("en"), terminal).chart
    assert "\n" in concise
    assert all(display_width(line) <= terminal.width for line in concise.splitlines())
    assert " ".join(concise.splitlines()) == format_command(active)

    pane.body_view = "full-command"
    full = _pane_render(pane, load_translator("en"), terminal).chart
    assert "\n" in full
    assert all(display_width(line) <= terminal.width for line in full.splitlines())
    assert "--ccusage-bin" in full
    assert format_full_command(active).count("\n") == 0
    assert _pane_copy_payload(pane, load_translator("en"), terminal) == format_full_command(active)


def test_dashboard_pane_copy_actions_follow_body_view() -> None:
    assert (
        "y copy"
        not in _adjustment_footer(
            "Current status: running", "timeline", "quick", "chart", load_translator("en"), 120
        )[3]
    )
    for view in ("command", "full-command", "data-table", "data-json"):
        assert ("y", "copy") in _pane_content_actions(view)
        assert (
            "y copy"
            in _adjustment_footer(
                "Current status: running", "timeline", "quick", view, load_translator("en"), 120
            )[3]
        )
