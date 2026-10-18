import math
from datetime import date
from pathlib import Path

import pytest

from ccusage_viz.animation import animation_style_choices
from ccusage_viz.cli import main
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.cli.routing import (
    _inject_default_command,
)
from ccusage_viz.command_parsing.common import _explicit_fields
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.configuration import standalone_from_chart_pane
from ccusage_viz.dashboard_preset_store import DashboardPresetStore, DashboardPresetStoreError
from ccusage_viz.errors import UsageError
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import (
    AnimationLaunch,
    AnimationPaneConfig,
    CustomChartConfig,
    CustomChartPaneConfig,
    CustomCommandSource,
    DashboardHostConfig,
    DashboardLaunch,
    EmptyPaneConfig,
    ProcessConfig,
    resolve_date_range,
)

from .helpers import namespace


def test_dataset_cli_parses_manager_and_local_list() -> None:
    parser = build_parser(load_translator("en"))

    manager = parser.parse_args(["dataset"])
    listing = parser.parse_args(["dataset", "list"])

    assert manager.command == "dataset"
    assert manager.dataset_command is None
    assert listing.dataset_command == "list"


def test_empty_dashboard_populates_fixed_and_named_layouts() -> None:
    parser = build_parser(load_translator("en"))

    fixed = _to_options(parser.parse_args(["dashboard", "--empty", "--grid", "2x2"]))
    named = _to_options(parser.parse_args(["dashboard", "--empty", "--layout", "spotlight-wide"]))

    assert len(fixed.panes) == 4
    assert all(isinstance(pane, EmptyPaneConfig) for pane in fixed.panes)
    assert len(named.panes) == 2
    assert all(isinstance(pane, EmptyPaneConfig) for pane in named.panes)


def test_bare_custom_dataset_routes_through_installed_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = build_parser(load_translator("en"))
    installed = CustomCommandSource("weread", ("dataset-weread", "ccuv"), source_kind="installed")
    monkeypatch.setattr(
        "ccusage_viz.datasets.service.DatasetService.command_source",
        lambda _service, dataset_id: installed if dataset_id == "weread" else None,
    )

    launch = _to_options(parser.parse_args(["chart", "timeline", "--dataset", "weread"]))

    assert isinstance(launch.chart, CustomChartConfig)
    assert launch.chart.source == installed


@pytest.mark.parametrize("kind", ("timeline", "stack", "ranking", "calendar"))
def test_installed_dataset_defaults_use_host_timezone_today(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    parser = build_parser(load_translator("en"))
    installed = CustomCommandSource("weread", ("dataset-weread", "ccuv"), source_kind="installed")
    monkeypatch.setattr(
        "ccusage_viz.datasets.service.DatasetService.command_source",
        lambda _service, dataset_id: installed,
    )

    launch = _to_options(
        parser.parse_args(["chart", kind, "--dataset", "weread", "--timezone", "Asia/Shanghai"])
    )

    assert isinstance(launch.chart, CustomChartConfig)
    assert launch.chart.date_range.until == date.today()
    assert launch.host.timezone == "Asia/Shanghai"


def test_installed_dataset_accepts_explicit_current_day_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = build_parser(load_translator("en"))
    installed = CustomCommandSource("weread", ("dataset-weread", "ccuv"), source_kind="installed")
    monkeypatch.setattr(
        "ccusage_viz.datasets.service.DatasetService.command_source",
        lambda _service, dataset_id: installed,
    )

    launch = _to_options(
        parser.parse_args(
            [
                "chart",
                "timeline",
                "--dataset",
                "weread",
                "--since",
                "2026-09-18",
                "--until",
                "2026-09-20",
            ]
        )
    )

    assert isinstance(launch.chart, CustomChartConfig)
    assert launch.chart.date_range.until == date(2026, 9, 20)


def test_standalone_conversion_preserves_custom_source_and_chart() -> None:
    source = CustomCommandSource("weread", ("reader", "ccuv"))
    chart = CustomChartConfig(
        "timeline",
        source,
        resolve_date_range("timeline", period="14d", since=None, until=None),
        group_by="book",
    )
    dashboard = DashboardLaunch(ProcessConfig(), DashboardHostConfig(refresh_interval=30), ())

    standalone = standalone_from_chart_pane(dashboard, CustomChartPaneConfig(chart))

    assert standalone.chart == chart
    assert standalone.chart.source == source
    assert standalone.host.interval == 30


def test_animate_gallery_preserves_positional_initial_style() -> None:
    parser = build_parser(load_translator("en"))

    default = _to_options(parser.parse_args(["animate", "--gallery"]))
    clock = _to_options(parser.parse_args(["animate", "digital-clock", "--gallery"]))

    assert isinstance(default, AnimationLaunch)
    assert default.gallery
    assert default.animation.style == animation_style_choices("standalone")[0]
    assert clock.gallery
    assert clock.animation.style == "digital-clock"


@pytest.mark.parametrize("command", ("timeline", "monitor"))
@pytest.mark.parametrize("mode", ("below-title", "inside", "hidden"))
def test_timeline_and_monitor_accept_legend_modes(command: str, mode: str) -> None:
    parser = build_parser(load_translator("en"))
    assert parser.parse_args(["chart", command, "--legend", mode]).legend == mode


def test_monitor_accepts_values_legend_mode() -> None:
    parser = build_parser(load_translator("en"))
    assert parser.parse_args(["chart", "monitor", "--legend", "values"]).legend == "values"


@pytest.mark.parametrize("mode", ("below-title", "hidden"))
def test_stack_accepts_supported_legend_modes(mode: str) -> None:
    parser = build_parser(load_translator("en"))
    assert parser.parse_args(["chart", "stack", "--legend", mode]).legend == mode


@pytest.mark.parametrize("command", ("timeline", "stack", "ranking", "monitor"))
def test_project_aggregation_is_not_a_public_chart_option(command: str) -> None:
    parser = build_parser(load_translator("en"))
    with pytest.raises(UsageError):
        parser.parse_args(["chart", command, "--project-aggregation", "exact"])


def test_animate_defaults_to_first_discovered_style_and_rejects_chart_options() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["animate"]))

    assert isinstance(options, AnimationLaunch)
    assert options.animation.style == animation_style_choices("standalone")[0]
    with pytest.raises(UsageError) as caught:
        parser.parse_args(["animate", "--density", "compact"])
    assert caught.value.key == "error.arguments"


def test_dashboard_accepts_explicit_animation_pane_and_rejects_bare_animate() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(
        parser.parse_args(["dashboard", "--pane", "timeline", "--pane", "animate rain"])
    )

    assert isinstance(options.panes[1], AnimationPaneConfig)
    assert options.panes[1].animation.style == "rain"
    assert (
        _to_options(parser.parse_args(["dashboard", "--pane", "animate snow"]))
        .panes[0]
        .animation.style
        == "snow"
    )
    for fragment in ("animate", "animate rain extra", "animate not-an-animation"):
        with pytest.raises(UsageError) as caught:
            _to_options(parser.parse_args(["dashboard", "--pane", fragment]))
        assert caught.value.key == "error.tui_panel"


def test_dashboard_has_no_global_density_option() -> None:
    parser = build_parser(load_translator("en"))
    with pytest.raises(UsageError) as caught:
        parser.parse_args(["dashboard", "--density", "compact"])
    assert caught.value.key == "error.arguments"


@pytest.mark.parametrize("style", ("step", "absolute"))
def test_style_is_rejected_for_the_wrong_command(style: str) -> None:
    parser = build_parser(load_translator("en"))
    with pytest.raises(UsageError) as caught:
        parser.parse_args(["chart", "calendar", "--style", style])
    assert caught.value.key == "error.arguments"


def test_historical_charts_reject_monitor_distribution_style() -> None:
    parser = build_parser(load_translator("en"))
    for command in ("timeline", "calendar", "stack", "ranking"):
        with pytest.raises(UsageError) as caught:
            parser.parse_args(["chart", command, "--style", "cumulative-bars"])
        assert caught.value.key == "error.arguments"


def test_timeline_rejects_removed_point_style() -> None:
    parser = build_parser(load_translator("en"))
    with pytest.raises(UsageError) as caught:
        parser.parse_args(["chart", "timeline", "--style", "point"])
    assert caught.value.key == "error.arguments"


def test_chart_lifecycle_defaults_and_rejects_removed_watch_options() -> None:
    parser = build_parser(load_translator("en"))
    default = _to_options(parser.parse_args(["chart", "timeline"]))
    assert default.host.interval == 10
    assert default.host.watch

    for arguments in (
        ["chart", "timeline", "--watch"],
        ["chart", "timeline", "--no-watch"],
        ["chart", "monitor", "--no-watch"],
        ["dashboard", "--watch"],
        ["dashboard", "--no-watch"],
        ["dashboard", "--interval", "20"],
    ):
        with pytest.raises(UsageError, match="error.arguments"):
            parser.parse_args(arguments)


@pytest.mark.parametrize(
    ("field", "value", "key"),
    [
        ("interval", math.nan, "error.interval_min"),
        ("interval", math.inf, "error.interval_min"),
        ("query_timeout", math.nan, "error.arguments"),
        ("query_timeout", math.inf, "error.arguments"),
    ],
)
def test_numeric_intervals_must_be_finite(field: str, value: float, key: str) -> None:
    with pytest.raises(UsageError) as caught:
        _to_options(namespace(**{field: value}))
    assert caught.value.key == key


@pytest.mark.parametrize(
    ("command", "by", "top", "key"),
    [
        ("timeline", None, 2, "error.top_requires_by"),
        ("monitor", None, 2, "error.top_requires_by"),
    ],
)
def test_top_requires_a_category_dimension(
    command: str, by: str | None, top: int, key: str
) -> None:
    with pytest.raises(UsageError) as caught:
        _to_options(namespace(command=command, by=by, top=top))
    assert caught.value.key == key


@pytest.mark.parametrize("dimension", ("agent", "model", "project"))
def test_grouped_timeline_defaults_to_top_three(dimension: str) -> None:
    options = _to_options(namespace(command="timeline", by=dimension, top=None))

    assert options.chart.top == 3
    assert options.chart.other == "show"


@pytest.mark.parametrize("dimension", ("agent", "model", "project"))
def test_grouped_monitor_defaults_to_top_three(dimension: str) -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["chart", "monitor", "--by", dimension]))

    assert options.chart.top == 3


def test_ranking_has_a_default_category_dimension_for_top() -> None:
    options = _to_options(namespace(command="ranking", by="project", top=5))
    assert options.chart.by == "project"
    assert options.chart.top == 5


@pytest.mark.parametrize(
    ("window", "key"),
    [("4m", "error.window_range"), ("25h", "error.window_range"), ("hour", "error.window_invalid")],
)
def test_monitor_window_is_strictly_validated(window: str, key: str) -> None:
    with pytest.raises(UsageError) as caught:
        _to_options(namespace(command="monitor", by=None, window=window))
    assert caught.value.key == key


@pytest.mark.parametrize("dimension", ("agent", "model", "project"))
def test_monitor_accepts_grouping_and_top(dimension: str) -> None:
    options = _to_options(
        namespace(command="monitor", demo=None, by=dimension, top=2, style="line")
    )
    assert options.chart.by == dimension
    assert options.chart.top == 2
    assert options.chart.window_seconds == 3600
    assert options.host.interval == 15.0


@pytest.mark.parametrize("dimension", ("agent", "model", "project"))
def test_monitor_grouping_rejects_bars(dimension: str) -> None:
    with pytest.raises(UsageError) as caught:
        _to_options(namespace(command="monitor", by=dimension, style="bars"))
    assert caught.value.key == "error.style_incompatible"


def test_demo_monitor_defaults_to_one_second_interval() -> None:
    options = _to_options(namespace(command="monitor", demo="small", by=None, style="bars"))
    assert options.host.interval == 1.0
    assert options.host.demo_seed is not None


@pytest.mark.parametrize("kind", ("timeline", "calendar", "stack", "ranking", "monitor"))
@pytest.mark.parametrize("prefix", ([], ["--lang", "zh"]))
def test_removed_root_chart_commands_are_rejected(kind: str, prefix: list[str]) -> None:
    args = [*prefix, kind]

    assert _inject_default_command(args) == args
    assert main(args) == 2


def test_ranking_defaults_to_dot_for_builtin_and_custom_commands() -> None:
    parser = build_parser(load_translator("en"))

    builtin = _to_options(parser.parse_args(["chart", "ranking"]))
    custom = _to_options(
        parser.parse_args(["chart", "ranking", "--dataset", "reading", "--command", "reader ccuv"])
    )

    assert builtin.chart.presentation.style == "dot"
    assert custom.chart.presentation.style == "dot"


def test_command_requires_a_dataset_source() -> None:
    parser = build_parser(load_translator("en"))

    with pytest.raises(UsageError) as caught:
        _to_options(parser.parse_args(["chart", "timeline", "--command", "reader ccuv"]))

    assert caught.value.key == "error.arguments"


@pytest.mark.parametrize(
    ("arguments", "error_key"),
    (
        (["chart", "ranking", "--partition-by", "logical_model"], "error.arguments"),
        (
            ["dashboard", "--pane", "ranking --partition-by logical_model"],
            "error.tui_panel",
        ),
    ),
)
def test_builtin_charts_reject_partition_by_without_dataset(
    arguments: list[str], error_key: str
) -> None:
    parser = build_parser(load_translator("en"))

    with pytest.raises(UsageError) as caught:
        _to_options(parser.parse_args(arguments), explicit=_explicit_fields(arguments))

    assert caught.value.key == error_key


def test_custom_ranking_rejects_an_explicit_top_without_grouping() -> None:
    parser = build_parser(load_translator("en"))
    namespace = parser.parse_args(
        ["chart", "ranking", "--dataset", "reading", "--command", "reader ccuv", "--top", "10"]
    )

    with pytest.raises(UsageError) as caught:
        _to_options(namespace, explicit=frozenset({"top"}))

    assert caught.value.key == "error.top_requires_by"


def test_large_top_values_are_accepted() -> None:
    parser = build_parser(load_translator("en"))
    assert _to_options(parser.parse_args(["chart", "ranking", "--top", "999"])).chart.top == 999


@pytest.mark.parametrize("timeout", ("0", "nan", "inf"))
def test_dashboard_rejects_non_positive_or_non_finite_timeout(timeout: str) -> None:
    parser = build_parser(load_translator("en"))
    with pytest.raises(UsageError) as caught:
        _to_options(parser.parse_args(["dashboard", "--query-timeout", timeout]))
    assert caught.value.key == "error.arguments"


def test_dashboard_rejects_named_grid_for_arbitrary_panes() -> None:
    parser = build_parser(load_translator("en"))

    with pytest.raises(UsageError) as caught:
        _to_options(
            parser.parse_args(
                [
                    "dashboard",
                    "--pane",
                    "monitor --by model",
                    "--pane",
                    "calendar",
                    "--grid",
                    "not-a-grid",
                ]
            )
        )

    assert caught.value.key == "error.tui_grid"


def test_dashboard_accepts_spotlight_wide2_as_a_layout_only() -> None:
    parser = build_parser(load_translator("en"))
    arguments = [
        "dashboard",
        "--pane",
        "timeline",
        "--pane",
        "ranking",
        "--pane",
        "monitor --style list",
        "--layout",
        "spotlight-wide2",
        "--column-weight",
        "2",
        "--column-weight",
        "1",
        "--row-weight",
        "1",
        "--row-weight",
        "1",
        "--row-weight",
        "1",
    ]

    options = _to_options(parser.parse_args(arguments))

    assert options.host.layout == "spotlight-wide2"
    assert options.host.column_weights == (16, 8)
    assert options.host.row_weights == (8, 8, 8)
    for layout in (
        "auto",
        "spotlight-wide",
        "spotlight-wide2",
    ):
        with pytest.raises(UsageError) as caught:
            _to_options(parser.parse_args(["dashboard", "--pane", "timeline", "--grid", layout]))
        assert caught.value.key == "error.tui_grid"


def test_dashboard_accepts_layout_weights_and_tracks_explicit_aliases() -> None:
    parser = build_parser(load_translator("en"))
    arguments = [
        "dashboard",
        "--pane",
        "timeline",
        "--pane",
        "stack",
        "--grid",
        "1x2",
        "--column-weight",
        "2",
        "--column-weight",
        "1",
        "--row-weight=3",
    ]

    options = _to_options(parser.parse_args(arguments), explicit=_explicit_fields(arguments))

    assert options.host.column_weights == (16, 8)
    assert options.host.row_weights == (24,)
    assert options.was_explicit("column_weights")
    assert options.was_explicit("row_weights")


def test_dashboard_narrow_clock_reuses_narrow_panes_with_short_clock_row() -> None:
    parser = build_parser(load_translator("en"))

    narrow = _to_options(parser.parse_args(["dashboard", "narrow"]))
    narrow_clock = _to_options(parser.parse_args(["dashboard", "narrow-clock"]))

    assert isinstance(narrow_clock.panes[0], AnimationPaneConfig)
    assert narrow_clock.panes[0].animation.style == "digital-clock"
    assert narrow_clock.panes[0].overlay.position == "bottom-right"
    assert tuple(pane.chart for pane in narrow_clock.panes[1:]) == tuple(
        pane.chart for pane in narrow.panes
    )
    assert narrow_clock.panes[-1].attachment_style == "mole-cat"
    assert narrow.panes[-1].attachment_style is None
    assert narrow_clock.host.grid == "4x1"
    assert narrow_clock.host.row_weights == (6, 14, 14, 12)
    assert narrow_clock.host.style == "framed"


def test_dashboard_wide_clock_reuses_wide_panes_below_compact_digital_clock_row() -> None:
    parser = build_parser(load_translator("en"))

    wide = _to_options(parser.parse_args(["dashboard", "wide"]))
    wide_clock = _to_options(parser.parse_args(["dashboard", "wide-clock"]))

    assert isinstance(wide_clock.panes[0], AnimationPaneConfig)
    assert wide_clock.panes[0].animation.style == "digital-clock"
    assert wide_clock.panes[0].overlay.position == "bottom-right"
    assert tuple(pane.chart for pane in wide_clock.panes[1:]) == tuple(
        pane.chart for pane in wide.panes
    )
    assert wide_clock.panes[-1].attachment_style == "mole-cat"
    assert wide.panes[-1].attachment_style is None
    assert wide_clock.host.grid == "2x2"
    assert wide_clock.host.layout == "spotlight-wide"
    assert wide_clock.host.row_weights == (5, 15, 14)
    assert wide_clock.host.style == "framed"


def test_dashboard_single_keeps_only_the_wide_clock_analog_pane() -> None:
    parser = build_parser(load_translator("en"))

    single = _to_options(parser.parse_args(["dashboard", "single"]))
    wide_clock = _to_options(parser.parse_args(["dashboard", "wide-clock"]))

    assert isinstance(single.panes[0], AnimationPaneConfig)
    assert single.panes[0].animation.style == "analog-clock"
    assert single.panes[0].overlay.text is None
    assert single.panes[0].overlay.command is None
    assert wide_clock.panes[0].overlay.command is not None
    assert single.host.grid == "1x1"
    assert single.host.layout is None
    assert single.host.row_weights is None
    assert single.host.style == "minimal"
    assert single.host.header_summary == "none"


def test_dashboard_unavailable_store_preserves_existing_error_for_builtin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "ccusage_viz.cli.configuration.dashboard_preset_state_root", lambda: tmp_path
    )

    def fail_list(_store: DashboardPresetStore) -> tuple[object, ...]:
        raise DashboardPresetStoreError("unavailable")

    monkeypatch.setattr(DashboardPresetStore, "list", fail_list)
    parser = build_parser(load_translator("en"))

    with pytest.raises(UsageError) as caught:
        _to_options(parser.parse_args(["dashboard", "wide"]))

    assert caught.value.key == "error.arguments"
    assert caught.value.values["detail"] == "user dashboard preset storage is unavailable"


def test_dashboard_structural_options_require_content() -> None:
    parser = build_parser(load_translator("en"))

    with pytest.raises(UsageError, match="error.arguments"):
        _to_options(
            parser.parse_args(["dashboard", "--grid", "2x2"]),
            explicit=frozenset({"grid"}),
        )


def test_dashboard_owns_distinct_pane_cadences() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(
        parser.parse_args(
            [
                "dashboard",
                "--refresh-interval",
                "30",
                "--sampling-interval",
                "5",
                "--pane",
                "timeline --period 7d",
                "--pane",
                "monitor",
            ]
        )
    )
    assert options.host.refresh_interval == 30
    assert options.host.sampling_interval == 5
    assert options.panes[0].chart.kind == "timeline"
    assert options.panes[1].chart.kind == "monitor"


@pytest.mark.parametrize("theme_option", ("--theme", "--the"))
def test_dashboard_ascii_rejects_explicit_or_abbreviated_pane_theme(
    theme_option: str,
) -> None:
    parser = build_parser(load_translator("en"))
    with pytest.raises(UsageError):
        _to_options(
            parser.parse_args(["dashboard", "--ascii", "--pane", f"timeline {theme_option} nord"])
        )


@pytest.mark.parametrize(
    "arguments",
    [
        ["dashboard", "--panel", "timeline"],
        ["dashboard", "--pan", "timeline"],
        ["dashboard", "--interval", "10"],
        ["dashboard", "--watch"],
        ["dashboard", "--no-watch"],
    ],
)
def test_dashboard_rejects_removed_or_ambiguous_options(arguments: list[str]) -> None:
    parser = build_parser(load_translator("en"))
    with pytest.raises(UsageError):
        parser.parse_args(arguments)


@pytest.mark.parametrize(
    "flag", ["--pick", "--pick-theme", "--color-scheme", "--preview-schemes", "--no-color"]
)
def test_obsolete_appearance_flags_are_rejected(flag: str) -> None:
    parser = build_parser(load_translator("en"))
    args = (
        ["chart", "timeline", flag, "nord"]
        if flag == "--color-scheme"
        else ["chart", "timeline", flag]
    )
    with pytest.raises(UsageError) as caught:
        parser.parse_args(args)
    assert caught.value.key == "error.arguments"
