# Dashboard pane repaint isolation

## Approved scope
Animation deadlines must not re-render unrelated data panes or rewrite their terminal cells. Keep existing query refresh intervals and preserve ranking scroll work already in the working tree. No new dependencies; Python >=3.11.

## Design
Cache each pane's fully composed local content and its unbounded overlay placements within the dashboard lifetime. An animation-only repaint re-renders only panes whose animation/attachment/overlay deadline is due. Ordinary paints (data acceptance, user interaction, feedback expiry, cursor editing), force paints, and geometry changes conservatively invalidate the cache. Recompose the grid from cached content, so cross-pane overlays retain correct ordering and removal.

FramePainter compares display cells in changed rows and writes only changed spans. Track ANSI SGR and OSC8 state, preserve wide glyph boundaries and combining marks, and blank removed cells. Unsupported controls fall back to whole-row output. First/forced frames remain complete refreshes; synchronized output remains supported.

## Validation
Dashboard regression: repeated animation ticks do not call static pane renderers; later ordinary paints and resize do. Multiple animation panes obey their individual deadlines, including attachments and text overlay deadlines. Terminal regressions: side-by-side static content is not emitted, disjoint changes are isolated, colors and hyperlinks are restored/closed, wide and combining glyphs are not split, shortening removes stale cells. Run focused tests and full suite.
