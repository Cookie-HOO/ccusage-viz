"""Runtime probes must publish V2 capabilities before the first chart request."""

from concurrent.futures import Future
from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest

import ccusage_viz.tui.completion as completion
import ccusage_viz.tui.queries as queries
import ccusage_viz.tui.session as sessions
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_component import CustomHistoricalComponent
from ccusage_viz.custom_models import (
    CustomCapabilities,
    CustomChartCapability,
    CustomDataset,
    CustomDimension,
    CustomProbeDescriptor,
    CustomUnit,
    LocalizedText,
    V2Dataset,
    V2HistoricalChartCapability,
    V2MetricCapabilities,
    V2MetricDescriptor,
    V2ProbeDescriptor,
)
from ccusage_viz.custom_protocol.responses import CustomProbeResponse, V2ProbeResponse
from ccusage_viz.i18n import load_translator
from ccusage_viz.lifecycle import FixedIntervalScheduler, LifecycleOperation, LifecycleTrigger
from ccusage_viz.options import CustomChartConfig, CustomCommandSource
from ccusage_viz.tui.models import CustomOutcome, TuiCustomPane


@pytest.mark.parametrize("legacy_replacement", [False, True])
def test_probe_publishes_partition_capability_before_first_primary(
    monkeypatch: pytest.MonkeyPatch, legacy_replacement: bool
) -> None:
    translator = load_translator("en")
    options = _to_options(
        build_parser(translator).parse_args(["dashboard", "--empty", "--header-style", "hidden"])
    )
    options = replace(options, host=replace(options.host, timezone="UTC"))
    submitted = []
    runtime = SimpleNamespace(
        submit=lambda intent: submitted.append(intent) or SimpleNamespace(cancel=lambda: None)
    )
    monkeypatch.setattr(sessions, "build_query_runtime", lambda: runtime)
    session = sessions.TuiSession(options, translator)
    session.executor.shutdown(wait=True)
    session.executor = SimpleNamespace(submit=lambda *args: Future())
    text = LocalizedText("Dataset", "数据集")
    dimension = CustomDimension("provider", text)
    metric = V2MetricDescriptor(
        "tokens",
        text,
        text,
        CustomUnit("count", text, "suffix", 0),
        "sum",
        V2MetricCapabilities(
            (dimension,),
            (),
            {
                "ranking": V2HistoricalChartCapability(
                    ("day",), (None, "provider"), (), partition_by=(None, "provider")
                )
            },
            partition_by=(dimension,),
        ),
        {},
    )
    descriptor = V2ProbeDescriptor("revision", "1", V2Dataset(text, text), (metric,), ())
    component = CustomHistoricalComponent(
        CustomChartConfig(
            "ranking",
            CustomCommandSource("dataset", ("dataset",)),
            DateRange(date(2026, 10, 1), date(2026, 10, 8)),
            metric_id=None if legacy_replacement else "tokens",
            partition_by=None if legacy_replacement else "provider",
            group_by="provider",
        )
    )
    pane = TuiCustomPane(
        component,
        FixedIntervalScheduler(10, now=0),
        LifecycleOperation("probe-test"),
        options.process,
    )
    session.panes = [pane]
    if legacy_replacement:
        # A reused pane must not retain its previous source's V2 descriptor.
        component.v2_descriptor = descriptor
        response = CustomProbeResponse(
            "dataset",
            CustomProbeDescriptor(
                "revision",
                "1",
                CustomDataset(text, text, metric.unit, "sum"),
                CustomCapabilities(
                    (dimension,),
                    (),
                    {"ranking": CustomChartCapability(("day",), (None, "provider"), ())},
                ),
                {},
                (),
            ),
        )
    else:
        response = V2ProbeResponse("dataset", descriptor)
    future = Future()
    future.set_result(
        CustomOutcome(0, result=SimpleNamespace(custom_response=response), purpose="probe")
    )
    pane.lifecycle.request(
        LifecycleTrigger.STARTUP, generation=0, now=0, start=lambda token: (future, lambda: None)
    )
    declarations = []
    original_intent = queries.custom_historical_query_intent

    def capture_intent(*args, **kwargs):
        declarations.append(kwargs["partition_declared"])
        return original_intent(*args, **kwargs)

    def follow_up(session, index, *, trigger, data_affecting):
        assert pane.probe_complete
        pane.lifecycle.request(
            trigger,
            generation=0,
            now=0,
            start=lambda token: queries.start_custom_submission(session, pane, token),
        )

    monkeypatch.setattr(queries, "custom_historical_query_intent", capture_intent)
    monkeypatch.setattr(queries, "refresh", follow_up)
    monkeypatch.setattr(
        "ccusage_viz.datasets.service.DatasetService.update_runtime_probe", lambda *args: None
    )
    try:
        assert completion.collect(session)
        assert component.error is None
        assert declarations == [not legacy_replacement]
        assert len(submitted) == 1
        assert component.v2_descriptor is (None if legacy_replacement else descriptor)
    finally:
        pane.lifecycle.shutdown()
