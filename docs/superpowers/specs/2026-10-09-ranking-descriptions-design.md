# Ranking Descriptions Design

## Goal

Allow a Custom Dataset Ranking item to carry a short, localized explanation.
The explanation is optional, appears under its corresponding rank when visible,
and gives a short label enough context without making the primary Ranking row
wide or difficult to scan.

The scope is Custom Dataset historical Ranking only. Native Ranking data has no
description source today and remains visually unchanged. Timeline, Stack, and
Calendar do not accept or render Ranking descriptions.

## Protocol

The extension is additive for both `ccuv.custom/v1` and `ccuv.custom/v2`.
Existing Datasets that omit both fields preserve their current behavior.

### Probe capability

Only `capabilities.charts.ranking` may declare the optional:

```json
"descriptions_default": "expanded"
```

Its allowed values are `"expanded"` and `"collapsed"`. Omission means
`"collapsed"`.

This is a stable presentation preference for the selected Dataset capability,
not a per-response instruction. V1 represents it on `CustomChartCapability`;
V2 represents it on `V2HistoricalChartCapability`. Both parser paths reject the
field for Timeline, Stack, Calendar, or Monitor capabilities and reject an
invalid type or value for Ranking.

### Ranking response entries

For a Ranking query only, an item in `data.series` may include:

```json
"description": {
  "en": "Release validation and regression testing account for most activity.",
  "zh_cn": "发布验证和回归测试构成了大部分活动。"
}
```

The value uses the existing required `LocalizedText` shape and language
selection rules. It is optional; an omitted value gives that item no secondary
row. An empty localized value is treated as absent after language selection.

`description` is valid only when the effective requested chart kind is
`ranking`. A Timeline, Stack, or Calendar response that supplies it fails
protocol validation rather than silently carrying a field that ccuv does not
consume. The locally synthesized `Other` entry never inherits an individual
description.

The model boundary keeps description data Ranking-specific rather than adding a
loosely usable property to every `CustomSeries`: parsing keeps the optional
localized value associated with the source item, and only Ranking projection
constructs a projected entry with it. Comparison responses use their numeric
facts only; the accepted primary Ranking response remains the source of
displayed labels and descriptions.

## Presentation

### Shared Ranking Geometry

Custom Dataset historical Ranking and ccuv historical Ranking use the same shared
presentation renderer for every supported style: `dot`, `dots`, bar variants,
and `list`. The renderer allocates stable columns from the complete displayed
set, rather than letting each row's label or value define its own geometry:

1. The title is centered independently in the complete terminal width.
2. An optional summary remains a left-aligned preamble above the title.
3. Every primary row has a left-aligned rank/status-and-label block, a middle
   visual track, and a right-aligned value/proportion block. The label block has
   a single fixed width, so all tracks begin in the same terminal column; the
   value/proportion block has a single fixed width, so its right edge aligns.
4. `list` has no visual track, but retains the same fixed left and right column
   policy; its completed rows are centered only as a whole within the viewport.

Dataset-owned display strings remain in the right-side value block. Comparison
markers and proportions are included when applicable before that block's width
is measured, preventing individual rows from shifting the value or track.

Custom Dataset Monitor `ranking` and `list` do not implement a parallel layout.
They continue to project Dataset facts into the native ccuv Monitor ranking
model and call the native renderer, replacing only the centered Dataset heading.
Thus all rows after the heading must be byte-for-byte identical to native ccuv
Monitor output given the equivalent model and render context.

Descriptions are plain text. They are never interpreted as Markdown, terminal
escape sequences, or links.

The primary Ranking row retains its current rank, label, bar/dot encoding,
value, percentage, and movement markers. When descriptions are visible, each
explained entry adds a secondary row directly below its primary row:

- It begins at the primary label column; it does not need to align with the
  visual track.
- It uses the complete available ranking width after the indent rather than the
  primary label column, so it can explain a short item with a longer sentence.
- It uses the selected palette's muted color and dim treatment, distinct from
  the primary item and categorical highlight.
- It wraps with ANSI-aware display width to at most two physical lines. Further
  content is truncated on the second row without changing row width.
- It has no bar, rank, numerical value, comparison glyph, or percentage.

The same renderer behavior applies to standalone and Dashboard Custom Ranking
views. Existing historical Ranking presentation remains unchanged when no entry
has a description.

## Visibility And Interaction

Description visibility is a presentation-only, per-pane or per-standalone-run
state. It is initialized only when the accepted Ranking capability and its
entries are known:

- If at least one displayed item has a non-empty description, the initial state
  follows `descriptions_default`.
- If no displayed item has a description, no description control is exposed.
- `minimal` density always suppresses description rows regardless of the saved
  default or runtime choice.
- In `compact` and `detailed` density, the effective state is the Dataset
  default until a user changes it during the current TUI session.

Uppercase `D` toggles the user override between expanded and collapsed for the
current Ranking. In Dashboard it applies only to the focused Ranking pane; in
standalone it applies to the current Ranking view. The binding appears in
controls and Help only when the current chart has descriptions and density is
not `minimal`.

The override is not query state, does not cause a refresh, and is not written to
CLI serialization, Dashboard history, Dashboard presets, or data exports.
Changing to `minimal` temporarily hides descriptions. Returning to `compact` or
`detailed` restores the Dataset default or the last current-session `D`
override.

## Error Handling And Compatibility

Malformed capability defaults, invalid response descriptions, and descriptions
on unsupported chart kinds fail through the existing Custom protocol validation
path. A valid Dataset that omits the fields behaves exactly as before.

Pane geometry remains stable in the horizontal dimension. Description expansion
only consumes vertical rows; Dashboard's existing local pane clipping decides
what can fit, with no change to layout topology or query scheduling.

## Verification

Tests cover:

- V1 and V2 Probe parsing and serialization for valid Ranking defaults, omitted
  defaults, invalid values, and fields forbidden on non-Ranking capabilities.
- Ranking response parsing for bilingual descriptions, language selection,
  omission, invalid localized content, and rejection on other chart kinds.
- Projection propagation for selected entries, exclusion from `Other`, and
  primary-response ownership across comparisons.
- Renderer output for collapsed and expanded descriptions, muted styling,
  indentation, available-width wrapping, two-row truncation, narrow panes, and
  minimal-density suppression.
- Standalone and Dashboard `D` routing, visibility conditions, no-refresh
  behavior, per-pane isolation, and restoration after leaving `minimal`.
- Geometry coverage for every Custom Dataset historical Ranking style,
  asserting centered headings, left-aligned summaries, common track start,
  fixed right-side alignment, and descriptions beginning at the label column.
- Custom Dataset Monitor `ranking` and `list` regression coverage asserting
  rows after the Dataset-owned heading exactly match native ccuv Monitor rows.
- Regression coverage showing native Ranking and description-free Custom
  Ranking retain their existing output.
