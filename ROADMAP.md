# Roadmap

`ccusage-viz` is currently at **0.1.2**. This roadmap describes public product contracts, not private implementation plans.

## 0.1.x

- `0.1.2` adds Monitor-local, calendar-day token distribution through `cumulative-bars`, including Today/Yesterday and hourly/30-minute projection controls, transparent retained-sample coverage, and table/JSON inspection. It does not add a collector integration.
- Continue refining Dashboard layouts, pane scheduling, and the global summary without adding compatibility aliases.
- Evaluate interval-aware completed-result caches and bounded recent/history refreshes for long-range Watch and Dashboard historical panes. Current polling intentionally remains unchanged until correctness, invalidation, and source-specific semantics are validated.

## 0.2.x

Integrate npm-packaged `ccuv-collector` after its package and versioned JSON protocol
are stable. It will supplement `ccusage` only for token data that `ccusage` does
not cover.

`ccuv-collector` owns normalization, local incremental state, adapter-local
deduplication, and opaque Agent/provenance identity across its own adapters.
`ccusage-viz` will invoke `ccusage` and the collector independently, normalize
both into its common domain, and own cross-component precedence and deduplication.
The public contract must define availability/error classification, overlap notices,
privacy boundaries, and fixture-based compatibility tests before integration.

This release series also provides room for other incompatible contract changes, such as breaking CLI semantics, data-source assumptions, or output guarantees that cannot be introduced compatibly in 0.1.x.

## 0.3.x

Integrate the separately maintained `term-animate` capability after a public design
pass establishes purpose, terminal capability fallback, reduced-motion/disable
controls, frame/resource budgets, and lifecycle ownership. Standalone views and
Dashboard panes may host additional animations while static chart and data
correctness remain independent of animation. This does not promise Monitor
state-driven animation until a stateful animation contract is ready.

## 1.0

Declare 1.0 when the CLI, TUI, data-source, and output contracts are stable enough for long-term users and integrations.

## Feedback

- [Bug report](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=bug_report.yml)
- [Feature request](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=feature_request.yml)
