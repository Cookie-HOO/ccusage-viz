# Preserve Top on Group Switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every built-in and Custom `b`/`B` grouping change preserve the exact current Top value, including `None`.

**Architecture:** The two existing shared adjustment boundaries own this behavior: `options.adjust_chart()` for built-in charts and `tui._cycle_custom_grouping()` for Custom charts. Remove their implicit `3`/`10` creation and ungrouped Timeline clearing, while retaining their grouping cycles and style-compatibility fallback unchanged.

**Tech Stack:** Python 3.11+, dataclasses, pytest, Ruff

**Spec:** `docs/superpowers/specs/2026-10-14-preserve-top-on-group-switch-design.md`

## Global Constraints

- Change only `b`/`B` grouping adjustments; do not change CLI defaults, Dataset descriptor defaults, metric-switch fallback, `+/-`, query, rendering, or persistence behavior.
- Grouping cycles must retain an exact existing `top`: `None` stays `None`; a positive integer stays identical.
- Preserve current grouping order and presentation-style compatibility fallback.
- Apply the invariant to built-in Timeline, Stack, Ranking, Monitor and to Custom historical and Monitor charts, in standalone and Dashboard paths through their shared helpers.

---

## File Structure

- `src/ccusage_viz/options.py` — owns built-in chart adjustment semantics used by standalone and Dashboard panes.
- `src/ccusage_viz/tui.py` — owns Custom Dataset grouping-cycle semantics shared by standalone Custom and Dashboard Custom panes.
- `tests/test_options.py` — unit tests for built-in `adjust_standalone()` grouping behavior.
- `tests/test_tui_custom.py` — unit tests for shared Custom grouping behavior, including Monitor.

### Task 1: Preserve Top across built-in grouping changes

**Files:**
- Modify: `tests/test_options.py` near `test_runtime_adjustments_replace_owned_nested_configs`
- Modify: `src/ccusage_viz/options.py:477-498`

**Interfaces:**
- Consumes: `adjust_standalone(config: StandaloneLaunch, key: str) -> StandaloneLaunch` and its delegation to `adjust_chart()`.
- Produces: existing `adjust_chart(chart, key, *, demo=False) -> ChartConfig` retains `chart.top` in its built-in `b/B` branch.

- [ ] **Step 1: Write failing built-in grouping-retention tests**

Add the following test in `tests/test_options.py` after `test_runtime_adjustments_replace_owned_nested_configs`:

```python
@pytest.mark.parametrize(
    ("chart", "key", "expected_by"),
    (
        (TimelineConfig("timeline", resolve_date_range("timeline", period="14d", since=None, until=None)), "b", "agent"),
        (StackConfig("stack", resolve_date_range("stack", period="14d", since=None, until=None), top=None), "b", "agent"),
        (RankingConfig("ranking", resolve_date_range("ranking", period="14d", since=None, until=None), top=None), "B", "composition"),
        (MonitorConfig("monitor", 3600, top=None), "b", "agent"),
    ),
)
def test_builtin_grouping_cycles_preserve_unbounded_top(chart, key, expected_by) -> None:
    source = StandaloneLaunch(ProcessConfig(), StandaloneHostConfig(), chart)

    updated = adjust_standalone(source, key)

    assert updated.chart.by == expected_by
    assert updated.chart.top is None


def test_builtin_grouping_cycles_preserve_explicit_top_in_both_directions() -> None:
    chart = TimelineConfig(
        "timeline",
        resolve_date_range("timeline", period="14d", since=None, until=None),
        by="model",
        top=7,
    )
    source = StandaloneLaunch(ProcessConfig(), StandaloneHostConfig(), chart)

    forward = adjust_standalone(source, "b")
    reverse = adjust_standalone(source, "B")

    assert (forward.chart.by, forward.chart.top) == ("project", 7)
    assert (reverse.chart.by, reverse.chart.top) == ("agent", 7)
```

Also add this assertion to prove a Timeline transition to total no longer clears an explicit selection:

```python
assert adjust_standalone(
    StandaloneLaunch(
        ProcessConfig(),
        StandaloneHostConfig(),
        TimelineConfig(
            "timeline",
            resolve_date_range("timeline", period="14d", since=None, until=None),
            by="composition",
            top=7,
        ),
    ),
    "b",
).chart.top == 7
```

- [ ] **Step 2: Run the new test selection and verify it fails**

Run:

```bash
uv run pytest tests/test_options.py -k 'builtin_grouping_cycles_preserve or runtime_adjustments_replace_owned_nested_configs' -q
```

Expected: FAIL because a `None` Top becomes `3` or `10`, and Timeline clears Top on its transition to `by=None`.

- [ ] **Step 3: Remove built-in implicit Top mutation**

In the `key in {"b", "B"}` branch of `adjust_chart()` in `src/ccusage_viz/options.py`, remove the local `top = ...` assignment. Change the return to carry the current value verbatim:

```python
return replace(chart, by=by, top=chart.top, presentation=presentation)
```

Do not alter `values`, `by`, `styles`, or `presentation` calculation. Do not alter the later `+/-` branches.

- [ ] **Step 4: Run built-in regression tests and verify they pass**

Run:

```bash
uv run pytest tests/test_options.py -k 'builtin_grouping_cycles_preserve or runtime_adjustments_replace_owned_nested_configs or stack_defaults_to_composition or monitor_list_is_available' -q
```

Expected: PASS. This demonstrates Top retention and preserves grouping/style behavior for Timeline, Stack, Ranking, and Monitor.

- [ ] **Step 5: Commit the built-in behavior change**

```bash
git add src/ccusage_viz/options.py tests/test_options.py
git commit -m "fix: preserve top while switching built-in groups"
```

### Task 2: Preserve Top across Custom grouping changes

**Files:**
- Modify: `tests/test_tui_custom.py` near `test_custom_monitor_grouping_cycles_from_total_in_declared_order`
- Modify: `src/ccusage_viz/tui.py:2736-2761`

**Interfaces:**
- Consumes: `_cycle_custom_grouping(config: CustomChartConfig, groupings: tuple[str | None, ...], *, step: int = 1) -> CustomChartConfig`.
- Produces: the same helper changes `group_by` and presentation compatibility only; it preserves `config.top` for Custom historical and Monitor callers.

- [ ] **Step 1: Write failing Custom grouping-retention tests**

Add the following tests in `tests/test_tui_custom.py` immediately before `test_custom_monitor_grouping_cycles_from_total_in_declared_order`:

```python
@pytest.mark.parametrize("step", (1, -1))
@pytest.mark.parametrize("top", (None, 6))
def test_custom_historical_grouping_cycles_preserve_top(step, top) -> None:
    chart = CustomChartConfig(
        "timeline",
        CustomCommandSource("reading", ("reader", "ccuv")),
        DateRange(date(2026, 10, 1), date(2026, 10, 8)),
        group_by=None,
        top=top,
    )

    updated = tui_module._cycle_custom_grouping(chart, (None, "book"), step=step)

    assert updated.group_by == "book"
    assert updated.top == top


def test_custom_historical_grouping_preserves_top_when_returning_to_total() -> None:
    chart = CustomChartConfig(
        "timeline",
        CustomCommandSource("reading", ("reader", "ccuv")),
        DateRange(date(2026, 10, 1), date(2026, 10, 8)),
        group_by="book",
        top=6,
    )

    updated = tui_module._cycle_custom_grouping(chart, (None, "book"))

    assert (updated.group_by, updated.top) == (None, 6)


@pytest.mark.parametrize("top", (None, 6))
def test_custom_monitor_grouping_cycles_preserve_top(top) -> None:
    chart = CustomChartConfig(
        "monitor",
        CustomCommandSource("router", ("router", "ccuv")),
        DateRange(date(2026, 10, 1), date(2026, 10, 8)),
        group_by=None,
        top=top,
    )

    updated = tui_module._cycle_custom_grouping(chart, (None, "model"))

    assert (updated.group_by, updated.top) == ("model", top)
```

- [ ] **Step 2: Run the new Custom tests and verify they fail**

Run:

```bash
uv run pytest tests/test_tui_custom.py -k 'custom_historical_grouping.*preserve_top or custom_monitor_grouping_cycles_preserve_top' -q
```

Expected: FAIL for the `top is None` cases because `_cycle_custom_grouping()` currently substitutes `3`; the return-to-total case currently clears `6`.

- [ ] **Step 3: Remove Custom implicit Top mutation**

In `_cycle_custom_grouping()` in `src/ccusage_viz/tui.py`:

1. In the `config.kind == "monitor"` return, replace:

```python
return replace(config, group_by=group_by, top=(config.top or 3) if group_by else None)
```

with:

```python
return replace(config, group_by=group_by, top=config.top)
```

2. In the final `replace()` call, replace:

```python
top=(config.top or 3) if group_by else None,
```

with:

```python
top=config.top,
```

Do not change the partition conflict logic, selected grouping, or compatible-style fallback.

- [ ] **Step 4: Run Custom grouping and related TUI tests and verify they pass**

Run:

```bash
uv run pytest tests/test_tui_custom.py -k 'custom_historical_grouping or custom_monitor_grouping or probe_capability_keeps_period_and_group_controls_after_rejected_query' -q
```

Expected: PASS. The shared helper is covered for historical and Monitor callers while existing capability-driven grouping behavior remains intact.

- [ ] **Step 5: Commit the Custom behavior change**

```bash
git add src/ccusage_viz/tui.py tests/test_tui_custom.py
git commit -m "fix: preserve top while switching custom groups"
```

### Task 3: Validate the completed shared adjustment contract

**Files:**
- Modify: none
- Test: `tests/test_options.py`, `tests/test_tui_custom.py`, `tests/test_tui_dashboard.py`

**Interfaces:**
- Consumes: completed built-in `adjust_chart()` and Custom `_cycle_custom_grouping()` contracts.
- Produces: validated behavior across the hosts that invoke those shared boundaries.

- [ ] **Step 1: Run the complete focused test suites**

Run:

```bash
uv run pytest tests/test_options.py tests/test_tui_custom.py tests/test_tui_dashboard.py -q
```

Expected: PASS. Dashboard uses the same built-in `adjust_standalone()` and Custom `_cycle_custom_grouping()` paths, so this checks host-level regressions without adding duplicated host-loop tests.

- [ ] **Step 2: Run Ruff on every changed source and test file**

Run:

```bash
uv run ruff check src/ccusage_viz/options.py src/ccusage_viz/tui.py tests/test_options.py tests/test_tui_custom.py
```

Expected: exit status 0.

- [ ] **Step 3: Inspect the final diff for scope compliance**

Run:

```bash
git diff HEAD~2..HEAD -- src/ccusage_viz/options.py src/ccusage_viz/tui.py tests/test_options.py tests/test_tui_custom.py
git status --short
```

Expected: only the two adjustment branches and their regression tests changed; unrelated pre-existing worktree changes and untracked files remain unmodified.

- [ ] **Step 4: Record validation in the final delivery**

Report the two implementation commits and the exact test/lint commands that passed. Do not make a validation-only commit.

## Plan Self-Review

- **Spec coverage:** Task 1 covers all built-in chart kinds through the shared branch, including forward/reverse cycling and Timeline total transition. Task 2 covers Custom historical and Monitor shared paths, including `None`, explicit integer, both directions, and total transition. Task 3 validates standalone and Dashboard suites plus lint and diff scope.
- **Placeholder scan:** No TBD/TODO, deferred implementation, or unspecified test steps remain.
- **Type consistency:** Tests use the existing `StandaloneLaunch`, chart config classes, `CustomChartConfig`, `adjust_standalone()`, and `_cycle_custom_grouping()` signatures; no new public interfaces are introduced.
