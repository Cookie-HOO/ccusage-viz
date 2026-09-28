# Roadmap

`ccusage-viz` is currently at **0.2.0**. This roadmap describes public product
contracts, not private implementation plans.

## Current direction

- `0.2.0` makes terminal animation a first-class presentation capability:
  provider-free standalone animation, ccuv-owned gallery browsing, explicit
  Dashboard animation panes, `wide-clock` and `narrow-clock` presets, and
  opt-in state-aware Monitor attachments. Animations remain presentation-only
  and do not change token data semantics.
- Continue refining Dashboard layouts, pane scheduling, and the global summary
  without adding compatibility aliases.
- Evaluate interval-aware completed-result caches and bounded recent/history
  refreshes for long-range Watch and Dashboard historical panes. Current
  polling intentionally remains unchanged until correctness, invalidation, and
  source-specific semantics are validated.
- Improve verified project attribution and source-specific compatibility
  coverage while preserving conservative token-only data handling.

## 1.0

Declare 1.0 when the CLI, TUI, data-source, and output contracts are stable
enough for long-term users and integrations.

## Feedback

- [Bug report](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=bug_report.yml)
- [Feature request](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=feature_request.yml)
