# Roadmap

[简体中文](roadmap.zh-CN.md)

`ccusage-viz` is currently at **0.2.2**. This roadmap describes public product
contracts and the prioritized requirement pool, not private implementation
plans.

## 0.2.x

- `0.2.x` makes terminal animation a first-class presentation capability:
  provider-free standalone animation, ccuv-owned gallery browsing, explicit
  Dashboard animation panes, clock presets, and opt-in state-aware Monitor
  attachments. Animations remain presentation-only and do not change token or
  Dataset data semantics.
- Continue refining Dashboard layouts, pane scheduling, and the global summary
  without adding compatibility aliases.
- Evaluate interval-aware completed-result caches and bounded recent/history
  refreshes for long-range Watch and Dashboard historical panes. Current
  polling intentionally remains unchanged until correctness, invalidation, and
  source-specific semantics are validated.

## 0.3.x

- `0.3.x` centers Custom Dataset as a public data-source capability: evolve
  Dataset discovery, installation, developer contracts, Metric selection, and
  Dashboard interaction while preserving Dataset ownership of source semantics.
- Continue developing related Custom Dataset capabilities such as Metric Groups,
  grouped Metric selection, in-pane switching, and Monitor behavior only when
  their protocol, lifecycle, resource, and compatibility contracts are explicit.
- This release line provides room for Custom Dataset contract changes that
  cannot be introduced compatibly in `0.2.x`.

## Requirement pool

- **Resumable Custom Monitor Metric switching:** after a user switches away
  from a previously visited related Metric, keep its sampling stream active
  within explicit resource bounds. Switching back should restore its retained
  observations and baseline as though it had never been hidden. This requires a
  dedicated design for per-Metric lifecycles, scheduling, cancellation,
  retention limits, error isolation, and a guarantee that observations and
  comparison facts never cross Metric boundaries.

## Feedback

- [Bug report](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=bug_report.yml)
- [Feature request](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=feature_request.yml)
