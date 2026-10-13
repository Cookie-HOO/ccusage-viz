# Custom Monitor Ranking Descriptions Design

## Goal

Extend the `ccuv.custom/v2` Custom Monitor observation contract so a Dataset can attach an optional localized description to each observation group. Preserve that description through the Custom Monitor model and render it only in the `ranking` presentation.

This brings Custom Monitor behavior in line with Custom historical Ranking while keeping Monitor `list`, `bars`, and timeline presentations unchanged.

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
  }
}
```

`description` uses the existing localized-text schema. Omission remains valid for backward compatibility. Empty localized text is normalized to absent. A present malformed value is a protocol/schema error and is not silently ignored.

## Data Flow

1. Parse the optional group description with the Monitor observation payload.
2. Retain it in the Custom Monitor series/group model and in its ranking projection entry.
3. Keep the description associated with its source row through sorting, filtering, and re-projection.
4. Pass it to the existing ranking-description presentation path when rendering Custom Monitor ranking.

Synthetic rows, including `Other`, have no description.

## Rendering

Descriptions render directly under their matching row in Custom Monitor `ranking`, using the same muted, width-bounded, localized ranking-description treatment used by Custom historical Ranking.

Whether a description is visible follows the existing ranking density rule: full and detailed densities show descriptions; minimal, compact, and normal densities hide them. No extra Monitor-specific visibility toggle or capability is added.

Descriptions must not render in Custom Monitor `list`, `bars`, or timeline views, even when source data contains descriptions.

## Compatibility and Boundaries

- Existing Datasets that omit descriptions retain identical behavior.
- The change is generic to ccusage-viz; Datasets own description content and localization.
- No built-in Monitor models or rendering behavior changes.
- Existing monitor aggregation, ordering, windowing, and request semantics remain unchanged.

## Verification

Add coverage for:

- valid localized Monitor group descriptions and omitted descriptions;
- malformed Monitor group descriptions being rejected by protocol parsing;
- description preservation through Custom Monitor ranking projection and sorting;
- descriptions rendering below their corresponding row in ranking when density permits;
- descriptions being hidden at compact/default ranking densities;
- descriptions never appearing in Custom Monitor list, bars, or timeline output;
- unchanged rendering for description-free Monitor responses.
