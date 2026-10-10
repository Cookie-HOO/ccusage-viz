# Ranking Description Density Design

## Goal

Make Custom Dataset Ranking descriptions a deterministic part of the selected
content density. Keep `D` as the reverse density-cycle key rather than a
separate description-expansion control.

## Behavior

For a Custom Dataset Ranking that returns per-entry descriptions:

| Density | Description rows |
| --- | --- |
| `minimal` | Hidden |
| `compact` | Hidden |
| `normal` | Hidden |
| `full` | Shown |
| `detailed` | Shown |

The renderer still omits a row whose source data has no description. Native
Rankings remain unchanged because they do not provide Dataset descriptions.

## Interaction And Data Contract

- Remove `D descriptions` from standalone and Dashboard controls and help.
- `d` cycles density forward and `D` cycles it backward. Switching density is
  the only way to change description visibility.
- Keep the legacy `descriptions_default` capability field accepted for protocol
  compatibility, but ignore it for presentation and stop documenting it as a
  user-facing control.
- Preserve `description` as an optional Ranking-series response field. It is
  still localized, searchable, and rendered at most two muted rows when the
  chosen density permits it.

## Implementation And Tests

- Resolve description visibility from `ChartPresentation.density` at the TUI
  boundary, then pass that boolean to the shared ranking renderer.
- Simplify custom rendering calls by removing the caller-owned override.
- Update English and Chinese protocol/developer documentation to describe the
  density-based behavior and remove `D` references.
- Replace tests for capability defaults and the `D` toggle with coverage for
  all density levels, controls, the compatibility parser, and existing
  description rendering/search behavior.

## Non-Goals

- Do not alter the density semantics of native charts or non-Ranking custom
  charts.
- Do not persist a second description preference in Dashboard presets.
