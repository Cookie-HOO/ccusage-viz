# Custom V2 Metric Switching Design

**Date:** 2026-10-12

## Goal

Let Dataset authors expose related but independently defined V2 Metrics—such as GitHub project cumulative Stars and days since last update—and let users switch them in place. This makes Ranking especially useful without inventing extra Ranking-only protocol concepts or forcing related values into descriptions.

The Dataset remains the authority over metric semantics, query interpretation, data membership, ordering, display, descriptions, units, and runtime constraints.

## Protocol

Add an optional `switch_group` to each V2 Metric descriptor:

```json
{
  "id": "stars",
  "label": {"en": "Stars", "zh-CN": "Star 数"},
  "switch_group": "github-tools-ranking",
  "capabilities": {"...": "..."}
}
```

- `switch_group` is a stable Dataset-local ID using the existing ID validation rules.
- Metrics with equal non-null `switch_group` are related candidates for in-place switching.
- Omitted `switch_group` means the Metric is not available through in-chart switching.
- A Metric belongs to at most one switch group. A group can contain one member to support incremental Dataset evolution.
- This is an additive V2 descriptor field. No protocol version, request field, or new sub-metric / Ranking-view type is introduced.
- A switch sends an ordinary V2 request using the target's existing `metric_id`.
- Existing explicit CLI and pane configuration retain `metric_id`; the group does not affect source selection semantics.

This deliberately reuses the established V2 multiple-Metric model. A Dataset author decides whether values are genuinely separate Metrics. If they are, their units, default settings, capabilities, summaries, presentation metadata, and runtime behavior remain independently owned.

## Candidate Selection and Controls

All V2 Custom chart kinds support in-place switching: Timeline, Stack, Calendar, Ranking, and Custom Monitor.

- `m` cycles forward and `M` cycles backward.
- Candidate order is exactly the declaration order in `descriptor.metrics`.
- A candidate must be in the current Metric's non-null `switch_group` and declare support for the active chart kind.
- The current Metric is included in the cycle, so one candidate means no effective destination.
- V1 Datasets never participate.
- The regular help always lists `m` / `M` as next / previous related Metric; it does not state the candidate count.
- If no alternate candidate exists, a press leaves the chart unchanged and shows a three-second notice that there is no related Metric to switch to.

## Fast Compatibility Check and Query Behavior

Metric switching preserves the pane's current query and presentation state. It does not apply target Metric defaults and does not silently reset values. Relevant state includes date range / period, fixed-range state, grouping, granularity, filters, Top / Other behavior, and chart-local presentation state.

Before sending a query, ccuv performs only cheap static checks from the target Metric declaration:

- target supports the active chart kind;
- if target declares `periods`, it includes the selected period;
- if target declares `group_by`, it includes the selected grouping;
- if target declares granularities, it includes the selected granularity.

A static mismatch rejects the switch, leaves the current Metric and facts unchanged, and shows a three-second warning identifying the incompatible field.

ccuv does not pre-query, Probe, or locally reproduce Dataset business rules. Filters, option validity, cross-field capability rules, data availability, and all Dataset-specific conditions are resolved by the ordinary target request.

For historical Custom charts, the switch is transactional: until the target request succeeds, the current Metric remains selected, rendered, and persisted. A target failure or `unsupported_query` leaves the old Metric and facts untouched and shows the normal failure feedback. On a successful target response, ccuv atomically replaces the selected `metric_id` with the target. The old Metric's facts, transient selection state, and any historical-query cache are discarded; it does not continue refreshing in the background. The accepted target response supplies its own title, label, unit, display, descriptions, summaries, and capabilities.

## Custom Monitor State

Custom Monitor must preserve sampling state per visited Metric rather than treating a switch as a reset.

Within a Monitor pane, maintain isolated runtime state by `metric_id`, including the component or equivalent accepted observations, comparison baseline, refresh scheduling, and capability-specific rendering state.

- The currently selected Metric is what the pane displays.
- First switching to a Metric creates its sampling state and establishes its baseline from its own observations.
- A Metric that has been visited continues sampling while another related Metric is displayed.
- Switching back restores that Metric's retained display history and ongoing sampling stream, as if it had never been hidden.
- Observation history, baselines, intervals, and comparison facts never cross Metric boundaries.
- Candidate Metrics that have never been visited are not prefetched or sampled, avoiding unexpected command execution.
- Target failure does not discard any retained state for previously visited Metrics.

The shared pane display window, focus, and local presentation settings persist through a switch, subject to the static compatibility checks above.

## Feedback and Persistence

- A successful switch briefly reports the target's localized label in the status area.
- Single-candidate and static-rejection notices expire after three seconds.
- A historical target request failure leaves the old chart selected and visible; it uses normal failure feedback without committing the target. Monitor failure does not discard retained per-Metric state.
- Dashboard presets persist only a successfully committed target `metric_id`; a pending or failed historical switch saves the old Metric.
- No new pane, CLI, or preset persistence field is needed.
- Existing V2 Datasets without `switch_group`, and all V1 Datasets, retain current behavior.

## Testing

1. **Protocol parsing and serialization**
   - Parse omitted and valid `switch_group` values.
   - Reject non-string, empty, and malformed IDs.
   - Preserve it through descriptor serialization / round-trip behavior.

2. **Candidate and input behavior**
   - Cycle forward and backward in descriptor order.
   - Exclude ungrouped Metrics, other groups, and Metrics that lack the active chart capability.
   - Verify a single candidate causes a notice without starting a request.
   - Keep `m/M` visible in help without a candidate count.

3. **Historical Custom charts**
   - Preserve all current state and replace only `metric_id` on a successful requested switch.
   - Reject declared period, group, or granularity mismatches before a request, retaining old data and configuration.
   - Send normal V2 target requests after static validation.
   - Keep the old Metric selected and rendered when a target request fails; discard old historical facts only after a successful target response.
   - Cover Ranking with independently rendered values, ordering, and descriptions for related Metrics.

4. **Custom Monitor**
   - Create state for a first-visited target Metric.
   - Keep visited Metric sampling alive while a different Metric is displayed.
   - Restore retained observations and baseline after switching back.
   - Prove observations and comparison facts do not mix between Metrics.
   - Ensure failed target queries do not damage retained state of other Metrics.
   - Verify a hidden, previously visited Metric keeps refreshing and resumes with continuous history when selected again.
