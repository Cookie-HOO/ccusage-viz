# Dashboard Layout Model Redesign

## Intent

Make Dashboard layout flexible and conceptually clear by separating complete Dashboard presets from spatial layout. A preset answers what the Dashboard contains and how it is presented. Layout answers only how the current ordered Pane sequence occupies space.

This is an intentionally breaking redesign. It does not parse, migrate, alias, warn about, or preserve the old `grid` / named-layout model.

## Goals

- Represent every Dashboard topology with two user-facing integers: ordinary-grid column count and leading spotlight Pane count.
- Keep built-in and saved presets as complete Dashboard configurations that include, but are not confused with, layout.
- Let CLI users reproduce a topology precisely.
- Let TUI users edit topology transactionally with live preview.
- Preserve direct row-height and column-width adjustment as a separate interaction.
- Remove layout names and the overlapping meanings of `wide`, `narrow`, `all`, and `spotlight-wide*` from layout selection.

## Non-goals

- Compatibility with old CLI flags, copied commands, saved preset documents, internal state, or tests.
- Automatic column selection based on terminal width.
- Arbitrary two-dimensional Pane spanning or individually positioned Pane rectangles.
- Selecting spotlight Panes independently from Pane order.
- Moving size-weight editing into the topology editor.
- Adding mouse divider dragging as part of this work.

## Domain model

Dashboard host and immutable Dashboard state use these layout fields:

```python
columns: int
spotlight: int
column_weights: tuple[int, ...] | None
row_weights: tuple[int, ...] | None
```

The old `grid: str` and `layout: str | None` fields are deleted everywhere.

Validation is strict:

- `columns >= 1`;
- `0 <= spotlight <= pane_count`;
- every weight is a positive integer;
- `column_weights`, when present, has exactly `columns` entries;
- `row_weights`, when present, has exactly the resolved row count entries.

The defaults are `columns=2`, `spotlight=0`, and equal sizing on both axes. `None` weights mean equal sizing; reconciled runtime integer shares remain an implementation detail.

## Topology

Pane order is authoritative. The first `spotlight` Panes each occupy one full-width row, in order from top to bottom. All remaining Panes form the ordinary region, placed left-to-right and then top-to-bottom in exactly `columns` logical columns.

For `pane_count`, define:

```python
ordinary_count = pane_count - spotlight
ordinary_rows = ceil(ordinary_count / columns) if ordinary_count else 0
row_count = spotlight + ordinary_rows
```

The last ordinary row may be incomplete. Its missing cells are empty; present Panes retain the same logical column assignment and column weights as preceding rows. A Dashboard continues to require at least one Pane.

Examples:

- `columns=3, spotlight=0`: all Panes form a three-column grid.
- `columns=3, spotlight=2`: Pane 1 and Pane 2 are separate full-width rows; Pane 3 onward form a three-column grid beneath them.
- `spotlight=pane_count`: every Pane is a full-width row; `columns` remains stored but currently has no visible effect.

The topology builder emits the existing slot/rectangle primitives so rendering, directional navigation, hit testing, and size adjustment share one geometry. Named layout branches, fixed `R×C` parsing, automatic shape selection, and rendered layout names are removed.

## Structural changes and weights

Topology parameters remain stable while Panes are added, removed, or reordered, except that deleting Panes clamps `spotlight` to the new Pane count. `columns` is not reduced when fewer ordinary Panes remain. Inserting a Pane adds it according to the existing ordered insertion semantics; reordering naturally changes which first N Panes are spotlighted.

When a topology edit or Pane lifecycle operation changes the number of logical columns, reset `column_weights` to `None`. When it changes the number of logical rows, reset `row_weights` to `None`. Preserve weights on an axis whose band count is unchanged. This rule is applied at the mutation boundary, so persisted and historical state always validates; rendering must not silently repair invalid state.

## Presets

A preset remains a complete Dashboard declaration: Pane configurations and order, host/runtime settings, presentation, topology, and optional size weights.

Built-in presets become:

| Preset | Panes | Columns | Spotlight |
|---|---:|---:|---:|
| `wide` | 4 | 2 | 0 |
| `narrow` | 3 | 1 | 0 |
| `all` | 10 | 2 | 0 |
| `wide-clock` | 5 | 2 | 1 |
| `narrow-clock` | 4 | 1 | 0 |
| `single` | 1 | 1 | 0 |

Existing Pane content, presentation settings, and valid weight intent remain unchanged where applicable. `wide-clock` retains its three row weights; `narrow-clock` retains its four row weights.

The built-in presets `spotlight-wide` and `spotlight-wide2` are deleted. They are not aliases and are omitted from help, completion, diagnostics, tests, and documentation.

Saved preset schema advances from `ccuv.dashboard-presets/v1` to `ccuv.dashboard-presets/v2`. The host wire object contains `columns` and `spotlight`, and does not contain `grid` or `layout`. A v1 collection or any old host shape fails with the existing unsupported-schema/strict-validation path. No migration or fallback is provided.

Applying a preset replaces the current topology and weights along with the rest of its complete Dashboard state. Editing current layout does not modify a saved preset until the user explicitly saves or overwrites it through the preset manager.

## CLI

Dashboard exposes:

```text
--columns C
--spotlight N
--column-weight WEIGHT   # repeat once per column
--row-weight WEIGHT      # repeat once per resolved row
```

`--columns` and `--spotlight` use the validation rules above. Explicit CLI values override values supplied by a built-in or saved preset in the same way other explicit Dashboard host options do. Weight validation occurs after Pane assembly and topology resolution, so expected counts reflect the final Pane count and effective explicit/preset topology. If an explicit topology override makes inherited preset weights dimensionally incompatible, clear the incompatible inherited axis to equal sizing; do not reject an otherwise valid topology override. In contrast, explicitly supplied weight flags with the wrong count remain a usage error.

Examples:

```bash
ccuv dashboard wide --columns 3 --spotlight 2
ccuv dashboard all --columns 4 --spotlight 3
ccuv dashboard wide --columns 3 --spotlight 2 \
  --column-weight 10 --column-weight 16 --column-weight 8 \
  --row-weight 8 --row-weight 5 --row-weight 11
```

`--grid` and `--layout` are deleted. Passing either is an ordinary unknown-argument error, not a deprecation diagnostic.

Full-command copying serializes `--columns` and `--spotlight` and emits repeated weight flags when weights are set. Re-parsing the copied command must reproduce the current topology and sizing exactly. It never emits old fields or named layouts.

## TUI topology editor

Global adjustment mode exposes one layout-structure action:

```text
z  layout
```

Pressing `z` enters a modal, transactional topology editor over the current Dashboard. It has two vertically arranged fields:

```text
› Spotlight Panes   2
  Panes per row     3
```

Localized Chinese labels are `聚焦数量` and `每行数量`. Controls are:

- Up/Down or `k`/`j`: select the previous/next field;
- Left/Right or `-`/`+`: decrease/increase the selected value;
- Tab: cycle the selected field;
- Enter: apply the whole draft;
- Escape: cancel the whole draft.

The TUI ranges are `0..pane_count` for spotlight and `1..pane_count` for columns. Values stop at boundaries rather than wrapping.

Each value change immediately previews the draft topology in the actual Dashboard. Preview must use draft topology and draft-compatible weights without mutating accepted session state, preset storage, lifecycle/query state, or undo history. If an axis band count differs from the accepted topology, that axis previews equal weights; otherwise it previews accepted weights.

Enter commits `columns`, `spotlight`, and any required axis weight resets as one Dashboard history mutation. If the resulting declaration is unchanged, it creates no history entry. Escape discards the draft and restores the exact accepted display. Adjustment timeout behaves as cancellation. Help and controls describe the editor state without allowing topology keys to leak to the underlying Dashboard.

The old named-layout chooser and custom `R×C` draft input are deleted, including the global `Z` action and their validation/error UI.

## Direct size adjustment

Topology editing and size editing remain separate. With a Pane focused, existing controls continue to adjust the logical band containing that Pane:

- `{` / `}` adjust its column;
- `J` / `K` adjust its row.

For a spotlight Pane, column adjustment has no geometric effect because the Pane spans all columns; the action should therefore be unavailable/no-op through the existing geometry-change check. Row adjustment changes that spotlight row. For an ordinary Pane, adjustments affect its shared ordinary column or row.

Each accepted direct size adjustment keeps its current undo behavior. This redesign does not combine a later size adjustment with the preceding topology edit.

## State, history, persistence, and command boundaries

The new fields replace old layout fields in:

- parser namespace and explicit-option tracking;
- `DashboardHostConfig` and built-in preset declarations;
- CLI materialization and validation;
- `DashboardState`, snapshots, restoration, undo, and redo;
- TUI session accepted state and topology-editor draft state;
- saved preset v2 wire parsing and serialization;
- command copying and round-trip parsing;
- rendering geometry and pointer/navigation consumers;
- localized help, status, errors, user documentation, and architecture documentation.

Layout changes are presentation-only. They must not recreate providers, change Pane business configuration, trigger queries, reset viewport-local chart state, or alter refresh scheduling.

## Removal scope

Delete concepts and code whose only purpose is the old model, including:

- `NAMED_LAYOUTS`, named-layout parsing, fixed-grid parsing, auto-shape layout, and rendered layout variants;
- `grid` / nullable `layout` precedence and every `layout or grid` call site;
- `wide`, `narrow`, and `all` entries from any layout shortcut list;
- `spotlight-wide` and `spotlight-wide2` special topology branches and presets;
- custom grid text-entry state and events;
- old help text, errors, docs, and tests that expose `R×C`, auto, or named layouts.

Do not add compatibility aliases or leave dead terminology in public surfaces.

## Testing and acceptance

Tests cover at least:

1. Pure topology for zero through all Panes spotlighted, varying columns, incomplete final rows, and one Pane.
2. Exact geometry, spanning spotlight rows, weights, minimum dimensions, gutters, navigation, and hit testing.
3. Strict model/CLI validation and final-Pane-count weight validation.
4. Built-in preset membership and exact topology defaults; deleted spotlight presets are rejected.
5. CLI explicit overrides and copied-command round trips using only new flags.
6. Preset v2 serialization/materialization and explicit v1 rejection.
7. TUI editor selection, boundaries, aliases, live preview, Enter, Escape, timeout, unchanged commit, and one-step undo/redo.
8. No query/lifecycle work during preview or topology commit.
9. Pane insertion, deletion, reorder, spotlight clamping, automatic reflow, and per-axis weight preservation/reset.
10. Direct row/column sizing in spotlight and ordinary regions.
11. Updated bilingual help, controls, diagnostics, and documentation contain no public old-layout terms.
12. Repository format, lint, type-check, full tests, and package build pass.

Acceptance is achieved when users can construct any supported leading-spotlight-plus-grid topology with integer parameters, preview and commit it safely in the TUI, reproduce it through CLI and presets, and encounter no ambiguity between presets and layouts.