# Custom Ranking Subday Heading Design

## Goal

Show the compact configured period such as `10m` in a V2 Custom Ranking heading instead of its full ISO-8601 query bounds.

## Scope

Only the heading projection for `TimestampRange` values in `src/ccusage_viz/render/custom.py`.

## Behavior

### Relative subday ranges

`resolve_custom_ranking_range()` already preserves the configured period on its rolling `TimestampRange` result (`relative_until=True`, `period="10m"`). When rendering a Custom Ranking heading for this form, the heading must use that period string. For example, a heading ends with `· 10m`, rather than `· [2026-10-14T03:47:41... , 2026-10-14T03:57:41...]`.

This is presentation-only. The exact `start_at` and `end_at` continue to be sent to the Dataset and continue to refresh from the query clock as they do today.

### Fixed timestamp ranges

A `TimestampRange` without a relative period remains an explicit interval. Its heading continues to render the localized precise timestamp range. This preserves visibility of user-selected or comparison-derived fixed bounds.

### Date ranges

Existing `DateRange` headings, including `1d`, calendar periods, and explicit date ranges, remain unchanged.

## Implementation Boundary

Use the existing `TimestampRange.relative_until` and `TimestampRange.period` fields at the Custom heading branch. Do not infer or recompute duration from timestamps, as that could alter configured spelling and rolling-range semantics.

## Testing

Add renderer-level regressions proving that:

- a relative `TimestampRange` with `period="10m"` includes `10m` and does not include ISO timestamp text;
- a fixed `TimestampRange` continues to include both ISO timestamp bounds;
- existing date-based Custom heading coverage remains unchanged.
