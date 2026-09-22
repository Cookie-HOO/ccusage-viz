# Monitor Time-of-Day Token Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Monitor-only cumulative-token distribution style that shows hourly or half-hourly local-calendar-day usage with truthful coverage states.

**Architecture:** Keep acquisition and counter differences in `ObservedTPM`; extend its minute aggregates to 50 hours and project retained values into calendar-aligned day buckets. Add dedicated distribution semantic types and renderer rather than altering rolling `TimelineModel`. The monitor component, standalone UI, and dashboard-pane UI select controls and projections by style.

**Tech Stack:** Python 3.12, dataclasses, `pytest`, Plotext/terminal rendering, existing localization catalogs.

**Spec:** `docs/superpowers/specs/2026-09-22-monitor-time-of-day-distribution-design.md`

## Global Constraints

- The product remains token-consumption and token-derived-metrics only; distribution values use `tokens`, never TPM.
- The distribution is Monitor-only; do not add timestamp reconstruction to historical providers.
- Raw intervals remain high-resolution for about one hour; only minute aggregates retain 50 hours.
- Realtime TPM controls remain capped at rolling 24 hours.
- Group identity/color is stable over the complete selected day; apply Top N + Other after full-day accumulation.
- Local calendar boundaries, aware ISO export values, gaps, resets, observed-zero, and DST must be represented truthfully.
- `ranking` and `list` omit ineffective `w`; the new style exposes `w` (Today/Yesterday) and `g` (Hourly/30 min).

---

### Task 1: Add distribution configuration and style-aware control semantics

**Files:**
- Modify: `src/ccusage_viz/options.py`
- Modify: `src/ccusage_viz/cli.py`
- Modify: `src/ccusage_viz/configuration.py`
- Test: `tests/test_options.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces `MonitorConfig.day_window: Literal["today", "yesterday"]` and `MonitorConfig.distribution_granularity: Literal["hour", "half-hour"]`.
- Produces `is_monitor_distribution(chart: MonitorConfig) -> bool` and style-aware adjustment-control helpers consumed by standalone and dashboard UI.

- [ ] **Step 1: Write failing option tests**

```python
def test_cumulative_monitor_style_cycles_day_and_granularity() -> None:
    chart = MonitorConfig(kind="monitor", window_seconds=3600, presentation=ChartPresentation(style="cumulative-bars"))
    assert adjust_chart(chart, "w").day_window == "yesterday"
    assert adjust_chart(chart, "g").distribution_granularity == "half-hour"


def test_ranking_and_list_ignore_window_adjustment() -> None:
    for style in ("ranking", "list"):
        chart = MonitorConfig(kind="monitor", window_seconds=21600, presentation=ChartPresentation(style=style))
        assert adjust_chart(chart, "w") == chart
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `pytest tests/test_options.py -k 'cumulative_monitor_style or ranking_and_list_ignore_window' -v`

Expected: FAIL because the configuration fields/style and behavior do not exist.

- [ ] **Step 3: Add configuration and cycling behavior**

Add the `cumulative-bars` Monitor style and fields with defaults `today` and `hour`. Implement the behavior below without changing the established rolling window tuple:

```python
if isinstance(chart, MonitorConfig) and chart.presentation.style == "cumulative-bars":
    if key == "w":
        return replace(chart, day_window=_cycle(("today", "yesterday"), chart.day_window, 1))
    if key == "g":
        return replace(
            chart,
            distribution_granularity=_cycle(("hour", "half-hour"), chart.distribution_granularity, 1),
        )
if key == "w" and isinstance(chart, MonitorConfig):
    if chart.presentation.style in {"ranking", "list"}:
        return chart
    return replace(chart, window_seconds=_cycle((300, 900, 1800, 3600, 21600, 43200, 86400), ...))
```

Ensure style/group compatibility retains `cumulative-bars` for total and all group modes. Leave CLI `--window` as the existing startup rolling-window option; the new settings are interactive display state.

- [ ] **Step 4: Add CLI/config parser tests and run focused option tests**

Run: `pytest tests/test_options.py tests/test_cli.py -k 'monitor or cumulative' -v`

Expected: PASS, including a regression that 24 hours remains the maximum rolling realtime choice.

- [ ] **Step 5: Commit configuration semantics**

```bash
git add src/ccusage_viz/options.py src/ccusage_viz/cli.py src/ccusage_viz/configuration.py tests/test_options.py tests/test_cli.py
git commit -m "feat: add monitor distribution configuration"
```

### Task 2: Retain 50-hour minute aggregates with exact coverage

**Files:**
- Modify: `src/ccusage_viz/processing/monitor.py`
- Test: `tests/test_monitor.py`
- Create: `tests/test_monitor_distribution.py`

**Interfaces:**
- Produces coverage-span information on retained minute aggregates.
- Preserves raw intervals for one hour and aggregate rollups for `50 * 3600` seconds.

- [ ] **Step 1: Write retention and gap-preservation tests**

```python
def test_minute_rollup_preserves_a_gap_between_covered_spans() -> None:
    observer = ObservedTPM(window_seconds=3600)
    # Add/roll up two valid intervals in the same minute separated by an invalid gap.
    # Assert the rollup coverage spans do not merge across that gap.
    assert rollup.coverage_spans == (CoverageSpan(0, 10), CoverageSpan(30, 40))


def test_rollups_retain_fifty_hours_and_clip_the_boundary() -> None:
    observer = ObservedTPM(window_seconds=3600)
    # Seed data on both sides of now - 50h and run maintenance.
    assert all(rollup.ended_at > now - 50 * 3600 for rollup in observer.rollups)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_monitor_distribution.py tests/test_monitor.py -k 'gap_between_covered or fifty_hours' -v`

Expected: FAIL because rollups do not preserve coverage spans and use 24-hour retention.

- [ ] **Step 3: Add immutable coverage spans and safe merge/clip logic**

Add:

```python
@dataclass(frozen=True, slots=True)
class CoverageSpan:
    started_at: float
    ended_at: float
```

Extend `MinuteRollup` with normalized non-overlapping spans. In `_append_rollup`, merge only overlapping or contiguous spans and derive `covered_seconds` from their union. In `_maintain`, use `retention_seconds = 50 * 3600`; clip span boundaries and proportionally retain values only for remaining valid coverage. Update observer copying to preserve the immutable span tuples.

- [ ] **Step 4: Run Monitor retention tests**

Run: `pytest tests/test_monitor.py tests/test_monitor_distribution.py -k 'rollup or retention or gap or reset' -v`

Expected: PASS; existing one-hour raw-to-minute behavior and reset/rebaseline protections remain green.

- [ ] **Step 5: Commit retention changes**

```bash
git add src/ccusage_viz/processing/monitor.py tests/test_monitor.py tests/test_monitor_distribution.py
git commit -m "feat: retain monitor rollups for daily distribution"
```

### Task 3: Project retained observations into local calendar-day buckets

**Files:**
- Modify: `src/ccusage_viz/chart_models.py`
- Modify: `src/ccusage_viz/processing/monitor.py`
- Test: `tests/test_monitor_distribution.py`

**Interfaces:**
- Produces `DistributionCoverage`, `TimeOfDayBucket`, and `TimeOfDayDistributionModel`.
- Produces `ObservedTPM.time_of_day_distribution(...) -> TimeOfDayDistributionModel`.

- [ ] **Step 1: Write calendar projection tests**

```python
def test_distribution_splits_an_interval_at_half_hour_boundaries() -> None:
    model = observer.time_of_day_distribution(..., granularity="half-hour", wall=aware_time)
    values = [bucket.values["Total"] for bucket in model.buckets if bucket.coverage != DistributionCoverage.UNOBSERVED]
    assert values == [45.0, 60.0, 15.0]


def test_distribution_marks_start_bucket_partial_and_prior_buckets_unobserved() -> None:
    model = observer.time_of_day_distribution(..., wall=local_datetime(2026, 9, 22, 10, 0))
    assert model.buckets[8].coverage is DistributionCoverage.UNOBSERVED
    assert model.buckets[9].coverage is DistributionCoverage.PARTIAL


def test_distribution_keeps_observed_zero_distinct_from_unobserved() -> None:
    assert full_zero_bucket.coverage is DistributionCoverage.FULL
    assert full_zero_bucket.values["Total"] == 0.0
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_monitor_distribution.py -v`

Expected: FAIL because no model or calendar projection exists.

- [ ] **Step 3: Add semantic model types**

Add immutable model types with aware boundary datetimes, bucket coverage, values, selected day/window/granularity, selected series, token metric, observed-from time, and project aggregation. Use `DistributionCoverage` values `full`, `partial`, and `unobserved`.

- [ ] **Step 4: Implement calendar projection**

Derive local midnight boundaries from the accepted aware wall time, not repaint time. Generate the full Today/Yesterday local-day geometry; proportional-overlap allocate retained values separately from union coverage. Select Top N from totals over the whole selected day and map all other keys to `Other` consistently in every bucket. Use `0.0` for observed zero and unavailable values only for unobserved buckets.

- [ ] **Step 5: Add grouping and DST tests, then run**

```python
def test_distribution_selects_top_groups_over_the_full_day() -> None:
    model = observer.time_of_day_distribution(..., by="model", top=1)
    assert tuple(series.name for series in model.series) == ("model-a", "Other")


def test_fall_back_day_contains_twenty_five_hourly_buckets() -> None:
    model = observer.time_of_day_distribution(..., wall=fall_back_local_time, day_window="yesterday")
    assert len(model.buckets) == 25
```

Run: `pytest tests/test_monitor_distribution.py -v`

Expected: PASS for splitting, gaps, groups, Today/Yesterday, observed zero, and DST.

- [ ] **Step 6: Commit calendar projection**

```bash
git add src/ccusage_viz/chart_models.py src/ccusage_viz/processing/monitor.py tests/test_monitor_distribution.py
git commit -m "feat: project monitor tokens by time of day"
```

### Task 4: Connect the distribution model to Monitor components

**Files:**
- Modify: `src/ccusage_viz/monitor_component.py`
- Test: `tests/test_monitor_component.py`

**Interfaces:**
- `MonitorComponent.model()` returns `TimelineModel | RankingModel | TimeOfDayDistributionModel`.
- `MonitorComponent.distribution_model(now: float, wall: datetime | None) -> TimeOfDayDistributionModel` supplies accepted-sample projection.

- [ ] **Step 1: Write component re-projection tests**

```python
def test_distribution_style_reprojects_retained_monitor_data_without_rebaseline() -> None:
    component = configured_component_with_samples()
    component.configure(with_style(component.candidate, "cumulative-bars"), data_affecting=False)
    assert isinstance(component.model(now=..., wall=...), TimeOfDayDistributionModel)
    assert component.observer.previous is not None


def test_distribution_day_and_granularity_changes_are_display_only() -> None:
    before = component.observer
    component.configure(adjust_standalone(component.candidate, "g"), data_affecting=False)
    assert component.observer is before
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_monitor_component.py -k 'distribution' -v`

Expected: FAIL because the component only returns timeline/ranking models.

- [ ] **Step 3: Implement model dispatch**

Dispatch `ranking`/`list` to current ranking behavior, `cumulative-bars` to a new distribution-model method, and all remaining styles to the current timeline path. Use accepted sample wall time in the distribution method. Keep day/granularity/style display-only; preserve existing data-affecting treatment for grouping/filter scope changes.

- [ ] **Step 4: Run focused component regressions**

Run: `pytest tests/test_monitor_component.py tests/test_monitor.py -k 'monitor or distribution' -v`

Expected: PASS.

- [ ] **Step 5: Commit component dispatch**

```bash
git add src/ccusage_viz/monitor_component.py tests/test_monitor_component.py
git commit -m "feat: route monitor distribution models"
```

### Task 5: Render cumulative stacked bars and coverage states

**Files:**
- Create: `src/ccusage_viz/render/monitor_distribution.py`
- Modify: `src/ccusage_viz/monitor_component.py`
- Modify: `src/ccusage_viz/render/__init__.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Produces `render_monitor_distribution(model: TimeOfDayDistributionModel, context: RenderContext) -> str`.

- [ ] **Step 1: Write renderer tests**

```python
def test_distribution_renderer_distinguishes_full_partial_and_unobserved() -> None:
    rendered = render_monitor_distribution(model_with_all_coverage_states(), context)
    assert "not observed" in rendered
    assert partial_hatch_marker in rendered
    assert full_bar_marker in rendered


def test_distribution_renderer_uses_tokens_and_day_metadata() -> None:
    rendered = render_monitor_distribution(model, context)
    assert "Token" in rendered
    assert "Today" in rendered
    assert "Hourly" in rendered
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_render.py -k 'distribution' -v`

Expected: FAIL because the renderer does not exist.

- [ ] **Step 3: Implement dedicated terminal renderer**

Render semantic stacked bars directly rather than using timeline bars. Use stable categorical colors from complete-day series order, `Other` color from the existing palette, local-time tick thinning, no-color/ASCII substitutions, coverage hatching, and a visible zero-baseline mark. Build a localized title and metadata line (`Hourly · observed from HH:MM`). Do not use the Monitor-start vertical-marker helper.

- [ ] **Step 4: Dispatch rendering and run tests**

Update component rendering to dispatch distribution models directly. Run: `pytest tests/test_render.py tests/test_monitor_component.py -k 'distribution or monitor' -v`

Expected: PASS with no ANSI codes in ASCII/no-color coverage.

- [ ] **Step 5: Commit renderer**

```bash
git add src/ccusage_viz/render/monitor_distribution.py src/ccusage_viz/render/__init__.py src/ccusage_viz/monitor_component.py tests/test_render.py
git commit -m "feat: render monitor token distribution"
```

### Task 6: Apply style-aware controls in standalone and dashboard Monitor UI

**Files:**
- Modify: `src/ccusage_viz/monitor.py`
- Modify: `src/ccusage_viz/tui.py`
- Modify: `src/ccusage_viz/options.py`
- Test: `tests/test_monitor.py`
- Test: `tests/test_tui.py`

**Interfaces:**
- Both UI hosts consume the shared style-aware control helper from `options.py`.

- [ ] **Step 1: Write control-matrix tests**

```python
def test_monitor_actions_hide_window_for_ranking_and_list() -> None:
    assert "window" not in action_labels_for_style("ranking")
    assert "window" not in action_labels_for_style("list")


def test_distribution_actions_show_day_and_granularity() -> None:
    labels = action_labels_for_style("cumulative-bars")
    assert "window" in labels
    assert "granularity" in labels
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_monitor.py tests/test_tui.py -k 'actions or adjustment or distribution' -v`

Expected: FAIL because quick controls use one shared static set.

- [ ] **Step 3: Make both hosts consume the control matrix**

Time-series styles expose `w`; ranking/list omit it; cumulative-bars expose both `w` and `g`. Update quick-state labels to show rolling duration, no range, or Today/Yesterday plus Hourly/30 min as appropriate. `g` is accepted only in cumulative-bars. UI-only changes must not rebaseline or replace retained observations. Preserve scope-changing filter/by semantics and current advanced-control applicability.

- [ ] **Step 4: Run UI control tests**

Run: `pytest tests/test_monitor.py tests/test_tui.py -k 'adjustment or action or monitor' -v`

Expected: PASS.

- [ ] **Step 5: Commit control behavior**

```bash
git add src/ccusage_viz/monitor.py src/ccusage_viz/tui.py src/ccusage_viz/options.py tests/test_monitor.py tests/test_tui.py
git commit -m "feat: tailor monitor controls to style"
```

### Task 7: Export distribution data, localize copy, document, and verify

**Files:**
- Modify: `src/ccusage_viz/data_view.py`
- Modify: `src/ccusage_viz/monitor.py`
- Modify: `src/ccusage_viz/tui.py`
- Modify: `src/ccusage_viz/locales/en.py`
- Modify: `src/ccusage_viz/locales/zh.py`
- Modify: `docs/usage.md`
- Modify: `docs/usage.zh-CN.md`
- Test: `tests/test_data_view.py`
- Test: `tests/test_i18n.py`

**Interfaces:**
- Produces `monitor_distribution_data_payload(model: TimeOfDayDistributionModel) -> list[dict[str, object]]`.

- [ ] **Step 1: Write export/localization tests**

```python
def test_distribution_payload_retains_unobserved_as_null() -> None:
    row = monitor_distribution_data_payload(model_with_unobserved_bucket())[0]
    assert row["coverage"] == "unobserved"
    assert row["value"] is None
    assert row["unit"] == "tokens"


def test_distribution_payload_retains_observed_zero() -> None:
    row = monitor_distribution_data_payload(model_with_observed_zero_bucket())[0]
    assert row["coverage"] == "full"
    assert row["value"] == 0.0
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_data_view.py tests/test_i18n.py -k 'distribution or catalogs' -v`

Expected: FAIL because payload and copy do not exist.

- [ ] **Step 3: Add export and copied UI route**

Emit one row per displayed bucket/series with aware ISO `started_at`/`ended_at`, selected `day_window`, `granularity`, identity/display fields, `tokens` unit, and coverage. Emit `None` for unobserved data and `0.0` for observed zero. Route monitor table/JSON modes to the new payload only for distribution models.

- [ ] **Step 4: Add exact catalog keys and user documentation**

Add matching English/Chinese strings for the title, day labels, granularity labels, observed-from metadata, coverage legend, and control states. Document the Monitor-only scope, Today/Yesterday and Hourly/30-min keys, 50-hour aggregate retention, and no historical backfill.

- [ ] **Step 5: Run affected tests and complete suite**

Run:

```bash
pytest tests/test_monitor_distribution.py tests/test_monitor.py tests/test_monitor_component.py tests/test_render.py tests/test_options.py tests/test_cli.py tests/test_data_view.py tests/test_i18n.py tests/test_tui.py -v
pytest -q
```

Expected: PASS.

- [ ] **Step 6: Commit integration and docs**

```bash
git add src/ccusage_viz/data_view.py src/ccusage_viz/monitor.py src/ccusage_viz/tui.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py docs/usage.md docs/usage.zh-CN.md tests/test_data_view.py tests/test_i18n.py
git commit -m "feat: export monitor time-of-day distribution"
```

## Plan self-review

- **Spec coverage:** Tasks 1–7 cover configuration/cycling, 50-hour aggregate retention, calendar/DST projection, grouped late Top N, explicit coverage states, component dispatch, dedicated rendering, standalone/dashboard controls, export, localization, documentation, and regression coverage.
- **No placeholder check:** Each task specifies concrete files, interfaces, test targets, commands, and implementation behavior; no deferred implementation steps remain.
- **Type consistency:** The distribution types and `ObservedTPM.time_of_day_distribution()` are introduced before component/render/export tasks consume them; all later paths consume `TimeOfDayDistributionModel`.
