# Ranking List and Monitor Ranking-Dot Design

## Goal

Expose a text-only `list` presentation for historical Ranking charts, and expose a `ranking-dot` Monitor presentation that renders the proportional graphic with Ranking's single-dot track.

## Scope

- Historical Ranking supports `dot`, `bar`, `dots`, and new `list` styles.
- `list` reuses the established list layout: rank/status, label, current value, optional comparison/value metadata, and descriptions. It renders no proportional bar, dot track, filled graphic, or graph-column heading; every remaining heading aligns with its data column.
- Monitor supports a new `ranking-dot` style in addition to the existing `ranking` and `list` styles.
- `ranking-dot` uses the existing Ranking model, grouping, refresh, observation, description, animation, and list-like Monitor controls. It differs from `ranking` only in the middle proportional graphic: the filled bar becomes Ranking's single-dot position track.
- The track uses `●` and `·`, with `o` and `.` in ASCII mode, and follows the existing Ranking dot color semantics. It does not add a marker before the rank or label.
- The behavior applies to native and Custom Dataset charts in standalone and Dashboard surfaces because both use the shared render/configuration paths.

## Architecture

`COMMAND_STYLES` is the source of selectable CLI and interactive styles. Add `list` to `ranking` and `ranking-dot` to `monitor`. Existing style-cycle and compatibility code continues to use this source.

The Monitor component and Custom Monitor renderer classify `ranking-dot` as a RankingModel presentation, alongside `ranking` and `list`. Existing Monitor-specific features that currently recognize `ranking`/`list` must recognize `ranking-dot` as well, so it has the same no-window control behavior and animation eligibility.

The shared ranking renderer remains responsible for both historical and observed ranking rows. Its historical list branch supplies the new Ranking style. Its observed branch selects the established single-dot track when `context.style == "ranking-dot"`; ordinary `ranking` output remains byte-for-byte behaviorally unchanged. The historical comparison-table list branch omits the graph heading and graph field together, then reallocates that width to the label while retaining the remaining column alignment.

## Data Flow and Error Handling

Both additions are presentation-only. Style selection changes neither provider requests nor ranking order, aggregation, Monitor baselines, refresh cadence, retained observations, search, scrolling, descriptions, or export semantics. Existing fallback handling for missing values, narrow terminals, color-disabled terminals, and ASCII terminals remains in force.

An unrecognized persisted style continues to be normalized through the existing compatible-style projection.

## Tests

Add focused tests for:

- Ranking style availability and style-cycle inclusion of `list`.
- Monitor style availability/cycling and RankingModel projection for `ranking-dot`.
- Historical native and Custom Ranking list rendering without proportional glyphs.
- Observed native and Custom Monitor `ranking-dot` rendering with a middle single-dot track, including color-disabled and ASCII fallback behavior, and no leading marker.
- Existing `ranking`, `list`, controls, and animation behavior remain unchanged except for accepting `ranking-dot` where ranking-like styles are supported.
