# Roadmap

`ccusage-viz` is currently at **0.1.0**. This roadmap describes public product contracts, not private implementation plans.

## 0.1.x

- Continue refining Dashboard layouts, pane scheduling, and the global summary without adding compatibility aliases.
- Add external Token and QPM data only when a supported upstream contract is available. External QPM will count logical requests and will never infer request counts from tokens or blindly count retries.
- Revisit animation only after a public design pass establishes its purpose, interaction model, terminal constraints, and maintenance boundary. It is not part of the current release contract.
- Evaluate interval-aware completed-result caches and bounded recent/history refreshes for long-range Watch and Dashboard historical panes. Current polling intentionally remains unchanged until correctness, invalidation, and source-specific semantics are validated.

## 0.2.0

A substantial release for incompatible contract changes, such as breaking CLI semantics, data-source assumptions, output guarantees, or other behavior that cannot be introduced compatibly in 0.1.x.

## 1.0

Declare 1.0 when the CLI, TUI, data-source, and output contracts are stable enough for long-term users and integrations.

## Feedback

- [Bug report](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=bug_report.yml)
- [Feature request](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=feature_request.yml)
