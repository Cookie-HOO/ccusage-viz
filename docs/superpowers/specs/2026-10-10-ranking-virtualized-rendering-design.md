# Ranking Virtualized Rendering Design

**Date:** 2026-10-10

## Goal

Keep large Dataset Ranking panes responsive by rendering only rows visible in a pane viewport rather than constructing formatted text, ANSI/OSC-8 link sequences, and click geometry for every ranked project.

## Design

The Ranking presentation renderer receives an optional viewport window expressed as a ranked-entry offset and visible entry count. It retains lightweight full-list work necessary for correct Ranking semantics: filtering, aggregate total/max, rank numbering, and any globally stable column measurements. It formats primary rows, description rows, comparison text, copy markers, and OSC-8 project links only for the requested window.

Dashboard calculates the available body height after pane chrome, notices, and controls. In normal browsing it requests the first visible window. In pane adjustment mode it requests the window at the adjustment offset. Up/Down changes that offset by one entry; Ctrl+Up/Ctrl+Down changes it by one visible page. No chart configuration or query changes occur.

The renderer returns explicit visible-entry geometry/identifiers alongside the rendered Ranking text, so Dataset Ranking copy/link hit testing uses only final visible rows and never scans a full generated chart string. The current no-viewport render contract remains unchanged for standalone and existing callers.

## Constraints

- Do not restore mouse-wheel Ranking scrolling.
- Preserve Ranking order, totals, percentages, bars/scales, comparison semantics, links, descriptions, and click behavior.
- Do not render unneeded per-entry ANSI, OSC-8, formatted values, or row strings.
- Dashboard full-frame composition remains unchanged; only Ranking pane content generation is virtualized.

## Tests

- A large projection with a small requested viewport formats only visible entries while retaining global rank/total/scale correctness.
- Offset changes select the expected ranked entries and clamp at the final page.
- Dataset copy/link hit targets map only rendered visible rows.
- Existing unwindowed renderer fixtures remain unchanged.
- Dashboard large Dataset Ranking accepts click/double-click shortly after render without requiring full-list row construction.
