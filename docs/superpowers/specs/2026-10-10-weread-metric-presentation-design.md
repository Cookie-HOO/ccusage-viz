# WeRead Metric And Ranking Presentation Design

## Goal

Restore the WeRead Dataset after the Gateway Skill version update, improve reading-time Ranking presentation without adding expensive enrichment calls, and expose the composition of all-time notes through one additional grouping on the existing `total_notes` Metric.

## Context

The current `tokenread` Dashboard preset successfully loads its local WeRead command and sends a valid `ccuv.custom/v2` request. Its `reading_time` monthly Book Ranking fails because the WeRead Agent Gateway returns `upgrade_info` for the Dataset's hard-coded `skill_version: "1.0.4"`.

The official WeRead Skill 1.0.5 documentation confirms that `/readdata/detail` and `/user/notebooks` request shapes and fields used by this Dataset have not changed. The update changes the mandatory version string to `1.0.5`; its new `readerLink` guidance affects book-browsing APIs, which the current ranking endpoint does not document as providing a stable direct-reader link.

## Scope

1. Update the Dataset's outbound WeRead Gateway `skill_version` to `1.0.5`, retaining strict `upgrade_info` handling.
2. Improve the `reading_time` Book/Category Ranking presentation from the data already in `/readdata/detail`:
   - human-readable localized duration display;
   - author description for Book rows when supplied by the ranking response;
   - optional direct-reader link only if the ranking response itself contains a valid `readerLink`.
3. Disable only per-row, prior-range Ranking comparison for `reading_time` Book/Category rankings.
4. Add `note_type` as a second supported grouping to the existing all-time `total_notes` Ranking Metric.

## Non-goals

- Do not create new Dataset Metrics.
- Do not add Timeline, Calendar, or Stack support for notes.
- Do not fetch `/book/info` while rendering a Ranking and do not expose a book introduction in this scope.
- Do not change `reading_time` Header/Pane summaries, which retain normal `comparisons` behavior.
- Do not modify ccuv host protocol, Router Dataset behavior, or user Dashboard preset structure.
- Do not bypass or ignore future Gateway `upgrade_info` responses.

## Dataset Contract

### Gateway version

Every WeRead Gateway request uses `skill_version: "1.0.5"`. A response with non-null `upgrade_info` remains a source failure: the Dataset must not interpret potentially changed data without first being updated.

### Reading time

`reading_time` remains an additive `sum` Metric with `summary: "comparisons"`.

- Timeline, Calendar, Stack, and ungrouped summary behavior are unchanged.
- Ranking retains Book and Category grouping and existing natural periods.
- The Ranking capability gains `comparison: "none"`.

`comparison: "none"` belongs only to `capabilities.charts.ranking`. It prevents ccuv from issuing an equal-duration prior-range Ranking query and suppresses per-row duration/rank comparison columns. It does not change `metric.summary: "comparisons"`; Dashboard Header and Pane Summary continue requesting current, sequential, and year-over-year total reading-time facts where source coverage exists.

Book rows may return:

- `display`: localized whole-minute duration, `"3h 24m"` / `"3小时24分钟"`;
- `description`: localized author text when non-empty;
- `link`: an absolute HTTPS `readerLink` only when the authoritative ranking payload supplies one.

Category rows receive the localized duration display but no book author or link. Empty, malformed, or non-HTTPS links are omitted. The Dataset never synthesizes `readerLink`, substitutes `deepLink`, or invokes `/book/info` to enrich a ranking.

### Total notes

`total_notes` remains an all-time, additive `sum` Metric with `summary: "total"` and the sole supported chart kind `ranking`.

Its `group_by` dimensions become:

- `book`: existing behavior. Each row's value is `reviewCount + noteCount + bookmarkCount` for a book.
- `note_type`: all-time composition. The Dataset returns exactly these source-owned IDs and values:

| ID | English label | Chinese label | Value |
| --- | --- | --- | --- |
| `highlight` | Highlights | 划线 | Sum of `noteCount` |
| `thought-review` | Thoughts & reviews | 想法与点评 | Sum of `reviewCount` |
| `bookmark` | Bookmarks | 书签 | Sum of `bookmarkCount` |

`note_type` has no time dimension. It is valid only for the existing Ranking `period: "all"`. It must not be represented as a daily fact, a historical Stack, a Timeline, or a Calendar because `/user/notebooks` provides current cumulative counts rather than creation-time facts.

## Implementation Boundaries

- The Gateway parses optional author and `readerLink` fields from `readLongest` records, preserves them in a typed ranking fact, and keeps existing strict numeric/ID validation.
- Metric code converts raw seconds into the existing exact Decimal point value and separately creates localized `display` text from whole minutes.
- `NotebookCounts` must retain the three component counts instead of only their already-summed total, allowing the Metric layer to aggregate Book or `note_type` rows without issuing additional Gateway requests.
- Any unexpected field shape for optional author/reader link does not invalidate a usable Ranking result; omit that optional presentation field. Invalid required ranking ID, title, or duration continues to fail the query.

## Validation

- Gateway request tests assert `skill_version: "1.0.5"`.
- A representative V2 `reading_time` Book Ranking response parses with `comparison: "none"`, localized display, author description, and valid HTTPS reader link.
- Category Ranking omits Book-only fields.
- Invalid/non-HTTPS reader links are omitted, not emitted.
- `total_notes` Probe descriptor exposes `book` and `note_type` dimensions while retaining only all-time Ranking.
- Book grouping and ungrouped notes totals retain current values.
- `note_type` grouping returns exactly three rows with the correct distinct component totals.
- A direct V2 monthly Book Ranking request using `WEREAD_API_KEY` no longer receives an upgrade failure after skill version update.
- Existing Go and relevant ccuv Python protocol/Dataset tests pass.
