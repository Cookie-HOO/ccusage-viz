# Dataset Ranking Comparison Availability Design

## Goal

Make Custom Dataset historical Ranking show comparison columns only when the
Dataset actually returns a previous-period comparison response. Preserve
comparison information for individual new entries when a valid comparison
response exists but does not contain every current entry.

This change applies only to Custom Dataset historical Ranking. Native Ranking
behavior, Ranking ordering, and all temporary notification behavior remain out
of scope.

## Current Problem

Custom Ranking projection currently treats two different situations alike:

1. No comparison response was returned for the selected period.
2. A comparison response was returned, but it has no row for one current
   series.

For both cases the projection uses a zero previous value and marks every
current row comparison-ready. The shared presentation renderer consequently
shows growth and rank-change columns even when the Dataset supplied no growth
information at all.

## Behavior

### No Dataset Comparison Response

When the accepted primary Custom Dataset Ranking response has no accepted
comparison response, the Ranking has no comparison data. The renderer hides
all comparison columns:

- `vs prior <period>` / growth is hidden.
- `Rank Delta` is hidden.

The current value, percentage, bar or dot track, rank ordering, descriptions,
search, and `Other` behavior continue unchanged. There is no persistent
message, toast, warning, sorting control, or fallback comparison value.

Existing presentation restrictions still apply: `all` period, narrow widths,
density, and the Dataset capability's `comparison: "full" | "rank" | "none"`
continue to govern which comparison columns can be shown.

### Dataset Comparison Response Exists

When an accepted comparison response exists, the Ranking has comparison data
even if it contains only a subset of the current Ranking entries.

- Entries found in the previous response receive their previous total and
  previous rank, and render normally under the available comparison mode.
- Entries absent from the previous response are marked as new. In a visible
  growth column they render `New`; in a visible rank-change column they render
  `New in ranking` (with localized equivalents).
- The synthetic `Other` entry never receives comparison facts or a new-entry
  label.

For a `comparison: "rank"` capability, only the rank-change column is eligible;
a missing previous entry is still rendered as `New in ranking`. For
`comparison: "full"`, both applicable columns are eligible. For
`comparison: "none"`, neither is eligible regardless of response data.

## Architecture

The projection boundary owns the distinction between global comparison
availability and per-entry history:

1. `process_custom_historical()` records whether an accepted comparison
   response exists for Custom Ranking.
2. It assigns `comparison_ready=True` only to a current series whose id exists
   in that response. An absent id retains `previous_total=None` and
   `comparison_ready=False`; it is not coerced to zero.
3. `CustomChartProjection` carries a boolean declaring that the selected
   Ranking has any comparison response, independent of the selected/current
   entries. This preserves eligibility when a valid prior response is empty or
   all of its entries fall outside Top.
4. `render_custom_ranking()` passes that projection-level availability to the
   shared historical Ranking presentation renderer.
5. The shared renderer only enables comparison columns when both its existing
   geometry/mode constraints and the new availability signal permit them. It
   uses per-entry comparison facts to choose a numeric delta, neutral marker,
   or localized new-entry label.

The generic shared renderer keeps its native behavior by default: its new
availability parameter defaults to enabled. Only Custom Dataset callers opt
into the explicit projection-level signal.

## Error Handling And Compatibility

An unavailable, pending, failed, stale, or unrequested Dataset comparison does
not count as a returned comparison response. It therefore hides the comparison
columns until an accepted comparison response is attached to the current
primary result.

No protocol shape changes are required. A custom command returns the same
current and previous Ranking data it already returns. Existing capabilities and
responses remain valid.

## Verification

Tests cover:

- Projection without a comparison response: no projected entry is
  comparison-ready and the projection reports comparison unavailable.
- Projection with a comparison response that omits one current series: matching
  entries retain numeric prior facts; the omitted entry is explicitly new.
- Custom Ranking rendering without a comparison response hides both comparison
  headers even at a detailed, wide viewport.
- A partial comparison response preserves visible columns and renders localized
  new-entry text for missing prior entries without applying it to `Other`.
- Existing full, rank-only, none, all-period, density, and width constraints
  remain intact.
- Native historical Ranking rendering retains its existing comparisons because
  the shared renderer's default remains comparison-available.
