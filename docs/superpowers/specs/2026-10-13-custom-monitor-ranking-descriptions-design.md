# Custom Monitor Ranking Descriptions and Displays Design

## Goal

Extend the `ccuv.custom/v2` Custom Monitor observation contract so a Dataset can attach optional localized `description` and `display` metadata to each observation group. Preserve both through the Custom Monitor model; render descriptions only in `ranking`, and use display text as the numeric value text in `ranking` and `list`.

This brings Custom Monitor group metadata in line with Custom historical Ranking while keeping Monitor `bars` and timeline presentations unchanged.

## Protocol

A Monitor observation group gains this optional field:

```json
{
  "id": "basic",
  "label": {"en": "basic", "zh-CN": "basic"},
  "value": "69.2",
  "description": {
    "en": "openrouter-1, openrouter-1o",
    "zh-CN": "openrouter-1, openrouter-1o"
  },
  "display": {
    "en": "69.2%",
    "zh-CN": "69.2%"
  }
}
```

`description` and `display` use the existing localized-text schema and mirror the corresponding Custom historical Ranking series fields. Omission remains valid for backward compatibility. Empty localized text is normalized to absent. A present malformed value is a protocol/schema error and is not silently ignored.

## Data Flow

1. Parse the optional group description and display text with the Monitor observation payload.
2. Retain both in the Custom Monitor group model and ranking projection entry.
3. Keep both fields associated with their source row through sorting, filtering, and re-projection.
4. Pass localized display text to observed ranking/list value rendering and descriptions to the ranking-description presentation path.

Synthetic rows, including `Other`, have neither field.

## Rendering

Descriptions render directly under their matching row in Custom Monitor `ranking`, using the same muted, width-bounded, localized ranking-description treatment used by Custom historical Ranking.

Whether a description is visible follows the existing ranking density rule: full and detailed densities show descriptions; minimal, compact, and normal densities hide them. No extra Monitor-specific visibility toggle or capability is added.

When present, `display` replaces the right-side numeric text for its corresponding row in Custom Monitor `ranking` and `list`, regardless of density. The numeric `value` remains authoritative for source-owned ranking order, bar lengths, Top/Other projection, and every time-based chart. `display` does not affect these calculations and never appears in bars or timeline views. When omitted, the row retains its existing numeric fallback formatting.

Descriptions must not render in Custom Monitor `list`, `bars`, or timeline views, even when source data contains descriptions.

## Compatibility and Boundaries

- Existing Datasets that omit descriptions and displays retain identical behavior.
- The change is generic to ccusage-viz; Datasets own description content and localization.
- No built-in Monitor models or rendering behavior changes.
- Existing monitor aggregation, ordering, windowing, and request semantics remain unchanged.

## Verification

Add coverage for:

- valid localized Monitor group descriptions/displays and omitted fields;
- malformed Monitor group descriptions or displays being rejected by protocol parsing;
- description/display preservation through Custom Monitor ranking projection and sorting;
- ranking rendering the description beneath the corresponding row and display as its value text;
- descriptions being hidden at compact/default ranking densities;
- list rendering display as its value text but never rendering descriptions;
- bars and timeline rendering neither field;
- unchanged rendering for description/display-free Monitor responses.
