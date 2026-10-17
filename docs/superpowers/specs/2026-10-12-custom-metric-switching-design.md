# Custom V2 Metric Switching Design

**Date:** 2026-10-12

## Goal

Let Dataset authors expose related but independently defined V2 Metrics—such as GitHub project cumulative Stars and days since last update—and let users switch them in place. This makes Ranking especially useful without inventing extra Ranking-only protocol concepts or forcing related values into descriptions.

The Dataset remains the authority over metric semantics, query interpretation, data membership, ordering, display, descriptions, units, and runtime constraints.

## Protocol

Add optional Dataset-level `metric_groups` resources and an optional `group_id` reference on each V2 Metric:

```json
{
  "metric_groups": [
    {
      "id": "github-tools",
      "title": {"en": "GitHub tools", "zh-CN": "GitHub 工具"}
    }
  ],
  "metrics": [
    {
      "id": "stars",
      "group_id": "github-tools",
      "title": {"en": "Stars", "zh-CN": "Star 数"},
      "capabilities": {"...": "..."}
    },
    {
      "id": "updated_days_ago",
      "group_id": "github-tools",
      "title": {"en": "Days since update", "zh-CN": "距上次更新天数"},
      "capabilities": {"...": "..."}
    }
  ]
}
```

- `metric_groups` is an optional ordered Dataset-level resource list. Every group has a unique stable ID and a required localized title.
- `Metric.group_id` is optional. When present, it must reference a declared Metric Group; a Metric belongs to at most one group.
- Metrics referencing the same Group are related candidates for in-place switching. A group may have one or zero members to support incremental Dataset evolution.
- A Dataset that omits `metric_groups` remains completely compatible: its Metric chooser is flat and `m/M` does not provide related-Metric switching.
- A Metric without `group_id` remains a normal flat chooser entry, after declared groups, and does not participate in `m/M`.
- A Group title such as `Unspecified` / `未声明` is ordinary Dataset-provided localized text. It is not a reserved representation of a missing `group_id` and behaves as every other Group.
- This is an additive V2 descriptor field. No protocol version, request field, or new sub-metric / Ranking-view type is introduced.
- A switch sends an ordinary V2 request using the target's existing `metric_id`.
- Existing explicit CLI and pane configuration retain `metric_id`; the Group does not affect source selection semantics.

This deliberately reuses the established V2 multiple-Metric model. A Dataset author decides whether values are genuinely separate Metrics. If they are, their units, default settings, capabilities, summaries, presentation metadata, and runtime behavior remain independently owned.

## Candidate Selection and Controls

All V2 Custom chart kinds support in-place switching: Timeline, Stack, Calendar, Ranking, and Custom Monitor.

- `m` cycles forward and `M` cycles backward.
- Candidate order is exactly the declaration order in `descriptor.metrics`.
- A candidate must reference the current Metric's declared `group_id` and declare support for the active chart kind.
- The current Metric is included in the cycle, so one candidate means no effective destination.
- V1 Datasets, ungrouped Metrics, and Datasets that omit `metric_groups` never participate.
- The Dataset-and-Metric chooser remains flat when `metric_groups` is omitted. When Groups are declared, it renders nonempty Groups in `metric_groups[]` order, displays each localized Group title, and indents members in `metrics[]` order below it. Metrics without `group_id` are then rendered as ordinary flat entries, with no host-generated heading. Empty Groups are not rendered.
- The regular help always lists `m` / `M` as next / previous related Metric; it does not state the candidate count.
- If no alternate candidate exists, a press leaves the chart unchanged and shows a three-second notice that there is no related Metric to switch to.

## Dataset-Driven Switch Normalization and Query Behavior

Metric switching initially preserves the pane's complete query and presentation
state: date range / period, fixed-range state, grouping, granularity, filters,
Top / Other behavior, and chart-local presentation state. ccuv does not perform
static capability compatibility rejection before that first target request.

The Dataset is the authority for Metric-specific compatibility. A normal target
request may accept the preserved state, or return its existing structured
`unsupported_query` error with `unsupported.field`. Only an `m/M`-initiated
Metric switch may normalize and retry that target request:

| Dataset `unsupported.field` | Target Metric normalization |
| --- | --- |
| `range.period` | Replace the period with `defaults.<kind>.period`. |
| `query.group_by` | Replace grouping with `defaults.<kind>.group_by`. |
| `query.granularity` | Replace granularity with `defaults.<kind>.granularity`. |
| `query.filters` or `query.filters.*` | Replace the entire filters state with `defaults.<kind>.filters`; use empty filters when no default exists. |
| `query.top` | Replace Top with `defaults.<kind>.top`. |

The Dataset reports one currently invalid field at a time. ccuv applies only
that field's target-Metric default and issues another ordinary target request.
It does not normalize `other`, style, theme, or any host-only presentation
property. A repeated unsupported category, an unknown field, a missing default,
or a default that would not change the request stops normalization and leaves
the current Metric selected.

Normalization is deliberately unavailable for direct user adjustments (`p/P`,
`b/B`, `g/G`, `f`, `+/-`): those retain their strict existing rejection
semantics. It is also unavailable for V1 Datasets and source replacement.

For historical Custom charts, switching remains transactional: until a target
request ultimately succeeds, the current Metric remains selected, rendered, and
persisted. A non-normalizable failure leaves old facts untouched and displays
the normal Dataset error. On success, ccuv atomically commits the target
`metric_id` and normalized configuration. The old Metric's facts, transient
selection state, and historical-query cache are discarded; it does not continue
refreshing in the background. The accepted target response supplies its own
title, label, unit, display, descriptions, summaries, and capabilities.

## Custom Monitor State

Custom Monitor follows the same transactional switch semantics as historical Custom charts. It does not retain or background-refresh Metrics after a successful switch.

- The currently selected Metric is what the pane displays and samples.
- Until the target Metric returns a successful first observation, the prior Metric remains selected, rendered, sampled, and persisted.
- A target failure leaves the prior Metric's observations, baseline, error-free state, and persisted `metric_id` untouched.
- On a successful target observation, ccuv atomically commits the target Metric and discards the prior Metric's observations, baseline, error state, and sampling state.
- Returning to a previously used Metric starts a fresh Monitor stream and baseline; it does not restore or prefetch old Metric history.
- Observation history, baselines, intervals, and comparison facts never cross Metric boundaries.

The shared pane display window, focus, and local presentation settings persist through a switch. Monitor uses the same Dataset-driven normalization retries before committing the target, and retains its existing single lifecycle and scheduler.

### Future optimization: resumable Monitor Metrics

Out of scope for this implementation: retain an independently scheduled sampling stream for each visited Metric after it is hidden, then restore its observations and baseline when users switch back. This would make a return switch appear uninterrupted, but requires per-Metric component state, concurrent per-pane lifecycles, cancellation/retirement rules, and explicit resource limits. It must never mix observations or comparison facts across Metrics. The current transactional design deliberately discards the old stream after a successful switch.

## Feedback and Persistence

- A successful switch briefly reports the target's localized label in the status area.
- A single-candidate notice expires after three seconds.
- A successful normalized switch reports the target localized label and the fields reset to target defaults (for example, period changed to `all` or filters reset).
- A target request failure leaves the old chart or Monitor selected and visible; it uses normal failure feedback without committing the target.
- Dashboard presets persist only a successfully committed target `metric_id`; a pending or failed switch saves the old Metric.
- No new pane, CLI, or preset persistence field is needed.
- Existing V2 Datasets without `metric_groups`, and all V1 Datasets, retain current behavior.

## Testing

1. **Protocol parsing and serialization**
   - Parse omitted and valid `metric_groups` resources and Metric `group_id` references.
   - Reject duplicate, non-string, empty, malformed, or unresolvable Group IDs.
   - Preserve groups and references through descriptor serialization / round-trip behavior.

2. **Candidate and input behavior**
   - Cycle forward and backward in descriptor order.
   - Exclude ungrouped Metrics, other Groups, and Metrics that lack the active chart capability.
   - Cover flat legacy chooser rendering, grouped chooser ordering and indentation, omitted `group_id` flat entries, and invisible empty Groups.
   - Verify a single candidate causes a notice without starting a request.
   - Keep `m/M` visible in help without a candidate count.

3. **Historical Custom charts**
   - Preserve all current state and replace only `metric_id` on a successful requested switch.
   - Send the preserved complete configuration as the first target request, even where target static capability declarations differ.
   - Normalize one Dataset-reported unsupported field at a time to the target Metric default, including full-filter reset for every `query.filters` field.
   - Stop safely for unknown, repeated, unchanged, or default-less unsupported fields and keep old facts selected.
   - Keep the old Metric selected and rendered when target normalization ultimately fails; discard old historical facts only after a successful target response.
   - Cover Ranking with independently rendered values, ordering, and descriptions for related Metrics.

4. **Custom Monitor**
   - Keep the old selected observations and baseline while target requests or normalization retries are pending or ultimately fail.
   - Commit the target only after its first accepted observation, then discard all prior Metric sampling state.
   - Verify returning to a previously used Metric starts a fresh stream.
   - Prove observations and comparison facts never cross Metric boundaries.
