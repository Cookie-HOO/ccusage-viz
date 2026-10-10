# Custom Ranking Pointer Scroll Design

**Date:** 2026-10-11
**Status:** Recommended approach approved; written specification awaiting review.

## Scope and decision

Implement direct mouse-wheel scrolling only for Custom Dataset historical Ranking panes in Dashboard. The user approved the recommended direct-scroll approach and explicitly excluded other Ranking types.

Do not change native Ranking, Custom Monitor ranking/list, standalone Custom charts, other chart types, text-view scrolling, keyboard bindings, or persisted configuration. Shared decoder/renderer extensions must leave existing callers' behavior unchanged outside the scoped Dashboard path.

This specification supersedes the wheel/kinetic/virtualization proposals dated October 9–10 only for this scope. Do not restore those implementations wholesale.

## Reference behavior

Source reviewed during design:

- Bubbles viewport: https://github.com/charmbracelet/bubbles/blob/main/viewport/viewport.go — enables wheel scrolling with a default delta of three lines and directly calls `ScrollDown` / `ScrollUp`.
- Textual widget: https://github.com/Textualize/textual/blob/main/src/textual/widget.py — vertical mouse-wheel handlers call pointer scrolling with `animate=False`.

Use their direct, bounded viewport movement rather than application-generated acceleration or inertia. Terminal mouse reports are discrete; they do not expose reliable physical trackpad distances. An operating system or terminal may continue generating reports after a physical gesture ends; the application must not add its own continuation.

## Current implementation

- `src/ccusage_viz/tui_input.py` discards SGR wheel reports.
- Dashboard in `src/ccusage_viz/tui.py` does not retain a Ranking scroll offset and calls Custom pane rendering without a window limit.
- `src/ccusage_viz/render/custom.py` and `render/ranking_presentation.py` already accept entry-window parameters, but entry windows alone cannot scroll through descriptions or separators by display line.
- Copy/link hit testing currently reconstructs a full-list rank lookup during painting.
- Recent commits reverted several scrolling implementations. This change addresses both wheel routing and per-scroll rendering work rather than simply reverting a revert.

## Interaction contract

1. Use each wheel report's terminal coordinates to select the displayed pane. No preceding click or motion report is necessary.
2. The complete pane rectangle, including its border, accepts scrolling. Dashboard header, footer, gaps, and other panes do not redirect wheel input to the focused pane.
3. Wheel input never changes focus, selection, adjustment mode, or search editing state.
4. Each vertical report changes the offset by `direction * min(3, visible_rows)` display lines. A zero-height viewport cannot scroll. Clamp the offset to `[0, max(0, total_rows - visible_rows)]` after each report.
5. Up/down reversal acts immediately. There is no velocity, acceleration, target offset, animation timer, or overscroll.
6. The list scrolls independently of its fixed chrome: summary/title, search line, count, and column headings above; audit/footer and notices below. Preserve existing space allocation for these elements.
7. Descriptions and item-spacing rows are part of the scrollable content. A viewport may start in a description or separator. Preserve the existing description truncation policy; this feature does not expand descriptions beyond their current two-line limit.
8. A modal, chooser, editor, help view, log view, or history view that owns input prevents background Ranking scrolling. Pane adjustment mode alone does not block scrolling an otherwise displayed eligible Ranking.
9. Horizontal wheel reports are ignored. Vertical reports remain vertical regardless of modifier bits; do not introduce new modifier bindings.
10. Pending-only, failed-only, empty, non-overflowing, or non-chart panes do not scroll. A recoverable error that leaves accepted Ranking content displayed may retain scrolling over that content.

## Architecture

### Input decoding and batching

Introduce a distinct immutable wheel event carrying direction, coordinates, and modifiers. Decode valid vertical SGR press reports (buttons 64/65 plus modifier bits); do not turn releases, motion, horizontal wheels, or malformed reports into scrolling.

Keep existing fragmented-control recovery, paste atomicity, bounded input buffers, click handling, and terminal cleanup.

For one input turn, process consecutive complete wheel reports already available in the bounded decoder buffer, apply their offsets in order, and paint at most once after the batch. Stop before a key, click, paste, or incomplete report without consuming that event. Do not wait for future wheel input to fill a batch. Do not sum signed deltas before clamping: down-then-up at a boundary has different semantics from a zero sum.

Wheel draining must not inherit the ordinary-event overload pacing that would replay a burst slowly. Do not change ordinary key/click pacing. The decoder's existing bounded read/buffer sizes bound each turn, so periodic work and non-wheel input are not starved.

Other hosts and modal loops must safely ignore the new event type rather than accidentally interpreting it as a key or mouse click.

### Pane-local viewport

Add a small, independently testable Custom Ranking viewport/layout module. Its session state owns:

- integer display-line offset;
- total scrollable line count and visible line count;
- a cached prepared layout tied to the accepted projection and presentation inputs;
- visible-entry geometry for copying and opening links.

The pure offset operation returns whether the visible position changed. Dashboard is responsible only for eligibility, coordinate conversion, state reconciliation, and requesting a paint. It must use the same resolved geometry as the displayed frame, including header height, borders, fullscreen/single-pane layouts, and adjustment chrome.

Do not put scroll state in chart configuration, query components, Dashboard history, or presets.

### Prepared layout and visible rendering

Separate layout preparation from formatting the visible window:

1. Prepare the matching entry sequence and stable identifiers, ranks, global totals, maximum scale, prior-rank comparisons, and column widths. Preserve current Custom Ranking semantics: displayed ranks are positions in the matching sequence, and totals/scales use the complete matching sequence, not the visible window. Resolve fallback prior ranks across that complete sequence, not one page.
2. Compute per-entry display heights, including the current description wrapping/truncation and item spacing. Retain cumulative line offsets so a display-line offset can locate the first overlapping entry without walking the entire list.
3. Format only entries intersecting the visible window, then clip their first/last lines as needed. Preserve ANSI styling and OSC-8 links; do not rewrap formatted Ranking rows as prose.
4. Return explicit fixed chrome, visible body rows, viewport counts, and copy/link hit metadata. Hit metadata must carry the stable entry identifier instead of deriving identity from displayed rank text.

Preparation may perform a linear pass over the accepted data to calculate layout facts, including scalar value widths where necessary. It must not build a complete styled chart. A warm wheel paint must not refilter the full projection, recompute global aggregates, wrap every description, format every entry, or rebuild a full-list click lookup.

Reuse existing presentation primitives. Extract narrowly scoped shared layout/entry-formatting helpers where necessary; keep the unwindowed rendering path compatible. In particular, do not make scroll position change column widths, totals, percentages, scales, comparison values, or which entry a copy/link marker identifies.

Retain only the current prepared layout per pane and bounded visible formatting state; do not accumulate a cache for every previously visited offset.

### Invalidation and reconciliation

- Search query change resets offset to zero and rebuilds matching/layout facts.
- Replacing a pane, changing dataset/metric/group/filter/period, or changing away from Ranking resets its session viewport. A Top adjustment preserves the numeric offset and clamps it to the newly available list.
- Periodic accepted-data refresh preserves the numeric offset where possible, then clamps to the new row count.
- Width, density, style, language, comparison settings, description visibility, or item spacing changes rebuild relevant layout facts and clamp the offset.
- Height or fixed-chrome height changes recompute the visible row count and clamp the offset.
- Theme, copied-marker feedback, search cursor state, notices, and summary/audit changes must refresh their visible output as needed without forcing full-list work when entry geometry is unchanged.
- Empty results clear stale geometry and offset. Replacement/pending views cannot reuse stale hit targets from an old Ranking.

### Copy/link interaction

Generate hit targets only for primary entry rows actually present in the final viewport. Translate their geometry through fixed chrome and pane framing exactly once. Hidden/clipped entries, description rows, and separator rows must not acquire primary-row copy targets.

Use the hit target's stable entry identifier to retrieve the existing copy payload or project link. Preserve current clipboard content, safe link behavior, click/double-click semantics, and copied-marker feedback. A search result or later page must never copy a different entry because its displayed rank differs from its source index.

### Data and repaint isolation

Scrolling changes only viewport presentation. It must not run a Dataset command, submit a refresh/summary query, modify scheduler deadlines, alter accepted data, or record an undo/preset mutation. Existing independently scheduled refreshes continue normally.

Use the existing Dashboard screen compositor/diff painter. No additional animation loop and no periodic scroll repaint are introduced. A batch that leaves the final display position unchanged does not request a wheel-induced paint.

## Verification

Add deterministic tests for:

- Vertical SGR up/down, modifiers, fragmented reports, ignored releases/horizontal reports, malformed recovery, and existing click/paste behavior.
- Ordered batch consumption, bounded work, preservation of intervening non-wheel events, immediate reversal, and no movement without a new report.
- Three-line steps, small/zero-height panes, top/bottom clamping, and no repaint at a boundary.
- Pointer targeting of an unfocused Custom historical Ranking, independent offsets in two panes, pane borders, header/footer/gaps, changed geometry, and modal ownership.
- Explicit exclusion of native Ranking, Custom Monitor, standalone, text views, and other charts.
- Fixed chrome; partial descriptions/separators at viewport edges; all existing spacing modes; search reset; refreshed data shrinkage; resize and density changes.
- Copy/link targets after scrolling and filtering, partial-entry clipping, and copied-marker feedback.
- No Dataset/query/scheduler/history work caused by wheel input.
- A synthetic 10,000-entry projection whose warm scroll formats only overlapping entries and does not rerun full-list preparation. Use instrumented call/work counts rather than flaky wall-clock assertions.
- Existing unwindowed renderer fixtures and Dashboard input/composition regressions.

Run focused tests and Ruff first, then the full test suite. Report unrelated baseline failures separately if present. Manual terminal validation should cover a wheel and a touchpad, repeated direction changes, two panes with different focus, long descriptions, and a burst followed by an immediate click/key. Automated success is not a claim that physical-device behavior was manually verified.

## Acceptance

Hovering anywhere inside an overflowing Custom historical Ranking pane and scrolling moves only its list, whether or not it is focused. Large lists remain responsive because warm scroll work is proportional to visible content rather than the entire Ranking. The application adds no inertia or delayed per-report repaint backlog. Existing ranking presentation, links/copy, unrelated chart interactions, and data lifecycles remain intact.
