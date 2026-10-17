



import pytest

from ccusage_viz import __version__
from ccusage_viz.cli import main
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.errors import UsageError
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import AnimationPaneConfig, StandaloneLaunch


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
    monkeypatch.setattr("ccusage_viz.cli.entrypoint.detect_language", lambda: "zh")

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

def test_text_cannot_be_parsed_as_a_dashboard_pane() -> None:
    parser = build_parser(load_translator("en"))

    with pytest.raises(UsageError):
        _to_options(parser.parse_args(["dashboard", "--pane", "text time-state"]))

def test_main_top_level_typo_lists_commands_and_suggests_dashboard(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_run(*_args: object) -> int:
        raise AssertionError("runtime must not start")

    monkeypatch.setattr("ccusage_viz.cli.entrypoint.run", fail_run)

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

def test_option_led_default_chart_route_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[object] = []
    monkeypatch.setattr(
        "ccusage_viz.cli.entrypoint.run",
        lambda launch, _tr: captured.append(launch) or 0,
    )

    assert main(["--demo", "small", "--lang", "en"]) == 0
    assert len(captured) == 1
    assert isinstance(captured[0], StandaloneLaunch)

def test_version_short_circuits_before_translation_or_runtime(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "ccusage_viz.cli.entrypoint.load_translator",
        lambda *_args, **_kwargs: pytest.fail("translator must not load"),
    )
    monkeypatch.setattr(
        "ccusage_viz.cli.entrypoint.run", lambda *_args, **_kwargs: pytest.fail("runtime must not start")
    )

    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"ccusage-viz {__version__}"

def test_dashboard_uses_launcher_from_local_wrapper_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = []
    monkeypatch.setenv("CCUV_LAUNCHER", "ccuv-local")
    monkeypatch.setattr(
        "ccusage_viz.cli.entrypoint.run", lambda route, _translator: captured.append(route) or 0
    )

    assert main(["dashboard"]) == 0
    assert captured[0].launcher == "ccuv-local"
    assert isinstance(captured[0].panes[0], AnimationPaneConfig)
    assert captured[0].panes[0].overlay.command == "ccuv-local text time-state --run"

def test_ascii_conflicts_only_with_explicit_theme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ccusage_viz.cli.entrypoint.run", lambda *_args: 0)
    assert main(["chart", "timeline", "--demo", "small", "--ascii"]) == 0
    for theme in ("classic", "no-color"):
        assert main(["chart", "timeline", "--demo", "small", "--ascii", "--theme", theme]) == 2
