# Dataset Filter Single-Select Design

**Date:** 2026-10-12

## Goal

Extend Custom Dataset runtime filters with Dataset-declared single-selection
semantics while retaining the existing explicit, multi-filter draft workflow.
Make the filter editor's top navigation show the currently effective selection
count for every filter dimension, and give its three chrome rows clear visual
hierarchy.

This enables source-owned context filters such as WeRead Similar Books' required
`seed_book` without creating Dataset-specific UI or changing query wire shape.

## Scope

This applies only to `src/ccusage_viz/custom_filter_draft.py`, which is used by
standalone Custom charts, Custom Monitor, and Dashboard Custom panes. Native
`ccusage` filters in `filter_draft.py` remain out of scope.

## Protocol

`runtime.filters[]` extends its existing optional `mode` field:

```json
{
  "id": "seed_book",
  "label": {"en": "Based on book", "zh-CN": "基于图书"},
  "mode": "single_select",
  "options": [
    {
      "id": "book-001",
      "label": {"en": "One Hundred Years of Solitude", "zh-CN": "百年孤独"}
    }
  ]
}
```

- Supported values are `"multi_select"` and `"single_select"`.
- Omitted `mode` remains `"multi_select"`, preserving all existing Datasets.
- `single_select` means ccuv sends at most one selected option ID for that
  filter. The existing query wire format remains unchanged: every filter value
  is still an array of option IDs.
- The Dataset remains authoritative for required filters, empty values, option
  validity, and cross-filter constraints. For example, a Similar Books Metric
  can reject a request without `seed_book`; ccuv must not infer a default.
- Filter modes and options remain response-runtime metadata. Different Metrics
  may expose different filter modes or choices.

### Dataset author guidance

Prefer `single_select` when choices are mutually exclusive, form a source-owned
mode, or express an understandable bucket/range. For example, a recency filter
may offer `Within 7 days`, `Within 30 days`, and `Any time`; selecting several
of those ranges simultaneously is ambiguous and harder to present. Use
`multi_select` only where users genuinely combine separate discrete dimension
values, such as languages, categories, tags, authors, or shelf labels. Do not
use `multi_select` merely because the protocol can transport an array.

## Editor Interaction

The current editor is one draft across all runtime filter dimensions. Its
explicit apply/cancel behavior remains unchanged:

- `Space` toggles the focused option.
  - For `multi_select`, it adds/removes that option while preserving other
    selections in the dimension.
  - For `single_select`, selecting an unselected option replaces every prior
    draft selection in that dimension; pressing Space on the selected option
    clears it.
- Lowercase `c` clears the active dimension for either mode.
- `Enter` applies the entire draft across every filter dimension and starts one
  query.
- `Esc` cancels the whole draft; it does not change the accepted chart query.
- Search, mouse option clicks, tabs, one-to-three column layout, scrolling,
  and localized option de-duplication retain their existing behavior. Mouse
  selection follows the same single-select replacement rule as Space.

This intentionally does not auto-apply a single select. A user may configure
`seed_book`, category, and shelf state before one final Enter and one Dataset
query.

## Effective Counts in Dimension Tabs

The first chrome row changes from labels only to an effective-count summary:

```text
[Language 1/101] · Type 0/18 · Domain 2/34 · Topic 0/56 · …
Selected 1 / 101
```

For each runtime filter dimension:

- `n` is the count of selected visible option IDs from the **accepted input
  filters passed when the editor opened**.
- `m` is the count of that dimension's de-duplicated visible options.
- Tabs deliberately do not update while the user changes the local draft. The
  second-row active-dimension count is the immediate draft feedback.
- Consequently, tab counts always describe the query currently rendered behind
  the editor, not an unsubmitted candidate query.
- A newly accepted Dataset response supplies the next runtime catalog; opening
  the editor again then reflects its accepted filter state.
- `single_select` naturally displays only `0/m` or `1/m`.
- Existing width clipping remains the only narrow-terminal behavior. This work
  does not add tab scrolling, hiding, or reordering.

## Visual Hierarchy

The editor has three chrome layers. Color is additive; no-color and ASCII modes
remain fully usable through text, brackets, and counts.

1. **Editor title** (painted by the host, for example `Edit filters`) uses the
   existing theme title / primary emphasis treatment.
2. **Dimension tab row** uses secondary hierarchy:
   - the current dimension label and brackets use primary emphasis;
   - an effective nonzero `n` uses secondary emphasis;
   - inactive labels and all `0/m` counts use muted text.
3. **Active-dimension count/search row** is tertiary status:
   - fixed words such as `Selected`, `Matching`, and `Total` are muted;
   - the immediate draft selected count is primary emphasis;
   - matching and total numeric values use normal text;
   - the search label is muted, entered query normal text, and active cursor
     primary emphasis.

Checkboxes, focused-option marker, warnings, continuation markers, and option
labels retain existing styling. The color treatment must use existing terminal
palette/theme tokens rather than hard-coded ANSI colors.

## WeRead Application

WeRead Similar Books can declare a source-owned Ranking-only Metric with
`periods: ["all"]`, `aggregation: "value"`, and `summary: "none"`. Its runtime
catalog may expose:

```json
{
  "id": "seed_book",
  "label": {"en": "Based on book", "zh-CN": "基于图书"},
  "mode": "single_select",
  "options": []
}
```

The Dataset lists a bounded meaningful book set, such as the user's shelf,
recent books, or completed books. A final request with no selected `seed_book`
is rejected by the Dataset with its localized actionable error. This same UI is
available to all Datasets and does not add WeRead-specific host behavior.

## Testing

1. **Protocol/model parsing**
   - Omitted mode defaults to `multi_select`.
   - Parse and serialize `single_select`.
   - Reject an unsupported mode.

2. **Draft semantics**
   - Multi-select preserves existing add/remove behavior.
   - Single-select replacement, deselection, clear, keyboard Space, and mouse
     click all preserve at most one draft option.
   - Enter applies all dimensions once; Esc preserves accepted input filters.

3. **Dimension counts**
   - Every tab renders accepted `n/m` using de-duplicated visible options.
   - Draft Space changes the active detailed count immediately but does not
     alter any tab count.
   - Unknown selected IDs are retained in query state but excluded from visible
     selected-count calculation.
   - Counts localize correctly in English and Simplified Chinese and survive
     clipping.

4. **Visual hierarchy**
   - Color-aware snapshots distinguish current tabs, effective nonzero counts,
     muted zero counts, and immediate draft count using existing palette tokens.
   - No-color rendering remains readable without ANSI escapes.

5. **Regression**
   - Existing search, tab navigation, columns, viewport, continuation markers,
     duplicate-label behavior, and Custom query application tests remain green.
