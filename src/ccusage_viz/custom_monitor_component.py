"""Lifecycle and source-native projections for Dataset V2 Monitor observations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta, tzinfo
from decimal import Decimal
from math import isfinite

from ccusage_viz.chart_models import (
    DistributionCoverage,
    MetricDescriptor,
    ObservedScope,
    RankingModel,
    ScalarRankingEntry,
    ScalarSeries,
    TimelineModel,
    TimeOfDayBucket,
    TimeOfDayDistributionModel,
    TimeOfDaySeries,
)
from ccusage_viz.custom_models import (
    CustomUnit,
    LocalizedText,
    V2HistoricalChartCapability,
    V2MetricCapabilities,
    V2MetricDescriptor,
    V2MonitorCapability,
    V2MonitorObservation,
    V2ProbeDescriptor,
    V2Runtime,
)
from ccusage_viz.custom_protocol import V2MonitorResponse
from ccusage_viz.options import CustomChartConfig, compatible_styles
from ccusage_viz.render.palette import COLOR_SCHEMES

# This is deliberately the largest local window offered by the Dashboard, rather
# than a query range.  Dataset Monitor requests remain source-owned.
_MAX_DISPLAY_WINDOW_SECONDS = 86_400


def custom_monitor_y_axis_max(values: list[float]) -> float:
    """Return a non-degenerate upper bound for source-owned Monitor timelines."""

    maximum = max(values, default=0.0)
    if not isfinite(maximum) or maximum <= 0:
        return 1.0
    return maximum


def custom_monitor_styles(aggregation: str, group_by: str | None = None) -> tuple[str, ...]:
    """Return the complete source-safe Monitor style cycle for an aggregation."""
    styles = ("bars", "line", "step", "points", "line-points", "ranking", "list")
    if group_by is not None:
        styles = tuple(style for style in styles if style != "bars")
    return (*styles, "cumulative-bars") if aggregation == "sum" else styles


def normalize_custom_monitor_style(
    config: CustomChartConfig, aggregation: str
) -> CustomChartConfig:
    """Normalize persisted presentation state against a metric's aggregation."""
    styles = custom_monitor_styles(aggregation, config.group_by)
    style = config.presentation.style
    if style in styles:
        return config
    # A value metric restored from a sum metric's state must not silently imply
    # accumulation; ranking is the nearest non-temporal presentation.
    fallback = "ranking" if style == "cumulative-bars" else styles[0]
    return replace(config, presentation=replace(config.presentation, style=fallback))


@dataclass(frozen=True, slots=True)
class CustomMonitorCompletion:
    generation: int
    config: CustomChartConfig
    response: V2MonitorResponse


@dataclass(frozen=True, slots=True)
class CustomMonitorPresentation:
    """Source-declared metadata needed to present Monitor observations."""

    title: LocalizedText
    description: LocalizedText
    unit: CustomUnit
    aggregation: str
    capability: V2MonitorCapability


@dataclass(frozen=True, slots=True)
class CustomMonitorSeries:
    key: str
    label: LocalizedText | None
    values: tuple[Decimal | None, ...]


@dataclass(frozen=True, slots=True)
class CustomMonitorPoint:
    """One plotted source-window endpoint; ``None`` preserves an actual gap."""

    ended_at: datetime
    observation: V2MonitorObservation | None


@dataclass(frozen=True, slots=True)
class CustomMonitorTimeline:
    points: tuple[CustomMonitorPoint, ...]
    series: tuple[CustomMonitorSeries, ...]


@dataclass(frozen=True, slots=True)
class CustomMonitorRankingEntry:
    key: str
    label: LocalizedText | None
    value: Decimal


@dataclass(frozen=True, slots=True)
class CustomMonitorRanking:
    entries: tuple[CustomMonitorRankingEntry, ...]


class CustomMonitorComponent:
    """Keep source-owned Monitor facts without adapting them into token facts."""

    __slots__ = (
        "accepted_at",
        "accepted_config",
        "accepted_response",
        "aggregation",
        "candidate",
        "capability",
        "display_window_seconds",
        "display_timezone",
        "distribution_day_window",
        "error",
        "generation",
        "history",
        "monitor_started_at",
        "presentation",
        "render_revision",
        "runtime",
        "v2_descriptor",
    )

    def __init__(self, config: CustomChartConfig) -> None:
        if config.kind != "monitor":
            raise ValueError("custom monitor component requires a monitor configuration")
        self.candidate = config
        self.aggregation = "sum"
        self.capability: V2MetricCapabilities | None = None
        self.presentation: CustomMonitorPresentation | None = None
        self.display_window_seconds = 3600
        self.display_timezone: tzinfo | None = None
        self.distribution_day_window: str = "today"
        self.accepted_config: CustomChartConfig | None = None
        self.accepted_response: V2MonitorResponse | None = None
        self.accepted_at: datetime | None = None
        self.error: BaseException | None = None
        self.generation = 0
        self.history: list[V2MonitorResponse] = []
        self.monitor_started_at: datetime | None = None
        self.render_revision = 0
        self.runtime: V2Runtime | None = None
        self.v2_descriptor: V2ProbeDescriptor | None = None

    @property
    def pending(self) -> bool:
        return self.accepted_config != self.candidate

    @property
    def accepted_activity_total(self) -> Decimal | None:
        """Return the latest Dataset-owned observation total for Monitor attachments."""
        return (
            self.accepted_response.observation.total if self.accepted_response is not None else None
        )

    @property
    def monitor_capability(self) -> V2MonitorCapability | None:
        """Return the selected metric's Monitor declaration, if probe resolution completed."""
        return self.presentation.capability if self.presentation is not None else None

    def configure(self, config: CustomChartConfig, *, data_affecting: bool) -> None:
        if config.kind != "monitor":
            raise ValueError("custom monitor component requires a monitor configuration")
        if config == self.candidate:
            return
        self.candidate = config
        if data_affecting:
            self.generation += 1
            self.error = None
            self.history.clear()
        elif self.accepted_config is not None:
            self.accepted_config = config
        self.render_revision += 1

    def set_capability(self, capability: V2MetricCapabilities, *, aggregation: str = "sum") -> None:
        """Retain capability compatibility for callers that do not have a metric descriptor."""
        monitor = capability.charts.get("monitor")
        if not isinstance(monitor, V2MonitorCapability):
            raise ValueError("custom monitor metric is missing its monitor capability")
        self.capability = capability
        self.aggregation = aggregation
        # A descriptor will replace this placeholder during normal V2 probe handling.
        if self.presentation is not None:
            self.presentation = replace(
                self.presentation, aggregation=aggregation, capability=monitor
            )
        self.render_revision += 1

    def set_metric(self, metric: V2MetricDescriptor) -> None:
        """Set the selected metric's complete source-declared presentation metadata."""
        monitor = metric.capabilities.charts.get("monitor")
        if not isinstance(monitor, V2MonitorCapability):
            raise ValueError("custom monitor metric is missing its monitor capability")
        self.capability = metric.capabilities
        self.aggregation = metric.aggregation
        if metric.aggregation != "sum" and self.candidate.presentation.style == "cumulative-bars":
            self.candidate = normalize_custom_monitor_style(self.candidate, metric.aggregation)
            if self.accepted_config is not None:
                self.accepted_config = normalize_custom_monitor_style(
                    self.accepted_config, metric.aggregation
                )
        self.presentation = CustomMonitorPresentation(
            metric.title,
            metric.description,
            metric.unit,
            metric.aggregation,
            monitor,
        )
        self.render_revision += 1

    def configure_display_window(self, window_seconds: int) -> None:
        """Change local Monitor retention without changing the Dataset request."""
        if window_seconds <= 0:
            raise ValueError("custom monitor display window must be positive")
        if window_seconds == self.display_window_seconds:
            return
        self.display_window_seconds = window_seconds
        self._prune_history()
        self.render_revision += 1

    def configure_display_timezone(self, timezone: tzinfo) -> None:
        """Set the host's local display timezone without changing Dataset requests."""

        if timezone == self.display_timezone:
            return
        self.display_timezone = timezone
        self.render_revision += 1

    def toggle_distribution_day_window(self) -> None:
        """Switch the cumulative projection between the local current and prior day."""

        self.distribution_day_window = (
            "yesterday" if self.distribution_day_window == "today" else "today"
        )
        self.render_revision += 1

    def start_monitoring(self, started_at: datetime) -> None:
        """Record the current custom Monitor session boundary for native timeline chrome."""

        if started_at.tzinfo is None:
            raise ValueError("custom monitor start time must be timezone aware")
        if self.monitor_started_at is None:
            self.monitor_started_at = started_at
            self.render_revision += 1

    def accept(self, completion: CustomMonitorCompletion, *, accepted_at: datetime) -> bool:
        if completion.generation != self.generation or completion.config != self.candidate:
            return False
        if (
            self.candidate.metric_id is not None
            and completion.response.metric_id != self.candidate.metric_id
        ):
            return False
        descriptor = completion.response.descriptor
        if descriptor is not None:
            metric = next(
                (item for item in descriptor.metrics if item.id == completion.response.metric_id),
                None,
            )
            if metric is None or not isinstance(
                metric.capabilities.charts.get("monitor"), V2MonitorCapability
            ):
                return False
            self.set_metric(metric)
            self.v2_descriptor = descriptor
        self.runtime = completion.response.runtime
        self.accepted_config = completion.config
        self.accepted_response = completion.response
        self.accepted_at = accepted_at
        endpoint = completion.response.observation.end_at
        self.history = [
            response for response in self.history if response.observation.end_at != endpoint
        ]
        self.history.append(completion.response)
        self.history.sort(key=lambda response: response.observation.end_at)
        self._prune_history()
        self.error = None
        self.render_revision += 1
        return True

    def fail(self, error: BaseException, *, generation: int) -> bool:
        if generation != self.generation:
            return False
        self.error = error
        self.render_revision += 1
        return True

    def timeline(self, *, timezone: tzinfo | None = None) -> CustomMonitorTimeline:
        """Return all source observations in the local display horizon.

        ``timezone`` affects endpoint labels only; values and their source instants
        remain unchanged and Decimal-native.
        """
        observations = self._display_observations()
        return self._timeline_from_observations(
            observations, timezone=timezone or self.display_timezone
        )

    def cumulative_timeline(self, *, timezone: tzinfo | None = None) -> CustomMonitorTimeline:
        """Return non-overlapping source windows for a sum-only cumulative bar view."""
        if self.aggregation != "sum":
            raise ValueError("cumulative monitor bars require a sum metric")
        observations = self._display_observations()
        window = timedelta(seconds=self._window_seconds())
        admitted: list[V2MonitorObservation] = []
        previous_end: datetime | None = None
        for observation in observations:
            if previous_end is None or observation.end_at >= previous_end + window:
                admitted.append(observation)
                previous_end = observation.end_at
        return self._timeline_from_observations(
            tuple(admitted), timezone=timezone or self.display_timezone
        )

    def ranking(self) -> CustomMonitorRanking:
        """Return only the latest source-owned values, without shares or comparisons."""
        response = self.accepted_response
        observation = response.observation if response is not None else None
        if observation is None:
            return CustomMonitorRanking(())
        if self.candidate.group_by is None:
            return CustomMonitorRanking(
                (CustomMonitorRankingEntry("total", None, observation.total),)
            )
        entries = tuple(
            CustomMonitorRankingEntry(group.id, group.label, group.value)
            for group in sorted(observation.groups, key=lambda item: (-item.value, item.id))
        )
        return CustomMonitorRanking(self._project_entries(entries))

    def heading(self, *, language: str) -> str:
        """Return the Dataset-owned Monitor heading shared by both product surfaces."""

        config = self.accepted_config or self.candidate
        title = (
            self._localized(self.presentation.title, language)
            if self.presentation is not None
            else (config.metric_titles[1] if language == "zh" else config.metric_titles[0])
            if config.metric_titles is not None
            else config.metric_id or config.source.dataset_id
        )
        group = self._group_label(config.group_by, language)
        return " · ".join((group, title, self._display_period_label(language)))

    def timeline_model(
        self,
        *,
        language: str,
        metric_title: str | None = None,
        timezone: tzinfo | None = None,
    ) -> TimelineModel:
        """Adapt source-owned window observations to the shared Monitor renderer model."""

        del metric_title
        timezone = timezone or self.display_timezone
        timeline = self.timeline(timezone=timezone)
        points, series = self._windowed_timeline(timeline, timezone=timezone)
        return TimelineModel(
            (),
            (),
            observed_at=points,
            monitor_started_at=(
                self.monitor_started_at.astimezone(timezone)
                if self.monitor_started_at is not None and timezone is not None
                else self.monitor_started_at
            ),
            observed_series=tuple(
                ScalarSeries(
                    item.key,
                    self._series_label(item.key, item.label, language),
                    tuple(float(value) if value is not None else None for value in item.values),
                    item.key == "Other",
                )
                for item in series
            ),
            metric=MetricDescriptor("tokens"),
            observed_scope=self._scope(),
            y_axis_max=custom_monitor_y_axis_max(
                [float(value) for item in series for value in item.values if value is not None]
            ),
            observed_current=tuple(
                ScalarRankingEntry(
                    entry.key,
                    self._series_label(entry.key, entry.label, language),
                    float(entry.value),
                )
                for entry in self.ranking().entries
            ),
        )

    def ranking_model(self, *, language: str, metric_title: str | None = None) -> RankingModel:
        """Adapt the latest source-owned values without adding native token semantics."""

        del metric_title
        return RankingModel(
            (),
            None,
            observed_entries=tuple(
                ScalarRankingEntry(
                    entry.key,
                    self._series_label(entry.key, entry.label, language),
                    float(entry.value),
                )
                for entry in self.ranking().entries
            ),
            metric=MetricDescriptor("tokens"),
            observed_scope=self._scope(),
        )

    def distribution_model(
        self,
        *,
        language: str = "en",
        metric_title: str | None = None,
        timezone: tzinfo | None = None,
    ) -> TimeOfDayDistributionModel:
        """Build cumulative source-window buckets while exposing factual observation gaps."""

        del metric_title
        if self.aggregation != "sum":
            raise ValueError("cumulative monitor bars require a sum metric")
        timezone = timezone or self.display_timezone
        observations = tuple(response.observation for response in self.history)
        if not observations:
            return TimeOfDayDistributionModel((), (), None, "today", "hour")
        source_window = timedelta(seconds=self._window_seconds())
        latest = observations[-1].end_at
        display_timezone = timezone or latest.tzinfo
        if display_timezone is None:
            raise ValueError("custom monitor observations must be timezone aware")
        latest_local = latest.astimezone(display_timezone)
        day = latest_local.date() - timedelta(days=self.distribution_day_window == "yesterday")
        first_start = datetime.combine(day, time.min, tzinfo=display_timezone)
        last_end = first_start + timedelta(days=1)
        buckets: list[TimeOfDayBucket] = []
        bucket_start = first_start
        while bucket_start < last_end:
            bucket_end = bucket_start + timedelta(hours=1)
            values: dict[str, float] = {}
            covered_seconds = 0.0
            covered_until = bucket_start
            for observation in observations:
                observed_end = observation.end_at.astimezone(display_timezone)
                observed_start = observed_end - source_window
                overlap_start = max(bucket_start, observed_start)
                overlap_end = min(bucket_end, observed_end)
                if overlap_end <= overlap_start:
                    continue
                # Dataset windows may overlap on a refresh cadence shorter than
                # their source window. Only count each interval once.
                uncovered_start = max(overlap_start, covered_until)
                if overlap_end <= uncovered_start:
                    continue
                fraction = (overlap_end - uncovered_start) / source_window
                for key, value in self._observation_values(observation).items():
                    values[key] = values.get(key, 0.0) + value * fraction
                covered_seconds += (overlap_end - uncovered_start).total_seconds()
                covered_until = overlap_end
            coverage = (
                DistributionCoverage.FULL
                if covered_seconds >= (bucket_end - bucket_start).total_seconds()
                else DistributionCoverage.PARTIAL
                if covered_seconds > 0
                else DistributionCoverage.UNOBSERVED
            )
            buckets.append(
                TimeOfDayBucket(
                    bucket_start,
                    bucket_end,
                    coverage,
                    values,
                )
            )
            bucket_start = bucket_end
        keys = tuple(dict.fromkeys(key for bucket in buckets for key in bucket.values))
        if self.candidate.group_by is None:
            keys = ("total",)
        elif self.candidate.top is not None:
            totals = {key: sum(bucket.values.get(key, 0.0) for bucket in buckets) for key in keys}
            kept = self._top_keys(totals)
            merged_buckets: list[TimeOfDayBucket] = []
            for bucket in buckets:
                values = {key: value for key, value in bucket.values.items() if key in kept}
                if self.aggregation == "sum":
                    other = sum(value for key, value in bucket.values.items() if key not in kept)
                    if other:
                        values["Other"] = other
                merged_buckets.append(
                    TimeOfDayBucket(bucket.started_at, bucket.ended_at, bucket.coverage, values)
                )
            buckets = merged_buckets
            keys = tuple(dict.fromkeys(key for bucket in buckets for key in bucket.values))
        labels = self._declared_group_labels(language)
        return TimeOfDayDistributionModel(
            tuple(buckets),
            tuple(
                TimeOfDaySeries(
                    key,
                    ("总计" if language == "zh" else "Total")
                    if key == "total"
                    else labels.get(key, key),
                    key == "Other",
                )
                for key in keys
            ),
            first_start,
            self.distribution_day_window,  # type: ignore[arg-type]
            "hour",
        )

    def _display_observations(self) -> tuple[V2MonitorObservation, ...]:
        if not self.history:
            return ()
        latest = self.history[-1].observation.end_at
        cutoff = latest - timedelta(seconds=self.display_window_seconds)
        return tuple(
            response.observation
            for response in self.history
            if response.observation.end_at >= cutoff
        )

    def _windowed_timeline(
        self, timeline: CustomMonitorTimeline, *, timezone: tzinfo | None
    ) -> tuple[tuple[datetime, ...], tuple[CustomMonitorSeries, ...]]:
        """Pad sparse Dataset observations over the entire local display horizon."""

        if not timeline.points:
            return (), ()
        interval = timedelta(seconds=self._window_seconds())
        latest = max(point.ended_at for point in timeline.points)
        first = latest - timedelta(seconds=self.display_window_seconds)
        points: list[datetime] = []
        cursor = first
        while cursor <= latest:
            points.append(cursor.astimezone(timezone) if timezone is not None else cursor)
            cursor += interval
        if points[-1].timestamp() != latest.timestamp():
            points.append(latest.astimezone(timezone) if timezone is not None else latest)
        indexes = {point.ended_at.timestamp(): index for index, point in enumerate(timeline.points)}
        padded = tuple(
            CustomMonitorSeries(
                item.key,
                item.label,
                tuple(
                    item.values[index]
                    if (index := indexes.get(point.timestamp())) is not None
                    else None
                    for point in points
                ),
            )
            for item in timeline.series
        )
        return tuple(points), self._project_timeline_series(padded)

    def _scope(self) -> ObservedScope:
        return ObservedScope(self._window_seconds(), "total")

    def _window_label(self) -> str:
        seconds = self._window_seconds()
        if seconds % 3600 == 0:
            return f"{seconds // 3600}h"
        if seconds % 60 == 0:
            return f"{seconds // 60}m"
        return f"{seconds}s"

    def _display_period_label(self, language: str) -> str:
        source = self._window_label()
        if self.candidate.presentation.style == "cumulative-bars":
            if language == "zh":
                day = "昨天" if self.distribution_day_window == "yesterday" else "今天"
                return f"{day} · 小时累计柱 · 数据窗口 {source}"
            return f"{self.distribution_day_window} · hourly cumulative bars · data window {source}"
        view = self._duration_label(self.display_window_seconds)
        return (
            f"视图 {view} · 数据窗口 {source}"
            if language == "zh"
            else f"view {view} · data window {source}"
        )

    @staticmethod
    def _duration_label(seconds: int) -> str:
        if seconds % 86400 == 0:
            return f"{seconds // 86400}d"
        if seconds % 3600 == 0:
            return f"{seconds // 3600}h"
        if seconds % 60 == 0:
            return f"{seconds // 60}m"
        return f"{seconds}s"

    @staticmethod
    def _localized(value: LocalizedText, language: str) -> str:
        return value.zh_cn if language == "zh" else value.en

    def _group_label(self, group_by: str | None, language: str) -> str:
        if group_by is None:
            return "总计" if language == "zh" else "Total"
        labels = self._declared_group_labels(language)
        return labels.get(group_by, group_by)

    def _declared_group_labels(self, language: str) -> dict[str, str]:
        capability = self.capability
        if capability is None:
            return {}
        return {
            item.id: self._localized(item.label, language)
            for item in capability.group_by
            if item.id is not None
        }

    def _series_label(self, key: str, label: LocalizedText | None, language: str) -> str:
        if key == "total":
            return "总计" if language == "zh" else "Total"
        return self._localized(label, language) if label is not None else key

    def _observation_values(self, observation: V2MonitorObservation) -> dict[str, float]:
        if self.candidate.group_by is None:
            return {"total": float(observation.total)}
        return {item.id: float(item.value) for item in observation.groups}

    def _top_keys(self, values: dict[str, Decimal | float]) -> set[str]:
        top = self.candidate.top
        if top is None or len(values) <= top:
            return set(values)
        return {
            key
            for key, _value in sorted(values.items(), key=lambda item: (-item[1], item[0]))[:top]
        }

    def _project_entries(
        self, entries: tuple[CustomMonitorRankingEntry, ...]
    ) -> tuple[CustomMonitorRankingEntry, ...]:
        if self.candidate.top is None or len(entries) <= self.candidate.top:
            return entries
        kept = self._top_keys({entry.key: entry.value for entry in entries})
        result = tuple(entry for entry in entries if entry.key in kept)
        if self.aggregation != "sum":
            return result
        other = sum((entry.value for entry in entries if entry.key not in kept), start=Decimal())
        return (
            (*result, CustomMonitorRankingEntry("Other", None, other))
            if other and self.candidate.other == "show"
            else result
        )

    def _project_timeline_series(
        self, series: tuple[CustomMonitorSeries, ...]
    ) -> tuple[CustomMonitorSeries, ...]:
        if self.candidate.top is None or len(series) <= self.candidate.top:
            return series
        totals = {
            item.key: sum((value for value in item.values if value is not None), start=Decimal())
            for item in series
        }
        kept = self._top_keys(totals)
        result = tuple(item for item in series if item.key in kept)
        if self.aggregation != "sum":
            return result
        other_values = tuple(
            sum(
                (item.values[index] or Decimal() for item in series if item.key not in kept),
                start=Decimal(),
            )
            for index in range(len(series[0].values))
        )
        return (
            (*result, CustomMonitorSeries("Other", None, other_values))
            if self.candidate.other == "show"
            else result
        )

    def _timeline_from_observations(
        self, observations: tuple[V2MonitorObservation, ...], *, timezone: tzinfo | None
    ) -> CustomMonitorTimeline:
        keys = tuple(
            dict.fromkeys(group.id for observation in observations for group in observation.groups)
        )
        labels = {
            group.id: group.label for observation in observations for group in observation.groups
        }
        if self.candidate.group_by is None:
            keys, labels = ("total",), {}
        points = tuple(
            CustomMonitorPoint(
                observation.end_at.astimezone(timezone)
                if timezone is not None
                else observation.end_at,
                observation,
            )
            for observation in observations
        )
        series = tuple(
            CustomMonitorSeries(
                key,
                None if key == "total" else labels[key],
                tuple(
                    observation.total
                    if key == "total"
                    else next(
                        (group.value for group in observation.groups if group.id == key), None
                    )
                    for observation in observations
                ),
            )
            for key in keys
        )
        return CustomMonitorTimeline(points, series)

    def _retention_seconds(self) -> int:
        capability = self.monitor_capability
        window = capability.window_seconds if capability is not None else 60
        cadence = (
            capability.refresh_interval_seconds
            if capability is not None and capability.refresh_interval_seconds is not None
            else window
        )
        # Preserve the largest selectable local horizon plus two factual source
        # intervals. This is a retention policy, never a request instruction.
        return max(_MAX_DISPLAY_WINDOW_SECONDS, self.display_window_seconds) + window + cadence

    def _prune_history(self) -> None:
        if not self.history:
            return
        latest = self.history[-1].observation.end_at
        cutoff = latest - timedelta(seconds=self._retention_seconds())
        self.history[:] = [
            response for response in self.history if response.observation.end_at >= cutoff
        ]

    def _window_seconds(self) -> int:
        capability = self.monitor_capability
        if capability is not None:
            return capability.window_seconds
        capability = self.capability.charts.get("monitor") if self.capability is not None else None
        return capability.window_seconds if isinstance(capability, V2MonitorCapability) else 60


def resolve_metric(config: CustomChartConfig, descriptor: V2ProbeDescriptor) -> CustomChartConfig:
    """Resolve an omitted Metric from a V2 Probe without guessing ambiguous sources."""
    if config.metric_id is not None:
        metric = next(
            (metric for metric in descriptor.metrics if metric.id == config.metric_id), None
        )
        if metric is None:
            raise ValueError("selected metric is not declared by runtime probe")
        chart_capability = metric.capabilities.charts.get(config.kind)
        periods = (
            chart_capability.periods
            if isinstance(chart_capability, V2HistoricalChartCapability)
            else ()
        )
        comparison = (
            chart_capability.comparison
            if isinstance(chart_capability, V2HistoricalChartCapability)
            else "full"
        )
        return replace(
            config,
            metric_summary=metric.summary,
            metric_periods=periods,
            metric_titles=(metric.title.en, metric.title.zh_cn),
            ranking_comparison=comparison,
        )
    selected = descriptor.default_metric_id
    if selected is None and len(descriptor.metrics) == 1:
        selected = descriptor.metrics[0].id
    if selected is None:
        raise ValueError("dataset declares multiple metrics; specify --metric")
    metric = next(metric for metric in descriptor.metrics if metric.id == selected)
    chart_capability = metric.capabilities.charts.get(config.kind)
    periods = (
        chart_capability.periods
        if isinstance(chart_capability, V2HistoricalChartCapability)
        else ()
    )
    comparison = (
        chart_capability.comparison
        if isinstance(chart_capability, V2HistoricalChartCapability)
        else "full"
    )
    return replace(
        config,
        metric_id=selected,
        metric_summary=metric.summary,
        metric_periods=periods,
        metric_titles=(metric.title.en, metric.title.zh_cn),
        ranking_comparison=comparison,
    )


def apply_custom_monitor_defaults(
    config: CustomChartConfig, metric: V2MetricDescriptor
) -> tuple[CustomChartConfig, int | None]:
    """Merge safe Dataset Monitor suggestions after Metric selection."""
    defaults = metric.defaults.get("monitor")
    capability = metric.capabilities.charts.get("monitor")
    if defaults is None or not isinstance(capability, V2MonitorCapability):
        return config, None
    explicit = config.initial_explicit
    group_by = config.group_by
    if (
        "group_by" not in explicit
        and (not defaults.declared or "group_by" in defaults.declared)
        and defaults.group_by in capability.group_by
    ):
        group_by = defaults.group_by
    top = config.top
    if "top" not in explicit and defaults.top is not None and group_by is not None:
        top = defaults.top
    presentation = config.presentation
    if "color_scheme" not in explicit and defaults.theme in COLOR_SCHEMES:
        presentation = replace(presentation, theme=defaults.theme)
    if "style" not in explicit and defaults.style in compatible_styles("monitor", group_by):
        presentation = replace(presentation, style=defaults.style)
    other = (
        defaults.other
        if "other" not in explicit and defaults.other is not None and metric.aggregation == "sum"
        else config.other
    )
    window = defaults.window_seconds if "window" not in explicit else None
    return (
        replace(
            config,
            filters=config.filters,
            presentation=presentation,
            group_by=group_by,
            top=top,
            other=other,
        ),
        window,
    )
