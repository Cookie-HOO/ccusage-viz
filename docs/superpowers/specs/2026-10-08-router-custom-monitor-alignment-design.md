# Dataset Monitor Alignment Design

## Goal

Make Dataset V2 custom Monitor charts behave and render like the corresponding
ccusage-viz native Monitor surface, while retaining Dataset-owned observation
values and metric semantics.

## Scope

This change applies to Dataset Monitor charts in standalone and Dashboard
surfaces. It does not change Dataset telemetry, the V2 protocol, historical
custom charts, or native Monitor aggregation.

Dataset Monitor follows the same alignment pattern as the existing custom
historical charts: it retains source-owned facts and exposes a dedicated
projection, while each host surface applies the presentation conventions of
its native counterpart. It does not convert Dataset observations into
``UsageRecord`` values or share the built-in Monitor's token-delta lifecycle.

## Surface Alignment

Dashboard Dataset Monitor aligns with Dashboard native Monitor: the same chart
layout, style/theme/density/legend behavior, adjustment-page conventions, and
ranking/list attachment placement apply. Dataset-specific Dashboard additions
remain available: command log history (`L`) and chart, command, and full-command
views with copying.

Standalone Dataset Monitor aligns with standalone native Monitor: the same
frame composition, chart layout, status/notices, adjustment workflow, and
shortcut meanings apply. It does not acquire Dashboard pane management, log
overlays, or pane-local animation attachments.

## Interaction

The Dataset Monitor exposes the native Monitor presentation cycle appropriate
to its source aggregation:

- `sum`: `bars`, `cumulative-bars`, `ranking`, `list`
- `value`: `bars`, `ranking`, `list`

`s` advances and `S` reverses that cycle. The adjustment footer and help show
these Monitor-specific style options rather than historical Ranking styles.

`w` changes the locally retained Dataset observation horizon. It never changes
the window passed to the Dataset command. On sum metrics, cumulative bars show
Dataset observation windows over that local horizon and explicitly identify
unobserved intervals. Value metrics do not offer cumulative bars.

`b` and `B` cycle Dataset-declared grouping in declaration order, including
the ungrouped `Total` state:

```text
Total -> public_model -> real_model -> Total
```

`B` travels in the reverse direction. A grouping change is query-affecting and
immediately requests a matching Monitor observation.

## Rendering

The display preserves the Dataset's authoritative `total` and group values.
ccuv does not create `Other`, apply Top-N, calculate shares, show a percentage
column, synthesize a historical comparison, or derive a token delta.

All presentation modes use a Dataset-native Monitor projection directly:

- `bars` renders an ordered horizontal bar view with the Monitor heading and
  final value for each group.
- `ranking` renders a Monitor ranking with rank, label, bar, and final value,
  but no historical comparison or percentage.
- `list` renders rank, label, and final value without a bar or percentage.

The heading uses Dataset-owned metadata in this fixed order:

```text
<group> · <metric title> · <Dataset monitor period/window>
```

Each value comes from the selected Dataset metric, group declaration, and
Monitor capability. It does not reuse built-in Monitor's TPM/token or
agent/model wording.

## Animation

Dashboard Dataset Monitor attachments are available in `ranking` and `list`,
matching Dashboard native Monitor. Their activity state is driven by the latest
accepted Dataset observation total: positive values request playback; zero
values stop playback. They do not require a locally derived token delta.

## Errors And Freshness

Source-owned observations remain valid only for their exact query identity.
Changing grouping discards the candidate display until the matching request is
accepted. Existing runtime capability and interval-mismatch notices remain.

## Verification

Focused tests cover:

- Dashboard and standalone use their respective native Monitor presentation
  surfaces while consuming the same Dataset-native projection;
- style cycling includes cumulative bars only for sum metrics;
- `b/B` cycles through ungrouped and Dataset-declared groups in both
  directions;
- each presentation omits percentage/share output and preserves source values;
- headings use Dataset metric, group, and Monitor window metadata;
- Dashboard Monitor attachment playback follows positive and zero observations;
- no Dataset Monitor rendering path calls obsolete `timeline_model`,
  `ranking_model`, or `distribution_model` component methods.
