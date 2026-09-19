# Runtime Architecture Redesign

**Status:** Approved design; ready for phased implementation

## Purpose

This redesign replaces the current command-specific execution loops with one capability-oriented runtime while preserving the converged product contract. It prepares internal seams for future Provider, Chart, declarative Theme/Style, and Animation capabilities without implementing a public plugin system.

No backward compatibility is required. Removed and renamed options, data structures, and internal entry points are deleted rather than aliased or wrapped.

## Goals

- Make `ccusage` one built-in Provider instead of a global architectural assumption.
- Reuse the same Chart Definition and Chart Component in Standalone and Dashboard.
- Separate Route, Query/Data Acquisition, Result Processing, and Rendering.
- Give configuration an immutable, ownership-specific representation.
- Unify lifecycle, scheduling, input, generation, Coverage, and Frame painting.
- Preserve only the two approved Dashboard query-sharing optimizations.
- Establish private static registries as future capability seams.
- Keep Chart and future Animation as distinct resource categories.
- Encode dependency directions in tests.

## Non-goals

This change does not implement:

- plugin discovery, installation, manifests, marketplace behavior, or dynamic imports;
- a public Provider, Chart, Theme, Style, or Animation protocol;
- external-source runtime support from the separately approved external-source design;
- Animation configuration, lifecycle cadence, interaction, resource budgets, or rendering protocol;
- Dashboard Header animation, logo slots, or generalized Header content;
- date-range union, Filter merging, Provider field supersets, generic batching/splitting, stale completed-result reuse, delayed Tick collection, automatic source deduplication, or adaptive intervals;
- non-TTY chart export;
- compatibility aliases or migration warnings for removed CLI syntax.

## Product model

```text
ccusage-viz
├── Standalone TUI
│   ├── Historical
│   │   ├── Timeline
│   │   ├── Calendar
│   │   ├── Stack
│   │   └── Ranking
│   └── Realtime
│       └── Monitor
└── Dashboard TUI
    └── Pane
```

Every chart interface remains a TUI. Pane is a Dashboard placement for the same Chart Component used by Standalone, plus Dashboard-owned composition context. The product continues to expose only Token usage and directly supported Token-derived metrics; TPM remains the only rate metric.

## Terminology

### Chart Definition

A stateless catalog entry for one chart type. It gives bootstrap a stable ID and references to narrow collaborators:

- a chart-configuration descriptor and defaults;
- a logical data-requirements descriptor;
- a processor/projector that converts normalized facts into a semantic result;
- a renderer for that semantic result;
- runtime-settings and inspection/data-view descriptors;
- a Component factory.

Query, Result Processing, Presentation, and Runtime import only the collaborator contract they consume, never the complete Definition. A Definition contains no session state, executes no Provider, and writes nothing to the terminal.

### Chart Component

One running chart instance. It owns:

- effective chart configuration;
- generation and Coverage;
- accepted normalized data;
- lifecycle phase and one pending opportunity;
- Observer state such as the previous Monitor snapshot;
- accepted success time and current error;
- semantic result and Chart Render;
- inspection content and command-serialization inputs.

A Component is the smallest product-level unit reused by Standalone and Dashboard.

### Host

The product shell that runs Components.

- `StandaloneHost` owns one Component, Standalone interaction, full-screen composition, and Standalone command copy.
- `DashboardHost` owns ordered Pane placements, Layout/Weights, focus, Dashboard Header and Summary, Dashboard command copy, and global Refresh/Sampling schedulers.

Dashboard does not invoke a Standalone route or event loop.

### Pane

A Dashboard-owned placement record containing the Component identity plus geometry, order, focus, and Dashboard-owned cadence context. It does not copy or specialize Chart behavior.

### Provider

A data-acquisition capability. A private Provider contract conceptually supplies:

```text
capabilities
compile(QueryIntent) → PhysicalPlan
fingerprint(PhysicalQuery) → stable key
execute(PhysicalQuery) → PhysicalResult
normalize(PhysicalResult) → ProviderResultFragment
assemble(PhysicalPlan, fragments) → ProviderResult
```

Providers own acquisition mechanics and normalization into host-defined facts. They do not own product scheduling, Filter semantics, chart aggregation, TUI lifecycle, or terminal rendering.

## End-to-end pipeline

```text
argv
  → Route
  → Configuration Preparation
  → Logical Query Planning
  → Coordinator / Provider Execution
  → Normalized Result
  → Result Processing
  → Semantic Chart Result
  → Rendering with Theme / Style
  → Standalone or Dashboard Composition
  → Complete Frame
  → Terminal Painter
```

### Route

Route probing identifies Help, Version, Standalone Chart, and Dashboard. Help and Version short-circuit before TTY checks, dependency checks, registry-backed runtime construction, terminal state changes, or queries. Dispatch remains extensible, but no unused Animation route case is added until a concrete Animation launch contract exists.

Chart routes produce typed launch intents. Routing chooses product form and content identity; it does not implement a chart.

### Query and data acquisition

Query contains three explicit internal stages.

#### Configuration preparation

```text
parse → compose defaults and Presets → validate → resolve startup values → effective configuration
```

Parsing constructs syntax-level input. Composition applies defaults, Presets, and appended Pane fragments according to ownership. Validation checks the complete composed configuration atomically. Resolution materializes startup-dependent values such as a lone Since boundary in the selected Timezone; it does not add defaults after validation.

All blocking configuration diagnostics occur before external dependencies or terminal mode changes. A diagnostic carries the command layer or Pane, field, invalid value, violated constraint, and—only when intent is reliable—a minimal semantic repair command and change summary.

#### Logical query planning

A shared logical planner creates immutable `QueryIntent` values independently for Standalone Components, Dashboard Summary, and Pane Components. It combines the owner's resolved Host context, reusable chart payload, Chart Definition data requirements, generation, trigger, and current Coverage. The resulting intent contains owner, generation, trigger, Provider ID, Data Scope and missing intervals, required resolution and dimensions, and execution options. Standalone and Dashboard use the same planner rather than duplicating missing-Coverage logic.

Chart Definitions declare requirements in Provider-neutral terms. They never emit subprocess argv.

#### Coordinator and physical execution

The Coordinator asks a Provider to compile a logical intent into a physical plan, executes its queries under bounded concurrency, and delivers one atomic immutable normalized result to each subscriber only after the plan is complete. Each plan carries an ID and explicit query order. The Provider assembles its normalized fragments into one result, combining Coverage, provenance, notices, and metadata; any required physical failure fails the plan, so Components never accept a last-fragment-wins partial result.

The only initial cross-owner optimizations are:

1. strict in-flight deduplication when Provider ID, physical fingerprint, and execution-affecting options are equal;
2. explicit sharing of compatible Monitor raw cumulative snapshots.

The Coordinator alone owns in-flight sharing and subscriber accounting. Each subscriber receives a detachable handle. Canceling or deleting one owner detaches only that subscriber; the physical operation is terminated only after its last subscriber detaches or process-level shutdown cancels all work. When a required fragment fails, or an owner's generation becomes obsolete, that plan immediately detaches its subscriptions from every remaining queued or running physical query. A physical query shared with another live plan continues; an unshared queued query is removed and an unshared running query is cancelled.

Even when physical work is shared, every owner retains independent generation checks, Coverage, previous Monitor snapshot, observation window, accepted time, business state, and error state. Stale delivery updates neither accepted data nor Coverage: data and its corresponding Coverage are accepted atomically only for the current generation. No completed-result cache is introduced.

The Coordinator does not own interval or Tick scheduling. Across independent owners it does not merge unlike requests or reuse completed stale work. For one owner, the shared logical planner may still combine adjacent missing Coverage intervals as allowed by the product contract.

## Provider boundary

### Built-in ccusage Provider

The existing query planner, subprocess runner, and schema decoder move behind a built-in `ccusage` Provider:

- Provider-specific planning compiles `QueryIntent` into `ccusage` commands.
- The subprocess adapter executes and cancels one physical query at a time. It retains timeout, process-tree termination, and bounded output capture; Coordinator-level limits provide bounded plan concurrency and all cross-owner in-flight deduplication.
- Output capture enforces an explicit byte ceiling configured in process context. Crossing it terminates the process and fails the physical query; temporary files are not introduced in this migration.
- Schema parsing becomes Provider normalization.
- `ccusage` dependency checks apply only when the effective Provider is `ccusage`.

The provider returns a common result envelope rather than exposing query kinds or argv downstream.

### Built-in Demo Provider

Demo is a separate built-in Provider. It produces deterministic normalized records in process, performs no `ccusage` dependency check, and uses the same downstream processing and rendering path as real data.

### Normalized result

```text
NormalizedResult
├── records
├── provenance
├── resolution
├── coverage
├── notices
└── provider_metadata
```

Usage records preserve Token composition, Agent, model, project identity, timestamps/dates, and original Provider provenance. The current closed `SourceKind` assumption is replaced by an extensible Provider reference without introducing public plugin registration.

## Result processing

Result Processing is a separate layer between Provider facts and presentation. It owns:

- Coverage and provenance acceptance;
- Filter candidate and selection resolution, with each dimension's candidates derived only from time range and Timezone rather than narrowed by the other Filter dimensions;
- Historical aggregation;
- Monitor cumulative-snapshot difference and counter-reset handling;
- Gap handling, observation windows, and minute rollups;
- Summary and comparison calculations over the complete accepted Scope before By/Top/Other; Dashboard Summary uses its own unfiltered Dashboard scope;
- By, Top, and Other for chart-visible series;
- chart-specific projection into immutable semantic models.

Existing immutable chart models remain the presentation boundary, after moving core time-range primitives out of CLI-owned modules.

The same normalized result can be processed independently by several consumers. Result Processing cannot start queries or alter Provider execution.

## Configuration model

The broad mutable `CommandOptions` object is removed. Configuration becomes immutable and ownership-specific.

Conceptual groups:

- process context: Language/Locale selection, `ccusage` binary, timeout, output limit, and Provider execution environment;
- reusable chart payload: date range or Monitor window, Filters, By, Top, Other, Granularity where supported, Theme, chart Style, Density, Legend, and chart-specific discriminated configuration;
- Standalone host context: resolved Provider/data mode, Timezone, ASCII, Demo Size when applicable, Watch/no-Watch, and Refresh or Sampling interval;
- Dashboard host context: one resolved Provider/data mode, Timezone, ASCII, Demo Size when applicable, Layout, Weights, Controls, shell Theme/Style/Density, Summary Granularity, and global intervals;
- Pane placement plus one reusable chart payload. Pane config cannot contain Provider/data mode, Timezone, ASCII, Demo Size, process context, or Dashboard-global settings.

A Component receives resolved Host context alongside its chart payload; the Host never mutates or silently overrides a Pane-owned field. Copying a Pane as Standalone materializes the required Dashboard Host context.

Date ranges and Period primitives live in a core time module rather than CLI options. Configuration serialization is canonical: reparsing a serialized command must reproduce the same effective configuration. Compact form may omit defaults; full form emits all reproducible effective values. Serialization is separate from clipboard I/O and does not attempt to reconstruct original Preset syntax.

No compatibility facade remains for deleted syntax.

## Runtime and scheduling

One shared lifecycle engine replaces separate Historical Watch, Monitor, and Dashboard loops.

```text
Action
  → reduce(SessionState, Action)
  → New State + Effects
```

Representative actions:

- Started, Tick, ManualRefresh;
- Pause, Resume, Resize;
- KeyPressed, MousePressed;
- SettingChanged, DraftCommitted, DraftDiscarded;
- QuerySucceeded, QueryFailed;
- DebounceElapsed.

Representative effects:

- SubmitQuery;
- ScheduleDebounce, CancelDebounce;
- SubmitProcessing, CancelProcessing;
- RebuildTickSequence;
- CopyContent;
- Repaint;
- Exit.

Every data-affecting setting change creates a new generation immediately. The candidate configuration and visible structure update immediately. `??` is used only when required data is missing and its query/processing lifecycle is in debounce, pending, or execution. Real zero is valid only inside authoritative Coverage; no-data, error, unavailable, and not-applicable states remain distinct. Only current-generation query and processing results alter visible accepted content. Advancing the generation immediately detaches obsolete query subscriptions and requests cancellation of obsolete processing and queued render work so stale tasks do not retain bounded execution slots.

Query, processing, and rendering activity are tracked independently rather than collapsed into one execution flag. Pending trigger state preserves trigger identity: at minimum periodic backlog, manual refresh, resume, and committed configuration/debounce work remain distinguishable. Pausing discards periodic backlog but does not erase an explicit manual refresh or the one completion required by a committed configuration change. Equivalent opportunities may coalesce within their own trigger class, while a Component still never overlaps the same pipeline stage for one generation.

Result Processing runs as bounded, cancellable, generation-tagged effects outside the reducer and terminal event loop. Workers return immutable completion events through one serialized runtime action queue. Only the runtime owner mutates state, composes Frames, or invokes the Painter. The first implementation does not add shared cross-owner indexes or pre-aggregations; this preserves the intentionally narrow optimization boundary, while bounded execution keeps one expensive projection from blocking input or another Component's result acceptance.

Historical Refresh, Monitor Sampling, Dashboard Refresh, and Dashboard Sampling use fixed monotonic baselines. Query duration, success, failure, manual refresh, pause, and resume do not shift the baseline. Debounce is independent and can be satisfied by an earlier Tick, manual refresh, or resume according to the preserved trigger state.

Historical no-Watch enters the same interactive TUI startup path, obtains the required result, paints one accepted Frame, and exits. Monitor and Dashboard reject no-Watch. Exit is ordered: stop admitting scheduler and debounce work; detach query subscriptions and cancel unshared work; cancel or drain processing and render work; suppress all late completion events; stop painting; restore terminal state last.

## Input and interaction

`tui_input.py` becomes the only terminal input decoder. Private duplicate input implementations are removed.

Host reducers translate input into semantic actions. Chart Definitions expose supported runtime settings and inspection views, but do not read terminal events directly. Dashboard adds focus, Pane lifecycle, layout editing, global settings, and global command copy around the same Component actions used by Standalone.

Nested draft editors retain commit/discard semantics. Ordinary runtime settings remain immediate.

## Rendering and Frame discipline

Chart processing produces immutable semantic models. A chart renderer receives a semantic model, a viewport/terminal-capability context, declarative Theme/Style, and transient annotations, and returns a `ChartRender` without terminal side effects.

Host composition combines all visible content into one complete `Frame`. `FramePainter` compares the complete Frame with the previous Frame and writes changed rows. No status, error, chart, or query path may bypass the current Frame with partial stdout writes.

Plotext remains isolated behind a serialized rendering adapter because of its process-global state. The adapter is invoked outside the reducer and terminal input loop; completion is tagged with both data generation and `render_revision`, where `render_revision` also advances for Theme/Style, viewport, and transient-annotation changes that do not require new data. The adapter keeps at most the running job plus the latest queued request for each Component, replacing older queued revisions; obsolete work is cancelled where supported and otherwise allowed to finish only for its completion to be discarded. UI-thread-only terminal composition and painting therefore remain responsive without letting stale render jobs delay the latest revision indefinitely.

The Dashboard Safety Minimum is derived before implementation only from shared shell and Pane structural invariants: every Pane retains a non-empty body row plus identity/focus and one compact diagnostic/status row, and the Dashboard retains its always-present Header identity. Border and separator costs are added by the selected shell Style. These invariants determine the tested global width/height floor. A renderer-specific minimum is not folded into that global constant; when one renderer cannot represent useful content inside an otherwise structurally valid Pane, that Pane degrades locally and displays its compact notice.

## Theme and Style

Theme and Style use separate private registries and declarative built-in definitions.

- Theme maps semantic roles to terminal presentation.
- Style selects compatible visual grammar.
- Dashboard shell Style is independent from Pane chart Style.
- Theme/Style do not query, mutate Data Scope, schedule, or write directly to the terminal.
- ASCII remains a global terminal capability mode and conflicts with every explicit Theme, including `no-color`.

No Theme inheritance or public theme schema is introduced in this redesign.

## Static capability registries

The composition root creates and explicitly populates:

- `ProviderRegistry`;
- `ChartRegistry`;
- `ThemeRegistry`;
- `StyleRegistry`.

Each registry rejects duplicate IDs, has deterministic order, and freezes before parser construction or runtime. Tests may construct isolated registries. Production modules do not scan filesystems, Python entry points, installed packages, or manifests.

There is no universal `Plugin` interface. Each capability seam remains narrow and typed to its own responsibility.

## Chart and future Animation resources

Chart and Animation are separate resource kinds:

- Chart requires Query, Result Processing, and chart rendering.
- Animation does not query usage data.
- Both may eventually run Standalone or occupy a Dashboard Pane.
- Animation receives its own Route instead of becoming a generic Chart post-processing stage.

Route dispatch and Host/content composition remain extensible, but this migration adds no Animation route case or resource discriminator. It must not invent `AnimationDefinition`, `AnimationComponent`, a common Hosted Component protocol, animation settings, frame budgets, or Header slots before an actual Animation implementation is designed.

Dashboard Header remains an ordinary product component. Static logo and animation requirements are not assumed to be the same capability.

## Dependency rules

- Core imports only the Python standard library.
- Configuration may depend on Core values and capability identifiers, never CLI or adapters.
- Query depends on Core and Provider contracts, never CLI, TUI, or rendering.
- Result Processing depends on Core semantic values, never Provider adapters or terminal code.
- Presentation depends on Core and chart/theme/style contracts, never Provider adapters.
- Built-ins implement capability contracts.
- Bootstrap is the only production composition root importing all built-ins.
- Dashboard does not import private Standalone or Monitor implementation functions.
- Library modules do not import parser construction.

Architecture tests enforce forbidden import edges and registry composition rules.

## Migration sequence

The migration is incremental but does not preserve legacy internal APIs.

### Phase 1: contracts, routing, and configuration

- Add black-box tests for accepted product behavior.
- Introduce core time and scope values.
- Add immutable process, Standalone, Dashboard, Pane, and discriminated chart configurations.
- Split route probing, parser construction, composition, validation, resolution, diagnostics, and serialization.
- Delete removed options and old compatibility paths directly.

### Phase 2: Provider-neutral Query

- Add private capability registries and explicit built-in registration.
- Introduce `QueryIntent`, `PhysicalQuery`, Provider result envelopes, provenance, and Provider references.
- Move `ccusage` planning/execution/normalization into its built-in Provider.
- Add the built-in Demo Provider.
- Implement bounded coordination and only the approved sharing rules.

### Phase 3: Result Processing and Charts

- Split generic filtering and Summary logic from chart-specific projection.
- Create one Definition per historical chart; Monitor remains a runtime/data mode that projects into Timeline or Ranking.
- Move Monitor difference/window/Gap state into its Component processing state.
- Create shared historical and Monitor Components and remove cross-imports between command loops.

### Phase 4: Rendering and declarative presentation

- Separate viewport/terminal capabilities, Theme, Style, chart presentation, and transient annotations.
- Add `ChartRender`, complete `Frame`, and `FramePainter`.
- Prevent all renderers and query paths from writing directly to stdout.

### Phase 5: shared runtime and Standalone Host

- Implement the reducer/effect runtime, fixed-baseline schedulers, debounce, generations, and pending-opportunity semantics.
- Host Historical and Monitor Components through Standalone Host.
- Route no-Watch through one accepted interactive Frame followed by exit.

### Phase 6: Dashboard Host

- Keep Dashboard layout/geometry in focused Dashboard Host modules, extracting only pure calculations where useful.
- Build Dashboard Host around the same Components.
- Give Summary and each Pane independent lifecycle envelopes.
- Implement Dashboard composition, global schedulers, focus, Pane lifecycle, settings, and command copy.

### Phase 7: removal and documentation

- Remove obsolete Watch, Monitor, and Dashboard loops and parser fragments.
- Remove old option tables, partial terminal writes, and compatibility-only localization keys.
- Update user documentation to match implemented syntax.
- Keep the maintainer architecture document synchronized with final module names.

At each phase, new code becomes the authoritative path and superseded code is deleted; a permanent dual architecture is not acceptable.

## Testing and acceptance

### Contract tests

Cover the stable product semantics before extraction:

- Help/Version short circuit without TTY or Provider dependency.
- chart routes require interactive stdin and stdout.
- the user-reference defaults currently approved for Historical Watch, including its 10-second interval, are represented in one configuration source of truth rather than duplicated in parser and runtime code;
- Historical no-Watch paints one accepted interactive Frame and exits.
- Monitor and Dashboard reject no-Watch.
- Period/fixed-date resolution and Timezone boundaries.
- configuration ownership and Preset plus appended Pane composition.
- preservation and command serialization of valid startup values outside a TUI control's common finite choices;
- explicit mode values, By terminology, and deleted option rejection.
- startup diagnostic structure and no side effects before validation succeeds.

### Provider and coordinator tests

- Provider compile/execute/normalize separation.
- Demo never checks or invokes `ccusage`.
- strict physical fingerprint equality for in-flight sharing.
- non-equivalent ranges, Filters, Providers, or execution options never share.
- subscriber cancellation and process-tree cleanup.
- shared raw results are immutable and owner state remains independent.

### Processing tests

- Coverage acceptance and distinct unknown, zero, no-data, error, unavailable, and not-applicable semantics;
- OR within one Filter dimension, AND across dimensions, and non-cascading Agent/Model/Project candidate lists;
- historical aggregation and Summary baselines over complete Scope before By/Top/Other, including unfiltered Dashboard Summary scope.
- Monitor differences, resets, Gaps, windows, minute rollups, By/Top/Other.
- one normalized result processed under different Component configurations.

### Runtime tests

Use a fake monotonic clock and deterministic effects to test:

- fixed baselines;
- no overlap and one pending opportunity;
- debounce cancellation/satisfaction;
- generation rejection of stale results;
- pause/resume/manual refresh behavior;
- independent Component completion/failure.

### Rendering tests

Use golden or structural Frames for:

- complete Frame composition;
- row-diff painting without partial bypasses;
- resize cleanup;
- narrow/wide layouts and renderer degradation;
- Safety Minimum values;
- declarative Theme/Style application and ASCII conflicts.

### Architecture and quality gates

- import-boundary tests;
- duplicate/frozen Registry tests;
- no old CLI aliases or compatibility wrappers;
- no renderer stdout calls;
- full `pytest`;
- `ruff format --check` and `ruff check`;
- `ty check src/`;
- package build.

The redesign completes only when repository-wide format, lint, type-check, test, and build gates pass. The five known format findings and five known type diagnostics are explicitly included in the migration cleanup phase; unrelated behavior is not refactored merely to satisfy style preferences.

## Documentation

`docs/architecture.md` and `docs/architecture.zh-CN.md` explain the implementation hierarchy and terminology for maintainers. The design philosophy continues to describe stable product constraints. User-facing command/reference documentation is updated only after corresponding implementation behavior is stable.
