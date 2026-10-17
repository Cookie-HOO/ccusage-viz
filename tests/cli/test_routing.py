import pytest

from ccusage_viz.cli import main
from ccusage_viz.cli.routing import (
    ShortCircuitKind,
    _inject_default_command,
    _top_level_typo,
    probe_short_circuit,
)
from ccusage_viz.errors import UsageError


def test_default_command_injection_preserves_animate() -> None:
    assert _inject_default_command(["animate", "rain"]) == ["animate", "rain"]


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
