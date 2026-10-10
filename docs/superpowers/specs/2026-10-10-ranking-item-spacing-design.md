# Ranking Item Spacing Design

**Date:** 2026-10-10

## Goal

Add a Ranking-only presentation control that cycles the visual separation between project blocks without changing Ranking data, query behavior, or ordering.

## Modes

The cyclic order is:

1. `compact` — current contiguous rows.
2. `space` — one blank row after every project block except the final block.
3. `line` — one muted horizontal separator row after every project block except the final block.
4. `box` — each project block is wrapped in a lightweight terminal box.

A project block includes its primary Ranking row and any enabled description rows. No separator is inserted inside a block.

## Scope

- Applies to native and Custom historical Ranking presentation.
- Works in Dashboard and standalone hosts through shared Ranking rendering.
- Is presentation-only: no provider request, query, re-ranking, Top mutation, or persisted data change.
- Does not affect non-Ranking charts.

## Rendering

`compact` preserves existing output exactly. `space` and `line` add rows between blocks. `line` uses terminal-width horizontal glyphs appropriate for ASCII/no-color output. `box` uses existing terminal border glyph conventions and preserves line width.

## Interaction

Add one Ranking-appropriate adjustment binding that cycles spacing. It appears only where Ranking controls are shown. A forward key cycles forward; its uppercase form cycles backward, following existing adjustment conventions.

## Tests

- Shared renderer snapshots for all four modes, including descriptions.
- One-item Ranking has no trailing blank/separator row.
- ASCII mode uses ASCII line/box glyphs.
- Adjustment action applies only to Ranking and does not mark configuration data-affecting or submit a query.
