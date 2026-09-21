# Versioning

`ccusage-viz` uses semantic versioning while it remains pre-1.0:

- **Patch (`0.1.x`)**: bug fixes, verified rendering/query improvements, documentation, and other changes that preserve the current public workflow.
- **Minor (`0.x.0`)**: new user-facing capabilities, source integrations, or public-contract changes that may require migration before 1.0.
- Before `1.0`, public interfaces may still change between minor releases.

## 0.1.1

`0.1.1` builds on `0.1.0` with:

- safer Codex project attribution and clearer incomplete-attribution notices;
- improved query, refresh, and partial-result states in interactive views;
- more robust Monitor cumulative-token/TPM state handling;
- visible, width-aware active filter summaries in historical views, Monitor, and TUI;
- stable merge-group fields in project-oriented data output;
- updated English and Chinese usage documentation.

## Deferred collector integration

DSH-specific provider and contract experiments are intentionally not part of `0.1.1`.

The next patch release ships the completed current work. A subsequent minor release may integrate the npm-packaged `ccuv-collector` once its package and JSON protocol are stable. That integration will use a collector-owned, opaque agent identity and provenance contract rather than a DSH-specific ccuv provider.
