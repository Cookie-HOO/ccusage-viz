# Unified Chart Naming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify chooser labels and rendered chart headings around localized Metric-first names, compact grouping/period syntax, Monitor view names, and deterministic narrow-pane reduction.

**Architecture:** Add one presentation-only heading module that receives semantic heading fields and chooses a width-fitting candidate without changing query/configuration identity. Keep chooser-only bilingual labels in localization, route built-in and Dataset historical renderers through the shared composer, then route built-in and Dataset Monitor renderers through the same composer with view-family and muted inline status metadata.

**Tech Stack:** Python 3.11–3.13, dataclasses, existing `Translator`, ANSI-aware formatting helpers, pytest, Ruff/ty through the project’s existing `uv` workflow.

**Spec:** `docs/superpowers/specs/2026-10-14-chart-naming-design.md`

## Global Constraints

- Do not rename `timeline`, `calendar`, `stack`, `ranking`, or `monitor` in CLI commands, persisted configuration, protocol payloads, or Python identifiers.
- Chinese canonical historical names are exactly `时间趋势`, `活跃日历`, `分组构成`, and `累计排名`; English historical names are exactly `Timeline`, `Calendar`, `Stack`, and `Ranking`.
- Chinese chooser entries include the English short type in parentheses; English chooser entries do not repeat it.
- Pane chooser group order is exactly `ccusage` → `自定义`/`Custom` → `其他`/`Other`; headings are not selectable.
- Keep `数据集…`/`Datasets…` as a second-level entry; do not flatten Dataset, Metric, or chart combinations into the Pane chooser.
- Preserve the existing Animation, Dataset, and Empty entry wording.
- Historical headings follow `Metric · chart · by dimension · period`; ungrouped headings omit `Total`.
- Partitioned Ranking uses `by partition → dimension`.
- Monitor rendered headings omit `Monitor` and use `趋势`/`Trend`, `排名`/`Ranking`, `列表`/`List`, or `累计柱`/`Cumulative bars`.
- Monitor headings show only the factual data window as `{duration} 窗口` / `{duration} window`; never add the local display horizon or sampling interval.
- Non-ready Monitor status stays inline, parenthesized, and muted/dim; ready status is omitted.
- Dataset V2 headings use localized `metric.title`; do not substitute Dataset name, Metric ID, or unit when a Metric title exists.
- Narrow-title reduction removes dimension first, then period/window, then width-truncates the Metric; use terminal display width and preserve ANSI/CJK correctness.
- Do not add Dataset names, filter summaries, `Total`, drawing-style details, or English type names to Chinese rendered chart headings.
- The working tree already contains unrelated edits. Never stage, reset, reformat, or commit files outside the current task’s explicit file list.

---

## File Structure

- Create `src/ccusage_viz/render/headings.py`: localized chart/view naming, semantic heading fields, candidate reduction, muted inline status, and width-safe composition.
- Create `tests/test_chart_headings.py`: focused unit tests for heading composition independent of plot geometry.
- Modify `src/ccusage_viz/locales/en.py` and `src/ccusage_viz/locales/zh.py`: canonical names, chooser-only labels/groups, `by` relationship, Monitor window/status copy.
- Modify `src/ccusage_viz/tui.py`: grouped chooser order and both blocking/modal chooser presentations.
- Modify `tests/test_tui_layout.py` and `tests/test_tui_dashboard.py`: chooser grouping, labels, navigation, and modal parity.
- Modify historical render files (`timeline.py`, `calendar.py`, `stack.py`, `ranking.py`, `custom.py`, `historical_render.py`): provide semantic Metric/chart/dimension/range fields to the shared composer.
- Modify Monitor render/component files (`timeline.py`, `ranking.py`, `monitor_distribution.py`, `custom_monitor.py`, `custom_monitor_component.py`): provide view family, factual window, and transient status to the shared composer.
- Modify renderer/component tests where old title assertions encode the replaced naming contract.
- Modify `README.md`, `README.zh-CN.md`, `docs/usage.md`, and `docs/usage.zh-CN.md`: use canonical user-visible names while retaining backticked CLI kinds.

---

### Task 1: Shared Semantic Heading Composer

**Files:**
- Create: `src/ccusage_viz/render/headings.py`
- Create: `tests/test_chart_headings.py`
- Modify: `src/ccusage_viz/render/__init__.py`
- Modify: `src/ccusage_viz/locales/en.py`
- Modify: `src/ccusage_viz/locales/zh.py`

**Interfaces:**
- Consumes: `RenderContext`, `Translator`, `display_width`, `truncate_middle_width`, `styled_text`, and `get_color_scheme`.
- Produces:
  - `HeadingSpec(metric: str, chart: str, dimension: str | None = None, partition: str | None = None, period: str | None = None, window: bool = False, status: str | None = None)`.
  - `chart_name(kind: str, translator: Translator) -> str`.
  - `monitor_view_name(style: str | None, translator: Translator) -> str`.
  - `compose_heading(spec: HeadingSpec, context: RenderContext) -> str`.
  - `heading_with_querying(heading: str, context: RenderContext) -> str`.
- `compose_heading()` returns an uncentered line. Existing renderers continue to call `heading_with_querying()` and then `center_text()` where their geometry expects a centered heading. Unlike legacy `title_with_querying()`, `heading_with_querying()` appends only the muted querying marker and never appends `context.filter_summary`.

- [ ] **Step 1: Write focused failing tests for canonical names and full heading order**

Create `tests/test_chart_headings.py` with these initial cases:

```python
from __future__ import annotations

from ccusage_viz.i18n import load_translator
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.headings import (
    HeadingSpec,
    chart_name,
    compose_heading,
    monitor_view_name,
)


def context(language: str = "en", *, width: int = 80, color: bool = False) -> RenderContext:
    return RenderContext(width, 20, load_translator(language), color=color)


def test_chart_names_use_canonical_localized_terms() -> None:
    zh = load_translator("zh")
    en = load_translator("en")

    assert [chart_name(kind, zh) for kind in ("timeline", "calendar", "stack", "ranking")] == [
        "时间趋势",
        "活跃日历",
        "分组构成",
        "累计排名",
    ]
    assert [chart_name(kind, en) for kind in ("timeline", "calendar", "stack", "ranking")] == [
        "Timeline",
        "Calendar",
        "Stack",
        "Ranking",
    ]


def test_monitor_styles_collapse_to_four_view_families() -> None:
    zh = load_translator("zh")
    en = load_translator("en")

    for style in ("bars", "line", "step", "points", "line-points"):
        assert monitor_view_name(style, zh) == "趋势"
        assert monitor_view_name(style, en) == "Trend"
    for style in ("ranking", "ranking-dot"):
        assert monitor_view_name(style, zh) == "排名"
        assert monitor_view_name(style, en) == "Ranking"
    assert monitor_view_name("list", zh) == "列表"
    assert monitor_view_name("list", en) == "List"
    assert monitor_view_name("cumulative-bars", zh) == "累计柱"
    assert monitor_view_name("cumulative-bars", en) == "Cumulative bars"


def test_historical_heading_places_metric_chart_dimension_and_period_in_order() -> None:
    assert compose_heading(
        HeadingSpec("Token", "累计排名", dimension="项目", period="30d"),
        context("zh"),
    ) == "Token · 累计排名 · by 项目 · 30d"


def test_partitioned_heading_uses_directional_dimension_relationship() -> None:
    assert compose_heading(
        HeadingSpec("Star", "累计排名", dimension="仓库", partition="语言", period="30d"),
        context("zh"),
    ) == "Star · 累计排名 · by 语言 → 仓库 · 30d"


def test_monitor_window_is_labeled_but_ungrouped_total_is_omitted() -> None:
    assert compose_heading(
        HeadingSpec("TPM", "趋势", period="1h", window=True), context("zh")
    ) == "TPM · 趋势 · 1h 窗口"
    assert compose_heading(
        HeadingSpec("Tokens", "Ranking", dimension="project", period="1h", window=True),
        context("en"),
    ) == "Tokens · Ranking · by project · 1h window"
```

- [ ] **Step 2: Run the focused tests and verify they fail because the module does not exist**

Run:

```bash
uv run pytest tests/test_chart_headings.py -v
```

Expected: collection fails with `ModuleNotFoundError: ccusage_viz.render.headings`.

- [ ] **Step 3: Implement canonical names and complete heading composition**

Create `src/ccusage_viz/render/headings.py` with this public shape:

```python
from __future__ import annotations

from dataclasses import dataclass

from ccusage_viz.formatting import display_width, truncate_middle_width
from ccusage_viz.i18n import Translator
from ccusage_viz.render.base import RenderContext, styled_text
from ccusage_viz.render.palette import get_color_scheme

_TEMPORAL_MONITOR_STYLES = frozenset({"bars", "line", "step", "points", "line-points"})
_RANKING_MONITOR_STYLES = frozenset({"ranking", "ranking-dot"})


@dataclass(frozen=True, slots=True)
class HeadingSpec:
    metric: str
    chart: str
    dimension: str | None = None
    partition: str | None = None
    period: str | None = None
    window: bool = False
    status: str | None = None


def chart_name(kind: str, translator: Translator) -> str:
    return translator.text(f"label.chart_{kind}")


def monitor_view_name(style: str | None, translator: Translator) -> str:
    if style in _RANKING_MONITOR_STYLES:
        family = "ranking"
    elif style == "list":
        family = "list"
    elif style == "cumulative-bars":
        family = "cumulative_bars"
    else:
        family = "trend"
    return translator.text(f"label.monitor_view_{family}")
```

Implement private helpers that create the dimension text (`by {dimension}` or `by {partition} → {dimension}`), period/window text, and candidate strings. Add these exact locale keys:

```python
# en.py
"label.chart_timeline": "Timeline",
"label.chart_calendar": "Calendar",
"label.chart_stack": "Stack",
"label.chart_ranking": "Ranking",
"label.monitor_view_trend": "Trend",
"label.monitor_view_ranking": "Ranking",
"label.monitor_view_list": "List",
"label.monitor_view_cumulative_bars": "Cumulative bars",
"label.heading_by": "by {dimension}",
"label.heading_window": "{duration} window",
"label.heading_status": "({status})",

# zh.py
"label.chart_timeline": "时间趋势",
"label.chart_calendar": "活跃日历",
"label.chart_stack": "分组构成",
"label.chart_ranking": "累计排名",
"label.monitor_view_trend": "趋势",
"label.monitor_view_ranking": "排名",
"label.monitor_view_list": "列表",
"label.monitor_view_cumulative_bars": "累计柱",
"label.heading_by": "by {dimension}",
"label.heading_window": "{duration} 窗口",
"label.heading_status": "（{status}）",
```

The complete candidate is `metric · chart · dimension · period`. Omit absent segments and never infer `Total`.

- [ ] **Step 4: Add failing tests for reduction, CJK width, and muted status**

Append:

```python
from ccusage_viz.formatting import display_width, strip_ansi


def test_heading_reduction_removes_dimension_before_period() -> None:
    spec = HeadingSpec("Token", "累计排名", dimension="非常长的项目维度", period="30d")

    assert compose_heading(spec, context("zh", width=31)) == "Token · 累计排名 · 30d"
    assert compose_heading(spec, context("zh", width=20)) == "Token · 累计排名"


def test_heading_truncates_metric_only_after_optional_segments_are_removed() -> None:
    heading = compose_heading(
        HeadingSpec("非常非常长的指标名称", "累计排名", dimension="项目", period="30d"),
        context("zh", width=18),
    )

    assert "累计排名" in heading
    assert "项目" not in heading
    assert "30d" not in heading
    assert display_width(heading) <= 18


def test_monitor_status_is_inline_localized_and_muted_when_color_is_enabled() -> None:
    spec = HeadingSpec("TPM", "趋势", period="1h", window=True, status="建立基线中")
    plain = compose_heading(spec, context("zh", color=False))
    colored = compose_heading(spec, context("zh", color=True))

    assert plain == "TPM · 趋势 · 1h 窗口（建立基线中）"
    assert strip_ansi(colored) == plain
    assert "\x1b[2m" in colored
    assert "\n" not in colored


def test_reduction_preserves_monitor_status_before_optional_window() -> None:
    heading = compose_heading(
        HeadingSpec("TPM", "趋势", dimension="模型", period="1h", window=True, status="采样中"),
        context("zh", width=22),
    )

    assert heading == "TPM · 趋势（采样中）"
```

- [ ] **Step 5: Run the new reduction tests and verify the initial composer fails them**

Run:

```bash
uv run pytest tests/test_chart_headings.py -v
```

Expected: complete-heading tests pass; reduction/status tests fail until candidate selection and styling are implemented.

- [ ] **Step 6: Implement semantic reduction and status styling**

Implement `compose_heading()` with candidate priority:

1. metric + chart + dimension + period/window + status;
2. metric + chart + period/window + status;
3. metric + chart + status;
4. truncated metric + chart + status.

Measure each candidate with `display_width()`. For candidate 4, reserve the display width of ` · {chart}{status}` and apply `truncate_middle_width()` only to `metric`. Style only the localized parenthesized status using:

```python
styled_text(
    translator.text("label.heading_status", status=spec.status),
    get_color_scheme(context.color_scheme).muted,
    context,
    dim=True,
)
```

Select width using the plain localized status before ANSI styling. If an exceptionally narrow width cannot contain chart plus status, preserve chart identity and use the existing width-safe clipping utility as the final defensive fallback; do not split ANSI sequences.

Implement `heading_with_querying()` by extracting the querying-marker branch from the existing `title_with_querying()` without reading `context.filter_summary`. Export `HeadingSpec`, `chart_name`, `monitor_view_name`, `compose_heading`, and `heading_with_querying` from `src/ccusage_viz/render/__init__.py`.

- [ ] **Step 7: Run focused tests and static checks**

Run:

```bash
uv run pytest tests/test_chart_headings.py -v
uv run ruff check src/ccusage_viz/render/headings.py tests/test_chart_headings.py
uv run ty check src/ccusage_viz/render/headings.py
```

Expected: all commands pass.

- [ ] **Step 8: Commit the shared heading primitive**

```bash
git add src/ccusage_viz/render/headings.py src/ccusage_viz/render/__init__.py \
  src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_chart_headings.py
git commit -m "feat: add semantic chart heading composer"
```

---

### Task 2: Pane Chooser Source Groups and Localized Labels

**Files:**
- Modify: `src/ccusage_viz/tui.py:325-359, 4750-4790, 7630-7750, 9250-9440, 9650-9685`
- Modify: `src/ccusage_viz/locales/en.py:34-36, 591-608, 769-775`
- Modify: `src/ccusage_viz/locales/zh.py:34-36, 584-601, 762-768`
- Modify: `tests/test_tui_layout.py:295-335`
- Modify: `tests/test_tui_dashboard.py`

**Interfaces:**
- Consumes: existing `_PANE_COMMANDS`, `_pane_chooser_rows()`, blocking `_choose_pane_type()`, and Dashboard modal chooser state.
- Produces:
  - `_PANE_GROUPS: tuple[tuple[str, tuple[str, ...]], ...]` as the single ordering source for both chooser render paths.
  - `_pane_chooser_rows(translator, selected)` with non-selectable group headings and positions for every command.
- Preserve `_PANE_COMMANDS` as the keyboard selection order derived from flattened groups: built-ins, `datasets`, `animate`, `empty`.

- [ ] **Step 1: Extend chooser tests with exact group order and labels**

Update `test_pane_chooser_localizes_names_and_includes_animation()` to assert ordered substrings rather than presence only:

```python
body = painted[0][0]
expected = (
    "ccusage",
    "时间趋势 (Timeline)",
    "活跃日历 (Calendar)",
    "分组构成 (Stack)",
    "累计排名 (Ranking)",
    "监测 (Monitor)",
    "自定义",
    "数据集…",
    "其他",
    "动画 (Animation)",
    "空白 (Empty)",
)
positions = [body.index(value) for value in expected]
assert positions == sorted(positions)
```

Add an English test:

```python
def test_pane_chooser_english_uses_short_non_redundant_names() -> None:
    # Paint once and close with Esc, matching the Chinese helper setup.
    body = painted[0][0]
    assert "Timeline (Timeline)" not in body
    assert "Calendar (Calendar)" not in body
    assert "\n  Timeline" in body or " Timeline" in body
    assert body.index("ccusage") < body.index("Custom") < body.index("Other")
```

Add a navigation test that starts on `timeline`, sends five downward events, then Enter, and asserts the returned value is `datasets`, proving headings and blank separators are skipped.

- [ ] **Step 2: Run chooser tests and verify old labels/order fail**

Run:

```bash
uv run pytest tests/test_tui_layout.py -k 'pane_chooser' -v
```

Expected: failures show old `监控`, old group names, Empty-first order, or redundant/missing expected ordering.

- [ ] **Step 3: Replace chooser constants with one grouped source of truth**

In `tui.py`, define:

```python
_PANE_GROUPS = (
    ("status.tui_pane_group_ccusage", ("timeline", "calendar", "stack", "ranking", "monitor")),
    ("status.tui_pane_group_custom", ("datasets",)),
    ("status.tui_pane_group_other", ("animate", "empty")),
)
_PANE_COMMANDS = tuple(command for _, commands in _PANE_GROUPS for command in commands)
```

Delete `_TOKEN_PANE_COMMANDS` and `_OTHER_PANE_COMMANDS`. Make `_pane_chooser_rows()` iterate `_PANE_GROUPS` directly.

Use these exact localized group names:

```python
# en.py
"status.tui_pane_group_ccusage": "ccusage",
"status.tui_pane_group_custom": "Custom",
"status.tui_pane_group_other": "Other",

# zh.py
"status.tui_pane_group_ccusage": "ccusage",
"status.tui_pane_group_custom": "自定义",
"status.tui_pane_group_other": "其他",
```

Remove the superseded `status.tui_pane_group_token` and `status.tui_pane_group_datasets` keys after `rg` confirms there are no consumers.

- [ ] **Step 4: Update chooser-only item labels without changing generic chart labels**

Set Chinese chooser labels exactly:

```python
"label.pane_timeline": "时间趋势 (Timeline)",
"label.pane_calendar": "活跃日历 (Calendar)",
"label.pane_stack": "分组构成 (Stack)",
"label.pane_ranking": "累计排名 (Ranking)",
"label.pane_monitor": "监测 (Monitor)",
```

Set English chooser labels exactly:

```python
"label.pane_timeline": "Timeline",
"label.pane_calendar": "Calendar",
"label.pane_stack": "Stack",
"label.pane_ranking": "Ranking",
"label.pane_monitor": "Monitor",
```

Do not change `label.pane_animate`, `label.pane_empty`, or `label.pane_datasets` values.

- [ ] **Step 5: Make the Dashboard non-blocking modal use the same grouped rows**

Find modal rendering branches that currently enumerate `_PANE_COMMANDS` directly (around the `DashboardPaneChooserModal` paint logic). Replace their flat body construction with `_pane_chooser_rows(translator, modal.index)`. Keep modal selection state indexed by `_PANE_COMMANDS`; map its selected command through the returned `positions` for viewport focus exactly as `_choose_pane_type()` does.

Do not alter the second-level Dataset modal. The first-level `datasets` selection must still call/open the existing Dataset flow.

- [ ] **Step 6: Add Dashboard modal parity and Dataset-depth tests**

In `tests/test_tui_dashboard.py`, add assertions against the modal paint output:

```python
assert "ccusage" in frame
assert "Custom" in frame
assert "Other" in frame
assert frame.index("Timeline") < frame.index("Datasets…") < frame.index("Animation")
```

Drive Enter on `datasets` and assert the next modal stage is the existing Dataset chooser, not an inline list of installed Dataset/Metric/chart rows. Use the test suite’s existing fake Dataset service fixture; assert no Dataset title appears in the first chooser frame and it appears only after selecting `Datasets…`.

- [ ] **Step 7: Run chooser and localization regressions**

Run:

```bash
uv run pytest tests/test_tui_layout.py -k 'pane_chooser' -v
uv run pytest tests/test_tui_dashboard.py -k 'chooser or dataset_modal' -v
uv run pytest tests/test_i18n.py -v
```

Expected: all pass; navigation still returns command IDs, never group headings.

- [ ] **Step 8: Commit chooser grouping**

```bash
git add src/ccusage_viz/tui.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py \
  tests/test_tui_layout.py tests/test_tui_dashboard.py
git commit -m "feat: group pane chooser by source"
```

---

### Task 3: Historical Built-in and Dataset Heading Integration

**Files:**
- Modify: `src/ccusage_viz/render/timeline.py`
- Modify: `src/ccusage_viz/render/calendar.py`
- Modify: `src/ccusage_viz/render/stack.py`
- Modify: `src/ccusage_viz/render/ranking.py`
- Modify: `src/ccusage_viz/render/custom.py`
- Modify: `src/ccusage_viz/historical_render.py`
- Modify: `tests/test_render.py`
- Modify: `tests/test_custom_component.py`
- Modify: `tests/test_custom_metric_switching.py`

**Interfaces:**
- Consumes: Task 1 `HeadingSpec`, `chart_name()`, and `compose_heading()`.
- Produces:
  - Built-in historical headings whose Metric is localized `Token`/`Tokens`.
  - Dataset historical headings whose Metric is the localized V2 `metric.title` projected through the existing `CustomPresentationDescriptor.dataset.title` compatibility field.
  - Existing pending/accepted/empty paths use the same semantic order.
- `RenderContext.title_content` continues to carry the localized grouping dimension on existing built-in paths; it is no longer treated as a prefix that replaces the Metric.

- [ ] **Step 1: Replace old historical title expectations with the approved contract**

Update/add `tests/test_render.py` cases:

```python
def test_historical_headings_are_metric_first_and_omit_total_grouping() -> None:
    timeline = TimelineModel((date(2026, 1, 1),), (Series("total", "Total", (usage(1),)),))
    ranking = RankingModel((RankingEntry("a", "A", usage(1_200)),), period())

    timeline_output = render_timeline(
        timeline,
        RenderContext(80, 24, load_translator("zh"), color=False, period="14d"),
    )
    ranking_output = render_ranking(
        ranking,
        RenderContext(
            80, 24, load_translator("zh"), color=False, period="30d", title_content="项目"
        ),
    )

    assert "Token · 时间趋势 · 14d" in timeline_output
    assert "Token · 累计排名 · by 项目 · 30d" in ranking_output
    assert "总计" not in timeline_output.splitlines()[0]
```

Add direct assertions for Calendar and Stack:

```python
assert "Token · 活跃日历 · 1y" in calendar_output
assert "Token · 分组构成 · by 模型 · 14d" in stack_output
```

Retain existing date-range tests but update prefixes to `Tokens · Timeline`, `Tokens · Calendar`, `Tokens · Stack`, or `Tokens · Ranking`.

- [ ] **Step 2: Add Dataset Metric-title and partitioned-Ranking tests**

In `tests/test_custom_component.py`, build a V2 projection whose localized Metric title is `Reading time` / `阅读时长`, unit is minutes, and Dataset title differs. Assert:

```python
assert "阅读时长 · 时间趋势 · 14d" in output
assert "微信读书" not in output.splitlines()[0]
assert "分钟" not in output.splitlines()[0]
```

For a grouped chart:

```python
assert "阅读时长 · 分组构成 · by 书籍 · 30d" in output
```

For partitioned Ranking:

```python
assert "Star · 累计排名 · by 语言 → 仓库 · 30d" in output
```

Keep existing value/axis assertions proving the unit still appears where values are formatted.

- [ ] **Step 3: Run focused historical tests and verify old renderer order fails**

Run:

```bash
uv run pytest tests/test_render.py -k 'heading or title or calendar or stack' -v
uv run pytest tests/test_custom_component.py -k 'heading or title' -v
uv run pytest tests/test_custom_metric_switching.py -k heading -v
```

Expected: failures show old chart-first names, `Total`/dimension prefixes, Dataset-title order, or old `日历热力图` copy.

- [ ] **Step 4: Route built-in historical renderers through `compose_heading()`**

For each historical renderer, construct the base heading before centering:

```python
heading_text = compose_heading(
    HeadingSpec(
        metric=context.translator.text("label.tokens_metric"),
        chart=chart_name("timeline", context.translator),
        dimension=context.title_content,
        period=resolved_period_or_range,
    ),
    context,
)
```

Add locale key values `label.tokens_metric: "Tokens"` in English and `label.tokens_metric: "Token"` in Chinese.

Use one helper in `headings.py` to resolve the existing relative period or localized fixed date range so Timeline, Calendar, Stack, Ranking, and pending headings do not duplicate range rules. The helper signature is:

```python
def heading_period(
    context: RenderContext,
    *,
    since: date,
    until: date,
) -> str:
    if context.period is not None:
        return context.period
    return context.translator.text(
        "label.date_range",
        since=since.isoformat(),
        until=until.isoformat(),
    )
```

It returns the compact `context.period` unchanged (`1w`, `1mo`, and `1y` must no longer expand to prose) or the existing localized fixed range. It does not append querying state.

After composition, preserve existing querying behavior by appending its muted marker through a small shared helper rather than feeding `filter_summary` into the heading. Active filter summaries must not enter the new standard title.

Specific renderer notes:

- Timeline: remove the old `title + Total` branch; an ungrouped timeline simply omits dimension.
- Calendar: use Metric + Calendar + period/range.
- Stack: use `context.title_content` as optional dimension, not as a replacement title.
- Ranking: preserve exact-project semantic detail outside the standard dimension slot only if required by existing project attribution tests; do not restore chart-first ordering. Preserve Top-share suffix behavior after the canonical base heading.
- `historical_render._pending_heading()`: use the same helper, so pending and accepted titles are identical apart from query status.

- [ ] **Step 5: Route custom historical headings through the same composer**

Refactor `render/custom.py::custom_heading()`:

- Metric = localized `descriptor.dataset.title` on the V2 compatibility projection, because `configuration.v2_metric_probe_descriptor()` deliberately maps `metric.title` into that field.
- Legacy fallback = existing authoritative localized presentation title; do not derive from `metric_id`.
- Chart = `chart_name(config.kind, translator)`.
- Dimension = localized group label only when `group_by` is non-null.
- Partition = localized partition label only when `partition_by` is non-null.
- Period = timestamp range’s declared compact period or exact half-open range; date range uses `heading_period()`.
- Do not append filters or unit labels.

Delete `_custom_timeline_heading()`’s unit-prefix/suffix addition to the title. Keep unit formatting on axes and values.

- [ ] **Step 6: Update pending, empty, and switching assertions**

Update old assertions such as `Ranking · all`, titles that place `Timeline` before a `pages` unit, or `$ · Reading · Timeline` to the canonical Metric-first form. Add one same-query refresh failure/pending test asserting the candidate title remains stable while numeric facts follow existing lifecycle policy.

Do not weaken non-heading assertions in these tests.

- [ ] **Step 7: Run historical render suites and static checks**

Run:

```bash
uv run pytest tests/test_render.py tests/test_custom_component.py tests/test_custom_metric_switching.py -v
uv run pytest tests/test_historical_component.py tests/test_application.py -v
uv run ruff check src/ccusage_viz/render src/ccusage_viz/historical_render.py \
  tests/test_render.py tests/test_custom_component.py tests/test_custom_metric_switching.py
uv run ty check src/ccusage_viz/render src/ccusage_viz/historical_render.py
```

Expected: all pass.

- [ ] **Step 8: Commit historical heading integration**

```bash
git add src/ccusage_viz/render/headings.py src/ccusage_viz/render/timeline.py \
  src/ccusage_viz/render/calendar.py src/ccusage_viz/render/stack.py \
  src/ccusage_viz/render/ranking.py src/ccusage_viz/render/custom.py \
  src/ccusage_viz/historical_render.py src/ccusage_viz/locales/en.py \
  src/ccusage_viz/locales/zh.py tests/test_render.py tests/test_custom_component.py \
  tests/test_custom_metric_switching.py
git commit -m "feat: unify historical chart headings"
```

---

### Task 4: Built-in and Dataset Monitor Heading Integration

**Files:**
- Modify: `src/ccusage_viz/render/timeline.py`
- Modify: `src/ccusage_viz/render/ranking.py`
- Modify: `src/ccusage_viz/render/monitor_distribution.py`
- Modify: `src/ccusage_viz/render/custom_monitor.py`
- Modify: `src/ccusage_viz/custom_monitor_component.py:420-455`
- Modify: `tests/test_render.py:1380-1725`
- Modify: `tests/test_custom_monitor.py`
- Modify: `tests/test_custom_monitor_component.py:280-310`
- Modify: `tests/test_monitor_component.py`
- Modify: `tests/test_tui_custom.py`

**Interfaces:**
- Consumes: Task 1 `HeadingSpec`, `monitor_view_name()`, and `compose_heading()`.
- Produces from `CustomMonitorComponent`:

```python
@dataclass(frozen=True, slots=True)
class CustomMonitorHeadingMetadata:
    metric: str
    dimension: str | None
    window_seconds: int
    status: str | None = None


def heading_metadata(self, *, language: str) -> CustomMonitorHeadingMetadata:
    config = self.accepted_config or self.candidate
    if self.presentation is not None:
        metric = self._localized(self.presentation.title, language)
    elif config.metric_titles is not None:
        metric = config.metric_titles[1] if language == "zh" else config.metric_titles[0]
    else:
        raise ValueError("custom Monitor heading requires resolved Metric presentation")
    dimension = self._group_label(config.group_by, language) if config.group_by else None
    return CustomMonitorHeadingMetadata(
        metric=metric,
        dimension=dimension,
        window_seconds=self.capability.window_seconds,
    )
```

During implementation, keep the existing guard used by Monitor rendering when `self.capability` is not yet available; candidate/pending rendering must use the resolved Metric capability passed by the host rather than inventing a duration.
- `CustomMonitorComponent` supplies source-owned semantic metadata only; `render/custom_monitor.py` supplies localized view names, width reduction, ANSI styling, and centering.
- Built-in Monitor derives Metric (`TPM` or `Token`), dimension, window, and state from `MetricDescriptor`, `ObservedScope`, and `RenderContext.style`.

- [ ] **Step 1: Write failing built-in Monitor heading tests for all four view families**

Replace old wording tests in `tests/test_render.py` with parameterized cases:

```python
def test_builtin_monitor_temporal_heading_uses_metric_view_dimension_and_window() -> None:
    model = TimelineModel(
        (),
        (),
        observed_at=(datetime(2026, 1, 1, 10, 0),),
        observed_series=(ScalarSeries("opus", "Opus", (1200.0,)),),
        metric=MetricDescriptor("tpm"),
        observed_scope=ObservedScope(3600, "model"),
    )
    rendered = render_timeline(
        model,
        RenderContext(80, 24, load_translator("en"), color=False, style="line"),
    )

    assert "TPM · Trend · by Model · 1h window" in rendered.splitlines()[0]


@pytest.mark.parametrize(
    ("style", "expected"),
    (
        ("ranking", "Tokens · Ranking · by Project · 1h window"),
        ("list", "Tokens · List · by Project · 1h window"),
    ),
)
def test_builtin_monitor_row_heading_uses_active_view(
    style: str, expected: str
) -> None:
    model = RankingModel(
        (),
        None,
        observed_entries=(ScalarRankingEntry("app", "App", 1200.0),),
        metric=MetricDescriptor("tokens"),
        observed_scope=ObservedScope(3600, "project"),
    )
    rendered = render_ranking(
        model,
        RenderContext(80, 24, load_translator("en"), color=False, style=style),
    )

    assert expected in rendered.splitlines()[0]
```

Add a distribution assertion:

```python
assert "Tokens · Cumulative bars · 1d window" in output.splitlines()[0]
```

Use `_distribution_model()` in `tests/test_render.py` and update its existing heading assertion from `Total · Token cumulative bars · Today · Hourly` to `Tokens · Cumulative bars · 1d window`. Do not include Today/Yesterday or hourly/half-hour granularity in the standard title.

- [ ] **Step 2: Write failing transient-state and width-reduction integration tests**

Add:

```python
def test_builtin_monitor_nonready_state_is_inline_muted_and_ready_is_omitted() -> None:
    sampling = render_timeline(sampling_model, colored_context)
    ready = render_timeline(ready_model, colored_context)

    assert "\n" not in sampling.splitlines()[0]
    assert strip_ansi(sampling.splitlines()[0]).endswith("(sampling)")
    assert "\x1b[2m" in sampling.splitlines()[0]
    assert "(ready)" not in strip_ansi(ready.splitlines()[0])
```

Render the same model at progressively narrow widths and assert dimension disappears before window, while status remains when practical. Keep plot-width assertions separate from heading assertions so a geometry failure is independently diagnosable.

- [ ] **Step 3: Write failing Custom Monitor tests for Metric title and excluded display horizon**

Replace `CustomMonitorComponent.heading()` assertions with metadata and rendered-heading assertions:

```python
def test_custom_monitor_heading_uses_metric_title_view_and_factual_window() -> None:
    component = _accepted_metric_component(style="line")
    component.configure_display_window(3600)
    rendered = render_custom_monitor(
        component,
        RenderContext(80, 20, load_translator("zh"), color=False, style="line"),
    )

    assert "请求数 · 趋势 · by 模型 · 90s 窗口" in rendered.splitlines()[0]
    assert "视图 1h" not in rendered.splitlines()[0]
    assert "数据窗口" not in rendered.splitlines()[0]
```

Add parameterized `ranking`, `ranking-dot`, and `list` expectations and assert the localized Dataset title and unit label do not appear in the heading. Keep existing tests that ensure ranking/list row geometry and descriptions remain unchanged.

- [ ] **Step 4: Run Monitor-focused tests and verify old titles fail**

Run:

```bash
uv run pytest tests/test_render.py -k monitor -v
uv run pytest tests/test_custom_monitor.py tests/test_custom_monitor_component.py -k 'heading or style' -v
uv run pytest tests/test_monitor_component.py tests/test_tui_custom.py -k monitor -v
```

Expected: old “recent/current/data window/view” titles fail the new assertions.

- [ ] **Step 5: Implement one built-in Monitor heading adapter**

Add private helpers to `render/headings.py`:

```python
def duration_label(seconds: int) -> str:
    return f"{seconds // 3600}h" if seconds % 3600 == 0 else f"{seconds // 60}m" if seconds % 60 == 0 else f"{seconds}s"


def monitor_heading_spec(
    *,
    unit: str,
    style: str | None,
    scope: ObservedScope,
    translator: Translator,
    dimension: str | None,
) -> HeadingSpec:
    metric = "TPM" if unit == "tpm" else translator.text("label.tokens_metric")
    status = None if scope.state == "ready" else translator.text(f"label.monitor_{scope.state}")
    return HeadingSpec(
        metric,
        monitor_view_name(style, translator),
        dimension=dimension,
        period=duration_label(scope.window_seconds),
        window=True,
        status=status,
    )
```

Avoid importing `ObservedScope` into `render/headings.py`: define `monitor_heading_spec()` with primitive parameters `unit: str`, `style: str | None`, `window_seconds: int`, `mode: str`, and `state: str`. Timeline and Ranking pass fields from their `ObservedScope`, keeping `chart_models` independent of rendering.

Use this adapter in observed Timeline and Ranking renderers. Dimension comes from scope mode only when mode is not `total`. Remove `_observed_heading()`’s old title templates while preserving querying markers and centered geometry.

- [ ] **Step 6: Integrate cumulative bars without retaining day/granularity title noise**

In `render/monitor_distribution.py`, compose `Tokens · Cumulative bars · [by dimension] · 1d window`. Derive optional dimension with the existing semantic-key logic, but map total to `None`. Treat the selected local calendar day as a one-day factual window; keep Today/Yesterday and hourly/half-hour detail in existing controls/data views rather than the standard heading.

Preserve legends, coverage display, plot sizing, and `title_with_querying()` behavior.

- [ ] **Step 7: Replace Custom Monitor string heading with semantic metadata**

Add `CustomMonitorHeadingMetadata` next to the existing Custom Monitor presentation dataclasses. Implement `heading_metadata()` using:

- selected localized `metric.title` from `self.presentation.title` or `config.metric_titles`;
- localized group label, with ungrouped total converted to `None`;
- capability `window_seconds`, never `display_window_seconds`;
- no ready status; use an existing non-ready observation state only when the component has one.

Remove or narrow the old `heading()` method after `rg` confirms all consumers use metadata. In `render/custom_monitor.py`, combine metadata with `monitor_view_name(component.candidate.presentation.style, translator)` and `compose_heading()`. Keep `_replace_heading()` so native chart geometry remains unchanged.

For Custom `cumulative-bars`, use the same factual capability window rather than Today/Yesterday display selection. Remove `_display_period_label()` from title construction; retain it for controls/data views if it has other consumers.

- [ ] **Step 8: Run Monitor suites and static checks**

Run:

```bash
uv run pytest tests/test_render.py -k monitor -v
uv run pytest tests/test_custom_monitor.py tests/test_custom_monitor_component.py \
  tests/test_monitor_component.py tests/test_tui_custom.py -k monitor -v
uv run ruff check src/ccusage_viz/render src/ccusage_viz/custom_monitor_component.py \
  tests/test_render.py tests/test_custom_monitor.py tests/test_custom_monitor_component.py
uv run ty check src/ccusage_viz/render src/ccusage_viz/custom_monitor_component.py
```

Expected: all pass; no Monitor title includes local display horizon or sample interval.

- [ ] **Step 9: Commit Monitor heading integration**

```bash
git add src/ccusage_viz/render/headings.py src/ccusage_viz/render/timeline.py \
  src/ccusage_viz/render/ranking.py src/ccusage_viz/render/monitor_distribution.py \
  src/ccusage_viz/render/custom_monitor.py src/ccusage_viz/custom_monitor_component.py \
  tests/test_render.py tests/test_custom_monitor.py tests/test_custom_monitor_component.py \
  tests/test_monitor_component.py tests/test_tui_custom.py
git commit -m "feat: unify monitor view headings"
```

---

### Task 5: Documentation and Full Regression Gate

**Files:**
- Modify: `README.md:70-145`
- Modify: `README.zh-CN.md:55-105`
- Modify: `docs/usage.md`
- Modify: `docs/usage.zh-CN.md`
- Test: full `tests/` suite

**Interfaces:**
- Consumes: final localized names and heading examples from Tasks 2–4.
- Produces: user documentation that distinguishes chooser type `Monitor` from rendered Monitor views and retains backticked CLI kind names.

- [ ] **Step 1: Add a documentation consistency check before editing prose**

Run searches and save the matches for comparison:

```bash
rg -n '日历热力图|监控 \(Monitor\)|Grouped composition|Timeline —|Ranking|Monitor —' \
  README.md README.zh-CN.md docs/usage.md docs/usage.zh-CN.md
```

Expected: existing legacy names are found.

- [ ] **Step 2: Update README chart tables and chooser descriptions**

Use these exact Chinese task names in prose/table labels:

- `时间趋势 \`timeline\``
- `活跃日历 \`calendar\``
- `分组构成 \`stack\``
- `累计排名 \`ranking\``
- `监测 \`monitor\`` for the chooser/product type

Describe rendered Monitor views as `趋势`, `排名`, `列表`, and `累计柱`. Keep command examples unchanged, including `ccuv chart timeline`, `ccuv chart monitor`, and style flags.

In English, use short terms `Timeline`, `Calendar`, `Stack`, `Ranking`, and `Monitor`; do not introduce `Activity calendar`, `Grouped composition`, or `Cumulative ranking` as canonical chart names.

- [ ] **Step 3: Update usage guides with the heading grammar**

Add a compact naming note in both usage guides with concrete examples:

```text
Token · 时间趋势 · by 模型 · 14d
Star · 累计排名 · by 语言 → 仓库 · 30d
TPM · 趋势 · 1h 窗口（建立基线中）
```

The English guide uses:

```text
Tokens · Timeline · by model · 14d
Stars · Ranking · by language → repository · 30d
TPM · Trend · 1h window (collecting baseline)
```

State that Monitor titles show the factual data window, not local display retention or sampling cadence, and that the transient parenthesized state is muted inline.

- [ ] **Step 4: Verify documentation no longer presents superseded names as canonical**

Run:

```bash
rg -n '日历热力图|监控 \(Monitor\)|Grouped composition \(Stack\)|Cumulative ranking' \
  README.md README.zh-CN.md docs/usage.md docs/usage.zh-CN.md
```

Expected: no matches, except an explicitly historical changelog quotation if one exists outside these four files.

- [ ] **Step 5: Run targeted naming regression suites**

Run:

```bash
uv run pytest tests/test_chart_headings.py tests/test_i18n.py tests/test_tui_layout.py \
  tests/test_tui_dashboard.py tests/test_render.py tests/test_custom_component.py \
  tests/test_custom_monitor.py tests/test_custom_monitor_component.py \
  tests/test_monitor_component.py -v
```

Expected: all pass.

- [ ] **Step 6: Run the full quality gate**

Run:

```bash
uv run pytest -q
uv run ruff check .
uv run ty check src
```

Expected: all pass. If unrelated pre-existing working-tree changes cause failures, record the exact failing test/check and verify the naming-focused suites still pass; do not reset or modify unrelated files.

- [ ] **Step 7: Review the diff for identity and scope safety**

Run:

```bash
git diff --check
git diff -- src/ccusage_viz/options.py src/ccusage_viz/chart_configuration.py \
  src/ccusage_viz/custom_protocol.py src/ccusage_viz/dashboard_presets.py
rg -n 'chart_kind|chart_id|kind: Literal' src/ccusage_viz/render/headings.py
```

Expected: no whitespace errors; no changes to stable kind/CLI/protocol/persistence files; the new heading module contains no query or persistence identity logic.

- [ ] **Step 8: Commit documentation and final regression updates**

```bash
git add README.md README.zh-CN.md docs/usage.md docs/usage.zh-CN.md
git commit -m "docs: align chart naming guidance"
```

- [ ] **Step 9: Report implementation evidence**

Record in the implementation summary:

- commits created for Tasks 1–5;
- targeted and full test commands with results;
- any unrelated pre-existing failures left untouched;
- confirmation that CLI/protocol/persisted kind IDs remain unchanged.
