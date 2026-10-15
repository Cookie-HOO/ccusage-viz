# Custom Refresh Display Policy Design

## Goal

Prevent Custom Ranking and Custom Monitor values from briefly becoming `??` during ordinary scheduled or user-initiated (`r`) refreshes. Preserve the current immediate-unknown behavior when the user changes data semantics, such as a metric, period, grouping, or filter.

## Scope

This policy applies to Custom Dataset Ranking and Monitor panes in Dashboard and standalone TUI surfaces.

It does not change query scheduling, source protocol contracts, accepted-result validation, or non-Custom charts.

## Refresh Classes

The host already labels operations with `LifecycleTrigger`. Rendering will use that operation reason together with whether the component has accepted facts:

| Refresh reason | Data semantics | Display while request is in flight |
| --- | --- | --- |
| `STARTUP` with no accepted result | Initial load | Loading / unknown state |
| `CONFIGURATION` that changes source facts | User switch (metric, range, group, filter, etc.) | Immediately show `??` / pending state for the target |
| `PERIODIC` | Same active configuration | Keep accepted values and mark as refreshing where existing chrome supports it |
| `MANUAL` (`r`) | Same active configuration | Keep accepted values and mark as refreshing where existing chrome supports it |

A configuration-only presentation change that does not require source data continues to re-render locally and must not show an unknown state.

## Data Flow and Rendering

1. Components retain their latest accepted response/model as they do today.
2. The pane lifecycle records the active `OperationToken`, whose `trigger` identifies whether the request is periodic, manual, startup, or configuration-driven.
3. A small rendering predicate determines whether retained accepted facts are eligible for display while a request is pending:
   - eligible for `PERIODIC` and `MANUAL` requests;
   - ineligible for data-affecting `CONFIGURATION` requests;
   - eligible only after the first accepted result for `STARTUP` (normally irrelevant after initial setup).
4. For an eligible refresh, Custom Ranking renders from its accepted projection/configuration and Custom Monitor renders from its accepted observation/history. Existing refresh/audit chrome supplies the in-flight indication without a new Custom-specific label.
5. For an ineligible request, render the current target’s pending/unknown state so stale values are never presented as the user’s newly selected metric, period, grouping, or filter.
6. On success, each existing component acceptance path atomically replaces the displayed accepted facts. On failure, preserve the prior accepted facts only for periodic/manual refreshes and surface the existing error indication; semantic switches retain their current failure behavior.

## `r` Decision

Global `r` is treated as `MANUAL`, not as a semantic switch. It retains every Custom Ranking/Monitor pane’s previously accepted values until replacement results arrive. This avoids an entire dashboard flashing to `??` merely because the user requested a refresh.

If `r` advances a relative time range, the retained display may temporarily describe the last accepted range. The refresh indicator communicates that it is being replaced; it must not be relabeled as the new range until the corresponding result is accepted.

## Testing

Add regression coverage for both Custom Ranking and Monitor that verifies:

- periodic refresh retains accepted numeric values while pending;
- global/manual refresh retains accepted numeric values while pending;
- a data-affecting user switch immediately renders unknown/pending target state;
- initial loading still renders pending/unknown state;
- successful completion replaces retained facts;
- a failed periodic/manual refresh retains accepted facts and reports the existing failure state.

Run focused TUI/component tests plus Ruff checks for changed files.

## Non-goals

- Do not introduce a cache beyond component-owned accepted facts.
- Do not alter custom provider requests or refresh cadence.
- Do not add a new global loading status UI.
- Do not apply this policy to built-in charts in this change.
