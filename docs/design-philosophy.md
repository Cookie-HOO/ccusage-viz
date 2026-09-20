# Design Philosophy

This document records the stable product concepts and design constraints of `ccusage-viz`. Command syntax, defaults, complete key maps, and Preset parameters belong in user documentation; implementation and release sequencing belong in design specifications and the roadmap.

## Product boundaries and forms

1. **The product expresses token consumption and directly supported derivatives only.**

   A token metric belongs only when a data source can express it directly and reliably. TPM is currently the only rate metric. Cost, monetary estimates, call or request counts, quotas, QPM, rate limits, and other metrics inferred from token counts are outside the product boundary.

2. **Standalone and Dashboard are the two product forms.**

   Every interactive chart interface is a TUI. Standalone runs Timeline, Calendar, Stack, Ranking, or Monitor independently. Dashboard organizes multiple independently configured charts in one TUI.

3. **A Pane preserves its corresponding Standalone data and chart semantics.**

   A Pane is a contextual superset of Standalone content. It adds composition concerns such as focus, placement, ordering, and switching, but Dashboard behavior must not change the underlying chart's time or metric contract.

   **Exception:** Dashboard owns Pane refresh and sampling cadence. Copying a Pane as a Standalone command materializes the corresponding Interval.

## Configuration ownership

1. **Dashboard settings control only the scope they explicitly own.**

   Configuration ownership has three categories. A setting affects only its category and never rewrites another through implicit inheritance.

   | Independent Dashboard setting | Scope | Pane behavior |
   | --- | --- | --- |
   | Layout, Weights, focus, Pane order | Dashboard geometry and navigation | Not part of Pane configuration |
   | Global pause, Controls | Dashboard session shell | A Pane owns no local pause or Controls state |
   | Dashboard Theme and Style | Shell, Header, and Summary | Does not change Pane Theme or chart Style |
   | Header Style and Summary period | Dashboard Header | Does not change Pane Density, Scope, or Granularity |

   | Uniform Dashboard setting | Effect on Panes |
   | --- | --- |
   | ASCII | Shell and every Pane use basic characters without color |
   | Real or Demo source mode | Summary and every Pane use one source mode |
   | Demo Size | Demo Summary and every Pane use one scale |
   | Timezone | Summary and every Pane use the same natural-day boundaries and time labels |
   | Refresh Interval | Drives Summary and every historical Pane; a Pane owns no Watch or local refresh |
   | Sampling Interval | Drives every Monitor Pane; a Pane owns no local sampling cadence |

   | Independent Pane setting | Ownership boundary |
   | --- | --- |
   | Time range and Filters | Each Pane defines its own Data Scope |
   | By, Top, and Other | Each Pane defines its own analysis and visible series |
   | Theme, Style, Density, and Legend | Each Pane defines chart presentation; Theme does not inherit Dashboard Theme |
   | Chart-specific settings | Belong only to the corresponding Pane |

   Pane configuration and Pane fragments must not contain Demo Mode or Demo Size. Standalone still owns its own Demo settings, Timezone, Interval, refresh, and pause behavior. Every Pane must remain independently explainable; copying it as Standalone materializes the necessary Dashboard-owned context.

2. **Process context is not Pane configuration.**

   Language, the `ccusage` executable, query timeout, and Provider execution environment apply uniformly within the process and are not Pane-overridable settings.

## Data scope and analytical semantics

1. **Time and Filters define Data Scope together.**

   Time range, timezone, and Agent, Model, and Project Filters determine the data used by both chart and Summary. Selections use OR within a dimension and AND across dimensions. Candidate values for each dimension depend only on time range and timezone; dimensions do not narrow one another.

2. **By, Top, and Other do not change Data Scope.**

   By reorganizes scoped data into visible series, Top truncates those series, and Other controls whether excluded series are combined. Summary always aggregates the complete Scope. Other never consumes a Top slot and is always last. When Ranking hides Other, its title exposes `Top N · X% of total`; showing Other restores full Scope coverage and omits the share.

3. **Display range and comparison Coverage are independent.**

   Display range determines chart dates. Comparison Coverage supplies Summary baselines only. The Component owns accepted comparison facts, Coverage, and supplemental state. Continuous Hosts render applicable uncovered comparisons as `??` and query only missing intervals: adjacent gaps may merge, while disjoint baselines remain separate rather than expanding into one continuous query. A successful empty covered interval is numeric zero; supplemental failure retains `??` and adds a local Notice.

4. **Rolling and fixed date modes make different promises.**

   Period defines a rolling range whose bounds advance with natural days in the selected Timezone. Day periods are trailing windows including today; Month, Quarter, and Year periods include the requested number of natural calendar periods and run from the earliest boundary through today. Thus `14d` means today plus the preceding 13 days, while `1mo`, `1q`, and `1y` mean month-to-date, quarter-to-date, and year-to-date. A trailing span that does not need calendar alignment can always be expressed in days.

   Supplying Since or Until selects fixed-date mode; Until alone is invalid, while Since alone resolves its end to today's date in the selected Timezone at startup. Every fixed-date view presents the resolved start and end dates explicitly, including a lone Since; it does not use a special since-to-date title. Fixed boundaries never advance during the session: an included current day may continue accumulating, but after midnight in the selected Timezone the range remains on that original date and becomes fully historical. Granularity is independent of the date mode, defaults to Day, and may be adjusted without changing the range.

5. **Historical Ranking and Monitor Ranking share visual grammar only.**

   Historical Ranking orders accumulated token consumption over a date range. Monitor Ranking orders only the newest valid cumulative sample pair: Total and Model express TPM calculated from actual monotonic elapsed time, while Agent and Project express that pair's Token delta. Retained Timeline history does not redefine or repopulate the current Ranking value. The two Ranking forms do not share a time or metric contract.

## Data consistency and asynchronous results

1. **`??` means only that required data has not arrived.**

   `??` is the uniform loading placeholder: data required by the current effective state is unknown and has entered the refresh lifecycle, including debounce, pending execution, or active execution. It appears as soon as a committed change invalidates the corresponding value; stale values or results from another configuration must not be presented as if they matched the new state. Only affected values become unknown—presentation-only changes and values that can be recomputed from accepted data remain available. `??` must not represent a real zero, no-data result, error, unavailable capability, or inapplicable field; each of those states requires its own explicit presentation. A missing record may be treated as a real zero only inside authoritative covered intervals.

2. **Every data-affecting adjustment creates a new generation.**

   Candidate configuration and visible structure update immediately; required data may arrive asynchronously. Repeated adjustment must eventually converge on one internally consistent state.

3. **Only the latest generation may change the current display.**

   Obsolete results may enter suitable caches or Coverage, but cannot overwrite the latest candidate state. Each component independently owns its generation, Coverage, observer, success time, and error state.

4. **Continuous TUIs permit eventual completion.**

   Watch, Monitor, and Dashboard may temporarily show `??` and fill it as subsequent results arrive. Historical no-Watch performs its required query and renders the accepted result once before exiting; it does not depend on a future periodic Tick.

## Presentation and visual semantics

1. **Density controls information outside the narrow chart.**

   Density has exactly three values. Minimal retains identity, chart, and compact runtime state. Compact adds the current filtered-Scope token value and active Filter-dimension count without comparisons or audit. Full adds applicable period comparisons and Host-supplied runtime audit. Standalone defaults to Full; a new or default Pane uses Compact. Dashboard has no global chart Density.

2. **Theme, Style, and Density each have one responsibility.**

   Theme controls semantic color. Style controls the current object's visual grammar. Density controls information volume. Dashboard Style specifically controls borders, separators, spacing, and focus emphasis; it does not propagate into Pane chart Style.

3. **Summary uses one metric and comparison grammar across product forms.**

   Standalone and Pane Summary calculate and present Token values and comparisons consistently from their chart's filtered Scope, before By, Top, and Other projection. The independent Dashboard Header Summary owns unfiltered data and Coverage and never inherits Pane Scope. Identity, Summary, and runtime status remain distinct information. A fixed date range has no inferred range-outside comparison baseline.

4. **Controls and Notices are independent of Density.**

   Controls are a session-level interaction shell and may be hidden to reclaim space. Notices required to interpret the output correctly must not disappear merely because Density is low. In Dashboard, each Notice remains in a bounded band inside its source Pane; Notices are neither globally aggregated nor deduplicated, and one Pane cannot consume another Pane's space.

5. **Dynamic TUI is the primary experience, with deliberate fallbacks for other environments.**

   Continuous, runtime-adjustable TUI views are the default product experience. Historical views also support no-Watch execution for one-time use, while ASCII provides an explicit compatibility path for older or constrained terminals. Capability checks must fail clearly and recommend a supported path rather than silently changing user configuration. Exact flags, conflicts, terminal requirements, and fallback behavior belong in the third-layer configuration and terminal references.

## Interaction principles

1. **CLI establishes initial state; TUI provides what-you-see-is-what-you-get adjustment for frequent changes.**

   Users may supply initial configuration through the CLI or enter the TUI from a default command and adjust visually. Runtime entry points cover product settings that users may compare or change repeatedly during a session. An adjustment must immediately represent the effective state and remain reproducible through a copied command.

   **Exception:** Settings that normally remain stable during a session, require open-ended string input, change the entire data lifecycle, or belong to the execution environment are CLI-only and do not appear in runtime adjustment. These include Timezone, ASCII, real or Demo source mode, Language, the `ccusage` executable, query timeout, and Provider execution environment. Dashboard Timezone, ASCII, and source mode still apply uniformly to the Summary and every Pane and cannot be overridden by a Pane. Actual rendering, Full Details, or Full Command may expose these effective values for inspection, but the settings surface does not show read-only controls. Demo Size is a presentation scale within Demo mode and remains runtime-adjustable there.

2. **Runtime-adjustable configuration uses explicit modes; exceptional execution intent uses flags.**

   A persistent, copyable setting whose states users compare or change at runtime is expressed as a valued CLI mode even when it currently has only two states. The CLI, TUI, status display, and copied command share the same concepts and canonical values. This keeps commands self-describing without requiring users to remember defaults or translate between a TUI state and a positive or negative flag. For example, Weekdays and Other use `show | hide`, while Stack Cache uses `combined | split`. Compact commands may omit default modes; Full commands state every effective mode explicitly.

   **Exception:** A conspicuous capability choice or execution-lifecycle exception that is normally absent may remain a flag when its presence fully expresses the intent and it is not an ordinary runtime-adjustable setting. ASCII and Historical no-Watch are the current exceptions. Mode consistency must not create redundant controls for behavior already owned by a higher-level setting such as Density, Style, or Layout.

3. **Quick and Advanced reveal capability progressively.**

   Quick and Advanced are divided by usage frequency rather than an internal distinction between data and appearance. Quick covers Data Scope, analysis, and primary presentation in common analytical workflows. Advanced contains infrequent, precise, or conditional controls. Both operate on the same immediate configuration, and contextually meaningless options are omitted rather than shown disabled.

   Standalone uses exactly two rows: current runtime status plus effective settings, then the active Quick or Advanced actions. Dashboard-global adjustment has one Dashboard-wide page for Theme, Style, Header, Summary, and Layout; it has no Advanced page or Pane-specific actions. Dashboard Pane adjustment begins with the same two chart rows as Standalone, followed by Dashboard-management rows for content/lifecycle, position/focus, and logical size ratios. `a` switches only the chart action row; Dashboard management remains available on either page. Enter or Escape finishes ordinary adjustment without rolling back changes. There is no clickable Finish target. On narrow terminals, complete low-priority action units are omitted and `…(+N)` reports the exact number still available by keyboard, while page identity, the `a` switch, and Enter/Escape guidance remain visible.

4. **Finite choices preserve and truthfully display any valid startup value.**

   The CLI may accept a wider range of valid values than the TUI's common choices. The TUI must preserve and display the current concrete value without labeling its origin, and opening, browsing, or leaving settings must not snap it to a choice. If the value is in the common sequence, adjustment continues from it. Otherwise, the first explicit adjustment enters the sequence at its first value, after which adjustment cycles through common choices only. Copied commands always reflect the current effective value. Equivalent settings follow this rule in Standalone, Dashboard, and Pane contexts.

   **Exception:** Layout Weights adjust directly from the current integer proportions rather than restarting from a preset sequence. Free-form or execution parameters without a runtime entry are also outside this rule.

5. **Configuration takes effect immediately unless a valid value requires a draft.**

   Most settings commit on each adjustment. The visible configuration updates at once, and any data already derivable from accepted facts is recomputed immediately. Enter and Escape therefore have the same meaning in an ordinary settings surface: both leave the surface while preserving the effective state. They do not save, discard, or roll back changes that have already taken effect. Layout and Weights follow the same rule.

   **Exception:** An operation that cannot produce a valid value until the user completes input or selection uses an isolated draft: Filter, Layout, Pane Replace, and Pane Add. Enter commits a valid complete draft and Escape discards only that child operation, returning to its parent adjustment. The Layout Editor displays its current `auto`, `ROWSxCOLUMNS`, `spotlight-wide`, or `spotlight-tall` input and keeps invalid input visible with an error. Pane Replace atomically installs a fresh default Pane at the same list index and retires the displaced lifecycle. Pane Add uses `N` for before and `n` for after the focused Pane's list index. Fixed layouts preserve their column count and expand their row count when insertion requires capacity; deletion reclaims only wholly empty trailing rows. A second confirmation is reserved for consequences that are destructive, difficult to reverse, or otherwise unclear; ordinary reversible configuration does not require one.

6. **Committed configuration and displayed data must describe the same state.**

   A committed data-affecting change updates visible configuration and invalidates obsolete work immediately. Values not yet known for the new state display `??`, and an immediate refresh intent is created. A short trailing debounce may replace repeated intermediate refreshes with one request for the latest state, but it must not delay the visible configuration, invalidation, placeholder, or generation change. Enter or Escape leaving an immediate settings surface flushes a refresh intent still waiting in the debounce window.

   Only affected values become unknown. Presentation-only changes require only repaint; changes fully computable from accepted data reprocess immediately; changes requiring new data use `??` until the current generation is accepted. Obsolete completion cannot restore stale values or clear the placeholder. Pause suppresses periodic backlog, not an explicit refresh caused by committed configuration or manual refresh, and such a completion does not resume periodic scheduling.

7. **Keys express stable concepts, not a generic capitalization rule.**

   `m` always means modify the current chart: it modifies the current view in Standalone and the current Pane in Dashboard browse mode; clicking a Pane selects it and performs the equivalent action. Uppercase `G` opens Dashboard-global settings, and clicking the Header is equivalent. Uppercase letters do not generally reverse their lowercase options. Related keys may instead represent distinct, stable families of the same concept: `p` cycles common trailing periods, while `P` cycles common natural periods to date. The interface names the active family so a calendar-aligned period is not mistaken for a trailing duration.

   **Exception:** Theme has a large, growing choice set, so `t` advances and `T` reverses. `N` and `n` are the deliberate semantic pair for inserting a Pane before or after the focused Pane's list index. Other ordinary letter actions are lowercase-only.

8. **Directional operations support both arrow keys and `hjkl`.**

   Any context that offers up, down, left, or right navigation or adjustment must also accept `k`, `j`, `h`, or `l` respectively and perform the identical state transition. Controls may combine both key sets in space-sensitive guidance, but the two entry paths must never differ in boundaries, cycling, or confirmation behavior.

9. **Responsibility boundaries prevent semantic confusion rather than useful multiple entry points.**

   Standalone, Dashboard, and Pane share terminology, ordering, state representation, and adjustment behavior, but each operation appears only where its target is unambiguous. Multiple entry points are valid when they express the same intent and produce the same result. One interaction concept must not silently change another; for example, changing Granularity does not change Period.

10. **Startup-blocking configuration errors provide uniform, actionable diagnostics.**

   Startup configuration is validated atomically before entering the TUI. A diagnostic locates the exact command scope, Pane, option, or value; explains the violated constraint; and, when intent can be inferred reliably, provides a complete recommended command with the smallest semantic edit and a change summary. Repairs preserve intent before removing input: trustworthy near-match correction, ownership-aware movement, structural reconciliation, or numeric boundary clamping take precedence over deleting a meaningless option. When intent cannot be determined reliably, the diagnostic offers a small set of explicit alternatives rather than fabricating one answer. Runtime data, Provider, terminal-space, and no-data conditions are not command repairs.

11. **Inspection shows content before enabling copy.**

   Chart mode does not expose copy. Non-Chart views such as Command, Markdown Table, and JSON identify both the current content and the next view, and copy always captures the complete current content.

   **Exception:** Dashboard-global inspection offers compact and full commands only, not cross-Pane Markdown or JSON. Each Pane owns its own `v` view cycle across Chart, Command, Full Command, data table, and data JSON. Dashboard does not provide a temporary terminal text-selection `c` mode; ordinary xterm mouse reporting remains enabled for Pane selection and is restored during terminal cleanup.

## Dashboard layout and sizing

1. **Layout defines topology; Weights describe relative size within the current topology only.**

   `auto` derives a stable grid from Pane count. A positive `ROWSxCOLUMNS` value fixes the column count while allowing trailing empty cells. `spotlight-wide` gives Pane 0 a full-width top band; `spotlight-tall` gives Pane 0 a full-height left band. On a narrow terminal, `spotlight-tall` may render through a wide fallback without changing its configured identity or Weights. Changing the configured Layout rebuilds equal Weights for the new topology; no hidden proportions are retained for other Layouts and no terminal pixels are reverse-engineered. Commands record only the positive integer Weights applicable to the current Layout, normalized by greatest common divisor, never terminal-dependent absolute dimensions.

2. **Panes share column proportions and per-row heights.**

   A width adjustment changes the selected Pane's shared logical column or Spotlight band; a height adjustment changes its logical row or band. The positive integer Weights normalize by greatest common divisor and copied commands reproduce them. Reordering swaps content without changing geometry or Weights; Pane list index 0 alone determines Spotlight identity, independently of interaction focus. In a fixed grid, Pane insertion preserves columns and appends only as many rows as required; deletion removes only wholly empty trailing rows. Arbitrary coordinates, overlap, per-cell topology, pagination, and Pane scrolling are not supported.

3. **The Safety Minimum protects correctness, not comfortable readability.**

   Dashboard applies a small uniform floor that prevents invalid geometry while preserving identity, focus, and a compact diagnostic. Explicit Layout and Weights are not blocked merely for falling below a recommended visual size; sparse Ranking and Monitor Ranking may remain useful in small areas.

4. **A Renderer adapts and degrades inside its own Pane.**

   A Renderer may reduce labels, ticks, decoration, or visible rows according to space. It shows a local space notice only when meaningful output is impossible. One Renderer's requirements must not trigger global reflow.

5. **Auto uses stable soft targets only.**

   Auto may consider Pane count and available space, but current data must not change the topology. Users retain control of readability through Weights, Density, Top, Legend, and Style.

## Dashboard scheduling, execution, and repainting

1. **Dashboard uses two fixed Tick sequences.**

   Refresh Tick offers work to the Summary and historical Panes. Sampling Tick offers work to Monitor Panes. Their session baselines do not move because of execution duration, success or failure, manual refresh, pause, or resume. Changing one Interval rebuilds only its corresponding sequence.

2. **Data-affecting adjustments complete the latest state after a debounce.**

   A setting takes effect immediately and creates a new generation. Content computable from existing data updates at once, while missing values show `??`. Only when the latest state still requires data does a short trailing debounce offer one refresh opportunity. Continued adjustment resets the debounce, preventing queries for intermediate states. A fixed Tick, manual refresh, or resume that occurs first satisfies and cancels the pending debounce without moving Tick baselines.

   **Exception:** Presentation-only changes and adjustments fully computable from existing data schedule no query; changing an Interval only rebuilds its Tick sequence.

3. **A shared trigger is not a shared completion barrier.**

   Every component independently starts, completes, fails, validates generation, and accepts results. A slow Pane does not delay another Pane, and a Tick never waits for the class to finish as a group.

4. **A slow component keeps at most one Pending opportunity.**

   When another Tick arrives during execution, the component starts no overlapping work and records one Pending flag. Completion services it immediately. Multiple missed Ticks do not queue. An Interval shorter than sustainable execution may cause continuous querying; this is an observable configuration outcome, not something the system silently corrects.

5. **Execution Coordinator reduces physical work without merging business state.**

   Summary and Panes produce logical requests carrying owner, generation, trigger, logical plan, source mode, and execution options. The Coordinator deduplicates strictly identical in-flight physical queries and may share a common Monitor raw snapshot that the product has explicitly proven safe, then delivers immutable results independently to each owner.

   **Exception:** The Coordinator currently does not union date ranges or differing Filters, create Provider field supersets, reuse completed stale results, or delay Ticks to collect a batch. A Provider-specific implementation may perform advanced optimization only through explicit coalescing and distribution contracts. Interval semantics always remain outside the Coordinator.

6. **Automatic updates submit a complete logical Frame.**

   Every result produces a complete Frame that is compared with the previous Frame before changed terminal rows are written. Components may update as their own results arrive, but no partial physical write may bypass Frame state.

7. **Refresh includes the reconciliation and repaint required by its results.**

   `r` always refreshes the current context. Sorting, derived computation, and full repaint caused by refreshed data are consequences of that same operation, not separate re-sort or repaint commands. A Dashboard manual refresh gives every component an immediate refresh opportunity, invalidates the paint cache, and covers the full Dashboard. Resume performs the same refresh and repaint before fixed Ticks continue. Resize automatically recomputes all geometry and clears obsolete regions without requiring a data query. Full repaint does not imply an unconditional terminal clear.

   **Exception:** Pause stops periodic Ticks only. Paused time creates no periodic work or backlog, while manual refresh and a one-shot completion debounced from an explicit configuration change may still run. Such completion does not resume periodic scheduling. A Monitor baseline, sampling gap, pause/resume, data-affecting reconfiguration, or counter reset clears the separate current observation until the next valid sample pair; retained Timeline history remains available and discontinuities remain Gaps. Standalone Watch and Monitor retain their own refresh, pause, and Interval behavior.

## Reproducibility and documentation boundaries

1. **Effective configuration must be reproducible as a command.**

   Copying Dashboard expands the actual Layout, Weights, Panes, and global settings. Copying a Pane produces an executable Standalone command and materializes Dashboard Timezone and the applicable Interval. Compact commands omit defaults; full commands state effective configuration explicitly.

2. **A Preset is a complete initial template, not a runtime mode.**

   A Preset supplies a complete Dashboard base state that may receive explicit startup overrides or appended Panes. Without a Preset, a command must explicitly provide a Pane, except for bare `dashboard`. Its source marker disappears permanently after any serializable runtime edit; startup composition and session actions such as refresh, pause, Controls visibility, inspection, query results, and Resize do not affect it. Copied commands always expand actual state rather than retaining the Preset name.

3. **Session state is excluded from reproducible configuration.**

   Current focus, pause state, Controls visibility, inspection view, and transient errors belong to the running session and do not enter copied commands.

4. **Design philosophy records stable constraints only.**

   Complete CLI spelling, option matrices, key maps, Preset contents, and operating examples belong in user guides. Component interfaces, state machines, and test criteria belong in formal design specifications. A new feature should fit one of these principles; any necessary exception must state its boundary explicitly.

5. **Documentation is layered by depth and kept consistent in one maintenance pass.**

   The README builds first-contact understanding through natural explanations and a small product map. Architecture documents define implemented ownership and runtime boundaries, while design philosophy explains stable principles and reasons. Formal design specifications preserve decisions and test criteria; the roadmap describes planned work only. English and Simplified Chinese documents must describe the same contracts, and changes to terminology, defaults, or ownership are reconciled across these layers rather than deferred.
