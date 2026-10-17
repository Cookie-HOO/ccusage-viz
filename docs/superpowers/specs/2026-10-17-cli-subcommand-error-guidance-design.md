# CLI Subcommand Error Guidance Design

## Goal

Make mistyped CLI subcommands actionable without making unrelated argument errors noisy. When parsing fails because a token is not a valid subcommand, preserve the existing localized argparse diagnostic and append the commands accepted at that exact level. When one supported command is a strong spelling match, also append a localized suggestion.

## Behavior

Guidance is scoped to the parser level that rejected the token:

- `ccuv dashbaord` lists the top-level commands: `chart`, `dashboard`, `animate`, `dataset`, and `text`, and suggests `dashboard`.
- `ccuv chart timline` lists the chart kinds: `timeline`, `calendar`, `stack`, `ranking`, and `monitor`, and suggests `timeline`.
- `ccuv dataset foo` lists the Dataset operations: `list` and `add-local`; it only suggests an operation when there is one strong match.
- Ordinary option/value failures, missing required values, and semantic validation errors retain their current output and do not gain a command list.

The existing first line remains intact. Follow-up lines use localized labels equivalent to:

```text
Invalid arguments: argument COMMAND: invalid choice: 'dashbaord' (...)
Supported commands: chart, dashboard, animate, dataset, text
Did you mean 'dashboard'?
```

The Chinese locale receives corresponding Chinese labels. Literal command names are not translated.

## Design

Top-level enrichment happens only after the existing parse has failed. Today an unknown leading positional such as `dashbaord` is rewritten by `_inject_default_command()` as an argument to the default `chart timeline` route, producing `unrecognized arguments` rather than an argparse subcommand `invalid choice`. The application will preserve that injection and parse flow exactly. If parsing raises the existing `UsageError`, a diagnostic-only classifier compares the untouched raw argv with that failure; only when the raw command-position token is unsupported and the same token appears in the parser's `unrecognized arguments` detail does it replace the error with top-level guidance. Uncertain cases retain the original error object.

Nested command failures are handled at the parser level. `LocalizedParser` will carry optional metadata describing the subcommand choices owned by that parser. Its `error()` override will identify argparse's invalid-subcommand failure, extract the rejected token, and attach structured values to a dedicated localized `UsageError`. This avoids adding guidance to every `error.arguments` failure and avoids reconstructing nested parser context later in `main()`.

The parser builder remains the source of truth for command ordering. Top-level failure enrichment and the `chart` and `dataset` parsers use the same declared command tuples rather than duplicating ad hoc lists. The rendered diagnostic is assembled through locale catalog entries so English and Chinese follow the existing error pipeline.

A spelling suggestion uses Python's standard-library close-match algorithm with a conservative cutoff and a single-result limit. A suggestion is emitted only when exactly one sufficiently close supported command is returned. The supported-command line is always emitted for a recognized invalid-subcommand failure, even when there is no suggestion.

The implementation must not parse arbitrary argparse prose for general errors. Matching is limited to argparse's known invalid-choice subcommand shape on parsers explicitly configured with subcommand metadata. Top-level handling starts from the structured original argument position and only confirms that the existing failure names that exact token as unrecognized; it never changes parsing or routing. If extraction or confirmation fails, behavior falls back to the unchanged generic `error.arguments` diagnostic.

## Testing

Parser-level tests will cover:

1. the screenshot case—a misspelled raw top-level command before default-route injection—including the full top-level list and `dashboard` suggestion;
2. top-level detection with a leading `--lang VALUE` pair;
3. a misspelled `chart` kind, including only chart kinds and the `timeline` suggestion;
4. an invalid `dataset` operation, including only Dataset operations;
5. a distant invalid command that lists choices without a suggestion;
6. Chinese localization of the follow-up labels;
7. an option-led default chart invocation and an ordinary invalid option/value, both retaining existing routing and generic errors without supported-command guidance.

A `main()`-level test will verify that the formatted diagnostic is written to stderr and exits with status 2. Existing help output, command ordering, default-command injection, and semantic validation remain unchanged.

## Scope

This change covers only registered argparse subcommand levels in the public CLI. It does not add fuzzy execution, automatic typo correction, command aliases, option-name suggestions, dashboard preset suggestions, or changes to help output.

This is a diagnostic-only change. Every argv sequence that currently parses successfully must produce the same namespace, launch configuration, route, side effects, and exit behavior after the change. Default-command injection and command execution are not modified. Preflight inspection may only intercept argv that already fails as an invalid subcommand; ambiguous cases must fall through to the existing parser and execution path.
