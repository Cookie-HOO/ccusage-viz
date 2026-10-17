from __future__ import annotations

from collections.abc import Hashable
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

from ccusage_viz.adjustment_timeout import AdjustmentIdleTimer
from ccusage_viz.animation import AnimationRenderer, AnimationSessionState
from ccusage_viz.animation_overlay import (
    AnimationOverlayRuntime,
    OverlayHistoryTableState,
    OverlayPlacement,
)
from ccusage_viz.builtin_summary import BuiltinPaneSummary
from ccusage_viz.coverage import DateCoverage
from ccusage_viz.custom_component import CustomHistoricalComponent
from ccusage_viz.custom_models import V2HistoricalChartCapability, V2MetricDescriptor
from ccusage_viz.custom_monitor_component import CustomMonitorComponent
from ccusage_viz.custom_protocol.responses import CustomSummaryResponse, V2SummaryResponse
from ccusage_viz.data_view import BodyView
from ccusage_viz.domain import UsageRecord
from ccusage_viz.errors import UsageError
from ccusage_viz.historical_component import (
    HistoricalChartComponent,
    HistoricalCompletion,
    HistoricalPurpose,
    UsageSnapshot,
)
from ccusage_viz.lifecycle import FixedIntervalScheduler, LifecycleOperation
from ccusage_viz.monitor_component import MonitorCompletion, MonitorComponent
from ccusage_viz.options import (
    ChartPaneConfig,
    CustomChartConfig,
    CustomChartPaneConfig,
    CustomCommandSource,
    DashboardLaunch,
    HistoricalChartConfig,
    ProcessConfig,
    StandaloneLaunch,
)
from ccusage_viz.processing.summaries import SummaryQueryPlan
from ccusage_viz.query.models import ProviderResult
from ccusage_viz.query.runtime import QueryRuntime
from ccusage_viz.render.grouped_ranking_viewport import GroupedRankingViewport
from ccusage_viz.render.ranking_viewport import RankingViewport


@dataclass(frozen=True, slots=True)
class HistoricalOutcome:
    generation: int
    purpose: HistoricalPurpose = HistoricalPurpose.PRIMARY
    completion: HistoricalCompletion | None = None
    error: BaseException | None = None


@dataclass(frozen=True, slots=True)
class MonitorOutcome:
    generation: int
    completion: MonitorCompletion | None = None
    error: BaseException | None = None


@dataclass(frozen=True, slots=True)
class MonitorWarmupOutcome:
    generation: int
    completions: tuple[MonitorCompletion, ...] = ()
    error: BaseException | None = None


PaneFuture = Future[HistoricalOutcome] | Future[MonitorOutcome] | Future[MonitorWarmupOutcome]


@dataclass(frozen=True, slots=True)
class BuiltinSummaryOutcome:
    generation: int
    plan: SummaryQueryPlan
    chart: HistoricalChartConfig
    result: ProviderResult | None = None
    error: BaseException | None = None


@dataclass(slots=True)
class TuiEmptyPane:
    pane_id: int = -1


@dataclass(frozen=True, slots=True)
class CustomOutcome:
    generation: int
    result: ProviderResult | None = None
    error: BaseException | None = None
    purpose: Literal["probe", "primary", "comparison"] = "primary"
    comparison_request_config: CustomChartConfig | None = None


@dataclass(frozen=True, slots=True)
class CustomLogRecord:
    timestamp: datetime
    status: str
    detail: str


@dataclass(slots=True)
class RankingSearchState:
    """Ephemeral local filter state for one Dashboard historical Ranking pane."""

    query: str = ""
    editing: bool = False
    density_notice: str | None = None


@dataclass(slots=True)
class TuiCustomPane:
    component: CustomHistoricalComponent | CustomMonitorComponent
    scheduler: FixedIntervalScheduler
    lifecycle: LifecycleOperation[Future[CustomOutcome]]
    process: ProcessConfig
    summary: CustomDashboardSummary | None = None
    probe_complete: bool = False
    pane_id: int = -1
    logs: list[CustomLogRecord] = field(default_factory=list)
    body_view: BodyView = "chart"
    text_offsets: dict[BodyView, int] = field(default_factory=dict)
    text_line_counts: dict[BodyView, int] = field(default_factory=dict)
    text_visible_rows: dict[BodyView, int] = field(default_factory=dict)
    error_offset: int = 0
    error_line_count: int = 0
    error_visible_rows: int = 0
    attachment: AnimationSessionState | None = None
    attachment_renderer: AnimationRenderer | None = None
    attachment_enabled: bool = False
    ranking_copy_rows: dict[int, tuple[object, int, int | None]] = field(default_factory=dict)
    copied_ranking_entry_id: object | None = None
    copied_ranking_until: float = 0.0
    copied_ranking_all_until: float = 0.0
    ranking_search: RankingSearchState = field(default_factory=RankingSearchState)
    ranking_item_spacing: str = "compact"
    ranking_viewport: RankingViewport = field(default_factory=RankingViewport)
    grouped_ranking_viewport: GroupedRankingViewport = field(default_factory=GroupedRankingViewport)

    @property
    def active_ranking_viewport(self) -> RankingViewport | GroupedRankingViewport:
        return (
            self.grouped_ranking_viewport
            if self.grouped_ranking_viewport.active
            else self.ranking_viewport
        )

    @property
    def interval(self) -> float:
        return self.scheduler.interval


@dataclass(slots=True)
class TuiChartPane:
    component: HistoricalChartComponent | MonitorComponent
    scheduler: FixedIntervalScheduler
    lifecycle: LifecycleOperation[PaneFuture]
    summary_lifecycle: LifecycleOperation[Future[BuiltinSummaryOutcome]] | None = None
    summary: BuiltinPaneSummary | None = None
    summary_error: BaseException | None = None
    summary_generation: int = 0
    pane_id: int = -1
    demo_ordinal: int = 0
    demo_warmed_generation: int | None = None
    render_warning: UsageError | None = None
    last_render: PaneRender | None = None
    body_view: BodyView = "chart"
    text_offsets: dict[BodyView, int] = field(default_factory=dict)
    text_line_counts: dict[BodyView, int] = field(default_factory=dict)
    text_visible_rows: dict[BodyView, int] = field(default_factory=dict)
    previous_values: dict[Hashable, float] = field(default_factory=dict)
    deltas: dict[Hashable, float] = field(default_factory=dict)
    values_initialized: bool = False
    previous_ranks: dict[Hashable, int] = field(default_factory=dict)
    rank_deltas: dict[Hashable, int] = field(default_factory=dict)
    attachment: AnimationSessionState | None = None
    attachment_renderer: AnimationRenderer | None = None
    attachment_enabled: bool = False
    ranking_search: RankingSearchState = field(default_factory=RankingSearchState)

    @property
    def interval(self) -> float:
        return _pane_options(self).host.interval


@dataclass(slots=True)
class TuiAnimationPane:
    """A render-only dashboard pane; it owns no provider or lifecycle runtime."""

    session: AnimationSessionState
    renderer: AnimationRenderer
    overlay: AnimationOverlayRuntime
    pane_id: int = -1
    body_view: BodyView = "chart"
    text_offsets: dict[BodyView, int] = field(default_factory=dict)
    text_line_counts: dict[BodyView, int] = field(default_factory=dict)
    text_visible_rows: dict[BodyView, int] = field(default_factory=dict)


TuiPane = TuiChartPane | TuiAnimationPane | TuiCustomPane | TuiEmptyPane


@dataclass(slots=True)
class HelpOverlayState:
    """The active Help context while preserving the underlying modal state."""

    timer: AdjustmentIdleTimer
    adjustment_remaining: float | None
    context: str = "dashboard"
    action: str | None = None
    selected: str | None = None
    dataset_id: str | None = None
    chart_kind: str | None = None
    scroll_offset: int = 0


@dataclass(slots=True)
class OverlayEditorState:
    """Uncommitted source drafts displayed within one Dashboard animation pane."""

    pane_index: int
    mode: str
    text_draft: str
    command_draft: str
    text_cursor: int | None = None
    command_cursor: int | None = None

    def __post_init__(self) -> None:
        self.text_cursor = len(self.text_draft) if self.text_cursor is None else self.text_cursor
        self.command_cursor = (
            len(self.command_draft) if self.command_cursor is None else self.command_cursor
        )

    @property
    def draft(self) -> str:
        return self.command_draft if self.mode == "command" else self.text_draft

    @property
    def cursor(self) -> int:
        cursor = self.command_cursor if self.mode == "command" else self.text_cursor
        assert cursor is not None
        return cursor

    @cursor.setter
    def cursor(self, value: int) -> None:
        if self.mode == "command":
            self.command_cursor = value
        else:
            self.text_cursor = value

    def replace_draft(self, value: str) -> None:
        if self.mode == "command":
            self.command_draft = value
        else:
            self.text_draft = value


@dataclass(slots=True)
class OverlayHistoryState:
    """Command-history table displayed within one Dashboard animation pane."""

    pane_index: int
    table: OverlayHistoryTableState = field(default_factory=OverlayHistoryTableState)


@dataclass(slots=True)
class DashboardDatasetModalState:
    """One nonblocking Dashboard Dataset selection transaction."""

    action: str
    pane_index: int
    initial: CustomChartConfig | None
    statuses: tuple[object, ...]
    service: object
    stage: str = "pane"
    index: int = 0
    offset: int = 0
    draft: CustomPaneDraft = field(default_factory=lambda: CustomPaneDraft())
    error: str | None = None
    future: Future[object] | None = None
    pending_dataset_id: str | None = None
    entries: tuple[object, ...] = ()
    selected_dataset_id: str | None = None
    artifact: object | None = None
    official_preview: tuple[object, bytes, object] | None = None
    chart_kinds: tuple[str, ...] = ()
    metrics: tuple[object, ...] = ()
    metric_id: str | None = None
    metric_summary: str = "comparisons"
    metric_periods: tuple[str, ...] = ()
    metric_titles: tuple[str, str] | None = None


def _custom_metric_periods(metric: V2MetricDescriptor, kind: str) -> tuple[str, ...]:
    """Return the periods declared for one Metric's selected historical chart."""

    capability = metric.capabilities.charts.get(kind)
    return capability.periods if isinstance(capability, V2HistoricalChartCapability) else ()


@dataclass(frozen=True, slots=True)
class MetricChooserRow:
    """One presentation row in the V2 Dataset Metric chooser."""

    kind: Literal["group", "metric", "description"]
    text: str
    metric_index: int | None = None


_DOUBLE_CLICK_SECONDS = 0.35


def _pane_options(pane: TuiChartPane) -> StandaloneLaunch:
    component = pane.component
    return component.accepted_options or component.candidate


def _pane_display_options(pane: TuiChartPane) -> StandaloneLaunch:
    component = pane.component
    if isinstance(component, HistoricalChartComponent) and getattr(component, "is_pending", False):
        return component.candidate
    if (
        isinstance(component, MonitorComponent)
        and component.candidate != component.accepted_options
    ):
        return component.candidate
    return _pane_options(pane)


def _chart_pane_config(pane: TuiChartPane) -> ChartPaneConfig:
    chart = _pane_options(pane).chart
    assert not isinstance(chart, CustomChartConfig)
    return ChartPaneConfig(chart)


def _custom_pane_options(dashboard: DashboardLaunch, pane: TuiCustomPane) -> StandaloneLaunch:
    from ccusage_viz.configuration import standalone_from_chart_pane

    chart = pane.component.accepted_config or pane.component.candidate
    return standalone_from_chart_pane(dashboard, CustomChartPaneConfig(chart))


@dataclass(slots=True)
class CustomDashboardSummary:
    """Per-dataset accepted state for one Header-owned source summary."""

    source: CustomCommandSource
    scheduler: FixedIntervalScheduler
    lifecycle: LifecycleOperation[Future[CustomOutcome]]
    filters: tuple[tuple[str, tuple[str, ...]], ...] = ()
    response: CustomSummaryResponse | V2SummaryResponse | None = None
    error: BaseException | None = None
    generation: int = 0
    accepted_at: datetime | None = None
    accepted_period: str | None = None
    accepted_as_of_date: date | None = None
    requested_period: str | None = None
    requested_as_of_date: date | None = None
    metric_id: str | None = None
    summary_mode: str = "comparisons"

    def select(
        self, source: CustomCommandSource, filters: tuple[tuple[str, tuple[str, ...]], ...]
    ) -> None:
        """Adopt the first visible Pane source only at a Header refresh boundary."""
        self.source = source
        self.filters = filters

    def invalidate(self) -> None:
        """Discard facts that no longer describe the selected summary query."""
        self.generation += 1
        self.lifecycle.detach_active()
        self.response = None
        self.error = None
        self.accepted_at = None
        self.accepted_period = None
        self.accepted_as_of_date = None
        self.requested_period = None
        self.requested_as_of_date = None


@dataclass(frozen=True, slots=True)
class CustomDashboardSource:
    """A Dataset source selected once per Header summary."""

    source: CustomCommandSource
    config: CustomChartConfig | None = field(default=None, compare=False)
    summary_mode: str = "comparisons"


@dataclass(slots=True)
class DashboardHeader:
    options: StandaloneLaunch
    runtime: QueryRuntime
    scheduler: FixedIntervalScheduler
    lifecycle: LifecycleOperation[Future[UsageSnapshot]]
    snapshot: UsageSnapshot | None = None
    error: str | None = None
    generation: int = 0
    records: tuple[UsageRecord, ...] = ()
    coverage: DateCoverage = field(default_factory=DateCoverage)
    accepted_at: datetime | None = None
    summary_period: str = "day"
    token_enabled: bool = True
    custom_summaries: dict[str, CustomDashboardSummary] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PaneLayout:
    """The exact cell geometry shared by rendering and pointer hit testing."""

    widths: tuple[int, ...]
    heights: tuple[int, ...]
    gutter: int

    @property
    def width(self) -> int:
        return sum(self.widths) + self.gutter * (len(self.widths) - 1)

    @property
    def height(self) -> int:
        return sum(self.heights) + self.gutter * (len(self.heights) - 1)


@dataclass(frozen=True, slots=True)
class PaneRender:
    chart: str
    notices: tuple[str, ...] = ()
    overlay_placements: tuple[OverlayPlacement, ...] = ()
    error_body: bool = False


@dataclass(frozen=True, slots=True)
class DashboardOverlayPlacement:
    source_index: int
    placement: OverlayPlacement


@dataclass(slots=True)
class CustomPaneDraft:
    kind: str = "timeline"
    dataset_id: str = ""
    command: str = ""
    field: int = 0
