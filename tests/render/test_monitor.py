from dataclasses import replace
from datetime import datetime

import plotext as plt
import pytest

from ccusage_viz.chart_models import (
    MetricDescriptor,
    ObservedScope,
    RankingModel,
    ScalarRankingEntry,
    ScalarSeries,
    TimelineModel,
)
from ccusage_viz.formatting import display_width, strip_ansi
from ccusage_viz.i18n import load_translator
from ccusage_viz.render.base import (
    RenderAudit,
    RenderContext,
    audit_row_visible,
    observed_start_marker,
    render_audit,
)
from ccusage_viz.render.observation import render_observation
from ccusage_viz.render.ranking import render_ranking
from ccusage_viz.render.surfaces import (
    SurfacePresentation,
    dashboard_pane_surface,
    standalone_surface,
)
from ccusage_viz.render.timeline import render_timeline
from ccusage_viz.terminal import Terminal

from .helpers import context


def test_detailed_surfaces_do_not_reserve_empty_audit_rows() -> None:
    presentation = SurfacePresentation(
        "timeline",
        "no-color",
        "linear",
        "below-title",
        "detailed",
        "show",
        "14d",
        "Total",
        None,
        None,
        None,
        None,
    )
    terminal = Terminal(80, 20, color=False, ascii=True)

    standalone = standalone_surface("timeline").context(
        terminal, load_translator("en"), presentation
    )
    dashboard = dashboard_pane_surface("timeline").context(
        terminal, load_translator("en"), presentation
    )

    assert standalone.height == 19
    assert dashboard.height == 20


def test_observed_monitor_heading_marks_only_query_pending_candidates() -> None:
    model = TimelineModel(
        (),
        (),
        observed_at=(datetime(2026, 1, 1, 10, 0),),
        observed_series=(ScalarSeries("Total", "Total", (1000.0,)),),
        metric=MetricDescriptor("tpm"),
        observed_scope=ObservedScope(900, "total", "sampling"),
    )

    querying = render_timeline(
        model, replace(context(), audit=RenderAudit(querying=True), pending=True)
    )
    refreshing = render_timeline(model, replace(context(), audit=RenderAudit(refreshing=True)))

    assert "querying" in querying
    assert "refreshing" not in refreshing


def test_observed_timeline_uses_wall_clock_axis_and_metric_heading() -> None:
    model = TimelineModel(
        (),
        (),
        observed_at=(datetime(2026, 1, 1, 10, 0), datetime(2026, 1, 1, 10, 5)),
        observed_series=(ScalarSeries("Total", "Total", (1000.0, 2500.0)),),
        metric=MetricDescriptor("tpm"),
        observed_scope=ObservedScope(900, "total"),
    )

    output = render_timeline(model, context(True))

    assert "TPM · Trend · 15m window" in output
    assert "10:00" in output and "10:05" in output
    assert "2026-01-01" not in output


def test_observed_start_marker_is_density_aware_and_time_anchored() -> None:
    points = (
        datetime(2026, 1, 1, 10, 0),
        datetime(2026, 1, 1, 10, 5),
        datetime(2026, 1, 1, 10, 10),
    )
    started_at = datetime(2026, 1, 1, 10, 2)

    render_context = replace(context(), width=140)
    full = observed_start_marker(points, started_at=started_at, context=render_context)
    compact = observed_start_marker(
        points, started_at=started_at, context=replace(render_context, density="compact")
    )
    minimal = observed_start_marker(
        points, started_at=started_at, context=replace(render_context, density="minimal")
    )

    assert full is not None
    assert full.position == pytest.approx(0.4)
    assert full.label == "Monitor started 10:02"
    assert compact is not None
    assert compact.label == "Started 10:02"
    assert minimal is not None
    assert minimal.label is None
    assert (
        observed_start_marker(points, started_at=datetime(2026, 1, 1, 9, 59), context=context())
        is None
    )


def test_observed_timeline_labels_visible_monitor_start_by_density() -> None:
    model = TimelineModel(
        (),
        (),
        observed_at=(
            datetime(2026, 1, 1, 10, 0),
            datetime(2026, 1, 1, 10, 5),
            datetime(2026, 1, 1, 10, 10),
        ),
        monitor_started_at=datetime(2026, 1, 1, 10, 2),
        observed_series=(ScalarSeries("Total", "Total", (1000.0, 1500.0, 2000.0)),),
        metric=MetricDescriptor("tpm"),
        observed_scope=ObservedScope(900, "total"),
    )

    full = render_timeline(model, replace(context(), width=140, density="full"))
    detailed = render_timeline(model, replace(context(), width=140, density="detailed"))
    compact = render_timeline(model, replace(context(), width=140, density="compact"))
    minimal = render_timeline(model, replace(context(), width=140, density="minimal"))

    assert "Monitor started 10:02" in full
    assert "Monitor started 10:02" in detailed
    assert "Started 10:02" in compact
    assert "Monitor started 10:02" not in minimal
    assert "Started 10:02" not in minimal


def test_observed_timeline_overlays_a_thin_start_marker_without_plotext_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = TimelineModel(
        (),
        (),
        observed_at=(
            datetime(2026, 1, 1, 10, 0),
            datetime(2026, 1, 1, 10, 5),
            datetime(2026, 1, 1, 10, 10),
        ),
        monitor_started_at=datetime(2026, 1, 1, 10, 2),
        observed_series=(ScalarSeries("Total", "Total", (1000.0, 1500.0, 2000.0)),),
        metric=MetricDescriptor("tpm"),
        observed_scope=ObservedScope(900, "total"),
    )

    monkeypatch.setattr(plt.figure, "line", lambda *args, **kwargs: pytest.fail("line called"))
    unicode = render_timeline(model, replace(context(), width=100, density="minimal"))
    ascii = render_timeline(model, replace(context(ascii=True), width=100, density="minimal"))

    assert unicode.count("┆") > 4
    assert "┆" not in ascii
    assert ascii.count(":") > 4


def test_observed_timeline_renders_sampling_state_inline_and_muted() -> None:
    model = TimelineModel(
        (),
        (),
        observed_at=(datetime(2026, 1, 1, 10, 0),),
        observed_series=(ScalarSeries("Total", "Total", (0.0,)),),
        metric=MetricDescriptor("tpm"),
        observed_scope=ObservedScope(900, "total", "sampling"),
    )

    output = render_timeline(
        model,
        RenderContext(80, 24, load_translator("en"), color=True, ascii=True),
    )
    ready = render_timeline(
        replace(model, observed_scope=ObservedScope(900, "total", "ready")),
        RenderContext(80, 24, load_translator("en"), color=False, ascii=True),
    )

    heading = output.splitlines()[0]
    assert strip_ansi(heading).strip().endswith("(sampling)")
    assert "\x1b[2m" in heading
    assert "(ready)" not in ready.splitlines()[0]


@pytest.mark.parametrize(
    ("density", "current"),
    [
        ("minimal", False),
        ("compact", False),
        ("full", True),
        ("detailed", True),
    ],
)
def test_monitor_density_controls_current_observation(
    density: str,
    current: bool,
) -> None:
    model = TimelineModel(
        (),
        (),
        observed_at=(datetime(2026, 1, 1, 10, 0),),
        observed_series=(ScalarSeries("Total", "Total", (1200.0,)),),
        metric=MetricDescriptor("tpm"),
        observed_scope=ObservedScope(900, "total"),
        observed_current=(ScalarRankingEntry("Total", "Total", 1200.0),),
    )
    render_context = RenderContext(
        80,
        24,
        load_translator("en"),
        color=False,
        density=density,
    )

    output = render_observation(model, render_context)

    assert ("observed · Total 1.2K TPM" in output) is current
    assert "vs " not in output


def test_detailed_audit_uses_host_supplied_sample_cadence() -> None:
    output = render_audit(
        RenderContext(
            80,
            24,
            load_translator("en"),
            color=False,
            density="detailed",
            audit=RenderAudit(
                datetime(2026, 1, 1, 10, 5),
                0.25,
                15,
                "sample",
            ),
        )
    )

    assert output == "updated 10:05:00 · ccusage 0.25s · sample every 15s"


def test_detailed_audit_appends_localized_muted_refreshing_suffix() -> None:
    audit = RenderAudit(datetime(2026, 1, 1, 10, 5), 0.25, 15, "sample", refreshing=True)
    plain = render_audit(
        RenderContext(80, 24, load_translator("en"), color=False, density="detailed", audit=audit)
    )
    colored = render_audit(
        RenderContext(80, 24, load_translator("en"), density="detailed", audit=audit)
    )
    chinese = render_audit(
        RenderContext(80, 24, load_translator("zh"), color=False, density="detailed", audit=audit)
    )

    assert plain == "updated 10:05:00 · ccusage 0.25s · sample every 15s · refreshing"
    assert strip_ansi(colored) == plain
    assert "\x1b[2m" in colored
    assert "\n" not in colored
    assert chinese.endswith(" · 刷新中")


@pytest.mark.parametrize(
    ("density", "audit", "visible"),
    (
        ("detailed", RenderAudit(), False),
        ("detailed", RenderAudit(querying=True), False),
        ("detailed", RenderAudit(accepted_at=datetime(2026, 1, 1)), True),
        ("detailed", RenderAudit(query_elapsed=0.25), True),
        ("detailed", RenderAudit(interval=60), True),
        ("detailed", RenderAudit(refreshing=True), True),
        ("full", RenderAudit(interval=60), False),
        ("compact", RenderAudit(interval=60), False),
        ("minimal", RenderAudit(interval=60), False),
    ),
)
def test_audit_row_visibility_matches_rendered_footer(
    density: str, audit: RenderAudit, visible: bool
) -> None:
    context = RenderContext(
        80, 24, load_translator("en"), color=False, density=density, audit=audit
    )

    assert audit_row_visible(density, audit) is visible
    assert bool(render_audit(context)) is visible


@pytest.mark.parametrize("density", ("minimal", "compact", "full"))
def test_non_detailed_audit_hides_refreshing_suffix(density: str) -> None:
    output = render_audit(
        RenderContext(
            80,
            24,
            load_translator("en"),
            color=False,
            density=density,
            audit=RenderAudit(refreshing=True),
        )
    )

    assert output == ""


def test_monitor_titles_use_metric_view_dimension_and_factual_window() -> None:
    model_ranking = RankingModel(
        (),
        None,
        observed_entries=(ScalarRankingEntry("opus", "Opus", 1200.0),),
        metric=MetricDescriptor("tpm"),
        observed_scope=ObservedScope(3600, "model"),
    )
    project_timeline = TimelineModel(
        (),
        (),
        observed_at=(datetime(2026, 1, 1, 10, 0),),
        observed_series=(ScalarSeries("app", "App", (1000.0,)),),
        metric=MetricDescriptor("tokens"),
        observed_scope=ObservedScope(3600, "project"),
    )

    assert "TPM · Ranking · by Model · 1h window" in render_ranking(model_ranking, context(True))
    assert "Tokens · Trend · by Project · 1h window" in render_timeline(
        project_timeline, context(True)
    )


def test_monitor_list_is_centered_and_omits_bar_tracks() -> None:
    model = RankingModel(
        (),
        None,
        observed_entries=(
            ScalarRankingEntry("alpha", "Alpha", 1200.0),
            ScalarRankingEntry("beta", "Beta", 800.0),
        ),
        metric=MetricDescriptor("tokens"),
        observed_scope=ObservedScope(900, "model"),
    )
    render_context = RenderContext(
        80,
        24,
        load_translator("en"),
        color=False,
        ascii=True,
        style="list",
        deltas={"alpha": 1.0, "beta": -1.0},
        rank_deltas={"alpha": 1, "beta": -1},
    )

    output = render_ranking(model, render_context)
    rows = output.splitlines()[-2:]

    assert all("#" not in row for row in rows)
    assert "1.2K" in rows[0] and "800" in rows[1]
    assert "^" in rows[0] and "v" in rows[1]
    assert all(
        abs((80 - display_width(row.lstrip())) // 2 - (len(row) - len(row.lstrip()))) <= 1
        for row in rows
    )
    assert all(display_width(line) <= 80 for line in output.splitlines())
