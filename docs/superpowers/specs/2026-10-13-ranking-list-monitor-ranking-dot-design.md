# Ranking List and Monitor Ranking-Dot Design

## Goal

Expose a text-only `list` presentation for historical Ranking charts, and expose a `ranking-dot` Monitor presentation that adds a leading categorical dot to each Monitor ranking row.

## Scope

- Historical Ranking supports `dot`, `bar`, `dots`, and new `list` styles.
- `list` reuses the established list layout: rank/status, label, current value, optional comparison/value metadata, and descriptions. It renders no proportional bar, dot track, or filled graphic.
- Monitor supports a new `ranking-dot` style in addition to the existing `ranking` and `list` styles.
- `ranking-dot` uses the existing Ranking model, grouping, refresh, observation, description, animation, and list-like Monitor controls. It differs from `ranking` only by a leading item marker.
- The marker uses each entry's categorical palette color. In no-color or ASCII contexts it falls back to an aligned plain-text marker.
- The behavior applies to native and Custom Dataset charts in standalone and Dashboard surfaces because both use the shared render/configuration paths.

## Architecture

`COMMAND_STYLES` is the source of selectable CLI and interactive styles. Add `list` to `ranking` and `ranking-dot` to `monitor`. Existing style-cycle and compatibility code continues to use this source.

The Monitor component and Custom Monitor renderer classify `ranking-dot` as a RankingModel presentation, alongside `ranking` and `list`. Existing Monitor-specific features that currently recognize `ranking`/`list` must recognize `ranking-dot` as well, so it has the same no-window control behavior and animation eligibility.

The shared ranking renderer remains responsible for both historical and observed ranking rows. Its historical list branch supplies the new Ranking style. Its observed branch emits a leading categorical dot only when `context.style == "ranking-dot"`; ordinary `ranking` output remains byte-for-byte behaviorally unchanged.

## Data Flow and Error Handling

Both additions are presentation-only. Style selection changes neither provider requests nor ranking order, aggregation, Monitor baselines, refresh cadence, retained observations, search, scrolling, descriptions, or export semantics. Existing fallback handling for missing values, narrow terminals, color-disabled terminals, and ASCII terminals remains in force.

An unrecognized persisted style continues to be normalized through the existing compatible-style projection.

## Tests

Add focused tests for:

- Ranking style availability and style-cycle inclusion of `list`.
- Monitor style availability/cycling and RankingModel projection for `ranking-dot`.
- Historical native and Custom Ranking list rendering without proportional glyphs.
- Observed native and Custom Monitor `ranking-dot` rendering with its marker, including color-disabled and ASCII fallback behavior.
- Existing `ranking`, `list`, controls, and animation behavior remain unchanged except for accepting `ranking-dot` where ranking-like styles are supported.
