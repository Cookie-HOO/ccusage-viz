# Ranking label coloring and bands implementation plan

Approved design: ../specs/2026-11-05-ranking-label-color-and-bands-design.md

Preserve all existing dirty worktree changes. No commits requested.

1. Protocol/projection: additive immutable V2 response bands (stable ID, optional LocalizedText), optional entry band_id; validate duplicate/dangling IDs, null/omitted fields, flat/grouped parity; carry current snapshot membership through projection and preparation; Other unclassified. Tests: custom_protocol and scalar projection.
2. Configuration: six-mode ChartPresentation.label_color_mode default change; native/custom Ranking CLI and pane --label-color; Ranking legend hidden/below-title; presets roundtrip; command reproduction; advanced C cycling and l legend; no query on presentation edits; undo/redo. Test CLI/presets/TUI.
3. Rendering: shared numeric direction resolver (refresh zero authoritative, comparison fallback only when absent); label-only semantic style preserving search; full band-order theme mapping; named represented-band legends below group heading / main title. Carry mode through contexts. Explicit legend rows/hit exclusion/scrollbar accounting; geometry and preparation invalidation including mode, legend, height and classification snapshot. Preserve existing arrows and horizontal geometry.
4. Integration: real TuiCustomPane completion and viewport tests, compact dot all scrollbar, repeated group-local IDs, legend placement and clipping, theme/resize/cache parity; bilingual docs.
5. ByteAI follow-up: inspect source-native model_load scales before selecting semantic bands; choose domain-grounded bands, not compressed sort values. queued_count ccuv mode increase. Adapter emits bands only for Ranking; rebuild registered binary after Go tests. Update only the two byteai preset panes atomically with backup; preserve all other user preferences. Sync custom tool manifest only if tool configuration/dependencies change, not ordinary source implementation.
6. Validation: focused tests per worker, broad Python regression, Go tests, live registered adapter -> ccuv current package, review deltas for unintended changes.

Parallel ownership:
A models/protocol/projection plus RankingPresentationEntry.band_id and preparation propagation.
B options/CLI/preset/command copy/TUI controls/locales.
C render helpers/renderers/contexts/viewport and render tests, coordinate model/context interfaces with A/B.
D separate byteai Go repository source/testing/docs.
Parent integration/bilingual docs/live preset update and final verification.

Design choice for ByteAI: model_load bands must use actual reported load; known percentage scales can use below-full/full categories consistent with existing full-load aggregate, score-scale sources require their own existing full-load rule or stay unclassified. No invented warning threshold. Queue increase-only is presentation policy, not protocol metadata.
