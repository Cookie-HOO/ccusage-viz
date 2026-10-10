# Model Source Prefix Normalization

## Goal

Native ccusage model views must aggregate the same model across source-prefixed
and unprefixed names. For example, `[pi] gpt-5.6-terra` and
`gpt-5.6-terra` represent one model and must appear as one row with one summed
value or TPM rate.

## Scope

Update the native model identity function used by historical processing,
Monitor processing, selector resolution, filter discovery, data-table export,
and JSON export. Custom Dataset dimensions are source-owned and stay unchanged.

## Identity Rule

Model identity will first remove one leading bracketed source prefix only when
it has the form `[source]` followed by one or more whitespace characters. The
remaining model name is then case-folded, as it is today.

Examples:

- `[pi] gpt-5.6-terra` becomes `gpt-5.6-terra`.
- `[PI] GPT-5.6-TERRA` becomes `gpt-5.6-terra`.
- `gpt-5.6 [pi]` is unchanged except for case-folding.
- `[pi]gpt-5.6-terra` is unchanged except for case-folding because no
  whitespace separates the prefix from the model name.

## Behavior

The shared identity ensures that native historical chart series, rankings,
Monitor counters and TPM projections aggregate values under the normalized
name. A model selector written with either the prefixed or unprefixed spelling
selects the same normalized model. Filter choices and exports expose the
normalized display name rather than the source prefix.

## Validation

Tests will cover identity edge cases, historical filtering and aggregation, and
Monitor rates built from snapshots whose model key changes between prefixed and
unprefixed forms. Existing case-variant behavior remains covered and must
continue to pass.
