from pathlib import Path

import pytest

from ccusage_viz.cli import main
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.common import _explicit_fields
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.dashboard import DASHBOARD_PRESETS
from ccusage_viz.dashboard_preset_store import DashboardPresetStore
from ccusage_viz.diagnostics import format_error
from ccusage_viz.errors import UsageError
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import (
    AnimationPaneConfig,
    ChartPaneConfig,
    DashboardHostConfig,
    DashboardLaunch,
    EmptyPaneConfig,
    ProcessConfig,
)
from ccusage_viz.presets.document import preset_from_launch


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
    monkeypatch.setattr(
        "ccusage_viz.cli.configuration.dashboard_preset_state_root", lambda: tmp_path
    )
    parser = build_parser(load_translator("en"))

    namespace = parser.parse_args(["dashboard", "spotlight-tall"])
    assert namespace.preset == "spotlight-tall"

    with pytest.raises(UsageError) as caught:
        _to_options(namespace)
    assert caught.value.key == "error.invalid_preset_suggestion"

    with pytest.raises(UsageError) as caught:
        parser.parse_args(["dashboard", "--pane", "timeline", "--layout", "spotlight-tall"])
    assert caught.value.key == "error.arguments"


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
    monkeypatch.setattr(
        "ccusage_viz.cli.configuration.dashboard_preset_state_root", lambda: tmp_path
    )

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
    monkeypatch.setattr(
        "ccusage_viz.cli.configuration.dashboard_preset_state_root", lambda: tmp_path
    )
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
    monkeypatch.setattr(
        "ccusage_viz.cli.configuration.dashboard_preset_state_root", lambda: tmp_path
    )
    tr = load_translator("en")

    with pytest.raises(UsageError) as caught:
        _to_options(build_parser(tr).parse_args(["dashboard", "wid-clock"]))

    text = format_error(caught.value, tr)
    assert "Supported presets: " + ", ".join(DASHBOARD_PRESETS) in text
    assert "Did you mean 'wide-clock'?" in text


def test_unknown_dashboard_preset_guidance_is_localized_in_chinese(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "ccusage_viz.cli.configuration.dashboard_preset_state_root", lambda: tmp_path
    )
    tr = load_translator("zh")

    with pytest.raises(UsageError) as caught:
        _to_options(build_parser(tr).parse_args(["dashboard", "wid-clock"]))

    text = format_error(caught.value, tr)
    assert "支持的预设：" + ", ".join(DASHBOARD_PRESETS) in text
    assert "你是不是想输入 'wide-clock'？" in text


def test_unknown_dashboard_preset_loads_user_records_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "ccusage_viz.cli.configuration.dashboard_preset_state_root", lambda: tmp_path
    )
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
    monkeypatch.setattr(
        "ccusage_viz.cli.configuration.dashboard_preset_state_root", lambda: tmp_path
    )
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
    monkeypatch.setattr(
        "ccusage_viz.cli.configuration.dashboard_preset_state_root", lambda: tmp_path
    )
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
    monkeypatch.setattr(
        "ccusage_viz.cli.configuration.dashboard_preset_state_root", lambda: tmp_path
    )
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
    monkeypatch.setattr(
        "ccusage_viz.cli.configuration.dashboard_preset_state_root", lambda: tmp_path
    )
    parser = build_parser(load_translator("en"))

    with pytest.raises(UsageError) as caught:
        _to_options(parser.parse_args(["dashboard", "wid-clock"]))

    assert caught.value.key == "error.arguments"
    assert caught.value.values["detail"] == "user dashboard preset storage is unavailable"
    builtin = _to_options(parser.parse_args(["dashboard", "wide"]))
    assert isinstance(builtin, DashboardLaunch)
    assert builtin.host.grid == "2x2"


def test_dashboard_builtin_and_saved_preset_success_remain_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "ccusage_viz.cli.configuration.dashboard_preset_state_root", lambda: tmp_path
    )
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
    monkeypatch.setattr(
        "ccusage_viz.cli.configuration.dashboard_preset_state_root", lambda: tmp_path
    )

    def fail_run(*_args: object) -> int:
        raise AssertionError("runtime must not start")

    monkeypatch.setattr("ccusage_viz.cli.entrypoint.run", fail_run)

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
