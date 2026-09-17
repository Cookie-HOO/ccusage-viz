# Plugin System Exploration

**Status:** exploratory design notes; not approved for implementation  
**Date:** 2026-09-15

## Context

A plugin is the installable and manageable unit. A source is one capability; a plugin may also provide a chart, theme, or animation. The approved source protocol remains in `2026-09-14-external-sources-design.md`; this document does not supersede it.

## Runtime principles

- Do not dynamically import third-party Python into the ccuv process.
- A plugin is a declarative manifest plus executable, script, or data assets.
- ccuv validates a manifest, resolves an explicitly selected capability, and invokes a controlled, versioned protocol.
- ccuv retains query planning, scheduling, normalized records, filters, timezone handling, provenance, aggregation, terminal rendering, and the main TUI lifecycle.
- Normal commands never implicitly search, install, update, or run plugins.

This avoids coupling plugins to private Python APIs while preserving host stability, terminal fallbacks, privacy behavior, and diagnostics.

## Candidate capabilities

### Source

A source owns external storage, filtering, and aggregation and emits external-source NDJSON v1. Installation must not silently enable it; selection is explicit:

```bash
ccuv timeline --source dsh
ccuv data --source dsh --no-ccusage
```

The DSH direction was a standalone `dsh-ccuv-bridge`; `dsh-usage-stats` and `dsh-all-usage` should not become ccuv runtime dependencies.

### Chart

A chart consumes ccuv-selected, normalized, filtered, provenance-aware data. It must not reread DSH, router, or log files or perform duplicate accounting. Built-ins remain top-level. Proposed commands:

```bash
ccuv chart list
ccuv chart info NAME
ccuv chart NAME --source dsh
ccuv chart PUBLISHER/NAME
```

The proposed output boundary is a validated structured terminal render tree, not unrestricted ANSI. This lets the host retain non-TTY fallback, color policy, copy/export, accessibility, snapshots, and future TUI compatibility.

### Theme and animation

Themes are proposed as data-only assets: no code execution, usage-data access, or TUI lifecycle control. Animation may use constrained title or status frames for Watch, Monitor, and TUI, and possibly a standalone `ccuv animate NAME` command. Animation should receive only aggregate or anonymized usage and be bounded by dimensions, frame rate, output size, and resource limits.

## Proposed management CLI

```bash
ccuv plugin browse
ccuv plugin search QUERY [--community]
ccuv plugin info ID
ccuv plugin install ID
ccuv plugin install github:OWNER/REPO[@VERSION]
ccuv plugin list
ccuv plugin doctor ID
ccuv plugin update ID
ccuv plugin disable ID
ccuv plugin enable ID
ccuv plugin remove ID
```

`browse` may show installed plugins, official candidates, and local cache. `search --community` is an explicit GitHub-topic search with clear `Official` versus `Community / Unverified` labels. Ordinary commands do not rebuild indexes or contact GitHub. Management terminology is `plugin`; runtime source selection remains `--source ID`.

Installation should read and validate the manifest and compatibility declaration, show publisher, capabilities, privacy/data access, network needs, and local-code execution risk, then require confirmation (with `--yes` for automation). It may download a release artifact or invoke a declared integration installer, run doctor/protocol checks, and atomically add the usable registry entry only after success. Installation must never silently enable a plugin. `disable` preserves installation but blocks ordinary runtime resolution; `remove` deletes only ccuv-managed plugin-owned files, never source history, user files, or host-tool data.

## Proposed manifest and distribution shape

The candidate root file is `ccuv-plugin.toml`. It is declarative and should describe plugin ID, name, version, description, repository, maintainer, compatible ccuv versions, distribution artifacts by platform and architecture, and repeatable capabilities containing kind, capability ID, executable argv, and protocol/version. It should also declare privacy properties and whether network access is required. Prefer argv arrays over arbitrary shell strings. The manifest is authoritative; GitHub topics are discovery markers only. Suggested topics include `ccuv-plugin`, `ccuv-source`, `ccuv-chart`, `ccuv-theme`, and `ccuv-animation`.

Discovery layers are local installed plugins, official-organization candidates, and explicit community topic search. “Official” should mean repository ownership by the official GitHub organization, not a personal account. Candidate official repositories discussed were `ccusage-viz/ccusage-viz`, `ccuv-plugin-dsh`, `ccuv-plugin-router`, and `ccuv-plugin-template`.

## Trust and safety direction

Checksums or signatures, publisher verification, sandboxing, formal permissions, package/install adapters, and whether installation is fully ccuv-owned remain unresolved. The system should make executable code and network access visible before confirmation rather than imply that a manifest makes code safe.

## Open decisions

These notes are not approval:

1. Start charts as independent `ccuv chart NAME` commands, or allow plugin tabs/panes in `ccuv tui`. The session recommendation was independent commands first; a future `tui-pane` capability would need explicit lifecycle, dimensions, keyboard routing, frame-rate, crash isolation, and permission contracts.
2. Full manifest schema, compatibility policy, and capability-specific protocol versions.
3. GitHub Releases versus package managers and other installation adapters.
4. Checksums/signatures, publisher verification, sandboxing, and formal permissions.
5. Chart input envelope, render-tree nodes, and error schema.
6. Theme schema and validation.
7. Animation protocol, isolation, budgets, and exact CLI.
8. Source-overlap warning/confirmation UX. Provenance must be retained; automatic de-duplication must not be guessed.
9. Download/install metrics and privacy-preserving adoption telemetry; GitHub release-download counts were discussed only as an imperfect proxy.
10. Whether installation uses a ccuv-owned artifact directory, delegated host-tool installation, or capability-specific adapters.
