# Custom Historical Refresh Retention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retain the most recently accepted Custom Historical chart during a primary refresh, using the existing density-controlled refresh indication instead of a loading replacement.

**Architecture:** `CustomHistoricalComponent` already keeps its accepted projection in `model`; change only the two TUI render boundaries that currently discard it while `is_pending`. An initial request with no accepted model still uses `render_custom_pending`; an existing model is passed through `_render_custom_projection` with `pending=True`, which reuses `RenderAudit` and its existing density visibility behavior.

**Tech Stack:** Python 3, pytest, existing `ccusage_viz` TUI/rendering stack.

**Spec:** `docs/superpowers/specs/2026-10-14-custom-historical-refresh-retention-design.md`

## Global Constraints

- Apply to Custom Historical Timeline, Stack, Calendar, and Ranking in Dashboard and standalone surfaces.
- Do not alter query scheduling, range refresh, component pending state, accepted-result state, provider code, or Custom Monitor behavior.
- Keep `render_custom_pending()` as the fallback only when no accepted `model` is available.
- Use the existing `pending`/`RenderAudit` rendering path; do not add Custom-specific copy, icons, or rows.
- The refresh indication remains visible only at densities where existing audit-row rules show it.
- Preserve the existing user worktree changes; stage only files changed by this task.

---

## File Structure

- Modify `src/ccusage_viz/tui.py` — change Dashboard and standalone Custom Historical pending branches to retain and render accepted projections.
- Modify `tests/test_tui_custom.py` — replace placeholder-specific pending assertions with accepted-projection retention, initial-loading fallback, and density-driven refresh visibility tests.

### Task 1: Lock the retained Custom Historical refresh behavior with regression tests

**Files:**
- Modify: `tests/test_tui_custom.py: test_pending_metric_switch_rendering_uses_retried_active_timestamp_config`
- Modify: `tests/test_tui_custom.py: test_custom_standalone_replacement_renders_candidate_loading_placeholder`
- Test: `tests/test_tui_custom.py`

**Interfaces:**
- Consumes: `CustomHistoricalComponent.is_pending -> bool`, `CustomHistoricalComponent.model -> CustomChartProjection | CustomRankingProjection | None`, and `tui_module._custom_standalone_render(component, translator, terminal, *, pending, summary=None) -> PaneRender`.
- Consumes: `tui_module._pane_render(pane, translator, terminal) -> PaneRender` for Dashboard Custom pane coverage.
- Produces: tests defining that an accepted model is retained in both surfaces during pending work, while no accepted model still yields `render_custom_pending()` output.

- [ ] **Step 1: Replace the pending metric-switch placeholder test with retained-projection assertions**

Remove the `render_custom_pending` monkeypatch/capture from `test_pending_metric_switch_rendering_uses_retried_active_timestamp_config`. Keep its accepted ranking fixture and call to `begin_metric_switch(...)`, then assert that both render surfaces retain the accepted range/chart instead of rendering the target range placeholder:

```python
assert "2026-09-01–2026-09-02" in standalone.chart
assert "2026-09-01–2026-09-02" in dashboard.chart
assert "Ranking · 10m" not in standalone.chart
assert "Ranking · 10m" not in dashboard.chart
assert "Loading data…" not in standalone.chart
assert "Loading data…" not in dashboard.chart
```

Keep `pending=True` in the standalone invocation and keep the Dashboard pane construction unchanged. This verifies that the branch does not hide accepted chart facts merely because a primary request is pending.

- [ ] **Step 2: Add an explicit Dashboard periodic-refresh regression test**

Immediately after the existing standalone replacement test, add a test that accepts a normal ranking response, calls `component.configure(replace(component.candidate, date_range=...), data_affecting=True)`, wraps it in `TuiCustomPane`, and renders it through `_pane_render`. Use a `full` density chart and a sufficiently tall terminal. Assert the accepted ranking label/value remains in the result, assert the candidate date range is absent, and assert the existing refresh text is visible:

```python
def test_custom_dashboard_refresh_retains_accepted_ranking_with_visible_audit() -> None:
    # Build an accepted full-density Custom Ranking, then make a data-affecting refresh pending.
    ...
    rendered = _pane_render(pane, load_translator("en"), Terminal(100, 24, False, True))

    assert "accepted-series-label" in rendered.chart
    assert "2026-09-01–2026-09-02" in rendered.chart
    assert "2026-09-17–2026-09-30" not in rendered.chart
    assert "refreshing" in rendered.chart.lower()
```

Use labels and data from the existing Custom Historical response helpers so the test only verifies surface behavior, not projection construction. Match the exact localized refresh string already emitted by existing `RenderAudit` tests if the renderer capitalizes or styles it differently.

- [ ] **Step 3: Change the standalone replacement expectation from candidate loading to accepted-chart retention**

Rename `test_custom_standalone_replacement_renders_candidate_loading_placeholder` to `test_custom_standalone_refresh_retains_accepted_projection`. After accepting the first timeline response and making the replacement pending, assert the accepted chart remains and the candidate placeholder is absent:

```python
assert "时间趋势 · 2026-09-01–2026-09-02" in rendered.chart
assert "时间趋势 · 2026-09-17–2026-09-30" not in rendered.chart
assert "今日 阅读" in rendered.chart
assert "正在加载数据…" not in rendered.chart
```

Keep Chinese locale coverage so this regression verifies retained accepted configuration is used for localized chart chrome.

- [ ] **Step 4: Add the initial-load fallback and low-density audit tests**

Add two focused standalone tests:

```python
def test_custom_standalone_initial_pending_still_renders_loading_placeholder() -> None:
    component = CustomHistoricalComponent(chart)
    component.pending_generation = component.generation

    rendered = tui_module._custom_standalone_render(
        component, load_translator("en"), Terminal(80, 16, color=False, ascii=True), pending=True
    )

    assert "Loading data…" in rendered.chart


def test_custom_standalone_low_density_refresh_retains_chart_without_audit_row() -> None:
    # Accept a minimal-density timeline, make its next request pending, and render it.
    ...
    assert "accepted-series-label" in rendered.chart
    assert "refreshing" not in rendered.chart.lower()
```

For the initial test, configure the component to be pending only after it has no model; do not fabricate an accepted response. For the low-density test, use `presentation=replace(ChartPresentation(), density="minimal")`, accept a response, then use a data-affecting `configure` call. Use the same refresh wording asserted in Step 2, normalized by `lower()`, rather than introducing a new string.

- [ ] **Step 5: Run the focused tests and verify the current implementation fails**

Run:

```bash
uv run pytest tests/test_tui_custom.py \
  -k 'pending_metric_switch or custom_dashboard_refresh_retains or custom_standalone_refresh_retains or initial_pending or low_density_refresh' -v
```

Expected: FAIL. Current behavior routes every `component.is_pending` state to `render_custom_pending(...)`, so retained-chart assertions fail; the initial-loading fallback continues to pass.

- [ ] **Step 6: Commit the test contract**

```bash
git add tests/test_tui_custom.py
git commit -m "test: cover custom historical refresh retention"
```

### Task 2: Render accepted projections during Custom Historical refreshes

**Files:**
- Modify: `src/ccusage_viz/tui.py: dashboard Custom Historical rendering branch near _pane_render`
- Modify: `src/ccusage_viz/tui.py: _custom_standalone_render`
- Test: `tests/test_tui_custom.py`

**Interfaces:**
- Consumes: `component.model`, `component.is_pending`, `component.request_config`, `component.accepted_config`, and `_render_custom_projection(model, config, translator, terminal, *, accepted_at, interval, pending, surface, summary=None, ...) -> CustomRenderedProjection`.
- Produces: Dashboard and standalone `PaneRender` output that uses the accepted projection/configuration during an in-flight primary request.

- [ ] **Step 1: Update the Dashboard Custom Historical pending guard**

In the Custom Historical Dashboard rendering path, narrow the existing pending-placeholder branch so it runs only when there is no accepted projection:

```python
if component.is_pending and component.model is None:
    active_config = component.request_config
    context = _custom_render_context(
        active_config,
        translator,
        terminal,
        accepted_at=component.accepted_at,
        interval=pane.interval,
        pending=True,
        surface=dashboard_pane_surface(active_config.kind),
    )
    rendered = render_custom_pending(active_config, context, component.presentation)
    audit = render_audit(context)
    return PaneRender("\n".join(line for line in (rendered, audit) if line))
```

Leave the subsequent `if component.model is None` loading branch in place. With a model present, execution must reach `_render_custom_projection(...)`, whose existing `pending=component.is_pending or pane.lifecycle.submission is not None` argument supplies refresh state without changing the accepted config/model arguments.

- [ ] **Step 2: Update the standalone Custom Historical pending guard**

Make the identical guard change in `_custom_standalone_render`:

```python
if component.is_pending and component.model is None:
    active_config = component.request_config
    context = _custom_render_context(
        active_config,
        translator,
        terminal,
        accepted_at=component.accepted_at,
        interval=interval,
        pending=True,
        surface=standalone_surface(active_config.kind),
    )
    rendered = render_custom_pending(active_config, context)
    audit = render_audit(context)
    return PaneRender("\n".join(line for line in (rendered, audit) if line))
```

Do not pass `request_config` into the normal projection rendering path. Its current `component.accepted_config or component.candidate` expression resolves to the accepted config whenever an accepted model exists, which is required for an old chart to remain coherent during a changed-range or metric request.

- [ ] **Step 3: Run the focused regression tests**

Run:

```bash
uv run pytest tests/test_tui_custom.py \
  -k 'pending_metric_switch or custom_dashboard_refresh_retains or custom_standalone_refresh_retains or initial_pending or low_density_refresh' -v
```

Expected: PASS. The accepted-projection tests and the initial placeholder test all pass; full density shows the pre-existing audit refresh signal and minimal density omits that audit row.

- [ ] **Step 4: Run the relevant Custom rendering suite**

Run:

```bash
uv run pytest tests/test_tui_custom.py tests/test_custom_component.py tests/test_custom_ranking_dashboard_scroll.py -q
```

Expected: PASS. In particular, pending metric-switch, source-replacement, ranking viewport, and standalone Custom rendering coverage must remain green.

- [ ] **Step 5: Run static checks on modified production and test files**

Run:

```bash
uv run ruff check src/ccusage_viz/tui.py tests/test_tui_custom.py
uv run ruff format --check src/ccusage_viz/tui.py tests/test_tui_custom.py
```

Expected: both commands exit zero.

- [ ] **Step 6: Commit the implementation**

```bash
git add src/ccusage_viz/tui.py tests/test_tui_custom.py
git commit -m "fix: retain custom historical charts while refreshing"
```

## Plan Self-Review

- **Spec coverage:** Task 1 covers accepted-model retention, initial-load fallback, Dashboard/standalone paths, and density-dependent refresh visibility. Task 2 changes only the two designated render boundaries and explicitly preserves existing component, scheduler, error, and monitor behavior.
- **Placeholder scan:** No incomplete implementation instructions, unspecified tests, or deferred error handling remain.
- **Type consistency:** The plan uses existing `CustomHistoricalComponent`, `PaneRender`, `_pane_render`, `_custom_standalone_render`, and `_render_custom_projection` interfaces without adding a new interface or state field.
