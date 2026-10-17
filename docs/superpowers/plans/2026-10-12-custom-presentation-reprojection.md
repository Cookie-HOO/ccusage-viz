# Custom Presentation Reprojection Bypass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make renderer-only Custom historical configuration changes reuse the accepted projection in O(1) instead of running `process_custom_historical()` over the full accepted response.

**Architecture:** Add a pure local-projection impact predicate alongside the existing query replacement predicate. `CustomHistoricalComponent.configure()` continues to reproject Top/Other/comparison changes, but renderer-only changes replace only the immutable projection's `config` reference and preserve series identity; existing comparison scheduling remains unchanged.

**Tech Stack:** Python 3.11+, frozen dataclasses, pytest, Ruff, uv; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-12-custom-presentation-reprojection-design.md`

## Global Constraints

- Theme, style, density, legend, and equivalent renderer-only changes make zero calls to `process_custom_historical()` when a compatible accepted model exists.
- Renderer-only changes preserve `model.series`, `model.days`, `model.unit`, `model.presentation`, `comparison_available`, and `show_percentage` identity/value.
- `top`, `other`, and `ranking_comparison` retain local `_reproject()` behavior.
- Query-identity changes retain existing `data_affecting=True` behavior and must not replace accepted facts through this fast path.
- Density transitions retain existing comparison-request scheduling and matching rules.
- No new cache, worker, dependency, persistence field, or input binding.
- The six established full-suite failures remain the comparison baseline.

---

### Task 1: Define and test the local projection boundary

**Files:**
- Modify: `src/ccusage_viz/custom_component.py`
- Test: `tests/test_custom_component.py`

**Interfaces:**
- Produces: `custom_projection_replacement_required(current: CustomChartConfig, updated: CustomChartConfig) -> bool`.
- The predicate is independent from `custom_replacement_required()`: query replacement remains unchanged.

- [ ] **Step 1: Write failing predicate tests**

```python
@pytest.mark.parametrize(
    "updated",
    (
        lambda value: replace(value, presentation=replace(value.presentation, theme="dracula")),
        lambda value: replace(value, presentation=replace(value.presentation, style="list")),
        lambda value: replace(value, presentation=replace(value.presentation, density="minimal")),
        lambda value: replace(value, presentation=replace(value.presentation, legend="none")),
        lambda value: replace(value, weekdays="hide"),
    ),
)
def test_renderer_only_changes_do_not_require_custom_reprojection(updated) -> None:
    current = config(kind="ranking", top=10)
    assert not custom_projection_replacement_required(current, updated(current))
```

```python
@pytest.mark.parametrize(
    "updated",
    (
        lambda value: replace(value, top=1),
        lambda value: replace(value, other="hide"),
        lambda value: replace(value, ranking_comparison="none"),
    ),
)
def test_local_projection_changes_require_custom_reprojection(updated) -> None:
    current = config(kind="ranking", top=10)
    assert custom_projection_replacement_required(current, updated(current))
```

- [ ] **Step 2: Run tests and confirm the helper is missing**

Run: `uv run pytest -o addopts='' tests/test_custom_component.py -k custom_reprojection -v`

Expected: FAIL because `custom_projection_replacement_required` is not defined.

- [ ] **Step 3: Implement the pure predicate**

Add the helper beside `custom_replacement_required()`. Compare only fields consumed by `process_custom_historical()` after query-compatible accepted data already exists. At minimum return true for changes in `top`, `other`, and `ranking_comparison`; renderer-owned `presentation` and `weekdays` changes return false. Do not weaken query replacement checks.

```python
def custom_projection_replacement_required(
    current: CustomChartConfig, updated: CustomChartConfig
) -> bool:
    return (
        current.top != updated.top
        or current.other != updated.other
        or current.ranking_comparison != updated.ranking_comparison
    )
```

- [ ] **Step 4: Run focused predicate tests**

Run: `uv run pytest -o addopts='' tests/test_custom_component.py -k 'replacement_required or custom_reprojection' -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/custom_component.py tests/test_custom_component.py
git commit -m "refactor: classify custom projection changes"
```

### Task 2: Bypass reprojection for renderer-only changes

**Files:**
- Modify: `src/ccusage_viz/custom_component.py`
- Test: `tests/test_custom_component.py`

**Interfaces:**
- `CustomHistoricalComponent.configure(config, *, data_affecting=False)` keeps its public signature.
- Fast path updates `accepted_config` and uses `replace(self.model, config=config)` while preserving projection facts.

- [ ] **Step 1: Write the failing processor-call and identity tests**

```python
@pytest.mark.parametrize(
    "presentation",
    (
        ChartPresentation(theme="dracula"),
        ChartPresentation(style="list"),
        ChartPresentation(density="minimal"),
    ),
)
def test_renderer_only_config_reuses_accepted_projection(
    monkeypatch: pytest.MonkeyPatch, presentation: ChartPresentation
) -> None:
    component = CustomHistoricalComponent(config(kind="ranking", top=None))
    assert component.accept_response(response())
    model = component.model
    assert model is not None
    revision = component.render_revision
    calls = []

    monkeypatch.setattr(
        custom_component_module,
        "process_custom_historical",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    updated = replace(component.candidate, presentation=presentation)
    component.configure(updated, data_affecting=False)

    assert calls == []
    assert component.accepted_config == updated
    assert component.model is not model
    assert component.model.config == updated
    assert component.model.series is model.series
    assert component.model.days is model.days
    assert component.render_revision == revision + 1
```

Add a local-projection test that spies on the processor while changing `top`, `other`, and `ranking_comparison`, delegates to the real processor, and asserts one call plus correct output.

- [ ] **Step 2: Run tests to prove renderer-only changes currently reproject**

Run: `uv run pytest -o addopts='' tests/test_custom_component.py -k 'renderer_only_config or local_projection_config' -v`

Expected: renderer-only test FAILS because `configure()` calls `_reproject()`.

- [ ] **Step 3: Implement the O(1) fast path**

Inside the existing compatible accepted-state branch:

```python
self.accepted_config = config
if custom_projection_replacement_required(previous_accepted, config) or self.model is None:
    self._reproject()
else:
    self.model = replace(self.model, config=config)
```

Capture the previous accepted config before replacement. Preserve the current guards for accepted response/config, pending state, and `custom_replacement_required()`. Do not alter `generation`, pending fields, comparison responses, or scheduler state.

- [ ] **Step 4: Add edge-state tests**

Test that:
- source/query-incompatible non-data-affecting config leaves accepted model/config identities unchanged;
- renderer-only change while pending does not replace accepted facts;
- missing-model state uses conservative `_reproject()` when accepted response/config are available;
- each accepted renderer-only configure increments `render_revision` once.

- [ ] **Step 5: Run component tests**

Run: `uv run pytest -o addopts='' tests/test_custom_component.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ccusage_viz/custom_component.py tests/test_custom_component.py
git commit -m "perf: bypass custom presentation reprojection"
```

### Task 3: Protect comparison and Dashboard integration

**Files:**
- Modify: `tests/test_custom_component.py`
- Modify only if a defect is exposed: `src/ccusage_viz/custom_component.py`
- Modify only if needed for an assertion: `tests/test_custom_ranking_dashboard_scroll.py`

**Interfaces:**
- `comparison_request_config()` remains authoritative.
- Dashboard `d/t/s` path performs no primary reprojection or query work.

- [ ] **Step 1: Add comparison-density transition tests**

Start with accepted primary data and verify:

```python
component.configure(
    replace(component.candidate, presentation=replace(component.candidate.presentation, density="detailed")),
    data_affecting=False,
)
assert component.comparison_request_config() is not None
assert component.model.series is original_series
```

Then attach a matching comparison response through the existing lifecycle, change to minimal density, and assert primary series values remain stable while `comparison_request_config()` becomes `None`. Change back to detailed and assert only matching accepted comparison facts are reused through the existing reproject lifecycle.

- [ ] **Step 2: Run comparison and Dashboard tests**

Run:

```bash
uv run pytest -o addopts='' \
  tests/test_custom_component.py -k 'comparison or renderer_only' \
  tests/test_custom_ranking_dashboard_scroll.py -k presentation -q
```

Expected: PASS without production TUI changes.

- [ ] **Step 3: Run broader Custom regressions**

Run:

```bash
uv run pytest -o addopts='' \
  tests/test_custom_component.py \
  tests/test_tui_custom.py \
  tests/test_custom_ranking_scroll.py \
  tests/test_custom_ranking_dashboard_scroll.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit test-only additions if separate**

```bash
git add src/ccusage_viz/custom_component.py tests/test_custom_component.py tests/test_custom_ranking_dashboard_scroll.py
git commit -m "test: preserve custom comparison presentation lifecycle"
```

### Task 4: Verify the profiled fast path

**Files:** Review only files changed in Tasks 1–3.

- [ ] **Step 1: Run lint and whitespace checks**

```bash
uv run ruff check src tests
git diff --check
```

Expected: PASS.

- [ ] **Step 2: Run focused feature suites**

```bash
uv run pytest -o addopts='' \
  tests/test_custom_component.py \
  tests/test_tui_custom.py \
  tests/test_custom_ranking_scroll.py \
  tests/test_custom_ranking_dashboard_scroll.py \
  tests/test_dashboard_repaint.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full suite**

Run: `uv run pytest -q`

Expected: no new failures beyond the established six-test baseline in `test_text_viewport.py`, `test_tui_dashboard.py`, and `test_tui_header.py`.

- [ ] **Step 4: Inspect scope**

```bash
git status --short
git diff --check HEAD~3..HEAD
```

Expected: clean working tree and only component/tests/docs changes associated with this optimization.

## Self-review

- **Spec coverage:** Task 1 defines the field boundary; Task 2 implements and proves O(1) renderer changes; Task 3 protects comparison and Dashboard behavior; Task 4 performs focused/full validation.
- **Placeholder scan:** No placeholders or undefined interfaces remain.
- **Type consistency:** The predicate accepts `CustomChartConfig`; the fast path operates on existing frozen `CustomChartProjection` via `dataclasses.replace`.
