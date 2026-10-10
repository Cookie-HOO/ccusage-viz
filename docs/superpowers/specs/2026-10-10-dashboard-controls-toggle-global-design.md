# Dashboard Controls Toggle Global Design

**Date:** 2026-10-10

## Goal

Present the Dashboard `c` control-bar toggle as a global operation rather than as a chart-local browsing control.

## Behavior

- In Dashboard chart browse mode, `c` continues to toggle the Dashboard controls/footer visibility.
- The global operations row advertises `c` alongside undo, redo, and Help.
- The ordinary chart-browse controls sentence no longer advertises `c`.
- Standalone chart controls remain unchanged because they do not have a Dashboard global-operations row.
- English and Chinese labels, usage documentation, and Dashboard interaction tests remain aligned.
