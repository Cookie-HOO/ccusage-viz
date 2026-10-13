# Grouped Ranking Viewport Fixes Design

## Goal

Remove sticky group headings from grouped Custom Ranking and restore mouse copying for individual inner Ranking entries.

## Scope

Included:

- remove grouped viewport sticky-heading state, rendering, capacity, scrolling, and scrollbar compensation;
- retain ordinary physical-line scrolling where original group headings scroll away naturally;
- fix grouped inner-entry row classification so the visible primary row containing the copy marker owns the series identity and hit target;
- preserve working group copy, group links, Copy All, Other behavior, search, scrolling, and stable identity restoration.

Excluded:

- numeric search investigation or changes;
- protocol, projection, Ranking calculations, controls, or non-grouped Ranking changes.

## Sticky Heading Removal

Delete `sticky_rows`, sticky eligibility/group-interval logic used only by sticky rendering, and sticky-specific effective-capacity/maximum-offset compensation. The viewport capacity is always `visible_rows`; maximum offset is `max(0, total_rows - visible_rows)`. No synthetic group label is inserted above the physical body.

Cached geometry may retain group heading indexes where needed for group-aware restoration, but it must not retain sticky-only series-presence facts.

## Inner Entry Hit Mapping

The shared Ranking renderer may emit non-entry chrome before a single rendered entry, including an empty heading line and detailed comparison header. Grouped geometry must not assume returned line zero is the primary entry.

For each inner entry, locate its actual primary rendered line using the visible rank/entry row structure, then classify:

- the primary line as `series` with `(group_id, series_id)`;
- following wrapped description lines as `series_description`;
- renderer-only blank/header lines are excluded from grouped physical geometry.

Hit collection then reads the copy/link marker from the correctly classified `series` row. Other remains a `series` row for geometry but has no individual copy hit.

## Verification

Tests cover:

- scrolling past a group heading never inserts a repeated heading;
- ordinary maximum offset and scrollbar bottom expose the final physical row without sticky compensation;
- grouped series rows produce `viewport.hits` identities;
- a real Dashboard mouse click on an inner series copy marker invokes `copy_command` with group-aware payload;
- group copy and links remain functional;
- Other still has no individual copy target;
- flat Ranking behavior remains unchanged.
