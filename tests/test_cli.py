import math
from argparse import Namespace

import pytest

from ccusage_viz import __version__
from ccusage_viz.cli import (
    ShortCircuitKind,
    _inject_default_command,
    _to_options,
    build_parser,
    main,
    probe_short_circuit,
)
from ccusage_viz.errors import UsageError
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import DEFAULT_STYLES
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
        parser.parse_args([command, "--help"])
    assert caught.value.code == 0
    assert description in capsys.readouterr().out


def test_route_probe_identifies_only_help_and_version() -> None:
    assert probe_short_circuit(["--version"]).kind is ShortCircuitKind.VERSION
    route = probe_short_circuit(["timeline", "--lang", "zh", "--help"])
    assert route is not None
    assert route.kind is ShortCircuitKind.HELP
    assert route.command == "timeline"
    assert route.language == "zh"
    assert probe_short_circuit(["timeline", "--period", "14d"]) is None


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
    assert parser.parse_args([command, "--legend", mode]).legend == mode


def test_monitor_accepts_values_legend_mode() -> None:
    parser = build_parser(load_translator("en"))
    assert parser.parse_args(["monitor", "--legend", "values"]).legend == "values"


@pytest.mark.parametrize("mode", ("below-title", "hidden"))
def test_stack_accepts_supported_legend_modes(mode: str) -> None:
    parser = build_parser(load_translator("en"))
    assert parser.parse_args(["stack", "--legend", mode]).legend == mode


def test_all_commands_accept_themes() -> None:
    parser = build_parser(load_translator("en"))
    for command in ("timeline", "calendar", "stack", "ranking", "monitor"):
        for theme in COLOR_SCHEMES:
            assert parser.parse_args([command, "--theme", theme]).color_scheme == theme
    with pytest.raises(UsageError) as caught:
        parser.parse_args(["timeline", "--theme", "unknown"])
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
        ("calendar", "absolute"),
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
        ("monitor", "ranking"),
    ],
)
def test_commands_accept_their_own_styles(command: str, style: str) -> None:
    parser = build_parser(load_translator("en"))
    assert parser.parse_args([command, "--style", style]).style == style


def test_style_is_rejected_for_the_wrong_command() -> None:
    parser = build_parser(load_translator("en"))
    with pytest.raises(UsageError) as caught:
        parser.parse_args(["calendar", "--style", "step"])
    assert caught.value.key == "error.arguments"


def test_timeline_rejects_removed_point_style() -> None:
    parser = build_parser(load_translator("en"))
    with pytest.raises(UsageError) as caught:
        parser.parse_args(["timeline", "--style", "point"])
    assert caught.value.key == "error.arguments"


def test_root_help_lists_localized_subcommand_summaries(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = build_parser(load_translator("zh"))
    with pytest.raises(SystemExit) as caught:
        parser.parse_args(["--help"])
    assert caught.value.code == 0
    output = capsys.readouterr().out
    assert "将每日 Token 用量绘制为折线图" in output
    assert "将累计 Token 用量绘制为排名" in output
    assert "animate" not in output


def namespace(**overrides: object) -> Namespace:
    values: dict[str, object] = {
        "command": "timeline",
        "period": None,
        "since": None,
        "until": None,
        "timezone": None,
        "agent": [],
        "model": [],
        "project": [],
        "no_watch": False,
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


def test_historical_lifecycle_defaults_and_validation() -> None:
    parser = build_parser(load_translator("en"))
    default = _to_options(parser.parse_args(["timeline"]))
    assert default.host.interval == 10
    assert default.host.watch

    one_shot = _to_options(
        parser.parse_args(["timeline", "--no-watch"]), explicit=frozenset({"no_watch"})
    )
    assert not one_shot.host.watch

    with pytest.raises(UsageError, match="error.arguments"):
        _to_options(
            parser.parse_args(["timeline", "--interval", "20", "--no-watch"]),
            explicit=frozenset({"interval", "no_watch"}),
        )


def test_continuous_routes_reject_ambiguous_lifecycle_options() -> None:
    parser = build_parser(load_translator("en"))
    with pytest.raises(UsageError, match="error.arguments"):
        _to_options(parser.parse_args(["monitor", "--no-watch"]), explicit=frozenset({"no_watch"}))
    for arguments in (
        ["timeline", "--watch"],
        ["dashboard", "--watch"],
        ["dashboard", "--no-watch"],
        ["dashboard", "--interval", "20"],
    ):
        with pytest.raises(UsageError, match="error.arguments"):
            parser.parse_args(arguments)


def test_ascii_conflicts_only_with_explicit_theme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ccusage_viz.cli.run", lambda *_args: 0)
    assert main(["timeline", "--demo", "small", "--ascii"]) == 0
    for theme in ("classic", "no-color"):
        assert main(["timeline", "--demo", "small", "--ascii", "--theme", theme]) == 2


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
    options = _to_options(parser.parse_args(["monitor", "--by", dimension]))

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
        parser.parse_args(["monitor", "--by", "token"])
    assert caught.value.key == "error.arguments"


@pytest.mark.parametrize("dimension", ("agent", "model", "project"))
def test_monitor_grouping_rejects_bars(dimension: str) -> None:
    with pytest.raises(UsageError) as caught:
        _to_options(namespace(command="monitor", by=dimension, style="bars"))
    assert caught.value.key == "error.style_incompatible"


def test_demo_monitor_defaults_to_one_second_interval() -> None:
    options = _to_options(namespace(command="monitor", demo="small", by=None, style="bars"))
    assert options.host.interval == 1.0


def test_global_language_options_precede_a_subcommand() -> None:
    assert _inject_default_command(["--lang", "zh", "timeline"]) == [
        "timeline",
        "--lang",
        "zh",
    ]


def test_large_top_values_are_accepted() -> None:
    parser = build_parser(load_translator("en"))
    assert _to_options(parser.parse_args(["ranking", "--top", "999"])).chart.top == 999


@pytest.mark.parametrize("timeout", ("0", "nan", "inf"))
def test_dashboard_rejects_non_positive_or_non_finite_timeout(timeout: str) -> None:
    parser = build_parser(load_translator("en"))
    with pytest.raises(UsageError) as caught:
        _to_options(parser.parse_args(["dashboard", "--query-timeout", timeout]))
    assert caught.value.key == "error.arguments"


def test_bare_dashboard_is_equivalent_to_wide_preset() -> None:
    parser = build_parser(load_translator("en"))

    bare = _to_options(parser.parse_args(["dashboard"]))
    wide = _to_options(parser.parse_args(["dashboard", "wide"]))

    assert bare == wide
    assert bare.host.grid == "2x2"
    assert bare.host.refresh_interval == 60
    assert bare.host.sampling_interval == 15
    assert tuple(pane.chart.kind for pane in bare.panes) == (
        "timeline",
        "stack",
        "ranking",
        "monitor",
    )


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
    assert narrow.panes[1].chart.by == "project"
    assert narrow.panes[1].chart.top == 5
    assert narrow.panes[2].chart.presentation.style == "ranking"
    assert len(all_panes.panes) == 10
    assert all_panes.host.grid == "5x2"
    assert all_panes.host.style == "framed"


def test_dashboard_preset_accepts_overrides_and_appended_panes() -> None:
    parser = build_parser(load_translator("en"))
    arguments = [
        "dashboard",
        "wide",
        "--refresh-interval",
        "20",
        "--pane",
        "calendar",
    ]

    options = _to_options(
        parser.parse_args(arguments), explicit=frozenset({"refresh_interval", "panes"})
    )

    assert options.host.refresh_interval == 20
    assert options.host.grid == "3x2"
    assert len(options.panes) == 5
    assert options.panes[-1].chart.kind == "calendar"


def test_dashboard_rejects_unknown_preset() -> None:
    parser = build_parser(load_translator("en"))

    with pytest.raises(UsageError, match="error.arguments"):
        parser.parse_args(["dashboard", "medium"])


def test_dashboard_options_require_a_preset_or_pane() -> None:
    parser = build_parser(load_translator("en"))

    with pytest.raises(UsageError, match="error.arguments"):
        _to_options(
            parser.parse_args(["dashboard", "--theme", "nord"]),
            explicit=frozenset({"color_scheme"}),
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
        "timeline --timezone UTC",
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
    args = ["timeline", flag, "nord"] if flag == "--color-scheme" else ["timeline", flag]
    with pytest.raises(UsageError) as caught:
        parser.parse_args(args)
    assert caught.value.key == "error.arguments"
