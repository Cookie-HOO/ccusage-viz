# Roadmap

[简体中文](roadmap.zh-CN.md)

`ccusage-viz` is currently at **0.3.2**. This roadmap describes public product
contracts and the prioritized requirement pool, not private implementation
plans.

## Delivered in 0.2.x

- Terminal animation became a first-class presentation capability through
  provider-free standalone animation, ccuv-owned gallery browsing, explicit
  Dashboard animation panes, clock presets, and opt-in state-aware Monitor
  attachments. Animations remain presentation-only and do not change token or
  Dataset data semantics.

## Current 0.3.x line

- `0.3.0` makes Custom Dataset a first-class public data-source capability with
  discovery, installation, developer contracts, Dashboard interaction, V2
  Metric Groups, grouped selection, in-pane related Metric switching,
  source-owned values, and Custom Monitor support.
- Continue hardening Dataset lifecycle and interaction behavior while preserving
  Dataset ownership of source semantics. Further retention behavior ships only
  when its protocol, resource, and compatibility contracts are explicit.
- Continue refining Dashboard layouts, pane scheduling, terminal performance,
  and global summaries without adding compatibility aliases.
- Evaluate interval-aware completed-result caches and bounded recent/history
  refreshes for long-range Dashboard historical panes. Current polling remains
  unchanged until correctness, invalidation, and source-specific semantics are
  validated.

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
