# CLI Preset Error Guidance Design

## Goal

Extend the existing invalid-subcommand guidance style to the two public preset positions that currently look inconsistent: `dashboard PRESET` and `text PRESET`. Preserve all successful parsing, preset loading, launch construction, routing, and execution behavior.

## User-facing behavior

An invalid Text preset keeps argparse's original detail and adds a localized preset list and, when there is one strong match, a suggestion:

```text
Invalid arguments: argument PRESET: invalid choice: 'time-stte' (choose from time-state)
Supported presets: time-state
Did you mean 'time-state'?
```

An unknown Dashboard preset keeps the current semantic error detail and adds all currently valid preset names:

```text
Invalid arguments: unknown dashboard preset: wid-clock
Supported presets: wide, spotlight-wide, spotlight-wide2, narrow, all, narrow-clock, wide-clock, single, my-preset
Did you mean 'wide-clock'?
```

English and Chinese localize the labels and suggestion sentence. Preset IDs remain literal.

## Candidate ownership and ordering

Text has one static candidate, `time-state`, declared once and reused by the parser and diagnostic metadata.

Dashboard candidates are the stable, de-duplicated concatenation of:

1. built-in `DASHBOARD_PRESETS` keys in their existing declaration/insertion order;
2. user preset names returned by `DashboardPresetStore.list()` in its existing validated stable order.

If a user preset has the same name as a built-in preset, it appears once. The change does not alter which preset wins or how a valid preset is materialized.

## Architecture

Generalize the existing close-match diagnostic builder so callers provide the localized item noun through distinct message keys or an explicit diagnostic kind. Command errors continue rendering `Supported commands`; preset errors render `Supported presets`. The matching algorithm, conservative cutoff, single-suggestion rule, original-detail preservation, and exit code remain shared.

For Text, configure the `LocalizedParser` with positional-choice metadata for the exact `preset` argument. Detection stays narrowly scoped to that parser and that argument, so invalid `--lang` values and other option errors remain ordinary one-line argument errors.

For Dashboard, do not add argparse `choices`: user preset names are dynamic, and valid user presets must continue parsing before storage lookup. Reuse the `DashboardPresetStore` instance already needed by the named-preset path. Once the store has loaded successfully, retain its listed records for both exact lookup and unknown-preset diagnostics rather than reading storage again. If loading is absent, corrupt, or unavailable, preserve current semantics:

- an absent collection contributes no user candidates;
- corrupt/unreadable storage keeps the existing storage-unavailable error where it currently applies;
- a valid built-in preset remains available despite a corrupt user collection, as today.

Only the final unknown-preset branch constructs preset guidance. It receives the original detail, merged candidates, and rejected preset name. No suggested value is executed or substituted.

## Diagnostic-only constraint

Every argv sequence that currently succeeds must produce the same namespace, selected preset, launch configuration, route, side effects, and exit behavior. The change must not modify built-in preset definitions, user preset persistence, precedence, default Dashboard selection, preset materialization, or Text output. An invalid preset remains exit code 2.

## Testing

Tests cover:

1. invalid `text time-stte` lists only `time-state` and suggests it in English and Chinese;
2. unrelated Text option/value failures do not receive preset guidance;
3. an unknown Dashboard preset lists all built-ins in stable order;
4. saved user presets are included after built-ins and can be suggested;
5. duplicate built-in/user names appear only once;
6. a distant Dashboard value lists presets without a suggestion;
7. corrupt/unavailable user storage retains existing errors and does not become an unknown-preset diagnostic;
8. valid built-in and user presets produce the same launch behavior as before;
9. neither invalid Text nor Dashboard preset reaches runtime execution.

## Scope

This change covers only `dashboard PRESET` and `text PRESET`. It does not alter animation styles, layout names, themes, chart styles, option-value diagnostics, fuzzy execution, aliases, or help output.
