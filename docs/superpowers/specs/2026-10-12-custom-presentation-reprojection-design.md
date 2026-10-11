# Custom presentation reprojection bypass

**Date:** 2026-10-12  
**Status:** Approved design; awaiting specification review

## Goal

Make presentation-only changes to a Custom historical chart reuse its accepted projection instead of running `process_custom_historical()` over the complete accepted response. Theme, style, density, and other renderer-only changes must update in constant time before the existing visible-window render path.

## Profiling evidence

A `py-spy` recording of `ccuv-local dashboard recentrepo` while repeatedly changing theme, style, and density produced 92,172 samples. The dominant interactive path was:

```text
apply_custom_presentation
→ CustomHistoricalComponent.configure
→ CustomHistoricalComponent._reproject
→ process_custom_historical
→ CustomProjectedSeries.__post_init__
```

This path accounted for 18,065 samples (19.60%). `process_custom_historical()` accounted for 14,428 samples (15.65%), and `CustomProjectedSeries.__post_init__()` for 14,298 samples (15.51%). By comparison, Dashboard pane rendering accounted for 6.14%, `render_custom_ranking_viewport()` for 4.68%, and Ranking scalar line preparation for 3.85%.

The remaining latency is therefore primarily caused by reconstructing the full accepted projection before rendering, not by formatting the visible Ranking window.

## Scope

This change applies to `CustomHistoricalComponent` and all Custom historical chart kinds that use its accepted `CustomChartProjection`. It optimizes non-data-affecting configuration changes while preserving:

- query and provider lifecycle behavior;
- candidate versus accepted configuration semantics;
- local Top/Other projection behavior;
- Ranking comparison request and accepted-comparison behavior;
- render revision and Dashboard history behavior;
- the existing Dashboard Custom Ranking visible-window optimization.

Custom Monitor has its own component and is outside this change. Native charts, standalone query scheduling, persisted configuration, and input bindings are unchanged.

## Projection-impact boundary

Add one pure predicate that determines whether a compatible accepted Custom historical projection must be reconstructed from its accepted response.

A local projection rebuild is required when a changed field affects the output produced by `process_custom_historical()`. This includes at least:

- `top`, because it changes the selected series;
- `other`, because it changes whether discarded series are folded into Other;
- `ranking_comparison`, because it changes whether accepted prior-range facts participate;
- any future non-query field that changes projected days, series values/order, comparison facts, unit, or source-owned presentation metadata.

A local projection rebuild is not required when only renderer-owned configuration changes. This includes:

- `presentation.theme`;
- `presentation.style`;
- `presentation.density`;
- `presentation.legend`;
- renderer-only weekday/display options that do not change the period axis or projected values.

Query-identity changes remain governed by the existing `custom_replacement_required()` and `data_affecting=True` lifecycle. The new predicate does not replace or broaden query invalidation.

## Component behavior

In `CustomHistoricalComponent.configure(config, data_affecting=False)`:

1. Preserve the current early return when `config == candidate`.
2. Update `candidate` and increment `render_revision` as today.
3. If no accepted response/config exists, the component is pending, or the accepted configuration is query-incompatible with the new config, preserve existing behavior and do not replace accepted facts.
4. If the new compatible config requires local projection replacement:
   - update `accepted_config`;
   - call `_reproject()` exactly as today.
5. If the change is renderer-only:
   - update `accepted_config`;
   - replace only the immutable projection's `config` reference with the new accepted config;
   - preserve the identities and values of `model.days`, `model.series`, `model.unit`, `model.presentation`, comparison availability, and percentage capability;
   - do not invoke `process_custom_historical()`.

The fast path must remain safe when `model` is unexpectedly absent: accepted response/config state remains authoritative, and the implementation may conservatively call `_reproject()` rather than manufacturing an incomplete projection.

## Ranking comparison lifecycle

Density controls whether complete Ranking comparison content is requested and displayed, but it does not change primary projected series values. Crossing a density boundary must therefore not rebuild the primary projection.

Existing comparison lifecycle behavior remains authoritative:

- `comparison_request_config()` is evaluated from the current candidate/accepted configuration as it is today;
- changing to a density that requires complete comparison content may schedule the existing prior-range request;
- changing away from complete content may stop requiring that request without discarding accepted primary data;
- an already accepted matching comparison response remains reusable;
- when comparison data is newly accepted or comparison-affecting configuration changes, `_reproject()` may still rebuild the model to attach the comparison facts.

The optimization must not display stale comparison facts under a config for which `comparison_config != comparison_request_config()`.

## Correctness and performance requirements

- Theme, style, density, legend, and equivalent renderer-only changes make zero calls to `process_custom_historical()` when a compatible accepted model exists.
- These changes preserve `model.series` identity, allowing `RankingViewport` stable-data caches to remain warm.
- The model's `config` equals the accepted renderer configuration after the fast path.
- Top/Other and comparison-affecting changes still reconstruct the projection and produce the same result as the current implementation.
- Source/query-incompatible changes do not replace accepted facts through the fast path.
- Every accepted configuration change still increments `render_revision` exactly once through the current configure path.
- No new cache, worker, background task, dependency, or persistence field is introduced.

## Validation

Add deterministic component tests that monkeypatch the `process_custom_historical` symbol used by `custom_component.py`:

1. Parameterize theme, style, density, legend, and applicable renderer-only fields. After an accepted response, configure each change with `data_affecting=False`; assert zero processor calls, updated candidate/accepted/model config, unchanged series identity, and one render revision increment.
2. Parameterize `top`, `other`, and `ranking_comparison`; assert the processor is called and the resulting selected/Other/comparison facts remain correct.
3. Verify a source/query-incompatible config passed as non-data-affecting does not replace the accepted model or accepted config.
4. Verify renderer-only changes while pending or without a model retain existing accepted/candidate semantics.
5. Verify density transitions preserve comparison request behavior and never attach a mismatched comparison response.
6. Retain and run the Dashboard Custom Ranking `d/t/s` regression, including offset, scrollbar, hits, no query lifecycle work, and copy/link behavior.

Run focused component, Custom TUI, and Custom Ranking suites; run Ruff and whitespace checks; then run the full suite and compare failures with the established six-test baseline.
