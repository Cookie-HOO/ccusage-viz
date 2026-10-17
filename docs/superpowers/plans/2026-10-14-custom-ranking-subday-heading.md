# Custom Ranking Subday Heading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render a rolling V2 Custom Ranking's compact configured subday period, such as `10m`, in its heading instead of full ISO-8601 bounds.

**Architecture:** `TimestampRange` already carries both precise bounds and rolling-range metadata. Update the `custom_heading()` presentation branch to use `TimestampRange.period` only when the range is marked `relative_until`; retain localized precise bounds for fixed timestamp intervals. This is a renderer-only change: querying, refreshing, and serialization remain untouched.

**Tech Stack:** Python 3, pytest, ccusage-viz renderer and Custom Dataset models.

**Spec:** `docs/superpowers/specs/2026-10-14-custom-ranking-subday-heading-design.md`

## Global Constraints

- Apply the change only to heading projection in `src/ccusage_viz/render/custom.py`.
- Do not recompute duration from `start_at` and `end_at`; use the stored `TimestampRange.period`.
- Preserve exact timestamp-range rendering for fixed timestamp intervals.
- Do not change Dataset request bounds, refresh semantics, Dashboard preset serialization, or date-based headings.

---

## File Structure

- Modify `src/ccusage_viz/render/custom.py`: select either the compact rolling-period label or the existing localized timestamp interval within `custom_heading()`.
- Modify `tests/test_custom_component.py`: replace the old rolling-range timestamp expectation with a compact-period regression and add a fixed-range timestamp regression.

### Task 1: Render rolling subday ranges as their configured period

**Files:**
- Modify: `tests/test_custom_component.py:1108-1130`
- Modify: `src/ccusage_viz/render/custom.py:140-151`

**Interfaces:**
- Consumes: `TimestampRange(start_at: datetime, end_at: datetime, relative_until: bool, period: str | None)` from `ccusage_viz.core.custom_ranking_time`.
- Produces: `custom_heading(config: CustomChartConfig, context: RenderContext, descriptor: CustomPresentationDescriptor | None = None) -> str`, whose rolling timestamp-range output contains `period` and omits ISO timestamps.

- [ ] **Step 1: Write the failing rolling-range regression**

Replace `test_timestamp_heading_uses_exact_aware_half_open_bounds` with this test. It retains an aware rolling range and asserts that the stored period is the display contract rather than an inferred duration:

```python
def test_relative_timestamp_heading_uses_configured_period() -> None:
    interval = TimestampRange(
        datetime.fromisoformat("2026-10-15T11:50:00+08:00"),
        datetime.fromisoformat("2026-10-15T12:00:00+08:00"),
        relative_until=True,
        period="10m",
    )
    chart = config(kind="ranking", metric_id="reading_time", date_range=interval)

    heading = custom.custom_heading(
        chart,
        RenderContext(120, 20, load_translator("en"), color=False),
    )

    assert heading.endswith(" · 10m")
    assert "2026-10-15T" not in heading
```

- [ ] **Step 2: Run the regression and verify it fails**

Run:

```bash
pytest tests/test_custom_component.py::test_relative_timestamp_heading_uses_configured_period -v
```

Expected: FAIL because the current renderer emits `label.timestamp_range`, including `2026-10-15T`.

- [ ] **Step 3: Implement the minimal heading selection**

In the `isinstance(config.date_range, TimestampRange)` branch of `custom_heading()`, replace unconditional timestamp localization with this conditional selection. Keep construction of `heading` and `title_content` handling exactly as it is:

```python
if config.date_range.relative_until and config.date_range.period is not None:
    range_label = config.date_range.period
else:
    range_label = context.translator.text(
        "label.timestamp_range",
        start_at=config.date_range.start_at.isoformat(),
        end_at=config.date_range.end_at.isoformat(),
    )
heading = f"{title} · {range_label}"
```

- [ ] **Step 4: Run the regression and verify it passes**

Run:

```bash
pytest tests/test_custom_component.py::test_relative_timestamp_heading_uses_configured_period -v
```

Expected: PASS; the heading ends in ` · 10m` and contains no ISO timestamp prefix.

- [ ] **Step 5: Commit the rolling-heading change**

```bash
git add src/ccusage_viz/render/custom.py tests/test_custom_component.py
git commit -m "fix: show custom ranking subday period in heading"
```

### Task 2: Preserve explicit fixed timestamp headings

**Files:**
- Modify: `tests/test_custom_component.py` adjacent to `test_relative_timestamp_heading_uses_configured_period`

**Interfaces:**
- Consumes: the Task 1 `custom_heading()` behavior and a fixed `TimestampRange` with `relative_until=False` and no period.
- Produces: a regression ensuring fixed timestamp headings continue to use `label.timestamp_range` with both ISO-8601 bounds.

- [ ] **Step 1: Write the fixed-range regression**

Add this test directly after the rolling-range test:

```python
def test_fixed_timestamp_heading_uses_exact_aware_half_open_bounds() -> None:
    interval = TimestampRange(
        datetime.fromisoformat("2026-10-15T11:50:00+08:00"),
        datetime.fromisoformat("2026-10-15T12:00:00+08:00"),
    )
    chart = config(kind="ranking", metric_id="reading_time", date_range=interval)

    heading = custom.custom_heading(
        chart,
        RenderContext(120, 20, load_translator("en"), color=False),
    )

    assert "[2026-10-15T11:50:00+08:00, 2026-10-15T12:00:00+08:00)" in heading
```

- [ ] **Step 2: Run the focused tests and verify they pass**

Run:

```bash
pytest tests/test_custom_component.py -k "timestamp_heading" -v
```

Expected: PASS; the relative case shows `10m`, and the fixed case retains exact half-open bounds.

- [ ] **Step 3: Run the full affected test module**

Run:

```bash
pytest tests/test_custom_component.py -v
```

Expected: PASS; existing date-only summaries and Custom historical component behavior remain unchanged.

- [ ] **Step 4: Commit the fixed-range regression**

```bash
git add tests/test_custom_component.py
git commit -m "test: preserve fixed custom ranking timestamp heading"
```
