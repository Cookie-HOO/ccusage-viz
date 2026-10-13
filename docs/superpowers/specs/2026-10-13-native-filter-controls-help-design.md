# Native Filter Controls and Help Design

**Date:** 2026-10-13

## Goal

Bring the shared native Filter editor used by Dashboard, Watch, and Monitor to the same safe terminal interaction standard as Custom Filter, while restoring Tab dimension switching in Custom Filter.

## Scope

The native `run_filter_editor()` gains a one-line footer, in-editor help, revised navigation, and explicit Ctrl-C propagation. Because Dashboard, Watch, and Monitor share this editor, all three native Filter hosts receive the behavior. Custom Filter changes only by restoring Tab as a next-dimension key; its existing help, footer, search, grid, repaint, and Ctrl-C behavior remain unchanged. Standalone Custom Historical Ctrl-C handling is out of scope.

## Native Filter controls

The native footer always occupies one physical terminal row and is bounded by the supplied terminal display width. It has three semantic sections:

- left: `h Help` and `Tab/←/→` dimension navigation;
- middle: `↑/↓ or j/k` option navigation and Space toggle;
- right: Enter Apply and Escape Cancel.

When the complete footer is too wide, it preserves the left and right sections and replaces the middle with one ellipsis. On extremely narrow terminals it uses display-width-safe middle truncation. It never emits a newline or exceeds the requested display width.

The formatting behavior should be shared with Custom Filter through a small generic three-section formatter rather than duplicated, while native and Custom retain separate localized action text.

## Native navigation

Outside help:

- Tab and Right Arrow move to the next available dimension with existing wraparound behavior.
- Left Arrow moves to the previous available dimension with existing wraparound behavior.
- Up/Down Arrows and `j`/`k` move through choices.
- Space toggles the focused value.
- `h` opens help.
- Plain `l` no longer changes dimension.
- Enter applies and Escape cancels as before.

## Native help

Help is ephemeral loop state and does not modify `FilterDraft`. Pressing `h` opens a localized help page inside the current Filter modal. It lists dimension navigation, option navigation, toggle, Apply, Cancel, Help return, and Ctrl-C exit.

While help is visible:

- `h` or Escape returns to the unchanged Filter editor;
- Ctrl-C raises `KeyboardInterrupt` immediately;
- all other input is ignored.

The help body clips each row to terminal display width. The existing `run_filter_editor()` callback interface does not change.

## Ctrl-C

Both normal native Filter and native Filter help explicitly raise `KeyboardInterrupt` on a real Ctrl-C key. Dashboard, Watch, and Monitor retain responsibility for cleanup and program exit through their existing outer handlers. No host catches Ctrl-C merely to return to the Filter caller.

## Custom Tab behavior

Custom Filter adds Tab to the existing Right Arrow next-dimension route. Left Arrow remains previous-dimension. `h/l` remain unavailable for dimension switching, and Custom help/search behavior is unchanged.

## Tests

Native Filter tests cover:

- full and compact one-line controls in English and Chinese;
- display width never exceeds the requested width;
- Tab/Right/Left dimension movement and wraparound;
- Up/Down and `j/k` choice movement;
- plain `l` does not switch dimensions;
- help content and `h`/Escape return without draft mutation;
- ordinary input is ignored in help;
- Ctrl-C raises in both editor and help;
- Apply, Cancel, and Space behavior remain unchanged.

Custom Filter receives a focused regression proving Tab moves to the next dimension and that its existing arrow/help/search behavior remains intact.

## Non-goals

- No change to native filter data discovery, rendering, selection semantics, or host repaint lifecycle.
- No attempt to merge `FilterDraft` and `CustomFilterDraft`.
- No change to Standalone Custom Historical Ctrl-C handling.
