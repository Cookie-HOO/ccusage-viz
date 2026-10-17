import pytest

from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.errors import _rejected_subcommand
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.diagnostics import format_error
from ccusage_viz.errors import UsageError
from ccusage_viz.i18n import load_translator
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


def test_animate_help_is_localized(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser(load_translator("zh"))

    with pytest.raises(SystemExit):
        parser.parse_args(["animate", "--help"])

    assert "运行不依赖数据提供方的终端动画" in capsys.readouterr().out


def test_animate_invalid_style_fails_during_option_materialization() -> None:
    parser = build_parser(load_translator("en"))

    options = _to_options(parser.parse_args(["animate", "snow"]))
    assert options.animation.style == "snow"
    with pytest.raises(UsageError):
        _to_options(parser.parse_args(["animate", "not-an-animation"]))


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
