# Unified Chart Naming Design

## Summary

Unify user-visible chart names and title composition without changing CLI commands, configuration IDs, protocol fields, or Python identifiers. Names should describe the user's task, remain compact in terminal panes, and work for both built-in Token data and arbitrary Dataset Metrics.

This design covers:

- the Dashboard Pane type chooser;
- built-in and Dataset historical chart headings;
- built-in and Dataset Monitor headings;
- localized Chinese and English names;
- responsive title reduction in narrow panes.

Animation, Dataset, and Empty entry names retain their existing wording.

## Goals

1. Give every chart kind one stable user-visible name.
2. Put the Metric before the chart type in rendered headings.
3. Keep Dataset-independent terminology: chart names must not assume every Metric represents usage.
4. Distinguish Monitor presentation views without repeating “Monitor” in every rendered heading.
5. Keep headings readable in narrow Dashboard panes.
6. Keep the Pane chooser short and stable as installed Datasets grow.

## Non-goals

- Renaming `timeline`, `calendar`, `stack`, `ranking`, or `monitor` in the CLI, configuration, protocol, or code.
- Flattening installed Datasets, Metrics, and chart capabilities into the first Pane chooser.
- Renaming the existing Animation, Dataset, or Empty chooser entries.
- Adding filters, Dataset names, sampling intervals, or local display horizons to chart headings.
- Changing chart data, projection, query, or rendering semantics.

## Canonical chart names

### Chinese

| Internal kind | User-visible name |
| --- | --- |
| `timeline` | 时间趋势 |
| `calendar` | 活跃日历 |
| `stack` | 分组构成 |
| `ranking` | 累计排名 |
| `monitor` | 监测 |

### English

English uses the existing short product terms rather than expanded translations.

| Internal kind | User-visible name |
| --- | --- |
| `timeline` | Timeline |
| `calendar` | Calendar |
| `stack` | Stack |
| `ranking` | Ranking |
| `monitor` | Monitor |

## Pane type chooser

The chooser is grouped by source or role, not by visual shape.

### Chinese layout

```text
ccusage
  时间趋势 (Timeline)
  活跃日历 (Calendar)
  分组构成 (Stack)
  累计排名 (Ranking)
  监测 (Monitor)

自定义
  数据集…

其他
  动画 (Animation)
  空白 (Empty)
```

### English layout

```text
ccusage
  Timeline
  Calendar
  Stack
  Ranking
  Monitor

Custom
  Datasets…

Other
  Animation
  Empty
```

Rules:

- Group headings are not selectable.
- Keyboard navigation traverses only entries.
- The fixed group order is `ccusage` → Custom → Other.
- Chinese built-in chart entries include the English internal product term in parentheses so users can map them to CLI chart kinds.
- English entries do not repeat the same term in parentheses.
- Animation, Dataset, and Empty retain their current entry names; only their grouping and ordering are standardized.
- `Datasets…` remains a second-level entry. Selecting it continues through Dataset → Metric → supported chart kind. Installed Datasets and their Metric/chart combinations are not expanded into the first chooser.

This hierarchy keeps the first chooser bounded and leaves dynamic readiness, installation, Metric grouping, descriptions, and capability handling to the dedicated Dataset flow.

## Historical chart headings

The canonical heading structure is:

> **Metric · chart name · by dimension · period**

The grouping segment is optional. An ungrouped chart omits it rather than displaying “Total.”

Chinese examples:

- `Token · 时间趋势 · 14d`
- `Token · 时间趋势 · by 模型 · 14d`
- `Token · 活跃日历 · 1y`
- `阅读时长 · 分组构成 · by 书籍 · 30d`
- `Star · 累计排名 · by 仓库 · 30d`

English examples:

- `Tokens · Timeline · 14d`
- `Tokens · Timeline · by model · 14d`
- `Reading time · Stack · by book · 30d`
- `Stars · Ranking · by repository · 30d`

### Partitioned Ranking

A partitioned Ranking preserves the existing directional relationship between the outer partition and inner ranking dimension:

> **Metric · Ranking · by partition → dimension · period**

Examples:

- `Star · 累计排名 · by 语言 → 仓库 · 30d`
- `Stars · Ranking · by language → repository · 30d`

The arrow's left side is the outer partition; its right side is the within-partition ranking dimension.

### Periods and fixed ranges

Relative periods use their compact canonical value, such as `1d`, `14d`, `30d`, or `1y`. They are not expanded into prose.

A fixed range may use the existing compact localized date-range representation. It occupies the same final slot as a relative period.

## Monitor headings

The Monitor chooser entry remains `监测 (Monitor)` / `Monitor`. Once rendered, the heading omits the generic Monitor name and identifies the active view directly.

### Monitor view names

| Styles | Chinese | English |
| --- | --- | --- |
| `bars`, `line`, `step`, `points`, `line-points` | 趋势 | Trend |
| `ranking`, `ranking-dot` | 排名 | Ranking |
| `list` | 列表 | List |
| `cumulative-bars` | 累计柱 | Cumulative bars |

The canonical Monitor heading structure is:

> **Metric · view · by dimension · duration window**

The grouping segment is optional. The heading displays only the factual data window. It does not display the local presentation horizon or sampling interval.

Chinese examples:

- `TPM · 趋势 · 1h 窗口`
- `Token · 排名 · by 项目 · 1h 窗口`
- `Token · 列表 · by Agent · 1h 窗口`
- `Token · 累计柱 · 1d 窗口`

English examples:

- `TPM · Trend · 1h window`
- `Tokens · Ranking · by project · 1h window`
- `Tokens · List · by agent · 1h window`
- `Tokens · Cumulative bars · 1d window`

For a source-owned Custom Monitor, the factual window is the Metric capability's `window_seconds`. Local observation retention or presentation controls remain outside the title. For the built-in Monitor, the title uses the data window represented by the rendered observation.

## Monitor transient status

A non-ready Monitor status remains on the heading line and is appended in localized parentheses:

- `TPM · 趋势 · 1h 窗口（建立基线中）`
- `TPM · Trend · 1h window (collecting baseline)`

Rules:

- The complete parenthesized status uses the existing muted/dim visual treatment.
- Status does not consume an additional row.
- Only states that explain incomplete data, such as baseline collection or sampling, are shown.
- Normal ready/running/observed states are omitted.
- Status is structurally separate from the stable heading text so it can be styled and reduced independently.

## Metric naming source

### Built-in charts

- Historical charts use `Token` as the Chinese Metric name and the established localized English equivalent (`Tokens`).
- Monitor uses `TPM` for rate facts and `Token`/`Tokens` for cumulative token facts.

### Dataset charts

- V2 Dataset charts use the selected localized `metric.title`.
- Legacy Dataset charts use their existing authoritative localized Metric/Dataset presentation title where no separate Metric title exists; the implementation must not invent a Metric ID-derived title.
- A heading must not substitute the Dataset name, Metric ID, or unit label for an available Metric title.
- Unit labels remain on values, axes, and legends and are not appended to the standard heading.

Dataset authors should use a noun or measurable concept for `metric.title`, such as “阅读时长”, “请求”, or “Star”, and avoid embedding chart terms such as “趋势” or “排名”. The host does not rewrite source-owned titles, even if an author supplies a redundant name.

## Responsive title reduction

Title construction must retain semantic segments long enough to reduce them deliberately rather than clipping the fully composed string immediately.

When the complete heading does not fit, reduce it in this order:

1. Remove `by dimension` (or the complete partition → dimension segment).
2. Remove the period or Monitor window.
3. Retain `Metric · chart/view` as the stable minimum heading.
4. For a non-ready Monitor, preserve the muted transient status where practical because it explains missing or incomplete content.
5. Only after optional segments are removed may the Metric text be width-truncated using the existing safe terminal-width utilities.

Historical example:

```text
Token · 累计排名 · by 项目 · 30d
Token · 累计排名 · 30d
Token · 累计排名
```

Monitor example:

```text
TPM · 趋势 · by 模型 · 1h 窗口（采样中）
TPM · 趋势 · 1h 窗口（采样中）
TPM · 趋势（采样中）
```

Reduction is based on terminal display width, not Python string length. It must preserve styling and avoid breaking ANSI escape sequences or wide characters.

## Excluded heading content

The standard heading does not include:

- Dataset name;
- active filter summary;
- “Total” for an ungrouped chart;
- Monitor local display horizon;
- sampling or refresh interval;
- low-level drawing styles such as line, step, points, or area;
- English chart terms in Chinese rendered chart headings.

These facts remain available in their existing controls, status surfaces, legends, help, or diagnostics.

## Architecture and implementation boundaries

The implementation should centralize user-visible naming and structured heading composition rather than duplicating string order in each renderer.

Recommended responsibilities:

1. **Localized naming metadata** maps chart kinds and Monitor style families to stable display names.
2. **Heading composition** accepts structured fields—Metric, chart/view, optional dimension relationship, period/window, and optional status—and produces full and reduced candidates.
3. **Renderers** provide semantic facts and render the selected heading; they do not independently choose alternate naming orders.
4. **Chooser presentation** owns source grouping and chooser-only bilingual labels.
5. **Protocol/configuration layers** retain current stable IDs and do not depend on localized display names.

This keeps renaming presentational and prevents user-visible wording from becoming a data or query identity.

## Error and pending states

- Candidate, pending, accepted, empty, and refresh-failed surfaces use the same naming function so a query lifecycle does not change title order.
- A failed replacement may display the candidate Metric and chart identity without displaying stale facts, following the existing lifecycle policy.
- Missing optional grouping metadata omits the grouping segment rather than emitting a guessed localized name.
- If only a stable machine dimension ID is available on a legacy path, existing fallback behavior may display that ID; no new translation is fabricated.
- Empty and unavailable data do not change the chart's canonical name.

## Testing

Add or update tests for:

1. Chinese and English canonical chart names.
2. Chinese chooser labels with English terms and non-redundant English chooser labels.
3. `ccusage`, Custom, and Other grouping, order, and navigation across non-selectable headings.
4. Preservation of the second-level Dataset → Metric → chart flow.
5. Historical headings with and without grouping.
6. Partitioned Ranking `partition → dimension` headings.
7. Compact relative periods and fixed-range fallback.
8. All four Monitor view families.
9. Built-in `TPM` versus `Token` Metric selection.
10. Dataset `metric.title` localization and exclusion of Dataset names and units.
11. Monitor data-window inclusion and exclusion of local display horizon and sampling interval.
12. Muted inline non-ready status and omission of ready status.
13. Responsive reduction at widths that trigger each reduction stage, including CJK and ANSI-colored text.
14. Consistent titles for pending, empty, accepted, and failed-refresh states.
15. No changes to CLI kind IDs, protocol chart kinds, or persisted Dashboard configuration.

## Documentation impact

README chart tables and usage documentation should use the canonical localized names when describing user tasks, while retaining backticked CLI kinds and commands. Monitor documentation may continue to explain the individual rendering styles, but screenshots and captions should distinguish chooser type (`Monitor`) from rendered view names (`Trend`, `Ranking`, `List`, and `Cumulative bars`).
