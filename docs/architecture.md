# How ccuv Works

This document describes the approved target architecture of `ccusage-viz`. The migration is in progress, so current modules do not yet match every boundary below. It is intended for maintainers and contributors; ordinary usage belongs in the README and user guides.

> **Status:** Target architecture under implementation. See the [runtime architecture design](superpowers/specs/2026-09-18-runtime-architecture-design.md) for migration phases.

[简体中文](architecture.zh-CN.md)

## Core concepts

`ccuv` distinguishes a chart type, a running chart instance, and the product shell that hosts it.

| Term | Meaning |
| --- | --- |
| **Chart Definition** | Stateless catalog entry for one chart type. It gives bootstrap a stable ID and references to separate configuration, data-requirement, processing, rendering, runtime-setting, and inspection collaborators. |
| **Chart Component** | One running chart instance. It owns its reusable chart payload and lifecycle state—generation, Coverage, accepted data, pending/running/error state, processed model, and rendered content—and receives resolved Host context without taking ownership of Host settings. |
| **Host** | Product shell that runs and presents Components. Standalone hosts one Component; Dashboard hosts ordered Components in Panes. |
| **Pane** | Dashboard placement and composition context for one Component. It adds geometry, focus, order, and Dashboard-owned cadence; it does not redefine chart semantics. |
| **Provider** | Data capability that compiles logical requests, executes physical queries, and returns normalized usage data with provenance, resolution, and Coverage. `ccusage` and Demo are built-in Providers. |

A Chart Component is the smallest product-level runtime unit shared by Standalone and Dashboard. Smaller functions and services remain reusable below it, but Hosts never reimplement a chart.

A Definition is to a Component what a blueprint is to an instance:

```text
Timeline Definition
├── create(config A) → Timeline Component A → Standalone Host
├── create(config B) → Timeline Component B → Dashboard Pane 1
└── create(config C) → Timeline Component C → Dashboard Pane 3
```

Each Component has independent state even when several Components share one Definition or one physical Provider query.

## Routing and hosts

Routing identifies the requested product operation before initializing chart runtime services:

```text
argv
  → Route
    ├── Help / Version       → short circuit
    ├── Standalone Chart     → one Chart Component + Standalone Host
    └── Dashboard            → many Chart Components + Dashboard Host
```

Help and Version do not initialize Providers, inspect chart TTY requirements, enter terminal input mode, or create the execution coordinator.

Standalone and Dashboard use the same Chart Definitions and Components. Their difference is only the Host:

- **Standalone Host:** one Component, one full-screen composition, Standalone Controls, lifecycle, inspection, and command copy.
- **Dashboard Host:** multiple Components, Header and Summary, Layout and Weights, focus and Pane lifecycle, global Controls, and Dashboard-owned Refresh and Sampling schedulers.

A Dashboard Route does not call the Standalone Route. Both construct Components from the same Definitions and pass them to different Hosts.

## Main chart pipeline

Chart products use four conceptual layers:

```text
1. Route
2. Query / Data Acquisition
3. Result Processing
4. Rendering
```

### 1. Route

The Route chooses a product operation and constructs a launch request. It does not perform queries or render charts.

### 2. Query and data acquisition

This layer has three stages.

#### Configuration preparation

```text
Parse → Compose defaults and Presets → Validate → Resolve startup values → Effective configuration
```

It owns syntax, option conflicts, Preset composition, appended Panes, Pane ownership rules, fixed-date resolution, and startup diagnostics. Validation completes before dependency checks, queries, alternate-screen entry, or terminal input changes.

#### Logical query planning

A shared logical planner produces an independent request for every data consumer—Standalone Component, Dashboard Summary, or Pane Component. It combines the owner's resolved Host context, reusable chart payload, Chart Definition data requirements, generation, trigger, and current Coverage into Provider-neutral scope, missing intervals, required resolution and dimensions, Provider selection, and execution options. The same planner is used in both product forms, so missing-Coverage planning does not diverge between Standalone and Dashboard.

A Chart Definition declares what data it needs. It never constructs a `ccusage` command or invokes a Provider itself.

#### Coordination and physical execution

The execution coordinator asks Providers to compile logical requests into physical queries, applies bounded concurrency, and delivers immutable results independently to each owner.

The initial optimization boundary is deliberately narrow:

- deduplicate strictly identical in-flight physical queries;
- share a Monitor raw cumulative snapshot only where the product has explicitly proven that sharing safe.

Across independent owners, the coordinator does not union date ranges, merge different Filters, construct field supersets, delay ticks to gather batches, reuse completed stale results, reconcile overlapping Sources, or own Interval semantics. This does not prohibit one owner's logical planner from combining adjacent missing Coverage intervals as defined by the product contract.

### 3. Result processing

Providers return facts in a common envelope:

```text
Normalized Result
├── records
├── provenance
├── resolution
├── Coverage
├── notices
└── provider metadata
```

Result processing converts those facts into chart semantics. Depending on the Chart Definition, it performs filtering, historical aggregation, Monitor cumulative-counter differences and reset handling, observation-window rollups, By, Top, Other, and Summary comparisons.

Query and result processing remain separate because one physical result can feed several Components with different configurations. Monitor Components may share a raw snapshot while retaining independent previous snapshots, gaps, windows, generations, and errors.

### 4. Rendering

```text
Semantic Chart Model
  → built-in chart renderer
  + declarative Theme / Style
  → Chart Render
  → Standalone or Dashboard composition
  → complete Frame
  → Terminal Painter
```

Renderers never query data or write directly to stdout. Status, Controls, Notices, settings, inspection content, and chart bodies are composed into a complete logical Frame. The Painter compares complete Frames and writes only changed terminal rows; a complete logical repaint does not imply an unconditional terminal clear.

Plotext rendering remains behind a serialized adapter because Plotext uses process-global state. Rendering work runs outside the reducer and terminal input loop; generation-tagged completion returns a `ChartRender` for acceptance before Frame composition.

## Runtime state

Hosts and Components communicate through actions and effects:

```text
Action → reduce(state, action) → new state + effects
```

Actions include ticks, manual refresh, pause/resume, resize, input, settings changes, query completion, query failure, and debounce expiry. Effects include query submission, bounded generation-tagged result processing, debounce scheduling, scheduler rebuilding, copy, repaint, and exit. Processing and serialized Plotext work run outside the reducer and terminal input loop.

Each data-owning Component keeps an independent lifecycle envelope:

```text
Component State
├── candidate chart payload + resolved Host context
├── accepted data
├── data generation + render revision
├── Coverage
├── query / processing / rendering activity
├── debounce handle
├── pending triggers by kind
├── observer
├── accepted success time
└── last error
```

A data-affecting adjustment increments the generation immediately and detaches obsolete effects. Data and its Coverage are accepted atomically only for the current generation; stale delivery updates neither. Theme/Style, viewport, and transient-only changes advance a separate render revision. The redesign introduces no completed-result cache.

Refresh, Sampling, debounce, manual refresh, resume, and committed configuration work remain distinguishable trigger sources. Fixed scheduler baselines do not move because of query duration, success, failure, manual refresh, pause, or resume. A slow Component never overlaps one pipeline stage for the same generation, and equivalent pending opportunities coalesce within their own trigger kind.

Workers return immutable completion actions through one serialized runtime queue. Only the runtime owner mutates state, composes Frames, and paints. Plotext serialization keeps only the latest queued render revision per Component. Shutdown stops admission, detaches/cancels work, suppresses late completions, stops painting, and restores terminal state last.

Historical no-Watch uses the same startup, query, acceptance, processing, Frame, and Painter path as Historical Watch, then exits after the first accepted Frame.

## Built-in capability registries

The implementation uses private, static registries for built-in capabilities:

- Provider Registry
- Chart Registry
- Theme Registry
- Style Registry

Registries use explicit registration, reject duplicate IDs, preserve deterministic order, and freeze before parsing or runtime begins. Only the application bootstrap composes production registries.

These registries are internal dependency-inversion seams, not a supported third-party Python API. The current architecture does not implement plugin discovery, manifests, installation, package scanning, dynamic Python imports, sandboxing, or public capability protocols.

### Providers

Built-in Providers are initially:

- `ccusage`: wraps query planning, safe subprocess execution, schema validation, and normalization;
- Demo: deterministic in-process records with no external dependency check.

Provider code does not import charts or presentation code. Chart code does not invoke Providers or read external storage.

### Charts

Each built-in chart has one Definition and can create any number of Components. Bootstrap assembles a Definition from narrow per-layer collaborators: configuration descriptor, data-requirements descriptor, processor/projector, renderer, runtime-settings descriptor, and inspection descriptor. Query, processing, and presentation import only the collaborator contract they consume, not the complete Definition. This catalog entry is not a public plugin wire contract.

### Theme and Style

Theme and Style are declarative presentation capabilities. Theme provides semantic color roles and palettes. Style describes compatible visual grammar. Neither reads Provider data, changes Data Scope, starts queries, controls the TUI lifecycle, or writes to the terminal.

## Future animation capability

Animation is a separate resource kind, not a Chart variant and not an implicit post-processing step for every chart.

A future Animation resource may:

- run through the Standalone Host;
- occupy a Dashboard Pane;
- update frames without querying usage data.

Chart Components require Query and Result Processing; Animation Components do not. Both may eventually share Host, viewport, Frame, input, and Painter infrastructure, but no common hosted-component protocol is frozen until both real implementations exist.

The current architecture keeps Route dispatch and Host/content composition extensible, but adds no unused Animation route case or resource discriminator yet. It does not define an Animation schema, plugin protocol, resource budget, frame cadence, or Dashboard Header integration. Header branding, static logos, and animation remain separate future design questions.

## Dependency direction

```text
CLI / TUI Driver
       ↓
Bootstrap and use cases
       ↓
Runtime engine
   ↙    ↓     ↘
Config Query Presentation
   ↘    ↓     ↙
       Core
       ↑
Capability contracts
       ↑
Built-in implementations
```

Rules:

- Core imports only the standard library.
- Configuration depends on Core values and capability identifiers, never TUI or Provider adapters.
- Query depends on Core and Provider contracts, never CLI, TUI, or rendering.
- Presentation depends on Core and chart/theme/style contracts, never Provider adapters.
- Built-ins implement capability contracts.
- Bootstrap is the only production composition root allowed to import all built-ins.
- No library module imports CLI parsing.
- Dashboard does not import private Standalone functions.
- Providers do not import charts; charts do not import Providers.

Import-boundary tests enforce these rules.
