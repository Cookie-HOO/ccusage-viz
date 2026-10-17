import shlex
from datetime import date

import pytest

from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_copy import format_command, format_full_command
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.configuration import (
    apply_custom_probe_defaults,
)
from ccusage_viz.core.time import DateRange, local_today
from ccusage_viz.custom_models import (
    CustomCapabilities,
    CustomChartCapability,
    CustomChartDefaults,
    CustomDataset,
    CustomProbeDescriptor,
    CustomUnit,
    LocalizedText,
    V2HistoricalChartCapability,
)
from ccusage_viz.errors import UsageError
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import (
    ChartPresentation,
    CustomChartConfig,
    CustomCommandSource,
    resolve_date_range,
    validate_custom_partition_selection,
)

from .option_helpers import _probe_descriptor


def test_custom_partition_selection_validation_rejects_invalid_combinations() -> None:
    capability = V2HistoricalChartCapability(
        ("day",),
        (None, "logical_model", "real_model"),
        (),
        partition_by=(None, "logical_model"),
    )

    validate_custom_partition_selection(None, None, capability)
    validate_custom_partition_selection("logical_model", "real_model", capability)
    with pytest.raises(ValueError, match="requires.*group_by"):
        validate_custom_partition_selection("logical_model", None, capability)
    with pytest.raises(ValueError, match="must differ"):
        validate_custom_partition_selection("logical_model", "logical_model", capability)
    with pytest.raises(ValueError, match="supported"):
        validate_custom_partition_selection("missing", "real_model", capability)


def test_custom_chart_config_appends_partition_without_breaking_positional_fields() -> None:
    source = CustomCommandSource("weread", ("reader", "ccuv"))
    chart = CustomChartConfig(
        "ranking",
        source,
        resolve_date_range("ranking", period="14d", since=None, until=None),
        (),
        ChartPresentation(),
        "real_model",
        3,
        "show",
        "day",
        "show",
        frozenset(),
        "tokens",
        "comparisons",
        (),
        None,
        "full",
        "logical_model",
    )

    assert chart.group_by == "real_model"
    assert chart.partition_by == "logical_model"


def test_custom_source_requires_dataset_and_nonempty_argv() -> None:
    source = CustomCommandSource("weread", ("reader", "ccuv"))
    assert source.dataset_id == "weread"
    assert source.source_kind == "command"
    with pytest.raises(ValueError, match="dataset"):
        CustomCommandSource("", ("reader",))
    with pytest.raises(ValueError, match="command"):
        CustomCommandSource("weread", ())
    with pytest.raises(ValueError, match="source_kind"):
        CustomCommandSource("weread", ("reader",), source_kind="other")  # type: ignore[arg-type]


def test_custom_probe_defaults_apply_to_an_unconfigured_ranking_chart() -> None:
    source = CustomCommandSource("weread", ("reader", "ccuv"))
    initial = CustomChartConfig(
        "ranking",
        source,
        resolve_date_range("ranking", period=None, since=None, until=None, today=date(2026, 9, 30)),
    )

    resolved = apply_custom_probe_defaults(initial, _probe_descriptor(), timezone="UTC")

    assert resolved.date_range.period == "1y"
    assert resolved.date_range.since == date(2026, 1, 1)
    assert resolved.date_range.until == local_today(timezone="UTC")
    assert resolved.group_by == "book"
    assert resolved.top == 10


def test_custom_probe_partition_default_does_not_overwrite_explicit_grouping() -> None:
    text = LocalizedText("Router", "路由")
    descriptor = CustomProbeDescriptor(
        "router-1",
        "1.0",
        CustomDataset(text, text, CustomUnit("token", text, "suffix", 0)),
        CustomCapabilities(
            (),
            (),
            {
                "ranking": CustomChartCapability(
                    ("day",),
                    ("logical_model", "real_model"),
                    (),
                    partition_by=("logical_model", "provider"),
                )
            },
        ),
        {"ranking": CustomChartDefaults("14d", "real_model", 10, partition_by="logical_model")},
        (),
    )
    initial = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        resolve_date_range("ranking", period="14d", since=None, until=None),
        group_by="logical_model",
        initial_explicit=frozenset({"group_by"}),
    )

    resolved = apply_custom_probe_defaults(initial, descriptor, timezone="UTC")

    assert resolved.group_by == "logical_model"
    assert resolved.partition_by == "provider"


def test_probe_capability_replaces_stale_explicit_partition_and_grouping() -> None:
    text = LocalizedText("Router", "路由")
    descriptor = CustomProbeDescriptor(
        "router-2",
        "1.0",
        CustomDataset(text, text, CustomUnit("millisecond", text, "suffix", 2)),
        CustomCapabilities(
            (),
            (),
            {"ranking": CustomChartCapability((), ("adapter,real_model",), ())},
        ),
        {"ranking": CustomChartDefaults("1d", "adapter,real_model", 10)},
        (),
    )
    initial = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        resolve_date_range("ranking", period="1d", since=None, until=None),
        group_by="real_model",
        partition_by="logical_model",
        initial_explicit=frozenset({"group_by", "partition_by"}),
    )

    resolved = apply_custom_probe_defaults(initial, descriptor, timezone="UTC")

    assert resolved.partition_by is None
    assert resolved.group_by == "adapter,real_model"


def test_absent_probe_defaults_preserve_valid_current_partition_and_grouping() -> None:
    text = LocalizedText("Router", "路由")
    descriptor = CustomProbeDescriptor(
        "router-1",
        "1.0",
        CustomDataset(text, text, CustomUnit("token", text, "suffix", 0)),
        CustomCapabilities(
            (),
            (),
            {
                "ranking": CustomChartCapability(
                    ("day",),
                    (None, "logical_model", "real_model"),
                    (),
                    partition_by=(None, "logical_model"),
                )
            },
        ),
        {},
        (),
    )
    initial = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        resolve_date_range("ranking", period="14d", since=None, until=None),
        group_by="real_model",
        partition_by="logical_model",
    )

    assert apply_custom_probe_defaults(initial, descriptor, timezone="UTC") == initial


def test_required_partition_capability_without_defaults_chooses_legal_pair() -> None:
    text = LocalizedText("Router", "路由")
    descriptor = CustomProbeDescriptor(
        "router-1",
        "1.0",
        CustomDataset(text, text, CustomUnit("token", text, "suffix", 0)),
        CustomCapabilities(
            (),
            (),
            {
                "ranking": CustomChartCapability(
                    ("day",),
                    ("logical_model", "real_model"),
                    (),
                    partition_by=("logical_model",),
                )
            },
        ),
        {},
        (),
    )
    initial = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        resolve_date_range("ranking", period="14d", since=None, until=None),
    )

    resolved = apply_custom_probe_defaults(initial, descriptor, timezone="UTC")

    assert (resolved.partition_by, resolved.group_by) == ("logical_model", "real_model")


def test_custom_probe_defaults_preserve_explicit_range_grouping_and_top() -> None:
    source = CustomCommandSource("weread", ("reader", "ccuv"))
    initial = CustomChartConfig(
        "ranking",
        source,
        DateRange(date(2026, 8, 1), date(2026, 8, 31), fixed_bounds=True),
        group_by="book",
        top=3,
        initial_explicit=frozenset({"since", "until", "group_by", "top"}),
    )

    resolved = apply_custom_probe_defaults(initial, _probe_descriptor(), timezone="UTC")

    assert resolved == initial


def test_invalid_custom_probe_defaults_leave_host_values_intact() -> None:
    source = CustomCommandSource("weread", ("reader", "ccuv"))
    initial = CustomChartConfig(
        "ranking",
        source,
        resolve_date_range("ranking", period="14d", since=None, until=None),
        presentation=ChartPresentation(theme="classic", style="dot"),
    )
    descriptor = _probe_descriptor()
    descriptor = CustomProbeDescriptor(
        descriptor.revision,
        descriptor.version,
        descriptor.dataset,
        descriptor.capabilities,
        {
            "ranking": CustomChartDefaults(
                "all",
                "missing",
                10,
                style="not-a-style",
                theme="not-a-theme",
                declared=frozenset({"period", "group_by", "top", "style", "theme"}),
            )
        },
        descriptor.environment,
    )

    resolved = apply_custom_probe_defaults(initial, descriptor, timezone="UTC")

    assert resolved == initial


def test_custom_ranking_partition_cli_and_command_round_trip() -> None:
    parser = build_parser(load_translator("en"))
    argv = [
        "chart",
        "ranking",
        "--dataset",
        "router",
        "--metric",
        "tokens",
        "--partition-by",
        "logical_model",
        "--group-by",
        "real_model",
        "--top",
        "3",
    ]

    launch = _to_options(
        parser.parse_args(argv), explicit=frozenset({"partition_by", "group_by", "top"})
    )

    assert isinstance(launch.chart, CustomChartConfig)
    assert launch.chart.partition_by == "logical_model"
    assert "partition_by" in launch.chart.initial_explicit
    assert "--partition-by logical_model --group-by real_model --top 3" in format_command(launch)
    reparsed = _to_options(parser.parse_args(shlex.split(format_full_command(launch))[1:]))
    assert reparsed.chart.partition_by == "logical_model"


def test_standalone_command_copy_outputs_and_round_trips_custom_partition() -> None:
    parser = build_parser(load_translator("en"))
    launch = _to_options(
        parser.parse_args(
            [
                "chart",
                "ranking",
                "--dataset",
                "router",
                "--metric",
                "tokens",
                "--partition-by",
                "logical_model",
                "--group-by",
                "real_model",
                "--top",
                "3",
            ]
        )
    )

    concise = format_command(launch)
    full = format_full_command(launch)
    copied = _to_options(parser.parse_args(shlex.split(full)[1:]))

    assert "--partition-by logical_model --group-by real_model" in concise
    assert "--partition-by logical_model --group-by real_model" in full
    assert isinstance(copied.chart, CustomChartConfig)
    assert (copied.chart.partition_by, copied.chart.group_by) == ("logical_model", "real_model")


def test_custom_partition_cli_rejects_invalid_combinations() -> None:
    parser = build_parser(load_translator("en"))
    equal = [
        "chart",
        "ranking",
        "--dataset",
        "router",
        "--partition-by",
        "model",
        "--group-by",
        "model",
    ]
    with pytest.raises(UsageError) as raised:
        _to_options(parser.parse_args(equal), explicit=frozenset({"partition_by", "group_by"}))
    assert "must differ" in str(raised.value.values["detail"])

    wrong_kind = ["chart", "timeline", "--dataset", "router", "--partition-by", "model"]
    with pytest.raises(UsageError) as raised:
        _to_options(parser.parse_args(wrong_kind), explicit=frozenset({"partition_by"}))
    assert "ranking" in str(raised.value.values["detail"])
