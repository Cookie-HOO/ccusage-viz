# Dashboard Narrow-pane Hang Fix — Design

**Date:** 2026-10-14

## Problem

Dashboard column-weight adjustment can allocate a pane a width of one terminal cell. Rendering that pane may call `formatting.wrap_width()` with `width=1` and text beginning with a double-width character, such as Chinese text or some emoji.

The existing word-splitting loop emits an empty row when no character fits, but does not consume the double-width character. It therefore repeats forever on the TUI main thread. The TUI raw mode disables `ISIG`; Ctrl-C is decoded as an ordinary `\x03` input event, so it cannot be handled while rendering is spinning.

## Goals

- Ensure all calls to `wrap_width()` terminate for every non-negative width and Unicode input.
- Prevent interactive Dashboard resizing from producing an unusable one-column pane when terminal space permits a usable layout.
- Render safely, without invoking complex chart renderers, when physical terminal geometry cannot satisfy the Dashboard pane minimum.
- Preserve existing normal-width layout and renderer behavior.

## Non-goals

- Change the TUI's Ctrl-C / `ISIG` input model.
- Redesign Dashboard layouts or weight persistence.
- Make every chart readable at arbitrarily tiny terminal dimensions.

## Design

### 1. Progress-guaranteed text wrapping

`formatting.wrap_width(value, width)` will retain its current empty result for non-positive widths. For positive widths, each inner wrapping iteration must either consume at least one source character or terminate.

When the next source character is wider than the requested width (notably a width-two character in a one-cell viewport), the wrapper will emit and consume that character as its own row. This deliberately permits that row's display width to exceed the requested width. Terminal renderers and callers subsequently clipping to their local geometry remain safe, while the input always advances.

The implementation will avoid emitting a synthetic empty segment in the long-word splitting loop. Its progress condition will be explicit, so combining characters, ANSI escape sequences, Chinese text, emoji, and mixed text all terminate.

### 2. Dashboard minimum axis allocation during weight changes

The shared Dashboard layout resolver will gain an axis minimum parameter or equivalent layout-aware allocation rule. Dashboard columns will receive a minimum width sufficient for a narrow but meaningful pane; rows will use the existing `MIN_PANE_HEIGHT` intent rather than merely declaring the constant.

Weight adjustment is constrained by the same allocation rule: an adjustment that would make the selected or neighbor band smaller than its minimum at the current terminal size is a no-op. This keeps the user able to resize panes back and forth and prevents a one-column pane during ordinary terminal sizes.

The resolver must still support physical terminals too small to honor all band minima. In that case, it will retain its current positive-size geometry allocation rather than raising, so the application remains recoverable after terminal resize.

### 3. Safe rendering fallback for undersized Dashboard panes

Before invoking a pane's chart renderer, Dashboard rendering will detect whether that pane's interior rectangle satisfies the renderer minimum geometry. If it does not, it will render a compact, clipped local placeholder using the pane theme and skip chart/viewport preparation entirely.

This fallback applies only to physically undersized panes, not normal narrow panes that satisfy the Dashboard minimum. It prevents present and future renderers from receiving pathological dimensions.

## Error handling and recovery

- `wrap_width()` never loops indefinitely due to an unplaceable glyph.
- Extreme persisted weights and physical terminal shrinkage yield a visible fallback pane, never a layout exception or blocked event loop.
- A resize back to adequate dimensions automatically resumes normal rendering; no state reset is needed.

## Tests

1. `wrap_width("路由请求数", 1)` completes and consumes all input.
2. Equivalent width-one cases cover emoji, mixed ASCII/CJK content, whitespace, and ANSI-styled content.
3. Dashboard layout allocation honors configured minimums when the terminal has sufficient room.
4. A requested resize beyond the minimum leaves weights/geometry unchanged.
5. A terminal too small for all minima still resolves positive pane rectangles.
6. Dashboard paint of an undersized pane produces the fallback without invoking the normal chart renderer.
7. Existing normal-size Dashboard layout and rendering tests remain unchanged.

## Acceptance criteria

- The reported screenshot scenario cannot make the Python main thread spin indefinitely.
- `wrap_width()` has a mechanically tested no-stall behavior at width one.
- Users cannot create a one-column Dashboard pane through ordinary weight adjustment when the terminal is wide enough for the configured layout.
- Shrinking the terminal below feasible dimensions remains recoverable and does not crash or hang the Dashboard.
