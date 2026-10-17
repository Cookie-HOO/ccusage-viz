from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time, timedelta, tzinfo
from decimal import Decimal

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
from ccusage_viz.custom_metric_switching import normalization_category, normalize_switch_config
from ccusage_viz.custom_models import (
    LocalizedText,
    V2MetricCapabilities,
    V2MetricDescriptor,
    V2MonitorCapability,
    V2MonitorObservation,
    V2ProbeDescriptor,
    V2Runtime,
)
from ccusage_viz.custom_monitor_models import (
    _MAX_DISPLAY_WINDOW_SECONDS,
    CustomMonitorCompletion,
    CustomMonitorHeadingMetadata,
    CustomMonitorPoint,
    CustomMonitorPresentation,
    CustomMonitorRanking,
    CustomMonitorRankingEntry,
    CustomMonitorSeries,
    CustomMonitorTimeline,
    custom_monitor_y_axis_max,
    normalize_custom_monitor_style,
)
from ccusage_viz.custom_protocol.responses import V2MonitorResponse
from ccusage_viz.options import CustomChartConfig, is_monitor_ranking_style


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
        "switch_normalizations",
        "switch_target_config",
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
        self.switch_target_config: CustomChartConfig | None = None
        self.switch_normalizations: frozenset[str] = frozenset()
        self.v2_descriptor: V2ProbeDescriptor | None = None

    @property
    def _display_config(self) -> CustomChartConfig:
        """Return the configuration whose semantics match the displayed facts."""

        return self.accepted_config or self.candidate

    @property
    def request_config(self) -> CustomChartConfig:
        """Return a target Metric being sampled without committing it to the pane."""

        return self.switch_target_config or self.candidate

    @property
    def pending(self) -> bool:
        return self.accepted_config != self.request_config

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

    def begin_metric_switch(self, config: CustomChartConfig) -> None:
        """Start sampling a related Metric while preserving current Monitor facts."""

        if config.kind != "monitor":
            raise ValueError("custom monitor component requires a monitor configuration")
        if config == self.candidate:
            return
        self.switch_target_config = config
        self.switch_normalizations = frozenset()
        self.generation += 1
        self.error = None
        self.render_revision += 1

    def retry_metric_switch(self, field: str, target: V2MetricDescriptor) -> bool:
        """Normalize one pending target request without discarding current observations."""

        category = normalization_category(field)
        if self.switch_target_config is None or category is None or category in self.switch_normalizations:
            return False
        updated = normalize_switch_config(self.switch_target_config, target, category)
        if updated is None:
            return False
        self.switch_target_config = updated
        self.switch_normalizations = self.switch_normalizations | {category}
        self.generation += 1
        self.error = None
        self.render_revision += 1
        return True

    def cancel_metric_switch(self) -> bool:
        """Discard a failed pending target while retaining accepted observations."""

        if self.switch_target_config is None:
            return False
        self.switch_target_config = None
        self.switch_normalizations = frozenset()
        self.error = None
        self.render_revision += 1
        return True

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
        if completion.generation != self.generation or completion.config != self.request_config:
            return False
        if (
            self.request_config.metric_id is not None
            and completion.response.metric_id != self.request_config.metric_id
        ):
            return False
        if self.switch_target_config is not None:
            self.candidate = self.switch_target_config
            self.switch_target_config = None
            self.switch_normalizations = frozenset()
            self.accepted_config = None
            self.accepted_response = None
            self.accepted_at = None
            self.history.clear()
            self.monitor_started_at = None
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
        if self.switch_target_config is not None:
            self.switch_target_config = None
            self.switch_normalizations = frozenset()
            self.error = None
            self.render_revision += 1
            return True
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
        if self._display_config.group_by is None:
            return CustomMonitorRanking(
                (CustomMonitorRankingEntry("total", None, observation.total),)
            )
        entries = tuple(
            CustomMonitorRankingEntry(group.id, group.label, group.value, group.description, group.display)
            for group in sorted(observation.groups, key=lambda item: (-item.value, item.id))
        )
        return CustomMonitorRanking(self._project_entries(entries))

    def heading_metadata(self, *, language: str) -> CustomMonitorHeadingMetadata:
        """Return source-owned facts for the shared Monitor heading composer."""

        config = self._display_config
        if self.presentation is not None:
            metric = self._localized(self.presentation.title, language)
        elif config.metric_titles is not None:
            metric = config.metric_titles[1] if language == "zh" else config.metric_titles[0]
        else:
            raise ValueError(
                "custom Monitor heading requires presentation.title or metric_titles"
            )
        return CustomMonitorHeadingMetadata(
            metric=metric,
            dimension=(
                self._group_label(config.group_by, language)
                if config.group_by is not None
                else None
            ),
            window_seconds=self._window_seconds(require_resolved=True),
        )

    def heading(self, *, language: str) -> str:
        """Return the legacy plain heading used by pre-chart loading surfaces."""

        config = self._display_config
        title = (
            self._localized(self.presentation.title, language)
            if self.presentation is not None
            else (config.metric_titles[1] if language == "zh" else config.metric_titles[0])
            if config.metric_titles is not None
            else config.metric_id or config.source.dataset_id
        )
        group = self._group_label(config.group_by, language)
        return " · ".join(
            part for part in (group, title, self._display_period_label(language)) if part
        )

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
                    description=self._localized(entry.description, language) if entry.description is not None else None,
                    display=self._localized(entry.display, language) if entry.display is not None else None,
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
        if self._display_config.group_by is None:
            keys = ("total",)
        elif self._display_config.top is not None:
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
        if self._display_config.presentation.style == "cumulative-bars":
            if language == "zh":
                day = "昨天" if self.distribution_day_window == "yesterday" else "今天"
                return f"{day} · 小时累计柱 · 数据窗口 {source}"
            return f"{self.distribution_day_window} · hourly cumulative bars · data window {source}"
        if is_monitor_ranking_style(self._display_config.presentation.style):
            return f"数据窗口 {source}" if language == "zh" else f"data window {source}"
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
        if self._display_config.group_by is None:
            return {"total": float(observation.total)}
        return {item.id: float(item.value) for item in observation.groups}

    def _top_keys(self, values: dict[str, Decimal | float]) -> set[str]:
        top = self._display_config.top
        if top is None or len(values) <= top:
            return set(values)
        return {
            key
            for key, _value in sorted(values.items(), key=lambda item: (-item[1], item[0]))[:top]
        }

    def _project_entries(
        self, entries: tuple[CustomMonitorRankingEntry, ...]
    ) -> tuple[CustomMonitorRankingEntry, ...]:
        config = self._display_config
        if config.top is None or len(entries) <= config.top:
            return entries
        kept = self._top_keys({entry.key: entry.value for entry in entries})
        result = tuple(entry for entry in entries if entry.key in kept)
        if self.aggregation != "sum":
            return result
        other = sum((entry.value for entry in entries if entry.key not in kept), start=Decimal())
        return (
            (*result, CustomMonitorRankingEntry("Other", None, other))
            if other and config.other == "show"
            else result
        )

    def _project_timeline_series(
        self, series: tuple[CustomMonitorSeries, ...]
    ) -> tuple[CustomMonitorSeries, ...]:
        config = self._display_config
        if config.top is None or len(series) <= config.top:
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
            if config.other == "show"
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
        if self._display_config.group_by is None:
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

    def _window_seconds(self, *, require_resolved: bool = False) -> int:
        capability = self.monitor_capability
        if capability is None and self.capability is not None:
            candidate = self.capability.charts.get("monitor")
            capability = candidate if isinstance(candidate, V2MonitorCapability) else None
        if capability is None:
            if require_resolved:
                raise ValueError("custom Monitor heading requires a resolved Monitor capability")
            return 60
        return capability.window_seconds
