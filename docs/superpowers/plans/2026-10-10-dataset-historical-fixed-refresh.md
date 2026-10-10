# Dataset Historical Fixed Refresh Implementation Plan

**Goal:** Allow Dataset historical chart capabilities to own a fixed refresh interval.

**Spec:** `docs/superpowers/specs/2026-10-10-dataset-historical-fixed-refresh-design.md`

1. Extend V1/V2 historical capability models and protocol parser/serializer with optional positive `refresh_interval_seconds`; reject it for non-historical/non-Ranking capability positions as required by protocol.
2. Propagate the capability through V2-to-V1 adaptation and `CustomHistoricalComponent` runtime capability state.
3. Add one effective-interval helper used by standalone custom and Dashboard custom historical scheduler construction/rebuild. Fixed capability interval wins over host interval.
4. After custom historical probe, reject standalone explicit `--interval` when a fixed interval is declared; Dashboard global interval remains valid.
5. Add parser, conversion, scheduler, and override tests.
