# Custom Filter Tab Navigation Design

**Date:** 2026-10-13

## Goal

Restore Tab as a next-dimension navigation key in Dataset Custom Filter.

## Scope

Only `run_custom_filter_editor()` changes. Pressing Tab outside search editing and help moves to the next Custom filter dimension using the existing `CustomFilterDraft.move_filter(1, choices)` behavior.

Existing behavior remains unchanged:

- Right Arrow moves to the next dimension.
- Left Arrow moves to the previous dimension.
- Up/Down Arrows and `j`/`k` move through options.
- `h` opens Custom Filter help.
- During search editing, Tab retains the editor's existing printable/non-printable handling and does not switch dimensions.
- While help is visible, Tab is ignored like other non-help input.
- Dimension movement resets option focus, query, search-editing state, and viewport through the existing `move_filter()` implementation.

## Tests

Add a focused `tests/test_custom_filter_draft.py` regression proving Tab switches to the next dimension and Space toggles an option in that dimension. Existing tests continue to cover arrows, help, and search precedence.

## Non-goals

- No changes to native `run_filter_editor()` or its Dashboard, Watch, and Monitor hosts.
- No native Filter help or footer changes.
- No change to Custom Filter help, footer, rendering, selection semantics, or Ctrl-C handling.
- No unified native/Custom Filter refactor.
