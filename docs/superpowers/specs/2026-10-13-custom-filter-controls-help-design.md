# Custom Filter Single-Line Controls and Help Design

**Date:** 2026-10-13

## Goal

Keep the Dataset Custom filter control bar on one terminal row without terminal auto-wrap, simplify navigation keys, and expose the complete key reference through an in-editor help page.

## Scope

Only `custom_filter_draft.py` and its localized Dataset Custom filter strings change. Native `filter_draft.py`, Dashboard global help, filter values, Apply/Cancel semantics, wrapped filter tabs, and modal repaint boundaries remain unchanged.

## Single-line control bar

The filter editor receives its terminal width and produces a display-width-safe control line before passing it to its host paint callback. The line has three logical sections:

- left: `h Help` and left/right-arrow filter switching;
- middle: option navigation and editing actions;
- right: `Enter Apply` and `Esc Cancel`.

When the complete line exceeds the terminal width, a pure formatter preserves the left and right sections and replaces omitted middle content with one ellipsis. It measures terminal display cells, does not split wide characters, and always returns a line whose display width is at most the supplied width. Extremely narrow widths degrade through display-width clipping while retaining as much of both ends as possible.

The footer remains exactly one row at every supported width. It is not wrapped into a tuple of rows.

## Navigation keys

Outside search editing and help:

- Left/Right arrows switch filter dimensions.
- Up/Down arrows and `j`/`k` move through options.
- `h` opens filter help.
- Plain `l` no longer switches dimensions.
- Plain `h` no longer switches dimensions because it is reserved for help.

All existing search, toggle, clear, column, Apply, Cancel, mouse, and paste behavior remains unchanged. While search editing is active, printable `h` continues to append to the search query rather than opening help.

## Filter help page

Help is ephemeral editor state and does not alter the filter draft. Pressing `h` outside search opens a localized help page inside the existing Filter modal. It lists every active shortcut in full, including arrows, `j`/`k`, search editing, selection, clear, columns, Apply, and Cancel.

While help is visible:

- `h` or Escape closes help and returns to the unchanged filter editor;
- Ctrl-C retains its existing interrupt behavior;
- all other keyboard, paste, and mouse events are ignored;
- the footer contains a short localized `h/Esc Back` instruction, formatted to one row.

The help body is clipped to the editor width per row and to the available editor height. Returning preserves the active filter, focused option, viewport, query, search-editing flag, columns, and unsubmitted selections.

## Interfaces

`run_custom_filter_editor()` continues to accept the existing `paint(body, controls)` callback and `width`/`height` arguments. It owns help visibility and passes an already width-bounded localized control line to every host, so standalone, Dashboard, and Custom Monitor need no host-specific formatting.

## Tests

Extend `tests/test_custom_filter_draft.py` to cover:

- full controls at wide width;
- narrow controls retain the left help/navigation and right Apply/Cancel ends, contain one ellipsis, and never exceed width in English or Chinese;
- arrows switch dimensions while plain `l` does not;
- `h` opens help outside search but is inserted into an active search query;
- help lists the complete shortcuts;
- `h` and Escape return from help without changing draft state;
- mouse and ordinary keys are ignored while help is visible;
- every painted footer remains one physical terminal row and within the requested width.

## Non-goals

- No Dashboard global-help integration.
- No footer wrapping or horizontal scrolling.
- No changes to filter tab wrapping, option geometry, protocol behavior, or host repaint logic.
