# Custom Ranking Scrollbar

**Date:** 2026-10-12
**Status:** User approved the design, including persistent visibility whenever content overflows.

## Scope

Only Dashboard Custom historical Ranking panes gain a scrollbar. Retain the approved one-display-line wheel step, pointer-based routing, no inertia, visible-window rendering, fixed chrome, and data/query isolation. Do not alter native rankings, Custom Monitor, standalone charts, keyboard bindings, or persistence.

## Appearance and layout

Reserve one column inside the right edge of the Custom Ranking chart area, separate from any pane border. Keep this gutter reserved while rendering the chart so search/refresh/overflow changes do not make columns oscillate. Draw the scrollbar only alongside the scrollable list, not alongside the fixed summary/title/search/count/table header or footer/notices. Use the existing palette's muted track and highlight thumb; Unicode track `│` and thumb `█`, ASCII `|` and `#`.

Visibility is based on complete rendered list height, including descriptions and spacing: `total_rows > visible_rows`. The scrollbar stays visible while idle and regardless of focus or pointer location. Hide it when all content fits, the list is empty/pending-only, or the pane is not a chart. A viewport with no drawable list rows cannot display or operate a bar. At a terminal width of one cell, retain the content rather than reserving the only column.

The thumb length reflects visible/total rows, with at least one terminal cell. When the track has at least two cells and the list overflows, leave at least one cell of thumb travel. Top and bottom content positions map exactly to track endpoints. A one-cell track has an indicator but no useful drag range. Discrete terminal rows mean scrolling one content row may not visibly move the thumb for very large lists.

## Interaction

- Wheel movement updates content and the thumb from the same viewport offset.
- Pressing the thumb captures dragging for that pane without changing focus, copying, opening links, or participating in double-click detection. Keep the grab location within the thumb; a press without movement must not change the offset.
- During a drag, use vertical pointer position even if it moves horizontally outside the pane. Clamp outside the track to top/bottom. Release ends capture, including a release outside the pane. Escape cancels capture at the current offset, with no rollback.
- Clicking the track above/below the thumb moves one visible page and does not start a drag or autorepeat.
- A wheel or other key cancels an existing drag before following its normal routing. Opening a modal, changing displayed geometry/list preparation, replacing a pane, entering a non-chart or pending-only view, and shutdown cancel capture. This prevents stale pointer geometry and stuck interaction.
- Block background scrollbar interaction while help/modal/chooser/editor/log/history owns input. Pane adjustment mode alone does not block it.

## Input and performance

Enable SGR button-motion reports (`1002`) only while an actual scrollbar drag is captured. Keep normal mouse reporting unchanged at rest and in other hosts. Disable motion reports at release/cancellation and in terminal cleanup even on exceptions. Represent motion separately from click events so other UI handlers cannot interpret movement as clicks.

Drain only consecutive complete buffered left-button motion reports during an active drag, keep the latest position, and repaint at most once per turn. Never consume or reorder a following release, click, wheel, paste, key, or incomplete report. Bypass ordinary overload pacing only for motion reports, not keys/clicks. No drag animation, pending target queue, or data refresh is introduced.

## Boundaries

A small pure scrollbar module owns geometry, pixel-cell/offset mapping, and grab state. Ranking viewport rendering owns the gutter, palette drawing, and pane-local bar geometry. Dashboard translates this to terminal coordinates using the displayed layout and owns capture lifecycle and terminal mode changes. It keeps the existing compositor and visible copy/link targets; scrollbar hit testing happens before normal click hit testing.

## Verification

Test overflow visibility (including idle, exact fit, descriptions, spacing and search), proportional thumb length/position and endpoints, one-cell/zero-height/narrow cases, and no content-width overlap. Test press without movement, grabbing at different points, track paging, horizontal departure, clamped vertical departure, release/Escape/cancellation, no focus/copy/double-click leakage, correct header/border/summary/notices geometry, and no query work.

Decode fragmented motion/release, validate modifier/button handling, check burst order/pacing, and guarantee terminal mode cleanup on errors. Retain one-line wheel, large-list bounded formatting, and excluded-host regressions. Run focused tests/Ruff then the full suite and compare existing baseline failures. Physical terminal/trackpad feel is not claimed unless manually tested.
