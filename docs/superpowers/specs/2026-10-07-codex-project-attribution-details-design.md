# Fixed Project Attribution Design

## Goal

Keep all observed token usage in project charts without presenting attribution
warnings or a separate diagnostics view.

## Design

The ccusage provider will represent ambiguous or unsupported project ownership
as ordinary project records under two global groups:

- `Unassigned`: no project locator is available, or the source cannot partition
  usage by project. This includes Codex sessions without a recoverable `cwd`,
  and OpenCode or Antigravity observations.
- `Unverified`: a project locator exists but is not an absolute path. This
  includes DSH or other agent rows such as `relative/project`.

The two groups merge across agents even under Exact aggregation. `v` expands
their rows with `attribution`, `source_project`, and `session_id` fields, so the
displayed project total remains traceable to its original source facts. Valid
absolute DSH paths become normal project records. Codex session IDs are shown
only in the data view, never in the chart label.

No project-attribution notices, `i` shortcut, or attribution-details view
remain after this change.

## Constraints

- Do not display session transcript content.
- Preserve raw source project values only in `v` for fixed-group records.
- Localize all new copy in English and Simplified Chinese.
- Fixed groups stay distinct from real projects and from each other.

## Validation

Provider, projection, and data-view tests cover fixed grouping, global group
merges, and expansion of the source attribution fields in `v`.
