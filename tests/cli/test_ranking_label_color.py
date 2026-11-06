"""Ranking label policy is ccuv presentation state, including absent band facts."""

import shlex

import pytest

from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_copy import (
    format_command,
    format_full_command,
    format_full_dashboard_command,
)
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.errors import UsageError
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import LABEL_COLOR_MODES, ChartPresentation
from ccusage_viz.presets.values import (
    DashboardPresetValidationError,
    _presentation_parse,
    _presentation_wire,
)


def parse(argv):
    return _to_options(build_parser(load_translator("en")).parse_args(argv))


@pytest.mark.parametrize("mode", LABEL_COLOR_MODES)
@pytest.mark.parametrize("custom", (False, True))
def test_cli_and_copied_commands_preserve_ranking_policy(mode, custom):
    source = ["--dataset", "reader", "--command", "reader"] if custom else []
    options = parse(["chart", "ranking", *source, "--label-color", mode, "--legend", "hidden"])
    assert options.chart.presentation.label_color_mode == mode
    for formatter in (format_command, format_full_command):
        command = formatter(options)
        copied = parse(shlex.split(command)[1:])
        assert copied.chart.presentation.label_color_mode == mode
        assert copied.chart.presentation.legend == "hidden"
    assert ("--label-color" in format_command(options)) == (mode != "change")
    assert "--label-color" in format_full_command(options)


@pytest.mark.parametrize("mode", LABEL_COLOR_MODES)
@pytest.mark.parametrize("custom", (False, True))
def test_pane_and_dashboard_command_roundtrip(mode, custom):
    source = " --dataset reader --command reader" if custom else ""
    prefix = "chart " if custom else ""
    dashboard = parse(
        [
            "dashboard",
            "--pane",
            f"{prefix}ranking{source} --label-color {mode} --legend hidden",
        ]
    )
    copied = parse(shlex.split(format_full_dashboard_command(dashboard))[1:])
    assert copied.panes[0].chart.presentation.label_color_mode == mode
    assert copied.panes[0].chart.presentation.legend == "hidden"


@pytest.mark.parametrize("mode", LABEL_COLOR_MODES)
def test_presentation_preset_policy_roundtrip(mode):
    presentation = ChartPresentation(style="dot", label_color_mode=mode)
    assert _presentation_parse(_presentation_wire(presentation), "ranking") == presentation


def test_old_preset_defaults_without_bands_query():
    wire = _presentation_wire(ChartPresentation(style="dot"))
    wire.pop("label_color_mode")
    assert _presentation_parse(wire, "ranking").label_color_mode == "change"
    assert parse(["chart", "ranking"]).chart.presentation.label_color_mode == "change"


@pytest.mark.parametrize("invalid", (None, "auto", "", 1))
def test_invalid_explicit_preset_policy_rejected(invalid):
    wire = _presentation_wire(ChartPresentation(style="dot"))
    wire["label_color_mode"] = invalid
    with pytest.raises(DashboardPresetValidationError, match="label_color_mode"):
        _presentation_parse(wire, "ranking")


@pytest.mark.parametrize(
    "argv",
    (
        ["chart", "ranking", "--label-color", "auto"],
        ["chart", "timeline", "--label-color", "change"],
    ),
)
def test_invalid_or_nonranking_cli_policy_rejected(argv):
    with pytest.raises(UsageError):
        parse(argv)
