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
@pytest.mark.parametrize("position", ("below-title", "inside", "hidden"))
def test_timeline_and_monitor_accept_legend_positions(command: str, position: str) -> None:
    parser = build_parser(load_translator("en"))
    assert parser.parse_args([command, "--legend-position", position]).legend_position == position


def test_monitor_accepts_values_legend_position() -> None:
    parser = build_parser(load_translator("en"))
    assert parser.parse_args(["monitor", "--legend-position", "values"]).legend_position == "values"


@pytest.mark.parametrize("position", ("below-title", "hidden"))
def test_stack_accepts_supported_legend_positions(position: str) -> None:
    parser = build_parser(load_translator("en"))
    assert parser.parse_args(["stack", "--legend-position", position]).legend_position == position


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


@pytest.mark.parametrize(
    ("command", "demo", "watch", "no_color"),
    [
        ("timeline", None, 5.0, False),
        ("timeline", "small", None, True),
        ("ranking", None, None, False),
        ("ranking", "large", 5.0, False),
    ],
)
def test_pick_accepts_supported_modes(
    command: str, demo: str | None, watch: float | None, no_color: bool
) -> None:
    options = _to_options(
        namespace(
            command=command,
            pick=True,
            demo=demo,
            watch=watch,
            no_color=no_color,
            color_scheme="nord",
            by="project" if command == "ranking" else "total",
            top=None,
        )
    )

    assert options.pick
    assert options.demo == demo
    assert options.watch == watch
    assert options.color_scheme == "nord"


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
        "watch": None,
        "demo": "small",
        "pick": False,
        "lang": "en",
        "ccusage_bin": "ccusage",
        "timeout": 30.0,
        "no_color": True,
        "ascii": True,
        "by": "total",
        "top": None,
        "show_other": False,
        "split_cache": False,
        "color_scheme": "classic",
        "style": "linear",
        "window": "1h",
        "interval": None,
        "no_summary": False,
    }
    values.update(overrides)
    if "style" not in overrides:
        values["style"] = DEFAULT_STYLES[str(values["command"])]
    return Namespace(**values)


@pytest.mark.parametrize(
    ("field", "value", "key"),
    [
        ("watch", math.nan, "error.watch_min"),
        ("watch", math.inf, "error.watch_min"),
        ("timeout", math.nan, "error.arguments"),
        ("timeout", math.inf, "error.arguments"),
    ],
)
def test_numeric_intervals_must_be_finite(field: str, value: float, key: str) -> None:
    with pytest.raises(UsageError) as caught:
        _to_options(namespace(**{field: value}))
    assert caught.value.key == key


@pytest.mark.parametrize(
    ("command", "by", "top", "key"),
    [
        ("timeline", "total", 2, "error.top_requires_by"),
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
def test_grouped_timeline_defaults_to_top_three_with_other(dimension: str) -> None:
    options = _to_options(namespace(command="timeline", by=dimension, top=None, show_other=False))

    assert options.top == 3
    assert options.show_other


@pytest.mark.parametrize("dimension", ("agent", "model", "project"))
def test_grouped_monitor_defaults_to_top_three(dimension: str) -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["monitor", "--by", dimension]))

    assert options.top == 3


def test_ranking_has_a_default_category_dimension_for_top() -> None:
    options = _to_options(namespace(command="ranking", by="project", top=5))
    assert options.by == "project"
    assert options.top == 5


@pytest.mark.parametrize(
    ("command", "by", "top", "key"),
    [
        ("timeline", "total", 1, "error.top_requires_by"),
        ("ranking", "model", None, "error.show_other_requires_top"),
    ],
)
def test_show_other_requires_a_group_cutoff(
    command: str, by: str, top: int | None, key: str
) -> None:
    with pytest.raises(UsageError) as caught:
        _to_options(namespace(command=command, by=by, top=top, show_other=True))
    assert caught.value.key == key


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
    assert options.by == dimension
    assert options.top == 2
    assert options.window_seconds == 3600
    assert options.interval == 15.0


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

    assert options.agents == ("claude",)
    assert options.models == ("sonnet",)
    assert options.projects == ("app",)


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


@pytest.mark.parametrize("command", ["timeline", "calendar", "stack"])
def test_summary_can_be_disabled(command: str) -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args([command, "--no-summary"]))
    assert options.no_summary


def test_ranking_summary_can_be_disabled() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["ranking", "--no-summary"]))
    assert options.no_summary


def test_demo_monitor_defaults_to_one_second_interval() -> None:
    options = _to_options(namespace(command="monitor", demo="small", by=None, style="bars"))
    assert options.interval == 1.0


def test_monitor_pick_explains_how_to_preview_appearance() -> None:
    with pytest.raises(UsageError) as caught:
        _to_options(namespace(command="monitor", demo=None, pick=True, by=None))
    assert caught.value.key == "error.monitor_pick"


def test_demo_monitor_pick_explains_that_demo_is_already_ready() -> None:
    with pytest.raises(UsageError) as caught:
        _to_options(namespace(command="monitor", demo="small", pick=True, by=None))
    assert caught.value.key == "error.monitor_demo_pick"


def test_global_language_options_precede_a_subcommand() -> None:
    assert _inject_default_command(["--lang", "zh", "timeline"]) == [
        "timeline",
        "--lang",
        "zh",
    ]


def test_large_top_values_are_accepted() -> None:
    parser = build_parser(load_translator("en"))
    assert _to_options(parser.parse_args(["ranking", "--top", "999"])).top == 999


@pytest.mark.parametrize("timeout", ("0", "nan", "inf"))
def test_dashboard_rejects_non_positive_or_non_finite_timeout(timeout: str) -> None:
    parser = build_parser(load_translator("en"))
    with pytest.raises(UsageError) as caught:
        _to_options(parser.parse_args(["dashboard", "--timeout", timeout]))
    assert caught.value.key == "error.arguments"


@pytest.mark.parametrize(
    "flag", ["--pick-theme", "--color-scheme", "--preview-schemes", "--no-color"]
)
def test_obsolete_appearance_flags_are_rejected(flag: str) -> None:
    parser = build_parser(load_translator("en"))
    args = ["timeline", flag, "nord"] if flag == "--color-scheme" else ["timeline", flag]
    with pytest.raises(UsageError) as caught:
        parser.parse_args(args)
    assert caught.value.key == "error.arguments"
