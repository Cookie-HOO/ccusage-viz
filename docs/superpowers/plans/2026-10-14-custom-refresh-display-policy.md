# Custom Refresh Display Policy Implementation Plan

## Goal

Keep accepted Custom Ranking and Monitor data visible while periodic and `r`-initiated refreshes run; show the target pending/unknown state immediately for data-affecting configuration changes.

## Design Reference

`docs/superpowers/specs/2026-10-14-custom-refresh-display-policy-design.md`

## Steps

1. Add a narrow TUI helper that identifies a retained-data refresh from the pane lifecycle operation: an accepted result exists and the active/pending operation is `PERIODIC` or `MANUAL`.
2. Apply the helper to Custom Historical Dashboard and standalone rendering. Keep the accepted projection for retained refreshes; route a configuration-triggered pending request to the existing target pending renderer, even if an accepted projection exists.
3. Apply the same trigger-aware policy to Custom Monitor Dashboard and standalone rendering. Periodic/manual refreshes render accepted observations with existing refresh chrome; configuration changes retain the existing pending target behavior.
4. Add focused tests for periodic/manual retention and configuration-switch unknown state for Custom Ranking and Monitor, including initial-load fallback.
5. Run focused pytest suites and Ruff checks. Stage only files belonging to this change; do not include unrelated worktree modifications.
