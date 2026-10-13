# Grouped Custom Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add V2 Custom Historical Ranking partitions so Datasets can return ordered outer groups containing independently sorted inner rankings, while preserving flat Ranking compatibility and stable search facts.

**Architecture:** Extend V2 descriptors, requests, and responses with optional partition metadata and a strict `series | groups` data union. Project grouped responses into immutable full-data facts before applying search, then render them through a focused grouped Ranking presentation and viewport path that reuses existing row formatting. Keep old Datasets and flat responses on their existing path.

**Tech Stack:** Python 3.11–3.13, frozen dataclasses, `Decimal`, argparse, pytest, Ruff, ty, terminal ANSI rendering.

**Spec:** `docs/superpowers/specs/2026-10-13-grouped-custom-ranking-design.md`

## Global Constraints

- Scope is V2 Custom Historical Ranking; do not add partitioning to built-in charts, Custom Monitor, V1, Timeline, Stack, or Calendar.
- Old descriptors, requests, responses, commands, and presets remain valid and retain the old wire format.
- `partition_by` and non-null `group_by` must differ; an active partition requires non-null `group_by`.
- Outer group order is Dataset-owned and must never be sorted or ranked by ccuv.
- Inner series are independently sorted, ranked, scaled, Top-projected, and folded into arithmetic Other per group.
- Totals, shares, Other, and comparisons use only series actually returned by the Dataset.
- Search changes visibility only; complete current data remains authoritative for rank, totals, shares, bars, and comparison.
- Signed Decimal values remain valid; a zero denominator omits only the affected share.
- `period=all` retains dated points and has no previous-period comparison.
- Dashboard filters live on Advanced for every chart; Standalone remains a single-level adjustment surface.
- Ranking spacing modes remain `compact`, `space`, `line`, and `dashed`; `dashed` gains muted theme styling.

---

### Task 1: Model Partition Capabilities, Defaults, Configuration, and Requests

**Files:**
- Modify: `src/ccusage_viz/custom_models.py`
- Modify: `src/ccusage_viz/options.py`
- Modify: `src/ccusage_viz/custom_protocol.py`
- Test: `tests/test_custom_protocol.py`
- Test: `tests/test_options.py`

**Interfaces:**
- Produces: `CustomChartConfig.partition_by: str | None`.
- Produces: `CustomChartDefaults.partition_by: str | None`.
- Produces: `CustomChartCapability.partition_by: tuple[str | None, ...] | None` and `V2HistoricalChartCapability.partition_by: tuple[str | None, ...] | None`; `None` means undeclared old capability, distinct from a declared empty tuple.
- Produces: `CustomCapabilities.partition_by: tuple[CustomDimension, ...] | None` and `V2MetricCapabilities.partition_by: tuple[CustomDimension, ...] | None`.
- Produces: `V2ChartRequest.partition_by: str | None` plus `partition_declared: bool`, with `to_wire()` omitting the key when false and emitting explicit JSON null when true.
- Produces: `validate_partition_selection(partition_by, group_by, capability) -> None`, raising `CustomProtocolError` for descriptor defaults and `ValueError` for local config construction through a small wrapper.

- [ ] **Step 1: Write failing capability, defaults, and request tests**

Add focused cases equivalent to:

```python
def test_v2_ranking_parses_partition_catalog_capability_and_default() -> None:
    root = v2_probe_root()
    metric = root["metrics"][0]
    metric["capabilities"]["partition_by"] = [
        {"id": "logical_model", "label": {"en": "Logical Model", "zh-CN": "逻辑模型"}}
    ]
    metric["capabilities"]["charts"]["ranking"]["partition_by"] = [None, "logical_model"]
    metric["defaults"]["ranking"]["partition_by"] = "logical_model"
    descriptor = parse_v2_probe_descriptor(root)
    parsed = descriptor.metrics[0]
    assert parsed.capabilities.partition_by[0].id == "logical_model"
    assert parsed.capabilities.charts["ranking"].partition_by == (None, "logical_model")
    assert parsed.defaults["ranking"].partition_by == "logical_model"


def test_v2_ranking_rejects_equal_default_partition_and_group() -> None:
    root = partitioned_v2_probe_root()
    root["metrics"][0]["defaults"]["ranking"].update(
        partition_by="logical_model", group_by="logical_model"
    )
    with pytest.raises(CustomProtocolError, match="must differ"):
        parse_v2_probe_descriptor(root)


def test_v2_request_omits_undeclared_partition_but_emits_declared_null() -> None:
    old = v2_chart_request(partition_by=None, partition_declared=False).to_wire()
    aware = v2_chart_request(partition_by=None, partition_declared=True).to_wire()
    assert "partition_by" not in old["query"]
    assert aware["query"]["partition_by"] is None
```

Also cover: partition IDs falling back to the grouping catalog, explicit partition catalog taking precedence, unknown IDs, partition on non-Ranking charts, required partition capability without null, active partition with null group, equal explicit selections, and request canonical keys distinguishing partition selections and declaration state.

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
uv run pytest tests/test_custom_protocol.py tests/test_options.py -q
```

Expected: failures for missing partition fields, omitted validation, and unchanged V2 request wire output.

- [ ] **Step 3: Add the typed fields without changing positional call sites accidentally**

Add new fields at the ends of existing dataclasses or make them keyword-only where appropriate. Use `None` for an undeclared partition capability/catalog and a tuple for a declared one. Add `partition_by` to `CustomChartConfig` as a defaulted field after `group_by` only if every positional construction is updated in the same edit; otherwise append it after existing defaulted fields and use keyword access everywhere.

Implement request serialization as:

```python
query: dict[str, object] = {
    "filters": {key: list(values) for key, values in self.filters},
    "group_by": self.group_by,
    "granularity": self.granularity,
    "top": self.top,
}
if self.partition_declared:
    query["partition_by"] = self.partition_by
```

Include `(request.partition_declared, request.partition_by)` in `canonical_custom_request_key()` for `V2ChartRequest`.

- [ ] **Step 4: Parse and validate partition catalogs, capabilities, and defaults**

In `_parse_v2_capabilities()`:

- parse optional metric-level `partition_by` as `CustomDimension` values;
- parse optional chart-level `partition_by` only for Ranking;
- validate non-null IDs against the explicit partition catalog, or against `group_by` dimensions when the catalog is absent;
- preserve undeclared versus declared capability state.

Extend `_parse_v2_defaults()` to accept optional `partition_by`, validate it against Ranking capability, reject it for other charts, require non-null grouping when active, and reject equal non-null dimensions. Keep old defaults valid when the field is absent.

- [ ] **Step 5: Run protocol and option tests**

Run:

```bash
uv run pytest tests/test_custom_protocol.py tests/test_options.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the protocol-domain foundation**

```bash
git add src/ccusage_viz/custom_models.py src/ccusage_viz/options.py src/ccusage_viz/custom_protocol.py tests/test_custom_protocol.py tests/test_options.py
git commit -m "feat: model custom ranking partitions"
```

---

### Task 2: Parse the Strict Flat-or-Grouped Ranking Response Union

**Files:**
- Modify: `src/ccusage_viz/custom_models.py`
- Modify: `src/ccusage_viz/custom_protocol.py`
- Test: `tests/test_custom_protocol.py`

**Interfaces:**
- Consumes: `V2ChartRequest.partition_by`, `partition_declared`, and parsed Ranking capability from Task 1.
- Produces: `CustomRankingGroup(id, label, series, description=None, display=None, comparison_display=None, link=None)`.
- Produces: `CustomData(series: tuple[CustomSeries, ...] = (), groups: tuple[CustomRankingGroup, ...] | None = None)`, where `groups is None` is flat and a tuple (including empty) is partitioned.
- Produces: `_parse_data(value, *, descriptions_allowed, partitioned=False, max_items=None) -> CustomData`.

- [ ] **Step 1: Write response-union and metadata tests**

Add cases equivalent to:

```python
def test_partitioned_v2_ranking_parses_ordered_groups_and_repeated_inner_ids() -> None:
    request = partitioned_ranking_request(partition_by="logical_model", group_by="real_model")
    root = v2_chart_response_root(request)
    root["data"] = {
        "groups": [
            ranking_group("coding", "Coding", [ranking_series("shared", "Model", "7")]),
            ranking_group("general", "General", [ranking_series("shared", "Model", "5")]),
        ]
    }
    response = parse_custom_response(json_bytes(root), request)
    assert [group.id for group in response.data.groups] == ["coding", "general"]
    assert response.data.groups[0].series[0].id == response.data.groups[1].series[0].id


def test_partitioned_v2_ranking_rejects_flat_data() -> None:
    request = partitioned_ranking_request(partition_by="logical_model", group_by="real_model")
    root = v2_chart_response_root(request)
    root["data"] = {"series": []}
    with pytest.raises(CustomProtocolError, match="data groups"):
        parse_custom_response(json_bytes(root), request)
```

Cover group metadata, empty groups, simultaneous `series` and `groups`, grouped response for null partition, duplicate group IDs, duplicate series IDs within one group, duplicate point dates, malformed localized fields, non-HTTPS group links, and `max_items` over the sum of all inner series.

- [ ] **Step 2: Run the focused parser tests and verify failure**

```bash
uv run pytest tests/test_custom_protocol.py -q
```

Expected: FAIL because `CustomData` and `_parse_data()` only support flat series.

- [ ] **Step 3: Implement group types and path-specific parsing**

Parse each group with names that identify the failing path:

```python
def _parse_ranking_group(value: object, *, index: int) -> CustomRankingGroup:
    name = f"data.groups[{index}]"
    source = _mapping(value, name)
    series = tuple(
        _parse_series(item, descriptions_allowed=True, name=f"{name}.series[{series_index}]")
        for series_index, item in enumerate(_sequence(source.get("series"), f"{name}.series"))
    )
    _unique_ids(series, f"{name}.series")
    return CustomRankingGroup(...)
```

Refactor `_parse_series()` and `_parse_point()` to accept a path/name argument while preserving existing default error wording for flat/V1 callers.

- [ ] **Step 4: Select the union from the issued request**

In `parse_custom_response()` for `V2ChartRequest`, resolve the metric and Ranking capability first, then call `_parse_data()` with:

```python
partitioned=request.partition_by is not None
max_items=capability.max_items if request_kind_is_ranking else None
```

Reject shape mismatches before constructing `V2ChartResponse`. For a declared null partition require flat data. Old undeclared requests remain flat.

- [ ] **Step 5: Run parser regressions**

```bash
uv run pytest tests/test_custom_protocol.py tests/test_custom_provider.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the grouped response union**

```bash
git add src/ccusage_viz/custom_models.py src/ccusage_viz/custom_protocol.py tests/test_custom_protocol.py
git commit -m "feat: parse grouped custom ranking responses"
```

---

### Task 3: Wire Partition Selection Through CLI, Defaults, Commands, and Presets

**Files:**
- Modify: `src/ccusage_viz/chart_configuration.py`
- Modify: `src/ccusage_viz/cli.py`
- Modify: `src/ccusage_viz/configuration.py`
- Modify: `src/ccusage_viz/command_copy.py`
- Modify: `src/ccusage_viz/dashboard_presets.py`
- Modify: `src/ccusage_viz/custom_component.py`
- Modify: `src/ccusage_viz/custom_metric_switching.py`
- Test: `tests/test_options.py`
- Test: `tests/test_command_copy.py`
- Test: `tests/test_dashboard_presets.py`
- Test: `tests/test_custom_metric_switching.py`
- Test: `tests/test_custom_component.py`

**Interfaces:**
- Consumes: typed partition fields from Task 1.
- Produces: `--partition-by ID` for Custom Ranking only.
- Produces: preset wire field `partition_by`, optional on read for backward compatibility and always emitted for new Custom panes.
- Produces: `_cycle_custom_partitioning()` is deferred to Task 8; this task handles initial and persisted configuration only.
- Produces: data-affecting query identity including `partition_by`.

- [ ] **Step 1: Write failing end-to-end configuration tests**

Add tests for:

```python
def test_custom_ranking_cli_accepts_partition_and_rejects_equal_group() -> None:
    options = parse_chart("ranking", "--dataset", "router", "--partition-by", "logical_model",
                          "--group-by", "real_model")
    assert options.chart.partition_by == "logical_model"
    with pytest.raises(UsageError, match="must differ"):
        parse_chart("ranking", "--dataset", "router", "--partition-by", "real_model",
                    "--group-by", "real_model")


def test_old_custom_preset_without_partition_loads_flat() -> None:
    wire = old_custom_ranking_preset_wire()
    pane = parse_dashboard_preset(wire).panes[0]
    assert pane.chart.partition_by is None
```

Also assert command copy emits `--partition-by`, defaults apply a valid Dataset suggestion, an explicit CLI null/absence beats defaults according to existing explicit-field rules, presets round-trip, query replacement detects partition changes, and metric switching chooses the target default/fallback without colliding with grouping.

- [ ] **Step 2: Run the configuration suite and verify failure**

```bash
uv run pytest tests/test_options.py tests/test_command_copy.py tests/test_dashboard_presets.py tests/test_custom_metric_switching.py tests/test_custom_component.py -q
```

Expected: failures for absent argparse/config/persistence fields and unchanged query identity.

- [ ] **Step 3: Add CLI and command-copy support**

Register `--partition-by` only on custom historical chart parsing, reject it unless `kind == "ranking"`, reject active partition without grouping, and reject equality before execution. Add `partition_by` to `initial_explicit`.

Emit command fragments in this order:

```text
--partition-by logical_model --group-by real_model --top 3
```

Update both standalone and Dashboard Pane command-copy paths.

- [ ] **Step 4: Apply defaults and metric-switch normalization**

Update `apply_custom_probe_defaults()` to choose a legal partition before grouping and Top. Extend metric-switch normalization with a `partition_by` category and use target defaults, then null, then the first required partition. When normalizing grouping, skip the active partition and reject when no non-null legal grouping remains.

Add `partition_by` to:

- `custom_replacement_required()`;
- `_query_identity()`;
- switch-target matching/normalization;
- V2 request creation in the provider/coordinator path.

Set `partition_declared=True` only when the active V2 Ranking capability declares `partition_by`.

- [ ] **Step 5: Persist partition state compatibly**

Write `"partition_by": chart.partition_by` in new preset wire. On read, accept both the old exact field set and the new field set; use `custom_wire.get("partition_by")` rather than requiring migration of old files. Include `partition_by` in persisted explicit-state fields.

- [ ] **Step 6: Run configuration and lifecycle regressions**

```bash
uv run pytest tests/test_options.py tests/test_command_copy.py tests/test_dashboard_presets.py tests/test_custom_metric_switching.py tests/test_custom_component.py tests/test_query_coordinator.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit configuration wiring**

```bash
git add src/ccusage_viz/chart_configuration.py src/ccusage_viz/cli.py src/ccusage_viz/configuration.py src/ccusage_viz/command_copy.py src/ccusage_viz/dashboard_presets.py src/ccusage_viz/custom_component.py src/ccusage_viz/custom_metric_switching.py tests/test_options.py tests/test_command_copy.py tests/test_dashboard_presets.py tests/test_custom_metric_switching.py tests/test_custom_component.py
git commit -m "feat: configure custom ranking partitions"
```

---

### Task 4: Build Full Grouped Projection Facts Before Search

**Files:**
- Modify: `src/ccusage_viz/processing/custom_historical.py`
- Test: `tests/test_custom_component.py`
- Test: `tests/test_transform.py`

**Interfaces:**
- Consumes: `CustomData.groups` and current/comparison grouped responses from Task 2.
- Produces: `CustomProjectedRankingGroup` with `id`, localized metadata, `series`, `total`, `previous_total`, `comparison_ready`, and `maximum`.
- Produces: `CustomChartProjection.groups: tuple[CustomProjectedRankingGroup, ...] | None`; `None` remains flat.
- Produces: immutable inner rank facts through `CustomProjectedSeries.rank: int | None`, assigned before Top/search.
- Preserves: existing `CustomChartProjection.series` flat behavior.

- [ ] **Step 1: Write grouped projection tests**

Add tests equivalent to:

```python
def test_grouped_projection_preserves_group_order_and_projects_top_other_per_group() -> None:
    projection = process_custom_historical(
        grouped_response(groups=(
            group("small-first", values=("4", "3", "2", "1")),
            group("large-second", values=("400", "300", "200", "100")),
        )),
        partitioned_config(top=2, other="show"),
    )
    assert [group.id for group in projection.groups] == ["small-first", "large-second"]
    assert [entry.total for entry in projection.groups[0].series] == [Decimal("4"), Decimal("3"), Decimal("3")]
    assert projection.groups[0].series[-1].is_other
    assert projection.groups[1].total == Decimal("1000")


def test_grouped_projection_share_denominators_precede_top_and_other_visibility() -> None:
    shown = process_custom_historical(grouped_response(...), partitioned_config(top=1, other="show"))
    hidden = process_custom_historical(grouped_response(...), partitioned_config(top=1, other="hide"))
    assert shown.groups[0].total == hidden.groups[0].total == Decimal("10")
```

Cover ascending order, stable ID tie-breaks, empty groups, signed values/negative Other, zero totals, all group totals/global total, group display fallback facts, repeated series IDs across groups, global max-items already validated, Dataset group order, and `period=all`.

- [ ] **Step 2: Run projection tests and verify failure**

```bash
uv run pytest tests/test_custom_component.py tests/test_transform.py -q
```

Expected: FAIL because the projection accepts only `response.data.series`.

- [ ] **Step 3: Introduce focused grouped projection helpers**

Implement helpers with exact responsibilities:

```python
def _project_source_series(
    sources: tuple[CustomSeries, ...], config: CustomChartConfig, *, sort_direction: str,
    previous: dict[str, CustomSeries] | None,
) -> tuple[tuple[CustomProjectedSeries, ...], Decimal, Decimal]:
    """Return visible Top/Other entries, full returned total, and full returned maximum."""


def _project_groups(
    current: tuple[CustomRankingGroup, ...],
    previous: tuple[CustomRankingGroup, ...] | None,
    config: CustomChartConfig,
    *,
    sort_direction: str,
) -> tuple[CustomProjectedRankingGroup, ...]:
    """Preserve current group order and independently project every group."""
```

Assign each concrete inner series its rank after full within-group sorting and before Top. Other has `rank=None`. Preserve full total and maximum even when Other is hidden.

- [ ] **Step 4: Add grouped previous-period matching**

Build previous lookup by group ID, then series ID within the matching group. Sum each previous group's actually returned series for group comparison. Do not synthesize disappeared entities or zero values. A moved series is absent in its new group and therefore new.

- [ ] **Step 5: Keep flat projection output unchanged**

Branch once near the top of `process_custom_historical()`:

```python
if response.data.groups is not None:
    return _process_grouped_ranking(...)
return _process_flat_historical(...)
```

Reject grouped data for non-Ranking configs defensively even though protocol parsing should already prevent it.

- [ ] **Step 6: Run projection suites**

```bash
uv run pytest tests/test_custom_component.py tests/test_transform.py tests/test_render.py -q
```

Expected: PASS with existing flat projection snapshots unchanged.

- [ ] **Step 7: Commit grouped projection**

```bash
git add src/ccusage_viz/processing/custom_historical.py tests/test_custom_component.py tests/test_transform.py
git commit -m "feat: project grouped custom rankings"
```

---

### Task 5: Fix Flat Custom Ranking Search Facts

**Files:**
- Modify: `src/ccusage_viz/render/custom_ranking_viewport.py`
- Modify: `src/ccusage_viz/render/ranking_viewport.py`
- Test: `tests/test_custom_ranking_scroll.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: existing flat `CustomChartProjection.series`.
- Produces: `RankingViewport.full_entries`, `entries` (matched visibility), `full_total`, and `full_maximum` or equivalent clearly named fields.
- Produces: stable rank carried from the complete current projection into matched entries.
- Preserves: active search text across refresh and viewport restoration by series ID.

- [ ] **Step 1: Add regressions demonstrating the current bug**

Add a viewport-level test, not only a direct renderer test:

```python
def test_viewport_search_preserves_full_rank_share_and_bar_scale_after_refresh() -> None:
    projection = ranking_projection((entry("alpha", 50), entry("beta", 30), entry("claude", 20)))
    output = render_viewport(projection, search="claude", show_percentage=True)
    assert row_for(output, "claude").lstrip().startswith("3 ")
    assert "20.0%" in row_for(output, "claude")
    assert bar_width(row_for(output, "claude")) < bar_width_for_full_scale()

    refreshed = ranking_projection((entry("claude", 60), entry("alpha", 35), entry("beta", 5)))
    output = render_viewport(refreshed, search="claude", show_percentage=True)
    assert row_for(output, "claude").lstrip().startswith("1 ")
    assert "60.0%" in row_for(output, "claude")
```

Also cover search by description/link, `Showing 1/3`, previous-rank comparison based on full data, and stable scroll anchor when the prior top visible ID survives refresh.

- [ ] **Step 2: Run the viewport tests and observe renumbering/recalculation**

```bash
uv run pytest tests/test_custom_ranking_scroll.py tests/test_render.py -q
```

Expected: new assertions fail with rank 1, 100%, and full-width matched bars.

- [ ] **Step 3: Separate full facts from matched visibility**

Prepare all `RankingPresentationEntry` objects first, including current full rank. Compute:

```python
full_entries = tuple(prepare_entry(entry, rank=rank) for rank, entry in enumerate(projection.series, 1))
matched_entries = filter_ranking_entries(full_entries, search_query)
viewport.total = sum(entry.current for entry in full_entries)
viewport.maximum = max((entry.current for entry in full_entries), default=Decimal(1)) or 1
```

Do not derive totals, maximum, or prior ranks from `matched_entries`. Pass preserved ranks to the renderer instead of relying on enumeration of the filtered tuple. A minimal compatible approach is adding `rank: int | None` to `RankingPresentationEntry` and making `render_historical_ranking()` use it when present.

- [ ] **Step 4: Restore by stable identity across source refresh**

Before replacing entries, record the stable ID intersecting the old viewport's top content line. After rebuilding matches and geometry, restore to that ID's new start when it still matches; otherwise clamp to the nearest surviving matched row. Do not reset merely because the projection tuple object changed.

- [ ] **Step 5: Run flat search and viewport regressions**

```bash
uv run pytest tests/test_custom_ranking_scroll.py tests/test_render.py tests/test_tui_custom.py -q
```

Expected: PASS; direct renderer and Dashboard viewport now agree.

- [ ] **Step 6: Commit the flat-search correction**

```bash
git add src/ccusage_viz/render/custom_ranking_viewport.py src/ccusage_viz/render/ranking_viewport.py tests/test_custom_ranking_scroll.py tests/test_render.py
git commit -m "fix: preserve custom ranking facts during search"
```

---

### Task 6: Render Group Headings and Independent Inner Rankings

**Files:**
- Create: `src/ccusage_viz/render/grouped_ranking.py`
- Modify: `src/ccusage_viz/render/custom.py`
- Modify: `src/ccusage_viz/render/ranking_presentation.py`
- Modify: `src/ccusage_viz/locales/en.py`
- Modify: `src/ccusage_viz/locales/zh.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `CustomChartProjection.groups` from Task 4 and preserved rank support from Task 5.
- Produces: `GroupedRankingPresentationGroup` containing localized heading metadata, full totals, maximum, and prepared inner entries.
- Produces: `render_grouped_custom_ranking(projection, context, ...) -> str` for non-viewport/standalone use.
- Reuses: existing Ranking value, delta, description, link, width, and row renderer; group headings request the same column geometry but omit rank and bar fields.

- [ ] **Step 1: Write grouped rendering tests first**

Add tests asserting:

```python
def test_grouped_ranking_renders_arrow_heading_group_metadata_and_independent_scales() -> None:
    output = render_grouped(grouped_projection(...), width=100, density="detailed")
    assert "Logical Model → Real Model · Ranking" in output
    assert "Coding Model" in output and "Routes coding workloads" in output
    assert not group_heading(output, "Coding Model").contains_bar
    assert rank_of(output, "coding-a") == 1
    assert rank_of(output, "general-a") == 1
    assert bar_width(output, "coding-a") == bar_width(output, "general-a")


def test_group_display_and_zero_denominators_follow_existing_columns() -> None:
    output = render_grouped(zero_and_custom_display_projection(), show_percentage=True)
    assert "source-owned total" in output
    assert "nan" not in output.lower() and "inf" not in output.lower()
```

Cover Dataset order, no group bars/ranks, group and item shares, negative shares, empty group no-data text, description density behavior, narrow layout column hiding, safe links, `period=all`, group comparison, Other without comparison, and `show_percentage=false`.

- [ ] **Step 2: Run renderer tests and verify failure**

```bash
uv run pytest tests/test_render.py -q
```

Expected: FAIL because grouped projections have no renderer.

- [ ] **Step 3: Implement a focused grouped presentation adapter**

In `grouped_ranking.py`, localize group/series metadata and build group presentation facts. Compute shares with explicit zero guards:

```python
group_share = None if global_total == 0 else group.total / global_total
item_share = None if group.total == 0 else entry.current / group.total
```

Do not sort groups. Use each group's stored full maximum and total when rendering inner rows.

- [ ] **Step 4: Reuse row-column logic for group headings**

Extract only the minimum shared layout primitive from `ranking_presentation.py`, for example:

```python
def render_ranking_heading_row(
    *, label: str, value: str, delta: str, share: str, description: str | None,
    columns: RankingColumns, context: RenderContext, link: str | None = None,
) -> tuple[str, ...]:
```

Its value/delta/share visibility and description wrapping must follow the same density and width rules as an ordinary Ranking entry. It emits no rank or scale/bar field.

- [ ] **Step 5: Dispatch grouped projections from Custom rendering**

In `render_custom_projection()` and `render_custom_ranking()`, route `projection.groups is not None` to `render_grouped_custom_ranking()`. Keep the flat call unchanged.

Generate the main heading from partition and grouping labels in the presentation descriptor. Extend `CustomPresentationDescriptor` to carry partition labels separately, falling back to group labels when the partition catalog is absent.

- [ ] **Step 6: Run rendering regressions**

```bash
uv run pytest tests/test_render.py tests/test_i18n.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit grouped presentation**

```bash
git add src/ccusage_viz/render/grouped_ranking.py src/ccusage_viz/render/custom.py src/ccusage_viz/render/ranking_presentation.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_render.py
git commit -m "feat: render grouped custom rankings"
```

---

### Task 7: Add Grouped Search, Physical Viewport, Sticky Headings, and Copying

**Files:**
- Create: `src/ccusage_viz/render/grouped_ranking_viewport.py`
- Modify: `src/ccusage_viz/render/ranking_viewport.py`
- Modify: `src/ccusage_viz/tui.py`
- Test: `tests/test_custom_ranking_scroll.py`
- Test: `tests/test_custom_ranking_dashboard_scroll.py`
- Test: `tests/test_tui_custom.py`

**Interfaces:**
- Consumes: grouped presentation/projection facts from Tasks 4 and 6.
- Produces: `GroupedRankingViewport`, with group-aware physical row geometry and stable `(group_id, series_id)` anchors.
- Produces: `render_grouped_custom_ranking_viewport(...) -> str`.
- Produces: copy hit identities that distinguish `("group", group_id)` from `("series", group_id, series_id)`.

- [ ] **Step 1: Write viewport and search behavior tests**

Add cases for:

```python
def test_grouped_search_matches_only_inner_fields_and_preserves_full_facts() -> None:
    output = render_grouped_viewport(search="sonnet")
    assert "Coding Model" in output
    assert "General Model" in output
    assert "Empty Unmatched Group" not in output
    assert original_rank(output, group="coding", item="sonnet") == 2
    assert original_share(output, group="coding", item="sonnet") == "30.6%"


def test_grouped_scroll_uses_sticky_label_only_after_original_heading_leaves() -> None:
    viewport = grouped_viewport(height=8)
    first = viewport.render(offset=0)
    scrolled = viewport.render(offset=4)
    assert count_visible(first, "Coding Model") == 1
    assert sticky_row(scrolled) == muted("Coding Model")
    assert "12.4K" not in sticky_row(scrolled)
```

Cover no sticky line when height cannot also show content, transition to next original heading, physical-line scrollbar range with descriptions and spacing, empty groups, search after refresh, stable anchor restoration, repeated inner IDs in different groups, and group identity in hit maps.

- [ ] **Step 2: Run viewport tests and verify failure**

```bash
uv run pytest tests/test_custom_ranking_scroll.py tests/test_custom_ranking_dashboard_scroll.py tests/test_tui_custom.py -q
```

Expected: FAIL because the flat viewport has no group row geometry or sticky heading.

- [ ] **Step 3: Implement grouped geometry as explicit row records**

Use a focused immutable row index rather than forcing pseudo-entries into flat geometry:

```python
@dataclass(frozen=True, slots=True)
class GroupedRankingRow:
    kind: Literal["group", "description", "separator", "series", "series_description", "empty"]
    group_id: str
    series_id: str | None
    source_line: int
```

Build full group geometry first, then matched visibility geometry. Preserve ranks/totals/maxima from the full projection. Search only inner entry fields; include normal group heading/description rows for groups with at least one match.

- [ ] **Step 4: Add sticky heading calculation**

When `offset` begins after a group's original heading and before the next group heading, reserve one visible row and render only a muted, safely clipped group label. Suppress it if the original heading is visible or fewer than two body rows are available.

Use existing `styled_text(..., scheme.muted, context, dim=True)` and strip interactivity from the sticky copy.

- [ ] **Step 5: Implement grouped copy payloads and hit handling**

Add helpers:

```python
def _grouped_ranking_series_clipboard_text(group_label, label, description, link) -> str: ...
def _grouped_ranking_group_clipboard_text(group, visible_entries) -> str: ...
def _grouped_ranking_clipboard_all_text(visible_groups) -> str: ...
```

Series copy begins with group label. Group copy includes group label/description/link and visible projected concrete entries. Search Copy All contains only matches with group headings. Other and sticky headings receive no individual hit.

- [ ] **Step 6: Route grouped Dashboard panes to the new viewport**

In `_render_tui_custom_pane()` or the nearest existing Custom Ranking dispatch, choose grouped viewport only when `projection.groups is not None`. Keep flat `RankingViewport` state for flat projections and clear incompatible viewport state when switching partition mode.

- [ ] **Step 7: Run grouped viewport and TUI tests**

```bash
uv run pytest tests/test_custom_ranking_scroll.py tests/test_custom_ranking_dashboard_scroll.py tests/test_tui_custom.py tests/test_tui_dashboard.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit viewport and copying support**

```bash
git add src/ccusage_viz/render/grouped_ranking_viewport.py src/ccusage_viz/render/ranking_viewport.py src/ccusage_viz/tui.py tests/test_custom_ranking_scroll.py tests/test_custom_ranking_dashboard_scroll.py tests/test_tui_custom.py
git commit -m "feat: add grouped ranking viewport"
```

---

### Task 8: Implement Dashboard Controls, Advanced Spacing, Advanced Filters, and Muted Dashes

**Files:**
- Modify: `src/ccusage_viz/tui.py`
- Modify: `src/ccusage_viz/render/ranking_viewport.py`
- Modify: `src/ccusage_viz/render/custom_ranking_viewport.py`
- Modify: `src/ccusage_viz/render/grouped_ranking_viewport.py`
- Modify: `src/ccusage_viz/locales/en.py`
- Modify: `src/ccusage_viz/locales/zh.py`
- Test: `tests/test_tui_dashboard.py`
- Test: `tests/test_tui_custom.py`
- Test: `tests/test_custom_ranking_scroll.py`

**Interfaces:**
- Consumes: partition capability/config from Tasks 1 and 3.
- Produces: `_cycle_custom_partitioning(config, partitions, groupings, step) -> CustomChartConfig`.
- Produces: conflict-safe `_cycle_custom_grouping()` that skips active partition IDs.
- Produces: Quick `g/G=partition`, Quick `s/S=style`, Advanced `s/S=spacing`, and Dashboard-wide Advanced `f=filters`.
- Produces: muted ANSI styling for existing `dashed` separators.

- [ ] **Step 1: Write binding and cycling tests**

Add assertions equivalent to:

```python
def test_grouped_ranking_quick_and_advanced_bindings_are_page_scoped() -> None:
    quick = binding_map(partitioned_ranking_pane(), "quick")
    advanced = binding_map(partitioned_ranking_pane(), "advanced")
    assert quick["g/G"] == "partition"
    assert quick["s/S"] == "style"
    assert "f" not in quick
    assert advanced["s/S"] == "spacing"
    assert advanced["f"] == "filters"


def test_partition_and_group_cycles_skip_each_other() -> None:
    config = partitioned_config(partition_by="logical", group_by="real")
    assert cycle_partition(config, (None, "logical", "real"), +1).partition_by is None
    assert cycle_group(config, ("logical", "real", "provider"), +1).group_by == "provider"
```

Cover reverse cycling, required partitions without null, no legal alternative with restricted feedback, all historical chart filters removed from Quick, Monitor/built-in filters still Advanced, and Standalone filters unchanged.

- [ ] **Step 2: Write muted dashed tests**

Assert the mode name remains `dashed`, color output contains the active scheme's muted ANSI color plus dim style, and no-color/ascii output remains an ordinary dashed separator.

- [ ] **Step 3: Run control tests and verify failure**

```bash
uv run pytest tests/test_tui_dashboard.py tests/test_tui_custom.py tests/test_custom_ranking_scroll.py -q
```

Expected: failures because `g/G` still controls spacing on Quick, historical filters appear on Quick, and dashed output is unstyled.

- [ ] **Step 4: Move page-scoped actions**

For Custom Ranking:

- Quick adds `g/G partition` only when partition capability is declared and has more than one effective choice;
- Quick keeps common `s/S style`;
- Advanced adds `s/S spacing`;
- Advanced includes `f filters` when runtime filters exist.

Move all Dashboard filter bindings to Advanced, including Custom Timeline/Calendar/Stack. Do not change Standalone action construction.

- [ ] **Step 5: Implement conflict-safe cycling and query refresh**

`g/G` cycles declared partition values while skipping the active grouping. `b/B` cycles grouping values while skipping the active partition. Partition/group changes are data-affecting and issue a new query; spacing changes are presentation-only.

When partition capability is undeclared, do not expose `g/G` and keep existing flat behavior.

- [ ] **Step 6: Style dashed separators as muted**

Centralize separator generation so flat and grouped viewports call one helper:

```python
def ranking_separator(spacing: str, context: RenderContext) -> str:
    if spacing == "dashed":
        raw = ("- " * max(1, context.width // 2)).rstrip()
        return styled_text(raw, get_color_scheme(context.color_scheme).muted, context, dim=True)
    ...
```

Keep geometry based on display width, not ANSI byte length.

- [ ] **Step 7: Run Dashboard/viewport regressions**

```bash
uv run pytest tests/test_tui_dashboard.py tests/test_tui_custom.py tests/test_custom_ranking_scroll.py tests/test_options.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit interaction changes**

```bash
git add src/ccusage_viz/tui.py src/ccusage_viz/render/ranking_viewport.py src/ccusage_viz/render/custom_ranking_viewport.py src/ccusage_viz/render/grouped_ranking_viewport.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_tui_dashboard.py tests/test_tui_custom.py tests/test_custom_ranking_scroll.py
git commit -m "feat: add grouped ranking controls"
```

---

### Task 9: Document the Protocol and Complete Cross-Cutting Verification

**Files:**
- Modify: `docs/custom-command-protocol.md`
- Modify: `docs/custom-command-protocol.zh-CN.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Test: all affected suites

**Interfaces:**
- Consumes: final wire schema and UI behavior from Tasks 1–8.
- Produces: authoritative English and Chinese Dataset-author documentation with matching examples and compatibility rules.

- [ ] **Step 1: Update English protocol documentation**

Document:

- optional metric `capabilities.partition_by` catalog and fallback;
- Ranking `partition_by` capability including null/required semantics;
- defaults and equality constraints;
- old-field omission versus declared explicit null request behavior;
- flat `data.series` versus partitioned `data.groups` union;
- group metadata and stable identities;
- dated points and `all` behavior;
- Dataset-owned outer order;
- per-group sort/Top/Other and Dataset-determined response coverage;
- returned-item totals, shares, signed values, and zero denominators;
- search invariants;
- `--partition-by` and Dashboard controls.

Use the Router logical-model/real-model example from the spec without inventing additional business semantics.

- [ ] **Step 2: Update Chinese protocol documentation with equivalent normative rules**

Keep field names and JSON identical to English. Translate explanatory text, errors, and UI labels only.

- [ ] **Step 3: Add a concise README discoverability example**

Add one command and one sentence in each README:

```bash
ccuv chart ranking --dataset router --partition-by logical_model --group-by real_model
```

Explain that declared V2 Datasets can show one independently ranked real-model list per logical model.

- [ ] **Step 4: Run targeted tests**

```bash
uv run pytest \
  tests/test_custom_protocol.py \
  tests/test_custom_component.py \
  tests/test_custom_metric_switching.py \
  tests/test_command_copy.py \
  tests/test_dashboard_presets.py \
  tests/test_render.py \
  tests/test_custom_ranking_scroll.py \
  tests/test_custom_ranking_dashboard_scroll.py \
  tests/test_tui_custom.py \
  tests/test_tui_dashboard.py -q
```

Expected: PASS.

- [ ] **Step 5: Run the complete quality gate**

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run ty check
```

Expected: all commands pass. If `ty` exposes pre-existing unrelated diagnostics, record the exact baseline and ensure no changed file adds a new diagnostic; do not suppress new errors globally.

- [ ] **Step 6: Manually smoke-test old and new Dataset shapes**

Run one existing flat Dataset Ranking and verify its command request omits `partition_by`. Run a fixture/development Dataset that declares partition capability and verify:

```text
Logical Model → Real Model · Ranking
```

Then check `g/G`, `b/B`, Top/Other, search, refresh, scrolling, sticky heading, Copy All, `s/S` on both adjustment pages, and Advanced filters. Capture command logs to confirm explicit null is sent only for a partition-aware Dataset.

- [ ] **Step 7: Commit documentation and final verification changes**

```bash
git add docs/custom-command-protocol.md docs/custom-command-protocol.zh-CN.md README.md README.zh-CN.md
git commit -m "docs: describe grouped custom rankings"
```
