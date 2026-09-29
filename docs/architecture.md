# How ccuv Works

This document describes the implemented architecture of `ccusage-viz`. It is intended for maintainers and contributors; ordinary usage belongs in the README and user guides.

> **Status:** Current architecture. The [runtime architecture design](superpowers/specs/2026-09-18-runtime-architecture-design.md) records the design decisions and completed migration phases.

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

| Layer | Concepts | Example |
| --- | --- | --- |
| **1. Route** | Route, launch request | `ccuv monitor` selects the Standalone Monitor operation. `ccuv dashboard` selects Dashboard and describes its Panes. Routing does not own runtime cadence or Component state. |
| **2. Query / Data Acquisition** | Config data scope, Query Intent, Provider, Provider Result | A Monitor Config specifies `by=model` and Filters. The logical planner combines them with Host context to produce a Query Intent. The `ccusage` Provider runs the query and returns normalized cumulative records. |
| **3. Result Processing** | Processor/projector, semantic Chart Model | Monitor processing uses the Component's previous snapshot and Observer to derive increments, TPM, and time buckets, then projects those semantics to a Timeline or Ranking Model. Historical processing aggregates daily records independently. |
| **4. Rendering** | Chart renderer, Chart Model, Theme, Style, Chart Render, Host composition, Painter | The selected Timeline or Ranking renderer consumes the projected Model. The Host adds Controls, Header, borders, and other product content to create a complete Frame; the Painter only diffs Frames and writes changed rows. |

Several concepts are orthogonal to the four stages:

| Concept | Boundary |
| --- | --- |
| **Chart Definition** | Stateless catalog metadata that identifies a presentation Chart and references its layered collaborators. It contains no concrete session configuration or runtime state. |
| **Chart Component** | A running instance with independent accepted/candidate configuration, facts, semantic result, generation, and errors across Query, Processing, and Rendering. |
| **Host** | Owns cadence, input, cancellation orchestration, geometry, complete-Frame composition, and terminal lifecycle. |
| **Pane** | Dashboard placement and runtime context for one Component: identity, geometry, order, focus, and Dashboard-owned cadence context. It does not duplicate Component business state. |

Definition and Component are therefore closer to blueprint and running instance than to a Python class and object relationship. Monitor is a special realtime runtime/data mode, not another Chart Definition: its timeline forms use the registered Timeline Chart and its ranking form uses the registered Ranking Chart.

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

Plotext rendering remains behind a serialized adapter because Plotext uses process-global state. Query is the only pipeline stage required to run asynchronously: Provider work commonly takes seconds, while current processing and rendering are millisecond-scale operations. Processing therefore remains a synchronous, isolated semantic transformation, and rendering remains synchronous through the serialized adapter. If profiling later demonstrates material input latency, the existing render boundary may move behind one serial worker without changing Component or Host semantics.

### Presentation and Scope contract

Chart presentation has exactly three Density values: `minimal`, `compact`, and `full`. Standalone defaults to `full`; each new or default Dashboard Pane explicitly uses `compact`. Density belongs to the chart configuration carried by Standalone or Pane. Dashboard has no global chart Density, and changes to Dashboard Theme, Style, Header, Summary, or Layout do not rewrite Pane-owned Density, Theme, Style, Filters, or analysis settings. A Density change advances render revision only; it does not change data Generation or scheduler baselines.

`minimal` retains identity, chart, and compact runtime state. `compact` adds the current filtered-Scope total and active Filter-dimension count. `full` adds applicable period comparisons and Host-supplied runtime audit. Controls and correctness-critical Notices are independent of Density. In Dashboard, each Pane formats a bounded local Notice band after resolving its own geometry; Notices are not globally aggregated or deduplicated and cannot consume another Pane's rows.

Time range, based on the host machine's local natural day, and Agent/Model/Project Filters define one chart Summary Scope. Filtering occurs before Summary calculation; By, Top, and Other are later projections and do not alter the Summary total or comparisons. Ranking with hidden Other carries `Top N · X% of total` metadata in its title; when Other is shown, the share is omitted because the chart covers the full filtered Scope. The Dashboard Header Summary is a separate owner with unfiltered data and Coverage, never a projection of Pane state.

A fixed range—including a lone Since whose end is resolved at startup—keeps both resolved bounds and infers no outside-range comparison Coverage. For rolling ranges, the historical Component owns accepted facts, comparison Coverage, missing intervals, supplemental pending/error state, and same-generation merges. Continuous Hosts first render uncovered applicable comparisons as `??`, then schedule only missing intervals; adjacent gaps may merge while disjoint baselines remain separate physical requests. A successful empty covered interval is numeric zero. A supplemental failure retains `??` and adds a local Notice. Historical no-Watch includes required comparison Coverage in its initial atomic request.

## Runtime state

Hosts and Components communicate through actions and effects:

```text
Action → reduce(state, action) → new state + effects
```

Actions include ticks, manual refresh, pause/resume, resize, input, settings changes, query completion, query failure, and debounce expiry. Effects include asynchronous query submission, debounce scheduling, scheduler rebuilding, copy, repaint, and exit. Accepted query completion is processed synchronously into a semantic model, then rendered synchronously through the serialized Plotext adapter before complete-Frame composition.

Each data-owning Component keeps an independent lifecycle envelope:

```text
Component State
├── candidate chart payload + resolved Host context
├── accepted data
├── data generation + processing/render revision
├── Coverage
├── active operation + subscription
├── debounce handle
├── pending trigger
├── observer
├── accepted success time
└── last error
```

### Runtime identity and result acceptance

Four identities keep product ownership, data intent, logical execution, and shared physical work separate:

| Identity | Meaning | Assigned by | Changes when |
| --- | --- | --- | --- |
| **Owner ID** | The Component or other data owner to which a result belongs | Host when the owner is created | The owner is destroyed and a new owner is created; moving or reconfiguring a Pane does not change it |
| **Generation** | The current version of the owner's data intent | Component when committed configuration requires data not satisfied by accepted facts and Coverage | Data requirements change; repaint, local reprocessing, periodic refresh, and manual refresh do not change it |
| **Operation ID** | One logical execution for an owner | Lifecycle coordinator when work is actually submitted | Every startup, periodic, manual, configuration, resume, or retry submission, including repeated work in the same generation |
| **Subscription ID** | One owner's interest in an in-flight physical query | Execution coordinator when attaching the operation | Every attachment or reattachment, even when an existing physical query can be reused |

A completion may mutate Component state only when its Owner ID and Generation match the current owner and data intent, its Operation ID is still the active operation, and its Subscription has not been detached. The stopping state rejects all completion. Rejection does not update data, Coverage, error, loading placeholders, pending intent, or a newer active operation.

Generation is not a query counter. For example, a periodic refresh and a later manual refresh of the same configuration share one Generation but receive different Operation IDs. This prevents a delayed periodic completion from being mistaken for the current manual operation. Conversely, changing a Theme keeps the Generation and active subscription because the facts remain valid; widening a date range beyond accepted Coverage increments the Generation, detaches obsolete work, and marks affected values `??`.

A Subscription is distinct from its physical query. If two Panes request the same physical data, each has its own Owner, Generation, Operation, and Subscription while the coordinator may run one physical query. When one Pane changes configuration, only its Subscription detaches. Physical cancellation is attempted only after the final subscriber detaches. A later manual request may attach with a new Operation and Subscription to a still-reusable physical query; the old subscription never becomes valid again.

A data-affecting adjustment increments the Generation immediately and detaches obsolete effects. Data and Coverage are accepted atomically only for the current Generation; stale success and stale failure update neither. Theme/Style, viewport, and transient-only changes advance a separate render revision. Changes computable from accepted facts advance processing/render revision without changing data Generation. The redesign introduces no completed-result cache.

Intentional detachment is not a business error. Configuration replacement, automatic-work cancellation on Pause, owner removal, and shutdown suppress the detached completion. Pause cancels automatic Startup, Periodic, and Resume work and clears periodic backlog, while an explicit manual refresh and committed-configuration completion remain allowed; their completion does not resume periodic scheduling. Shutdown detaches every subscription, clears pending and debounce state, rejects all later completion, then closes runtime and terminal resources in order.

Refresh, Sampling, debounce, manual refresh, resume, and committed configuration work remain distinguishable trigger sources. Fixed scheduler baselines do not move because of query duration, success, failure, manual refresh, pause, or resume. A slow Component never overlaps one pipeline stage for the same generation, and equivalent pending opportunities coalesce within their own trigger kind.

Asynchronous Query workers return immutable completion actions through one serialized runtime queue. Only the runtime owner mutates state, synchronously processes accepted facts, serially renders charts, composes Frames, and paints. Render revision still distinguishes successive visible states, but no render worker or render-completion queue is introduced without measured need. Shutdown stops admission, detaches/cancels work, suppresses late completions, stops painting, and restores terminal state last.

Historical no-Watch uses the same startup, query, acceptance, processing, Frame, and Painter path as Historical Watch, then exits after the first accepted Frame.

## Built-in capability registries

The implementation uses private, static registries for built-in capabilities:

- Provider Registry
- Chart Registry
- Theme Registry
- Style Registry

Registries use explicit registration, reject duplicate IDs, preserve deterministic order, and freeze before parsing or runtime begins. Only the application bootstrap composes production registries.

These registries are private dependency-inversion seams for composing the current built-in application. They are not public APIs.

### Providers

Built-in Providers are initially:

- `ccusage`: wraps query planning, safe subprocess execution, schema validation, and normalization;
- Demo: deterministic in-process records with no external dependency check.

Provider code does not import charts or presentation code. Chart code does not invoke Providers or read external storage.

### Charts

Each built-in chart has one Definition and can create any number of Components. Bootstrap assembles a Definition from narrow per-layer collaborators: configuration descriptor, data-requirements descriptor, processor/projector, renderer, runtime-settings descriptor, and inspection descriptor. Query, processing, and presentation import only the collaborator contract they consume, not the complete Definition.

### Theme and Style

Theme and Style are declarative presentation capabilities. Theme provides semantic color roles and palettes. Style describes compatible visual grammar. Neither reads Provider data, changes Data Scope, starts queries, controls the TUI lifecycle, or writes to the terminal.

## Animation hosts

Animation is a separate resource kind, not a Chart variant and not an implicit post-processing step for every chart. ccuv discovers host-eligible effects from `term-animate`'s curated catalog at runtime and uses the catalog-wide effect ID as its selection key. The library declares where an effect may embed; ccuv applies that declaration separately for standalone animation, Dashboard animation Pane, and Monitor attachment hosts.

`term-animate` remains a pure projection dependency. ccuv owns terminal lifecycle, input, viewport allocation, session clocks, repaint deadlines, clipping, and cleanup, while named library themes remain library-owned. It passes active/idle state only to effects that declare state support. An animation Pane owns no Provider, query runtime, scheduler, or lifecycle operation.

An Overlay is a host-local presentation resource, owned by its standalone animation host or Dashboard Animation Pane rather than by a Chart, Provider, or the animation library. Static text needs no schedule. A command Overlay owns its local shell execution schedule, bounded result history, and sanitized display output; its lifecycle ends with its host. Overlay repaint and command deadlines can redraw only their existing host frame and never start a token-data query.

Monitor attachments are local to their Monitor Pane or standalone Monitor host and are disabled by default. Users enable one from the advanced ranking/list controls; it then renders after a comparable accepted interval is available and uses ccuv's accepted token-delta decision to choose active versus idle for effects that declare state support. Their repaint deadlines redraw the existing frame only; they never initiate a query. Enabled attachments begin with the `classic` theme; advanced controls cycle all library-declared Monitor effects and then ccuv-local `none`. This transient `none` state retains no catalog effect, creates no provider work, and is unavailable to standalone animation and Dashboard animation panes.

Dashboard undo/redo is likewise bounded, session-only UI state owned by the Dashboard Host. It records Dashboard-state-represented composition and settings, never Provider results, Chart facts, or persisted configuration. It does not restore host-local Overlay drafts, position or offset mutations, or command-result history.

Chart Components require Query and Result Processing; animation projection does not. The shared terminal Frame and Painter infrastructure composes their output without turning animation into a chart component or widening chart/provider dependencies.

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
