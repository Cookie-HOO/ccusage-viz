import math
from argparse import Namespace
from datetime import date
from pathlib import Path

import pytest

from ccusage_viz import __version__
from ccusage_viz.animation import animation_style_choices
from ccusage_viz.cli import (
    ShortCircuitKind,
    _explicit_fields,
    _inject_default_command,
    _rejected_subcommand,
    _to_options,
    _top_level_typo,
    build_parser,
    main,
    probe_short_circuit,
)
from ccusage_viz.configuration import standalone_from_chart_pane
from ccusage_viz.dashboard import DASHBOARD_PRESETS
from ccusage_viz.dashboard_preset_store import DashboardPresetStore, DashboardPresetStoreError
from ccusage_viz.dashboard_presets import preset_from_launch
from ccusage_viz.diagnostics import format_error
from ccusage_viz.errors import UsageError
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import (
    DEFAULT_STYLES,
    AnimationLaunch,
    AnimationPaneConfig,
    ChartPaneConfig,
    CustomChartConfig,
    CustomChartPaneConfig,
    CustomCommandSource,
    DashboardHostConfig,
    DashboardLaunch,
    EmptyPaneConfig,
    ProcessConfig,
    StandaloneLaunch,
    resolve_date_range,
)
from ccusage_viz.render.palette import COLOR_SCHEMES


@pytest.mark.parametrize(
    ("language", "command", "description"),
    [
        ("en", "timeline", "Render daily token usage as a line chart"),
        ("zh", "calendar", "将每日 Token 用量绘制为日历热力图"),
    ],
)
def test_subcommand_help_is_localized(
    language: str, command: str, description: str, capsys: pytest.CaptureFixture[str]
) -> None:
    parser = build_parser(load_translator(language))
    with pytest.raises(SystemExit) as caught:
        parser.parse_args(["chart", command, "--help"])
    assert caught.value.code == 0
    assert description in capsys.readouterr().out


def test_text_and_animate_help_describe_public_interfaces(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = build_parser(load_translator("en"))

    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])
    root_help = capsys.readouterr().out
    assert "text       Generate provider-free dynamic text presets" in root_help
    assert "==SUPPRESS==" not in root_help

    with pytest.raises(SystemExit):
        parser.parse_args(["text", "--help"])
    text_help = capsys.readouterr().out
    assert "Localized status for the current local time band" in text_help
    assert "Print the current text (default)" in text_help
    assert "Describe the preset and its output" in text_help

    with pytest.raises(SystemExit):
        parser.parse_args(["animate", "--help"])
    animate_help = capsys.readouterr().out
    for option in (
        "--overlay-text",
        "--overlay-command",
        "--overlay-position",
        "--overlay-color",
        "--overlay-interval",
        "--overlay-max-width",
        "--overlay-offset-x",
        "--overlay-offset-y",
    ):
        assert option in animate_help
    assert "--overlay-time-band" not in animate_help
    assert "Seconds between command-overlay refreshes" in animate_help


def test_invalid_chart_kind_lists_only_chart_kinds_and_suggests_match() -> None:
    tr = load_translator("en")
    parser = build_parser(tr)

    with pytest.raises(UsageError) as caught:
        parser.parse_args(["chart", "timline"])

    assert caught.value.key == "error.invalid_subcommand_suggestion"
    text = format_error(caught.value, tr)
    assert "argument KIND: invalid choice: 'timline'" in text
    assert "Supported commands: timeline, calendar, stack, ranking, monitor" in text
    assert "Did you mean 'timeline'?" in text
    assert "dashboard" not in text


def test_rejected_subcommand_accepts_repr_quoted_choice_rendering() -> None:
    assert (
        _rejected_subcommand(
            "argument KIND: invalid choice: 'timline' (choose from 'timeline', 'calendar')",
            "KIND",
            ("timeline", "calendar"),
        )
        == "timline"
    )


def test_invalid_dataset_operation_lists_only_dataset_operations() -> None:
    tr = load_translator("en")
    parser = build_parser(tr)

    with pytest.raises(UsageError) as caught:
        parser.parse_args(["dataset", "unknown-operation"])

    text = format_error(caught.value, tr)
    assert caught.value.key == "error.invalid_subcommand"
    assert "Supported commands: list, add-local" in text
    assert "Did you mean" not in text
    assert "timeline" not in text


def test_invalid_chart_kind_guidance_is_localized_in_chinese() -> None:
    tr = load_translator("zh")
    parser = build_parser(tr)

    with pytest.raises(UsageError) as caught:
        parser.parse_args(["chart", "timline"])

    text = format_error(caught.value, tr)
    assert "支持的命令：timeline, calendar, stack, ranking, monitor" in text
    assert "你是不是想输入 'timeline'？" in text


def test_invalid_option_value_does_not_gain_subcommand_guidance() -> None:
    tr = load_translator("en")
    parser = build_parser(tr)

    with pytest.raises(UsageError) as caught:
        parser.parse_args(["chart", "timeline", "--density", "standard"])

    assert caught.value.key == "error.arguments"
    assert "Supported commands" not in format_error(caught.value, tr)


def test_invalid_text_preset_lists_presets_and_suggests_match() -> None:
    tr = load_translator("en")
    with pytest.raises(UsageError) as caught:
        build_parser(tr).parse_args(["text", "time-stte"])
    assert caught.value.key == "error.invalid_preset_suggestion"
    text = format_error(caught.value, tr)
    assert "argument preset: invalid choice: 'time-stte'" in text
    assert "Supported presets: time-state" in text
    assert "Did you mean 'time-state'?" in text


def test_invalid_text_preset_guidance_is_localized_in_chinese() -> None:
    tr = load_translator("zh")
    with pytest.raises(UsageError) as caught:
        build_parser(tr).parse_args(["text", "time-stte"])
    text = format_error(caught.value, tr)
    assert "支持的预设：time-state" in text
    assert "你是不是想输入 'time-state'？" in text


def test_invalid_text_option_value_has_no_preset_guidance() -> None:
    tr = load_translator("en")
    with pytest.raises(UsageError) as caught:
        build_parser(tr).parse_args(["text", "time-state", "--lang", "bad"])
    assert caught.value.key == "error.arguments"
    assert "Supported presets" not in format_error(caught.value, tr)


def test_dataset_cli_parses_manager_and_local_list() -> None:
    parser = build_parser(load_translator("en"))

    manager = parser.parse_args(["dataset"])
    listing = parser.parse_args(["dataset", "list"])

    assert manager.command == "dataset"
    assert manager.dataset_command is None
    assert listing.dataset_command == "list"


def test_dataset_list_reads_registered_records_without_running_probes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class Service:
        def registrations(self) -> tuple[object, ...]:
            return ()

        def __init__(self) -> None:
            self.probe_calls = 0

    monkeypatch.setattr("ccusage_viz.datasets.service.DatasetService", Service)

    assert main(["dataset", "--lang", "en", "list"]) == 0
    assert capsys.readouterr().out == "No registered datasets\n"


def test_text_time_state_writes_a_localized_dynamic_status(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["text", "time-state", "--lang", "zh"]) == 0
    assert capsys.readouterr().out.startswith(("🛌", "🌅", "💼", "🍜", "🌆"))


def test_text_time_state_detects_language_when_omitted(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("ccusage_viz.cli.detect_language", lambda: "zh")

    assert main(["text", "time-state"]) == 0
    assert capsys.readouterr().out.startswith(("🛌", "🌅", "💼", "🍜", "🌆"))


def test_text_time_state_describe_explains_implementation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["text", "time-state", "--describe", "--lang", "en"]) == 0
    assert capsys.readouterr().out.strip() == (
        "Outputs one emoji status line from the local time at runtime.\n\n"
        "Time states:\n"
        "  00:00–06:00  🛌 Good night zzz\n"
        "  06:00–09:00  🌅 Good morning\n"
        "  09:00–12:00  💼 Working…\n"
        "  12:00–14:00  🍜 On lunch break…\n"
        "  14:00–18:00  💼 Working…\n"
        "  18:00–24:00  🌆 Good evening\n\n"
        "Without --lang, Simplified Chinese environments are detected automatically and all "
        "other environments use English. ccuv text time-state and ccuv text time-state --run "
        "both print the current status."
    )


def test_text_run_is_equivalent_to_default(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["text", "time-state", "--lang", "en"]) == 0
    default = capsys.readouterr().out

    assert main(["text", "time-state", "--run", "--lang", "en"]) == 0
    assert capsys.readouterr().out == default


def test_empty_dashboard_populates_fixed_and_named_layouts() -> None:
    parser = build_parser(load_translator("en"))

    fixed = _to_options(parser.parse_args(["dashboard", "--empty", "--grid", "2x2"]))
    named = _to_options(parser.parse_args(["dashboard", "--empty", "--layout", "spotlight-wide"]))

    assert len(fixed.panes) == 4
    assert all(isinstance(pane, EmptyPaneConfig) for pane in fixed.panes)
    assert len(named.panes) == 2
    assert all(isinstance(pane, EmptyPaneConfig) for pane in named.panes)


def test_custom_pane_fragment_preserves_normalized_filters_and_compact_density() -> None:
    parser = build_parser(load_translator("en"))

    dashboard = _to_options(
        parser.parse_args(
            [
                "dashboard",
                "--pane",
                'custom timeline --dataset reading --command "reader export" '
                "--filter category=fiction --filter category=literature",
            ]
        )
    )

    pane = dashboard.panes[0]
    assert isinstance(pane, CustomChartPaneConfig)
    assert pane.chart.filters == (("category", ("fiction", "literature")),)
    assert pane.chart.presentation.density == "compact"


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


def test_text_cannot_be_parsed_as_a_dashboard_pane() -> None:
    parser = build_parser(load_translator("en"))

    with pytest.raises(UsageError):
        _to_options(parser.parse_args(["dashboard", "--pane", "text time-state"]))


def test_animate_gallery_preserves_positional_initial_style() -> None:
    parser = build_parser(load_translator("en"))

    default = _to_options(parser.parse_args(["animate", "--gallery"]))
    clock = _to_options(parser.parse_args(["animate", "digital-clock", "--gallery"]))

    assert isinstance(default, AnimationLaunch)
    assert default.gallery
    assert default.animation.style == animation_style_choices("standalone")[0]
    assert clock.gallery
    assert clock.animation.style == "digital-clock"


def test_default_command_injection_preserves_animate() -> None:
    assert _inject_default_command(["animate", "rain"]) == ["animate", "rain"]


def test_main_top_level_typo_lists_commands_and_suggests_dashboard(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_run(*_args: object) -> int:
        raise AssertionError("runtime must not start")

    monkeypatch.setattr("ccusage_viz.cli.run", fail_run)

    assert main(["dashbaord", "--lang", "en"]) == 2

    error = capsys.readouterr().err
    assert "unrecognized arguments: dashbaord" in error
    assert "Supported commands: chart, dashboard, animate, dataset, text" in error
    assert "Did you mean 'dashboard'?" in error


def test_main_top_level_typo_honors_leading_language_option(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--lang", "zh", "dashbaord"]) == 2

    error = capsys.readouterr().err
    assert "支持的命令：chart, dashboard, animate, dataset, text" in error
    assert "你是不是想输入 'dashboard'？" in error


def test_distant_top_level_failure_lists_commands_without_suggestion(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["nonsense", "--lang", "en"]) == 2

    error = capsys.readouterr().err
    assert "Supported commands: chart, dashboard, animate, dataset, text" in error
    assert "Did you mean" not in error


@pytest.mark.parametrize(
    ("raw_args", "key", "detail"),
    [
        (["--period", "14d"], "error.arguments", "unrecognized arguments: --period"),
        (["dashboard"], "error.arguments", "unrecognized arguments: dashboard"),
        (["timeline"], "error.arguments", "unrecognized arguments: timeline"),
        (["dashbaord"], "error.invalid_subcommand", "unrecognized arguments: dashbaord"),
        (["dashbaord"], "error.arguments", "unrecognized arguments: something-else"),
    ],
)
def test_top_level_typo_returns_original_for_uncertain_failures(
    raw_args: list[str], key: str, detail: str
) -> None:
    original = UsageError(key, detail=detail)

    assert _top_level_typo(raw_args, original) is original


def test_option_led_default_chart_route_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[object] = []
    monkeypatch.setattr(
        "ccusage_viz.cli.run",
        lambda launch, _tr: captured.append(launch) or 0,
    )

    assert main(["--demo", "small", "--lang", "en"]) == 0
    assert len(captured) == 1
    assert isinstance(captured[0], StandaloneLaunch)


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--period", "14d"], ["chart", "timeline", "--period", "14d"]),
        (["chart", "ranking"], ["chart", "ranking"]),
        (["dashboard"], ["dashboard"]),
        (["dataset", "list"], ["dataset", "list"]),
        (["dashbaord"], ["chart", "timeline", "dashbaord"]),
    ],
)
def test_subcommand_guidance_does_not_change_default_injection(
    argv: list[str], expected: list[str]
) -> None:
    assert _inject_default_command(argv) == expected


def test_route_probe_identifies_only_help_and_version() -> None:
    assert probe_short_circuit(["--version"]).kind is ShortCircuitKind.VERSION
    route = probe_short_circuit(["chart", "timeline", "--lang", "zh", "--help"])
    assert route is not None
    assert route.kind is ShortCircuitKind.HELP
    assert route.command == "chart timeline"
    assert route.language == "zh"
    assert probe_short_circuit(["chart", "timeline", "--period", "14d"]) is None


def test_version_short_circuits_before_translation_or_runtime(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "ccusage_viz.cli.load_translator",
        lambda *_args, **_kwargs: pytest.fail("translator must not load"),
    )
    monkeypatch.setattr(
        "ccusage_viz.cli.run", lambda *_args, **_kwargs: pytest.fail("runtime must not start")
    )

    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"ccusage-viz {__version__}"


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


def test_all_commands_accept_exactly_four_density_values() -> None:
    parser = build_parser(load_translator("en"))
    for command in ("timeline", "calendar", "stack", "ranking", "monitor"):
        for density in ("minimal", "compact", "full", "detailed"):
            assert parser.parse_args(["chart", command, "--density", density]).density == density
        assert parser.parse_args(["chart", command]).density == (
            "full" if command == "ranking" else "detailed"
        )
    with pytest.raises(UsageError) as caught:
        parser.parse_args(["chart", "timeline", "--density", "standard"])
    assert caught.value.key == "error.arguments"


@pytest.mark.parametrize("command", ("timeline", "stack", "ranking", "monitor"))
def test_project_aggregation_is_not_a_public_chart_option(command: str) -> None:
    parser = build_parser(load_translator("en"))
    with pytest.raises(UsageError):
        parser.parse_args(["chart", command, "--project-aggregation", "exact"])


def test_animate_help_is_localized(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser(load_translator("zh"))

    with pytest.raises(SystemExit):
        parser.parse_args(["animate", "--help"])

    assert "运行不依赖数据提供方的终端动画" in capsys.readouterr().out


def test_animate_defaults_to_first_discovered_style_and_rejects_chart_options() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["animate"]))

    assert isinstance(options, AnimationLaunch)
    assert options.animation.style == animation_style_choices("standalone")[0]
    with pytest.raises(UsageError) as caught:
        parser.parse_args(["animate", "--density", "compact"])
    assert caught.value.key == "error.arguments"


def test_animate_invalid_style_fails_during_option_materialization() -> None:
    parser = build_parser(load_translator("en"))

    options = _to_options(parser.parse_args(["animate", "snow"]))
    assert options.animation.style == "snow"
    with pytest.raises(UsageError):
        _to_options(parser.parse_args(["animate", "not-an-animation"]))


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


def test_all_commands_accept_themes() -> None:
    parser = build_parser(load_translator("en"))
    for command in ("timeline", "calendar", "stack", "ranking", "monitor"):
        for theme in COLOR_SCHEMES:
            assert parser.parse_args(["chart", command, "--theme", theme]).color_scheme == theme
    with pytest.raises(UsageError) as caught:
        parser.parse_args(["chart", "timeline", "--theme", "unknown"])
    assert caught.value.key == "error.arguments"


@pytest.mark.parametrize(
    ("command", "style"),
    [
        ("timeline", "linear"),
        ("timeline", "step"),
        ("timeline", "no-line"),
        ("timeline", "points"),
        ("timeline", "line-points"),
        ("timeline", "stem"),
        ("timeline", "area"),
        ("calendar", "relative"),
        ("calendar", "grid"),
        ("stack", "stacked"),
        ("stack", "stacked-pattern"),
        ("stack", "grouped"),
        ("stack", "grouped-thin"),
        ("stack", "normalized"),
        ("ranking", "bar"),
        ("ranking", "dot"),
        ("ranking", "dots"),
        ("monitor", "bars"),
        ("monitor", "line"),
        ("monitor", "step"),
        ("monitor", "points"),
        ("monitor", "line-points"),
        ("monitor", "cumulative-bars"),
        ("monitor", "ranking"),
        ("monitor", "ranking-dot"),
        ("monitor", "list"),
        ("ranking", "list"),
    ],
)
def test_commands_accept_their_own_styles(command: str, style: str) -> None:
    parser = build_parser(load_translator("en"))
    assert parser.parse_args(["chart", command, "--style", style]).style == style


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


def test_root_help_lists_localized_subcommand_summaries(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = build_parser(load_translator("zh"))
    with pytest.raises(SystemExit) as caught:
        parser.parse_args(["--help"])
    assert caught.value.code == 0
    output = capsys.readouterr().out
    assert "绘制独立图表" in output
    assert "animate" in output


def namespace(**overrides: object) -> Namespace:
    values: dict[str, object] = {
        "command": "timeline",
        "period": None,
        "since": None,
        "until": None,
        "agent": [],
        "model": [],
        "project": [],
        "demo": "small",
        "lang": "en",
        "ccusage_bin": "ccusage",
        "query_timeout": 30.0,
        "ascii": True,
        "by": None,
        "top": None,
        "other": "show",
        "cache": "combined",
        "color_scheme": "classic",
        "style": "linear",
        "window": "1h",
        "interval": None,
        "legend": "below-title",
        "granularity": "day",
        "weekdays": "show",
    }
    values.update(overrides)
    if "style" not in overrides:
        values["style"] = DEFAULT_STYLES[str(values["command"])]
    return Namespace(**values)


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


def test_dashboard_uses_launcher_from_local_wrapper_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = []
    monkeypatch.setenv("CCUV_LAUNCHER", "ccuv-local")
    monkeypatch.setattr(
        "ccusage_viz.cli.run", lambda route, _translator: captured.append(route) or 0
    )

    assert main(["dashboard"]) == 0
    assert captured[0].launcher == "ccuv-local"
    assert isinstance(captured[0].panes[0], AnimationPaneConfig)
    assert captured[0].panes[0].overlay.command == "ccuv-local text time-state --run"


def test_ascii_conflicts_only_with_explicit_theme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ccusage_viz.cli.run", lambda *_args: 0)
    assert main(["chart", "timeline", "--demo", "small", "--ascii"]) == 0
    for theme in ("classic", "no-color"):
        assert main(["chart", "timeline", "--demo", "small", "--ascii", "--theme", theme]) == 2


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


def test_monitor_parser_keeps_startup_selectors() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(
        parser.parse_args(
            [
                "chart",
                "monitor",
                "--agent",
                "claude",
                "--model",
                "sonnet",
                "--project",
                "app",
                "--by",
                "project",
                "--style",
                "line",
            ]
        )
    )

    assert options.chart.filters.agents == ("claude",)
    assert options.chart.filters.models == ("sonnet",)
    assert options.chart.filters.projects == ("app",)


def test_monitor_parser_rejects_unknown_grouping() -> None:
    parser = build_parser(load_translator("en"))
    with pytest.raises(UsageError) as caught:
        parser.parse_args(["chart", "monitor", "--by", "token"])
    assert caught.value.key == "error.arguments"


@pytest.mark.parametrize("dimension", ("agent", "model", "project"))
def test_monitor_grouping_rejects_bars(dimension: str) -> None:
    with pytest.raises(UsageError) as caught:
        _to_options(namespace(command="monitor", by=dimension, style="bars"))
    assert caught.value.key == "error.style_incompatible"


def test_demo_monitor_defaults_to_one_second_interval() -> None:
    options = _to_options(namespace(command="monitor", demo="small", by=None, style="bars"))
    assert options.host.interval == 1.0
    assert options.host.demo_seed is not None


def test_demo_seed_is_shared_by_dashboard_panes_and_varies_between_invocations() -> None:
    parser = build_parser(load_translator("en"))

    first = _to_options(parser.parse_args(["dashboard", "--demo", "small"]))
    second = _to_options(parser.parse_args(["dashboard", "--demo", "small"]))
    fixed = _to_options(parser.parse_args(["dashboard", "--demo", "small", "--demo-seed", "47"]))

    assert first.host.demo_seed is not None
    assert first.host.demo_seed != second.host.demo_seed
    assert fixed.host.demo_seed == 47
    assert all(
        standalone_from_chart_pane(fixed, pane).host.demo_seed == 47
        for pane in fixed.panes
        if isinstance(pane, ChartPaneConfig)
    )


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


def test_clock_overlay_source_uses_automatic_language_detection() -> None:
    parser = build_parser(load_translator("zh"))

    options = _to_options(parser.parse_args(["dashboard", "wide-clock", "--lang", "zh"]))

    assert isinstance(options.panes[0], AnimationPaneConfig)
    assert options.panes[0].overlay.command == "ccuv text time-state --run"
    assert options.panes[0].overlay.position == "bottom-right"


def test_bare_dashboard_is_equivalent_to_wide_clock_preset() -> None:
    parser = build_parser(load_translator("en"))

    bare = _to_options(parser.parse_args(["dashboard"]))
    wide_clock = _to_options(parser.parse_args(["dashboard", "wide-clock"]))

    assert bare == wide_clock
    assert bare.host.grid == "2x2"
    assert bare.host.refresh_interval == 60
    assert bare.host.sampling_interval == 15
    assert isinstance(bare.panes[0], AnimationPaneConfig)
    assert bare.panes[0].animation.style == "digital-clock"
    assert bare.panes[0].overlay.command is not None
    assert bare.panes[0].overlay.command == "ccuv text time-state --run"
    assert tuple(
        pane.chart.kind for pane in bare.panes[1:] if isinstance(pane, ChartPaneConfig)
    ) == (
        "timeline",
        "stack",
        "ranking",
        "monitor",
    )


@pytest.mark.parametrize(
    ("preset", "kinds"),
    [
        ("spotlight-wide", ("timeline", "stack", "ranking")),
        ("spotlight-wide2", ("timeline", "stack", "ranking", "monitor")),
    ],
)
def test_dashboard_spotlight_presets_feature_the_first_pane(
    preset: str, kinds: tuple[str, ...]
) -> None:
    parser = build_parser(load_translator("en"))

    options = _to_options(parser.parse_args(["dashboard", preset]))

    assert options.host.layout == preset
    assert options.host.style == "framed"
    assert tuple(pane.chart.kind for pane in options.panes) == kinds
    assert {pane.chart.presentation.density for pane in options.panes} == {"compact"}


def test_dashboard_allows_user_preset_names_but_rejects_unknown_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ccusage_viz.cli.dashboard_preset_state_root", lambda: tmp_path)
    parser = build_parser(load_translator("en"))

    namespace = parser.parse_args(["dashboard", "spotlight-tall"])
    assert namespace.preset == "spotlight-tall"

    with pytest.raises(UsageError) as caught:
        _to_options(namespace)
    assert caught.value.key == "error.invalid_preset_suggestion"

    with pytest.raises(UsageError) as caught:
        parser.parse_args(["dashboard", "--pane", "timeline", "--layout", "spotlight-tall"])
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


def test_dashboard_help_exposes_public_named_layouts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = build_parser(load_translator("en"))

    with pytest.raises(SystemExit) as caught:
        parser.parse_args(["dashboard", "--help"])

    assert caught.value.code == 0
    output = capsys.readouterr().out
    assert "--layout" in output
    assert "spotlight-wide2" in output
    assert "spotlight-monitor" not in output


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


@pytest.mark.parametrize(
    ("arguments", "key", "values"),
    [
        (
            ["--column-weight", "0", "--column-weight", "1", "--row-weight", "1"],
            "error.tui_layout_weight_positive",
            {"axis": "column"},
        ),
        (
            ["--column-weight", "1", "--row-weight", "1"],
            "error.tui_layout_weight_count",
            {"axis": "column", "expected": 2, "actual": 1, "layout": "1x2"},
        ),
    ],
)
def test_dashboard_rejects_invalid_layout_weights(
    arguments: list[str], key: str, values: dict[str, object]
) -> None:
    parser = build_parser(load_translator("en"))
    with pytest.raises(UsageError) as caught:
        _to_options(
            parser.parse_args(
                [
                    "dashboard",
                    "--pane",
                    "timeline",
                    "--pane",
                    "stack",
                    "--grid",
                    "1x2",
                    *arguments,
                ]
            )
        )

    assert caught.value.key == key
    assert caught.value.values == values


@pytest.mark.parametrize(
    "arguments",
    [
        ["dashboard", "spotlight-wide", "--grid", "2x2"],
        ["dashboard", "wide-clock", "--layout", "auto"],
        ["dashboard", "spotlight-wide2", "--layout", "auto"],
        ["dashboard", "--pane", "timeline", "--grid", "1x1", "--layout", "auto"],
    ],
)
def test_dashboard_rejects_conflicting_preset_grid_and_layout(
    arguments: list[str],
) -> None:
    parser = build_parser(load_translator("en"))

    with pytest.raises(UsageError) as caught:
        _to_options(parser.parse_args(arguments))

    assert caught.value.key == "error.arguments"


def test_dashboard_narrow_clock_reuses_narrow_panes_with_short_clock_row() -> None:
    parser = build_parser(load_translator("en"))

    narrow = _to_options(parser.parse_args(["dashboard", "narrow"]))
    narrow_clock = _to_options(parser.parse_args(["dashboard", "narrow-clock"]))

    assert isinstance(narrow_clock.panes[0], AnimationPaneConfig)
    assert narrow_clock.panes[0].animation.style == "digital-clock"
    assert narrow_clock.panes[0].overlay.position == "bottom-right"
    assert narrow_clock.panes[1:] == narrow.panes
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
    assert wide_clock.panes[1:] == wide.panes
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


def test_dashboard_narrow_and_all_presets_expand_to_concrete_state() -> None:
    parser = build_parser(load_translator("en"))

    narrow = _to_options(parser.parse_args(["dashboard", "narrow"]))
    all_panes = _to_options(parser.parse_args(["dashboard", "all"]))

    assert narrow.host.grid == "3x1"
    assert tuple(pane.chart.kind for pane in narrow.panes) == (
        "timeline",
        "ranking",
        "monitor",
    )
    assert narrow.host.style == "framed"
    assert narrow.panes[0].chart.presentation.style == "line-points"
    assert narrow.panes[1].chart.presentation.style == "dot"
    assert narrow.panes[1].chart.by == "project"
    assert narrow.panes[1].chart.top == 10
    assert narrow.panes[2].chart.window_seconds == 3600
    assert narrow.panes[2].chart.presentation.style == "ranking"
    assert narrow.panes[2].chart.top == 3
    assert all("--top" not in panel for panel in DASHBOARD_PRESETS["narrow"].panels)

    assert len(all_panes.panes) == 10
    assert all_panes.host.grid == "5x2"
    assert all_panes.host.style == "split"
    assert all("--top" not in panel for panel in DASHBOARD_PRESETS["all"].panels)
    assert {pane.chart.presentation.density for pane in all_panes.panes} == {"minimal"}
    assert all_panes.panes[5].chart.kind == "stack"
    assert all_panes.panes[5].chart.presentation.style == "grouped-thin"
    assert all_panes.panes[5].chart.presentation.theme == "contrast"
    assert len({pane.chart.presentation.theme for pane in all_panes.panes}) > 3


@pytest.mark.parametrize(
    "arguments",
    (
        ["dashboard", "wide", "--refresh-interval", "20"],
        ["dashboard", "wide", "--pane", "calendar"],
        ["dashboard", "wide", "--query-timeout", "20"],
        ["dashboard", "wide", "--timezone", "UTC"],
    ),
)
def test_dashboard_named_preset_rejects_configuration_overrides(arguments: list[str]) -> None:
    parser = build_parser(load_translator("en"))

    with pytest.raises(UsageError) as caught:
        _to_options(parser.parse_args(arguments), explicit=_explicit_fields(arguments))

    assert caught.value.key == "error.arguments"


def test_dashboard_named_preset_allows_ccusage_bin_override() -> None:
    parser = build_parser(load_translator("en"))
    arguments = ["dashboard", "wide", "--ccusage-bin", "/opt/bin/ccusage"]

    options = _to_options(parser.parse_args(arguments), explicit=_explicit_fields(arguments))

    assert options.process.ccusage_bin == "/opt/bin/ccusage"
    assert options.was_explicit("ccusage_bin")


def test_dashboard_named_empty_preserves_preset_configuration() -> None:
    parser = build_parser(load_translator("en"))

    preset = _to_options(parser.parse_args(["dashboard", "wide"]))
    emptied = _to_options(
        parser.parse_args(["dashboard", "wide", "--empty"]),
        explicit={"empty"},
    )

    assert emptied.process == preset.process
    assert emptied.host == preset.host
    assert len(emptied.panes) == len(preset.panes)
    assert all(isinstance(pane, EmptyPaneConfig) for pane in emptied.panes)


def test_dashboard_user_preset_empty_preserves_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    parser = build_parser(load_translator("en"))
    saved = DashboardLaunch(
        ProcessConfig(ccusage_bin="preset-ccusage", query_timeout=17),
        DashboardHostConfig(grid="1x1", timezone="Asia/Shanghai", demo_size="50", demo_seed=3),
        (EmptyPaneConfig(),),
    )
    DashboardPresetStore(tmp_path).save(preset_from_launch("my-dashboard", saved))
    monkeypatch.setattr("ccusage_viz.cli.dashboard_preset_state_root", lambda: tmp_path)

    emptied = _to_options(
        parser.parse_args(["dashboard", "my-dashboard", "--empty"]),
        explicit={"empty"},
    )

    assert emptied.process == saved.process
    assert emptied.host == saved.host
    assert len(emptied.panes) == len(saved.panes)
    assert all(isinstance(pane, EmptyPaneConfig) for pane in emptied.panes)


def test_dashboard_user_preset_allows_ccusage_bin_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    parser = build_parser(load_translator("en"))
    saved = DashboardLaunch(
        ProcessConfig(ccusage_bin="preset-ccusage", query_timeout=17),
        DashboardHostConfig(grid="1x1", timezone="Asia/Shanghai", demo_size="50", demo_seed=3),
        (EmptyPaneConfig(),),
    )
    DashboardPresetStore(tmp_path).save(preset_from_launch("my-dashboard", saved))
    monkeypatch.setattr("ccusage_viz.cli.dashboard_preset_state_root", lambda: tmp_path)
    arguments = ["dashboard", "my-dashboard", "--ccusage-bin", "/opt/bin/ccusage"]

    loaded = _to_options(parser.parse_args(arguments), explicit=_explicit_fields(arguments))

    assert loaded.process.query_timeout == saved.process.query_timeout
    assert loaded.process.ccusage_bin == "/opt/bin/ccusage"
    assert loaded.host == saved.host
    assert loaded.panes == saved.panes
    assert loaded.was_explicit("ccusage_bin")


def test_unknown_dashboard_preset_lists_builtins_and_suggests_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ccusage_viz.cli.dashboard_preset_state_root", lambda: tmp_path)
    tr = load_translator("en")

    with pytest.raises(UsageError) as caught:
        _to_options(build_parser(tr).parse_args(["dashboard", "wid-clock"]))

    text = format_error(caught.value, tr)
    assert "Supported presets: " + ", ".join(DASHBOARD_PRESETS) in text
    assert "Did you mean 'wide-clock'?" in text


def test_unknown_dashboard_preset_guidance_is_localized_in_chinese(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ccusage_viz.cli.dashboard_preset_state_root", lambda: tmp_path)
    tr = load_translator("zh")

    with pytest.raises(UsageError) as caught:
        _to_options(build_parser(tr).parse_args(["dashboard", "wid-clock"]))

    text = format_error(caught.value, tr)
    assert "支持的预设：" + ", ".join(DASHBOARD_PRESETS) in text
    assert "你是不是想输入 'wide-clock'？" in text


def test_unknown_dashboard_preset_loads_user_records_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ccusage_viz.cli.dashboard_preset_state_root", lambda: tmp_path)
    calls = 0
    original_list = DashboardPresetStore.list

    def counted_list(store: DashboardPresetStore) -> tuple[object, ...]:
        nonlocal calls
        calls += 1
        return original_list(store)

    monkeypatch.setattr(DashboardPresetStore, "list", counted_list)

    with pytest.raises(UsageError):
        _to_options(build_parser(load_translator("en")).parse_args(["dashboard", "wid-clock"]))

    assert calls == 1


def test_unknown_dashboard_preset_lists_saved_names_after_builtins_and_suggests_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved = DashboardLaunch(
        ProcessConfig(),
        DashboardHostConfig(grid="1x1"),
        (EmptyPaneConfig(),),
    )
    DashboardPresetStore(tmp_path).save(preset_from_launch("my-dashbord", saved))
    monkeypatch.setattr("ccusage_viz.cli.dashboard_preset_state_root", lambda: tmp_path)
    tr = load_translator("en")

    with pytest.raises(UsageError) as caught:
        _to_options(build_parser(tr).parse_args(["dashboard", "my-dashboard"]))

    text = format_error(caught.value, tr)
    supported = next(line for line in text.splitlines() if line.startswith("Supported presets:"))
    assert supported == "Supported presets: " + ", ".join((*DASHBOARD_PRESETS, "my-dashbord"))
    assert "Did you mean 'my-dashbord'?" in text


def test_unknown_dashboard_preset_deduplicates_saved_builtin_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved = DashboardLaunch(
        ProcessConfig(),
        DashboardHostConfig(grid="1x1"),
        (EmptyPaneConfig(),),
    )
    DashboardPresetStore(tmp_path).save(preset_from_launch("wide", saved))
    monkeypatch.setattr("ccusage_viz.cli.dashboard_preset_state_root", lambda: tmp_path)
    tr = load_translator("en")

    with pytest.raises(UsageError) as caught:
        _to_options(build_parser(tr).parse_args(["dashboard", "not-a-preset"]))

    supported = next(
        line
        for line in format_error(caught.value, tr).splitlines()
        if line.startswith("Supported presets:")
    )
    assert supported.split(": ", 1)[1].split(", ").count("wide") == 1


def test_distant_dashboard_preset_lists_candidates_without_suggestion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ccusage_viz.cli.dashboard_preset_state_root", lambda: tmp_path)
    tr = load_translator("en")

    with pytest.raises(UsageError) as caught:
        _to_options(build_parser(tr).parse_args(["dashboard", "xyzzy"]))

    text = format_error(caught.value, tr)
    assert caught.value.key == "error.invalid_preset"
    assert "Supported presets: " + ", ".join(DASHBOARD_PRESETS) in text
    assert "Did you mean" not in text


def test_unknown_dashboard_preset_preserves_corrupt_store_error_and_builtin_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / DashboardPresetStore.filename).write_text("{not-json", encoding="utf-8")
    monkeypatch.setattr("ccusage_viz.cli.dashboard_preset_state_root", lambda: tmp_path)
    parser = build_parser(load_translator("en"))

    with pytest.raises(UsageError) as caught:
        _to_options(parser.parse_args(["dashboard", "wid-clock"]))

    assert caught.value.key == "error.arguments"
    assert caught.value.values["detail"] == "user dashboard preset storage is unavailable"
    builtin = _to_options(parser.parse_args(["dashboard", "wide"]))
    assert isinstance(builtin, DashboardLaunch)
    assert builtin.host.grid == "2x2"


def test_dashboard_unavailable_store_preserves_existing_error_for_builtin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ccusage_viz.cli.dashboard_preset_state_root", lambda: tmp_path)

    def fail_list(_store: DashboardPresetStore) -> tuple[object, ...]:
        raise DashboardPresetStoreError("unavailable")

    monkeypatch.setattr(DashboardPresetStore, "list", fail_list)
    parser = build_parser(load_translator("en"))

    with pytest.raises(UsageError) as caught:
        _to_options(parser.parse_args(["dashboard", "wide"]))

    assert caught.value.key == "error.arguments"
    assert caught.value.values["detail"] == "user dashboard preset storage is unavailable"


def test_dashboard_builtin_and_saved_preset_success_remain_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ccusage_viz.cli.dashboard_preset_state_root", lambda: tmp_path)
    parser = build_parser(load_translator("en"))
    expected_builtin = _to_options(parser.parse_args(["dashboard", "wide"]))
    saved = DashboardLaunch(
        ProcessConfig(ccusage_bin="saved-ccusage", query_timeout=17),
        DashboardHostConfig(grid="1x1", timezone="UTC"),
        (EmptyPaneConfig(),),
    )
    DashboardPresetStore(tmp_path).save(preset_from_launch("saved-dashboard", saved))

    builtin = _to_options(parser.parse_args(["dashboard", "wide"]))
    loaded = _to_options(parser.parse_args(["dashboard", "saved-dashboard"]))

    assert isinstance(loaded, DashboardLaunch)
    assert builtin == expected_builtin
    assert loaded.process == saved.process
    assert loaded.host == saved.host
    assert loaded.panes == saved.panes


def test_invalid_dashboard_preset_does_not_reach_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("ccusage_viz.cli.dashboard_preset_state_root", lambda: tmp_path)

    def fail_run(*_args: object) -> int:
        raise AssertionError("runtime must not start")

    monkeypatch.setattr("ccusage_viz.cli.run", fail_run)

    assert main(["dashboard", "wid-clock", "--lang", "en"]) == 2
    assert "Did you mean 'wide-clock'?" in capsys.readouterr().err


def test_dashboard_host_options_use_the_default_preset() -> None:
    parser = build_parser(load_translator("en"))

    options = _to_options(
        parser.parse_args(["dashboard", "--theme", "nord"]),
        explicit=frozenset({"color_scheme"}),
    )

    assert options.host.theme == "nord"
    assert options.panes[0].animation.style == "digital-clock"


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


@pytest.mark.parametrize(
    "fragment",
    [
        "timeline --interval 10",
        "timeline --interval=10",
        "timeline --inter=10",
        "timeline --no-watch",
        "timeline --no-wat",
        "timeline --watch",
        "timeline --ascii",
        "timeline --demo small",
        "timeline --lang zh",
        "timeline --ccusage-bin custom",
        "timeline --ccusage-b custom",
        "timeline --query-timeout 5",
        "timeline --query-time 5",
        "timeline --pane stack",
        "timeline --grid 1x1",
        "timeline --refresh-interval 5",
        "monitor --sampling-interval 5",
        "timeline --header-style compact",
        "timeline --header-summary month",
        "timeline --header-interval 5",
        "dashboard",
        "timeline 'unterminated",
    ],
)
def test_dashboard_pane_rejects_host_process_and_lifecycle_options(fragment: str) -> None:
    parser = build_parser(load_translator("en"))
    with pytest.raises(UsageError) as caught:
        _to_options(parser.parse_args(["dashboard", "--pane", fragment]))
    assert caught.value.key == "error.tui_panel"


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
