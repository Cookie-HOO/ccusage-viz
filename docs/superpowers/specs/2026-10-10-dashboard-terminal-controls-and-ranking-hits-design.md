# Dashboard Terminal Controls and Ranking Hit Testing Design

**Date:** 2026-10-10

## Goal

Restore terminal-first Dashboard interaction without mouse-wheel chart scrolling:

- Pane adjustment/edit mode scrolls with Up/Down and Ctrl+Up/Ctrl+Down.
- `c` globally and persistently toggles Dashboard controls.
- Dataset Ranking copy and project-link mouse targets work on a single click.
- A double-click in a Ranking copy/link target is treated exactly as one target click, not as pane-edit entry.

## Scope

This design applies to the interactive Dashboard only. It does not restore wheel scrolling, alter Ranking data, change standalone charts, or change query/scheduler behavior.

## Adjustment-Mode Keyboard Scrolling

When Dashboard pane adjustment mode is active, its content uses a terminal viewport:

- Up and Down move the edit panel viewport by one rendered line.
- Ctrl+Up and Ctrl+Down move by one viewport page.
- The viewport offset is local to the active adjustment presentation and is clamped to the rendered panel bounds.
- These keys never alter chart configuration, submit a query, move pane focus, or exit adjustment mode.
- Existing adjustment letter keys retain their current behavior.
- The offset resets when the active adjustment target changes or adjustment mode is exited.

## Global Persistent Controls Toggle

`c` is handled before Dashboard pane/modal-specific key routing whenever the Dashboard owns normal keyboard input.

- It toggles one Dashboard-session `controls_hidden` flag.
- The flag applies to all Dashboard bodies: chart, pane adjustment, modal/editor surfaces where controls are host-composed, and text views.
- Pane changes, focus changes, edit-mode entry/exit, and body-view changes do not reset it.
- Only another `c` restores controls.
- `c` remains unavailable only to an input field that explicitly owns literal text entry, such as a source/editor draft.

## Dataset Ranking Mouse Targets

Dataset Ranking rendering records hit rectangles from the same final line/column geometry used to draw each entry:

- Copy glyph rectangle: a single click copies the entry’s existing clipboard representation and shows current feedback.
- Project-link rectangle: a single click invokes the existing external-link opener for that entry URL.
- A click outside both rectangles is available to Dashboard pane click/double-click handling.
- Either target consumes the click before pane double-click detection. Consequently a double-click on copy or link is two target clicks and never opens pane adjustment.
- Hit data is refreshed with every Ranking render and cleared when the pane is not rendering a compatible Dataset Ranking, preventing stale targets after resize, filtering, or view changes.

## Tests

Add focused Dashboard tests for:

1. adjustment Up/Down and Ctrl+Up/Ctrl+Down viewport calculations without chart configuration/query mutations;
2. persistent global `c` across pane adjustment and body-view transitions;
3. Dataset Ranking single-click copy and link targets using final rendered coordinates;
4. double-clicking a target does not enter pane adjustment; and
5. ordinary double-click outside targets still enters pane adjustment.

Run existing Dashboard, Dataset Ranking, input, and rendering regressions.
