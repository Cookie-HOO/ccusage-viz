# Ranking List and Monitor Ranking-Dot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add text-only historical Ranking lists and dot-prefixed Monitor rankings across native and Custom Dataset surfaces.

**Architecture:** Extend the central style registry so CLI, TUI, Dashboard, and persisted presentation normalization expose the two styles consistently. Reuse the shared Ranking renderer: its existing historical list path becomes selectable for Ranking, while its observed-ranking path adds a leading marker only for `ranking-dot`; Monitor and Custom Monitor classify that style as a Ranking projection.

**Tech Stack:** Python 3.12, pytest, terminal ANSI rendering, existing chart options and shared ranking renderer.

**Spec:** `docs/superpowers/specs/2026-10-13-ranking-list-monitor-ranking-dot-design.md`

## Global Constraints

- Historical Ranking supports `dot`, `bar`, `dots`, and `list`; `list` renders no proportional bar, dot track, or filled graphic.
- Monitor supports `ranking-dot` alongside existing styles.
- `ranking-dot` must preserve existing Ranking model, grouping, refresh, observation, description, animation, and ranking-like controls.
- Its marker uses the entry categorical palette color, with aligned no-color and ASCII fallback.
- Changes are presentation-only: no provider request, ordering, aggregation, baseline, refresh, retained-observation, search, scroll, description, or export behavior changes.
- Native and Custom Dataset Monitor paths must behave consistently.

---

## File Structure

- `src/ccusage_viz/options.py`: Canonical selectable style tuples and ranking-like Monitor predicates.
- `src/ccusage_viz/monitor_component.py`: Native Monitor style-to-model projection.
- `src/ccusage_viz/render/custom_monitor.py`: Custom Monitor style-to-renderer projection.
- `src/ccusage_viz/render/ranking.py`: Observed Monitor row marker rendering and list geometry.
- `src/ccusage_viz/monitor.py`, `src/ccusage_viz/tui.py`: Existing ranking-like style guards expanded to include `ranking-dot` where relevant.
- `tests/test_options.py`, `tests/test_monitor_component.py`, `tests/test_custom_monitor.py`, `tests/test_render.py`: Regression coverage for selection, projection, and rendering.

### Task 1: Register the two selectable styles

**Files:**
- Modify: `src/ccusage_viz/options.py`
- Test: `tests/test_options.py`

**Interfaces:**
- Produces: `COMMAND_STYLES["ranking"]` containing `"list"` and `COMMAND_STYLES["monitor"]` containing `"ranking-dot"`.
- Produces: a shared `is_monitor_ranking_style(style: str) -> bool` predicate returning true for `ranking`, `ranking-dot`, and `list`.
- Consumes: existing `compatible_styles()` and `adjust_standalone()` style cycling.

- [ ] **Step 1: Write failing style-availability and cycle tests**

```python
def test_ranking_and_monitor_ranking_dot_styles_are_selectable() -> None:
    assert "list" in compatible_styles("ranking", None)
    assert "ranking-dot" in compatible_styles("monitor", None)

    ranking = StandaloneLaunch(
        RankingConfig("ranking", resolve_date_range("ranking", period="7d", since=None, until=None))
    )
    assert adjust_standalone(ranking, "s").chart.presentation.style == "bar"
    assert adjust_standalone(adjust_standalone(adjust_standalone(ranking, "s"), "s"), "s").chart.presentation.style == "list"
```

Add a Monitor cycle assertion from `ranking` to `ranking-dot`, preserving the established ordering around `list`.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `uv run pytest tests/test_options.py -k 'ranking_and_monitor_ranking_dot_styles_are_selectable' -v`

Expected: FAIL because `list` is unavailable for Ranking and `ranking-dot` is unavailable for Monitor.

- [ ] **Step 3: Add canonical styles and the shared predicate**

```python
COMMAND_STYLES = {
    # ...
    "ranking": ("dot", "bar", "dots", "list"),
    "monitor": (
        "bars", "line", "step", "points", "line-points",
        "ranking", "ranking-dot", "list", "cumulative-bars",
    ),
}


def is_monitor_ranking_style(style: str) -> bool:
    return style in {"ranking", "ranking-dot", "list"}
```

Replace the local `{"ranking", "list"}` checks in `options.py` with `is_monitor_ranking_style()` where they describe Monitor ranking-like behavior.

- [ ] **Step 4: Run options tests**

Run: `uv run pytest tests/test_options.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the style registry work**

```bash
git add src/ccusage_viz/options.py tests/test_options.py
git commit -m "feat: add ranking list and monitor dot styles"
```

### Task 2: Project `ranking-dot` as a shared Monitor Ranking model

**Files:**
- Modify: `src/ccusage_viz/monitor_component.py`
- Modify: `src/ccusage_viz/render/custom_monitor.py`
- Test: `tests/test_monitor_component.py`
- Test: `tests/test_custom_monitor.py`

**Interfaces:**
- Consumes: `is_monitor_ranking_style(style: str) -> bool` from `options.py`.
- Produces: `MonitorComponent.model()` returns `RankingModel` for `ranking-dot`.
- Produces: `render_custom_monitor()` routes `ranking-dot` to `render_ranking()`.

- [ ] **Step 1: Write failing native and Custom Monitor projection tests**

```python
def test_ranking_dot_style_projects_monitor_to_ranking_model() -> None:
    component = monitor_component_with_style("ranking-dot")
    assert isinstance(component.model(now=10.0, count=20), RankingModel)


def test_custom_monitor_ranking_dot_uses_ranking_heading() -> None:
    component = custom_monitor_component_with_style("ranking-dot")
    rendered = render_custom_monitor(component, RenderContext(80, 20, load_translator("en")))
    assert component.heading(language="en") in rendered
```

Use the existing fixtures/builders in each test module rather than adding parallel test infrastructure.

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `uv run pytest tests/test_monitor_component.py tests/test_custom_monitor.py -k 'ranking_dot' -v`

Expected: FAIL because native Monitor treats the style as Timeline and Custom Monitor calls `render_timeline()`.

- [ ] **Step 3: Route the style through the existing Ranking paths**

```python
from ccusage_viz.options import is_monitor_ranking_style

# MonitorComponent.model()
if is_monitor_ranking_style(chart.presentation.style):
    return self.ranking_model(now=now, count=count, wall=wall)

# render_custom_monitor()
if is_monitor_ranking_style(style):
    return _replace_heading(
        render_ranking(component.ranking_model(language=context.translator.language), context),
        heading,
        context,
    )
```

- [ ] **Step 4: Run native and Custom Monitor regression tests**

Run: `uv run pytest tests/test_monitor_component.py tests/test_custom_monitor.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the projection work**

```bash
git add src/ccusage_viz/monitor_component.py src/ccusage_viz/render/custom_monitor.py tests/test_monitor_component.py tests/test_custom_monitor.py
git commit -m "feat: project monitor dot style as ranking"
```

### Task 3: Render the categorical Monitor dot without changing normal ranking

**Files:**
- Modify: `src/ccusage_viz/render/ranking.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: observed `RankingModel`, `ScalarRankingEntry`, and `RenderContext.style == "ranking-dot"`.
- Produces: one leading per-entry marker in the observed row; normal `ranking` and `list` output remains unchanged.

- [ ] **Step 1: Write failing renderer tests for color and fallback output**

```python
def test_observed_ranking_dot_prefixes_each_entry_with_a_marker() -> None:
    rendered = render_ranking(
        observed_ranking_model(),
        RenderContext(80, 20, load_translator("en"), color=False, style="ranking-dot"),
    )
    rows = rendered.splitlines()[1:]
    assert all(row.lstrip().startswith("● ") for row in rows)


def test_observed_ranking_dot_uses_ascii_marker_in_ascii_mode() -> None:
    rendered = render_ranking(
        observed_ranking_model(),
        RenderContext(80, 20, load_translator("en"), color=False, ascii=True, style="ranking-dot"),
    )
    assert "o " in rendered
```

Also assert a `style="ranking"` fixture has no newly introduced leading dot.

- [ ] **Step 2: Run the focused renderer tests to verify they fail**

Run: `uv run pytest tests/test_render.py -k 'ranking_dot' -v`

Expected: FAIL because the observed renderer treats `ranking-dot` as a bar-like style and has no leading marker.

- [ ] **Step 3: Add a marker before each observed ranking row**

In `render_ranking()`, derive the per-entry color from the existing entry semantics (`scheme.other` for Other, otherwise `scheme.highlight`) and construct:

```python
ranking_dot = (
    colored_mark("o" if context.ascii else "●", entry_color, context) + " "
    if context.style == "ranking-dot"
    else ""
)
```

Prefix both observed list-layout and chart-layout rows with `ranking_dot`. Reduce the observed available row geometry by `display_width(ranking_dot)` so values remain within `context.width`. Treat `ranking-dot` as the normal `ranking` graphic branch for the proportional mark; only the leading categorical marker is new.

- [ ] **Step 4: Run renderer regressions**

Run: `uv run pytest tests/test_render.py -k 'ranking or observed' -q`

Expected: PASS.

- [ ] **Step 5: Commit renderer work**

```bash
git add src/ccusage_viz/render/ranking.py tests/test_render.py
git commit -m "feat: render monitor ranking dots"
```

### Task 4: Apply ranking-like controls and animation eligibility

**Files:**
- Modify: `src/ccusage_viz/monitor.py`
- Modify: `src/ccusage_viz/tui.py`
- Test: `tests/test_monitor.py`
- Test: `tests/test_tui.py`

**Interfaces:**
- Consumes: `is_monitor_ranking_style(style: str) -> bool`.
- Produces: `ranking-dot` hides ineffective Monitor window controls and is eligible for existing Monitor ranking/list animation controls in standalone and Dashboard UI.

- [ ] **Step 1: Write failing control tests**

```python
def test_ranking_dot_uses_ranking_like_monitor_controls() -> None:
    chart = MonitorConfig("monitor", 3600, presentation=ChartPresentation(style="ranking-dot"))
    assert not monitor_window_adjustment_available(chart)
    assert animation_actions_for_monitor(chart)
```

Use existing action/helper tests in `tests/test_monitor.py` and `tests/test_tui.py`; assert the actual existing labels or action tuples rather than inventing a production helper if none exists.

- [ ] **Step 2: Run focused control tests to verify they fail**

Run: `uv run pytest tests/test_monitor.py tests/test_tui.py -k 'ranking_dot' -v`

Expected: FAIL because guards only recognize `ranking` and `list`.

- [ ] **Step 3: Replace all Monitor ranking/list style guards with the predicate**

Import `is_monitor_ranking_style` in `monitor.py` and `tui.py`. Replace only checks that govern Monitor controls, animation attachment, or ranking-model rendering; leave historical Ranking checks untouched.

```python
if is_monitor_ranking_style(chart.presentation.style):
    # Existing ranking/list behavior unchanged.
```

Do not alter controls for Timeline, cumulative-bars, or historical Ranking.

- [ ] **Step 4: Run Monitor and TUI regressions**

Run: `uv run pytest tests/test_monitor.py tests/test_tui.py tests/test_tui_custom.py -q`

Expected: PASS.

- [ ] **Step 5: Commit UI parity work**

```bash
git add src/ccusage_viz/monitor.py src/ccusage_viz/tui.py tests/test_monitor.py tests/test_tui.py
git commit -m "feat: support monitor dot ranking controls"
```

### Task 5: Validate complete presentation coverage

**Files:**
- Verify: `src/ccusage_viz/options.py`
- Verify: `src/ccusage_viz/monitor_component.py`
- Verify: `src/ccusage_viz/render/custom_monitor.py`
- Verify: `src/ccusage_viz/render/ranking.py`
- Verify: `src/ccusage_viz/monitor.py`
- Verify: `src/ccusage_viz/tui.py`
- Verify: `tests/test_options.py`
- Verify: `tests/test_monitor_component.py`
- Verify: `tests/test_custom_monitor.py`
- Verify: `tests/test_render.py`

- [ ] **Step 1: Run formatting and static checks**

Run: `uv run ruff check src/ccusage_viz/options.py src/ccusage_viz/monitor_component.py src/ccusage_viz/render/custom_monitor.py src/ccusage_viz/render/ranking.py src/ccusage_viz/monitor.py src/ccusage_viz/tui.py tests/test_options.py tests/test_monitor_component.py tests/test_custom_monitor.py tests/test_render.py tests/test_monitor.py tests/test_tui.py`

Expected: PASS.

- [ ] **Step 2: Run the focused complete test suite**

Run: `uv run pytest tests/test_options.py tests/test_monitor_component.py tests/test_custom_monitor.py tests/test_render.py tests/test_monitor.py tests/test_tui.py tests/test_tui_custom.py -q`

Expected: PASS.

- [ ] **Step 3: Inspect final diff and commit verification record if needed**

Run: `git diff HEAD~4..HEAD --check && git status --short`

Expected: no whitespace errors and a clean working tree.

## Plan Self-Review

- **Spec coverage:** Task 1 exposes both styles; Task 2 covers native and Custom projection; Task 3 covers graphical, color, and ASCII rendering; Task 4 covers ranking-like Monitor controls and animations; Task 5 verifies the complete focused suite. All behavior remains presentation-only by reusing existing models and render paths.
- **Placeholder scan:** No undefined implementation interfaces, TBDs, or deferred test descriptions remain.
- **Type consistency:** `is_monitor_ranking_style(style: str) -> bool` is introduced in Task 1 and consumed consistently in Tasks 2 and 4; `ranking-dot` is the exact style literal throughout.
