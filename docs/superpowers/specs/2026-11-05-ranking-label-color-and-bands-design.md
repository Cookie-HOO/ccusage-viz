# Ranking label coloring and semantic bands

## Status and scope

Design completed and independently reviewed; final design approval precedes implementation planning. User-confirmed intent: Dataset protocols describe data semantics only; ccuv owns rendering. Rank-change and value-change arrows remain ccuv-controlled. The six independent label modes (`change`, `increase`, `decrease`, `direction`, `band`, `none`) are ccuv presentation options. A Ranking may declare one set of semantic bands, with optional names. Named bands get a legend in the group heading area, or below the main title for an ungrouped Ranking. Unnamed bands have no legend entry. Providing classification facts does not automatically select band coloring; the default remains `change`.

The details explicitly labeled “design choice” below are recommendations by the designer, not additional user requirements.

## Goals

- Support label modes: any numeric change (default), increase only, decrease only, direction-specific colors, semantic band colors, and no semantic coloring.
- Preserve arrow generation, geometry, alignment, sorting, group totals, and group-local rank numbering.
- Keep business classification independent of rendering and numeric sorting. Football qualification bands, for example, are facts determined by the Dataset, not ccuv thresholds.
- Preserve existing Dataset behavior when optional fields are absent.

Non-goals: arbitrary RGB from Datasets, executable predicates, user-authored numeric thresholds, multiple classification dimensions, band headings inserted among entries, group-heading coloring by bands, Monitor bands, and V1 band extensions.

## Protocol extension (V2 Ranking only)

Add optional `data.bands`, an ordered list of objects with required stable `id` and optional localized `label`. Add optional `band_id` on each Ranking series entry. Flat and grouped responses share the same response-level definitions; grouped entries reference them identically.

```json
{
  "data": {
    "bands": [
      {"id": "direct", "label": {"en": "Direct qualification", "zh-CN": "直接晋级"}},
      {"id": "playoff", "label": {"en": "Playoff", "zh-CN": "附加赛"}},
      {"id": "eliminated"}
    ],
    "series": [
      {"id": "team-a", "label": {"en": "Team A", "zh-CN": "球队 A"}, "value": "18", "band_id": "direct"}
    ]
  }
}
```

Validation:

- Missing `bands` equals an empty set. Missing `band_id` means unclassified, not last band.
- IDs follow existing protocol identifier validation; duplicate band IDs and unknown references reject the response.
- Design choice: optional fields may be omitted or null; `bands: null` is equivalent to absence. A present label must satisfy existing bilingual LocalizedText validation.
- Array order is the Dataset's band order, not a sorting instruction for entries. IDs, not labels, identify bands.
- No colors, styles, severity, thresholds, rank intervals, or glyph instructions are sent.
- Bands belong to the current response snapshot. Comparison responses may have different bands; current response membership is authoritative for current label rendering.
- Synthetic Other entries are unclassified; ccuv must not infer a band from their constituents.
- This is an additive extension to `ccuv.custom/v2`, with no extra request and no rendering configuration in requests. Document limitations of older readers; do not assume they display bands.

## ccuv presentation configuration

Add `label_color_mode` to Ranking presentation/preset state:

| Value | Behavior |
| --- | --- |
| `change` | Highlight when the current numeric change is nonzero; default |
| `increase` | Use theme trend-increase color only when numeric change is positive |
| `decrease` | Use theme trend-decrease color only when numeric change is negative |
| `direction` | Positive/negative changes use theme trend-increase/trend-decrease colors |
| `band` | Current membership maps to theme categorical colors |
| `none` | Ordinary label style, no semantic color or bold emphasis |

Defaulting and controls:

- Missing preset field resolves to `change`; invalid explicit values are rejected. Dataset band definitions never automatically switch the selected label mode.
- Design choice: expose a named Ranking advanced adjustment control, not raw color editing. Choose an unused binding during implementation after inspecting current bindings; show active mode in help. CLI/pane grammar uses `label-color`; persisted field uses `label_color_mode`.
- All modes except `band` work for native, V1, and V2 Rankings. Only V2 Rankings with nonempty accepted band definitions offer `band` in the interactive cycle.
- Design choice: preserve an explicitly configured `band` mode if facts temporarily have no bands; render ordinary labels and no legend, rather than secretly changing the stored preference. It remains possible to select another mode. Preset loading need not query the Dataset to validate presentation state.
- Style/theme/density/mode/legend changes are presentation-only: no provider requests, no refresh-baseline advancement; undo/redo and preset persistence apply.

Numeric direction semantics:

- Increase/decrease refers to raw numeric value, never rank, formatted display, metric desirability, or position after sorting.
- Design choice: use a single label-change resolver across styles. Prefer the per-entry accepted primary-refresh delta when present, including zero. If absent, use an available, comparison-ready period difference. This avoids today's list-only fallback discrepancy. Missing comparison/baseline means unknown, not zero; new entries have no artificial direction.
- `change` retains the theme highlight color with existing label emphasis. `increase` uses theme trend-increase for positive changes only; `decrease` uses theme trend-decrease for negative changes only. `direction` uses both trend colors. Directional label styling matches the numeric value-change arrows, with the same existing bold emphasis; zero/unknown and the nonmatching sign retain ordinary styling.
- Rank/value arrows retain their existing computation and color rules. No Dataset customization or new arrows are introduced.
- Pending rows suppress change-based label emphasis as today. Design choice: accepted band membership may remain colored while retained facts are pending, because membership is a property of that snapshot rather than a new change assertion.

## Band coloring and legends

- Map the full declared band order to theme categorical colors, before Top, search, or viewport filtering. Reuse the same mapping for all groups. Never assign colors from visible rows or localized names.
- Design choice: colors repeat when bands exceed the theme palette; names remain distinct in the legend. No guarantee that categorical colors encode good/bad or ordinal severity.
- `band` supersedes change-based label coloring. Arrows still communicate changes. Unclassified and Other rows retain ordinary styling.
- Only label text receives semantic coloring; copy/link decorations, rank, value, track, and group heading value keep their current independent styles. Search matching must remain recognizable and must not be erased by outer semantic styling.
- Legends appear only in `band` mode and only for definitions with a label. Do not fall back to displaying an unnamed band's ID.
- Design choice: each group shows named bands represented in its accepted projected entries, in declaration order, before local search/window filtering. Ungrouped Ranking uses the same rule over its entries. This prevents scrolling/search from changing the color key. If all represented bands are unnamed, emit no legend row.
- Group legend is an auxiliary row immediately below the existing group heading and before its description/entries, not a new subgroup. Keep group values and copy/link targets on the existing heading row. Ungrouped legend goes below the main title.
- Respect the existing legend setting: hidden omits legends; existing non-hidden settings render in the heading area (Ranking does not gain an inside-the-track legend).
- Use a colored swatch plus localized label (`●` or ASCII equivalent). In no-color mode names remain visible and no ANSI coloring is emitted; unnamed classification has no visible fallback in this first version.
- Use the bounded, terminal-cell-aware legend packing convention in `render/legend.py`, at most two rows when height permits. Oversized names/omitted entries may be shortened or counted. Never append legends to the numeric right column. Legend rows consume vertical capacity explicitly, without changing horizontal entry-column budgets.

## Projection, geometry and lifecycle

Carry immutable band definitions and entry membership through protocol parsing, scalar projection, presentation preparation, and both direct and viewport renderers. Do not infer membership from rank/Decimal/display.

- Accepted response replaces definitions/membership atomically. Stable entry/group identities and existing refresh baselines remain unchanged.
- Grouped and flat paths must share color mapping, direction resolution, and legend construction helpers.
- No new padding, icon slot, or label-width budget is introduced by label coloring.
- Viewport geometry includes mode/legend visibility and all facts that affect legend row count. Data replacement invalidates old preparation/geometry through existing identity-based mechanisms. Theme-only color changes must not retain cached styled text; geometry caches hold scalar facts only.
- Include legend row kinds and source-line offsets explicitly in grouped geometry. Scrolling, row counts, scrollbar ranges, copy targets, and cached resize restoration must include those rows. A legend row has no group or entry copy hit and cannot steal the heading hit.
- Design choice: existing clipboard/data exports retain their formats for this first version; no legend rows are copied and no implicit band-name insertion into entry text. Raw protocol JSON still exposes classification facts.
- Preserve current numeric column and arrow-slot layout. The separately identified grouped compact numeric truncation issue is not fixed as part of this work.

## Verification requirements

1. Protocol: flat/grouped parsing, omitted/null fields, bilingual labels, duplicate IDs, dangling membership, all unnamed, mixed named/unnamed, empty band definitions; backward-compatible old payloads.
2. Projection: current-response membership, prior-response differences, stable repeated entry IDs across groups, Top/search filtering and unclassified Other.
3. All modes: increase/decrease/zero/unknown, identical display but different Decimal, refresh zero overriding comparison change, first baseline, pending rows, native/V1/V2, list and non-list styles. Arrows remain unchanged.
4. Label-only application, search emphasis, theme switching, no-color and ASCII; deterministic mapping independent of scroll/search/Top; palette overflow.
5. Real Dashboard TuiCustomPane completion -> preparation -> grouped viewport with compact/dot/all/scrollbar. Assert group legends follow headings, values/arrow positions are unchanged by mode, true scrollbar range, heading copy hits and warm/resize cache parity.
6. Ungrouped title legend, no-label/no-legend, mixed labels, hidden legend, CJK names, narrow/short terminal, descriptions and multi-line legend clipping.
7. CLI, advanced controls, no-query presentation changes, undo/redo, old/new presets and saved band preference with absent runtime bands.
8. Update English/Chinese protocol and user/developer documentation with semantic-versus-rendering ownership and a qualification-table example.

## Files expected to participate

Protocol models/parsing/Ranking validation; scalar projection; Ranking entry preparation; palette/legend helpers; historical/grouped direct and viewport renderers; ChartPresentation, pane grammar, CLI, preset values/materialization; TUI adjustments/history/help; protocol/render/viewport/interaction tests and bilingual documentation. Exact file boundaries are left to the implementation plan.
