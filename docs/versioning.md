# Versioning

`ccusage-viz` uses semantic versioning while it remains pre-1.0:

- **Patch (`0.1.x`)**: bug fixes, verified rendering/query improvements, documentation, and Alpha-stage CLI or interaction refinements. Compatibility changes are documented in the release notes.
- **Minor (`0.x.0`)**: substantial new user-facing capabilities or source integrations before 1.0.
- Before `1.0`, public interfaces may still change between releases.

## 0.1.3

`0.1.3` refines the Alpha interaction and presentation contracts:

- historical ranges, Monitor query scopes, copied commands, and forwarded `ccusage`
  queries now use the host machine's local natural date; `--timezone` is no longer
  accepted, so users who relied on a different IANA boundary must run ccuv on a
  host configured for that local date;
- command, full-command, Markdown-table, and JSON inspection pages now scroll
  complete rendered text with Up/Down, `h` (top), and `e` (end); notices and
  controls remain fixed, and copying always retains the complete payload;
- the existing Monitor `cumulative-bars` presentation now uses clearer
  day/granularity titles, centered local-time labels, adaptive bar widths,
  responsive legends, deterministic Dashboard Demo warmup, and README examples;
- removed the redundant notice emitted when all groups already fit within
  `--top` and therefore no Other series is needed.

This release does not reconstruct historical intraday data or add any collector
integration.

## 0.1.2

`0.1.2` adds a Monitor-only view of retained token increments by local time of
day:

- `cumulative-bars` projects accepted Monitor samples into local calendar-day
  token bars instead of TPM, with existing Total, Agent, Model, and Project
  grouping plus full-day Top/Other selection;
- Monitor adjustment adds Today/Yesterday and hourly/30-minute bucket controls.
  These reproject retained samples without rebaselining the observer or changing
  the sampling cadence;
- distribution buckets retain full, partial, and unobserved coverage states,
  distinguish observed zero from missing observation data in table/JSON output,
  preserve sampling/reset gaps, and handle local DST fall-back days;
- Monitor table and JSON views expose aware bucket bounds, selected day and
  granularity, token-unit values, coverage, and the existing bounded project
  display provenance fields;
- standalone and Dashboard Monitor controls, renderer behavior, English and
  Simplified Chinese usage guidance, and regression coverage were aligned around
  the new view;
- Dashboard's `z` layout chooser now keeps fixed-capacity layouts visible but
  marks choices that cannot fit the current Pane count as unavailable, and
  navigation skips those choices.

This is observed, in-memory Monitor history only. It does not reconstruct
intraday history from historical providers or add a collector integration.

## 0.1.1

`0.1.1` improves project attribution safety, interactive reliability, and
project-oriented inspection:

- safer project presentation that never reconstructs opaque Claude identifiers as
  filesystem paths, with conservative Claude–Codex Name aggregation, clearer
  Agent-qualified Exact labels, and improved incomplete-attribution notices;
- project-grouped Monitor support for `--project-aggregation name|exact`, while
  preserving exact counters and deltas before display projection;
- bounded aggregation provenance in project Markdown and JSON data views through
  chart-matching `display_project` labels and payload-local `merge_group` values;
  Ranking expands Name groups into safe contributor rows, while `Other` remains
  aggregate-only;
- complete, case-insensitive matching for Agent, Model, and Project selectors,
  with one normalized lower-case model identity across filtering, aggregation,
  Monitor counters, and display;
- clearer candidate query, refresh, and partial-result states, including
  width-aware active-filter summaries in historical views, Monitor, and the TUI;
- recovery-oriented handling for recognized transient `unified_daily`
  local-database failures: accepted views remain available when possible and UI
  notices provide a sanitized retry/next-refresh path without exposing stderr;
- automatic return from standalone and Dashboard adjustment modes after three
  minutes without keyboard or mouse interaction; open filter drafts cancel with
  the same semantics as `Esc`;
- updated English and Simplified Chinese usage, design, README, and known-issues
  guidance.

`merge_group` is deterministic only within the current data payload; it is not a
durable project identifier. Its contributor rows are bounded display provenance,
not a raw-record or filesystem-path export.

## Deferred collector integration

A subsequent minor release may integrate the npm-packaged `ccuv-collector` once
its package and JSON protocol are stable. That integration will use a
collector-owned, opaque agent identity and provenance contract.
