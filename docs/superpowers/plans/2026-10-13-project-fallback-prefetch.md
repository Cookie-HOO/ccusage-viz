# Project Fallback Prefetch and Atomic Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Treat the primary project observation and every required agent-session fallback as one atomic refresh, while learning exception agents so later refreshes prefetch their fallbacks concurrently with normal in-flight sharing.

**Architecture:** Extend physical queries with provider-neutral speculative/scheduling metadata. The coordinator starts primary and speculative work together, waits only for primary work before provider dependency resolution, then reuses required speculative futures, launches newly required work, and detaches irrelevant speculation. Keep ccusage-specific learned-agent state and replacement in `CcusageProvider`; compile remembered fallbacks into initial plans, discover new fallbacks after A, and directly replace A exception records with each successful normalized B result.

**Tech Stack:** Python 3.11–3.13, frozen dataclasses, `threading` synchronization, `concurrent.futures`, pytest, Ruff, ty.

**Spec:** `docs/superpowers/specs/2026-10-13-project-fallback-prefetch-design.md`

## Global Constraints

- Apply the behavior to every agent requiring a project fallback, never hard-code Pi as the scheduling policy.
- Keep learned state process-local, thread-safe, non-persistent, and isolated by ccusage source identity.
- Do not add CLI/configuration options; the fallback concurrency limit is exactly `4`.
- A and every fallback confirmed necessary by A form one atomic provider result.
- A required fallback execution or normalization failure fails the refresh; never publish A's temporary `Unassigned` aggregate.
- Successful normalized B records directly replace corresponding A exception records without token-total or resolved-project validation; empty B is valid.
- A speculative fallback failure is irrelevant when A no longer identifies that agent as exceptional.
- Preserve existing physical-query fingerprinting and in-flight sharing; scheduling/dependency metadata must not alter fingerprints.
- Period changes may waste at most one speculative fallback round before A refreshes learned state.
- Preserve unrelated working-tree changes and untracked files.

## File Structure

- `src/ccusage_viz/query/models.py` — add immutable scheduling metadata for speculative physical queries.
- `src/ccusage_viz/query/provider.py` — define the generic provider hook that declares required follow-up queries after primary fragments are known.
- `src/ccusage_viz/query/coordinator.py` — start speculative work, resolve dependencies from primary results, await only required work, enforce scheduling-group limits, and assemble exactly once.
- `src/ccusage_viz/providers/ccusage.py` — own learned exception-agent state, compile remembered fallbacks, classify A, resolve required/irrelevant outcomes, and directly replace A exception records with normalized B records.
- `src/ccusage_viz/locales/en.py`, `src/ccusage_viz/locales/zh.py` — localize the internal missing-fallback-fragment error.
- `tests/test_query_coordinator.py` — protect generic concurrency, sharing, speculative dependency, and cancellation semantics.
- `tests/test_ccusage_provider.py` — protect learned-agent compilation, source isolation, dynamic addition/removal, and atomic direct replacement.
- `tests/test_historical_component.py` — prove failed replacement retains the previously accepted snapshot and successful retry replaces it atomically.

---

### Task 1: Model speculative scheduling without changing physical identity

**Files:**
- Modify: `src/ccusage_viz/query/models.py:110-190`
- Modify: `src/ccusage_viz/query/provider.py:1-70`
- Test: `tests/test_query_coordinator.py`

**Interfaces:**
- Consumes: existing `PhysicalQuery`, `PhysicalResult`, `ProviderResultFragment`, and provider protocol.
- Produces: `PhysicalQuery.scheduling_group: str | None`, `PhysicalQuery.scheduling_limit: int | None`, `PhysicalQuery.speculative: bool`, and optional `Provider.resolve_queries(plan, primary_fragments) -> tuple[PhysicalQuery, ...]`.

- [ ] **Step 1: Add failing model tests for scheduling metadata and fingerprints**

Add tests showing that valid scheduling metadata is stored, invalid combinations are rejected, and scheduling metadata does not change physical identity:

```python
def test_physical_query_scheduling_metadata_does_not_change_fingerprint() -> None:
    plain = PhysicalQuery(ProviderRef("recording"), "shared", ("--value", "1"))
    scheduled = PhysicalQuery(
        ProviderRef("recording"),
        "shared",
        ("--value", "1"),
        scheduling_group="project-fallback",
        scheduling_limit=4,
        speculative=True,
    )

    assert scheduled.fingerprint == plain.fingerprint
    assert scheduled.scheduling_group == "project-fallback"
    assert scheduled.scheduling_limit == 4
    assert scheduled.speculative


@pytest.mark.parametrize(
    ("group", "limit"),
    [(None, 4), ("project-fallback", None), ("project-fallback", 0)],
)
def test_physical_query_rejects_invalid_scheduling_metadata(
    group: str | None, limit: int | None
) -> None:
    with pytest.raises(ValueError, match="scheduling"):
        PhysicalQuery(
            ProviderRef("recording"),
            "invalid",
            scheduling_group=group,
            scheduling_limit=limit,
        )
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `uv run pytest tests/test_query_coordinator.py -k 'scheduling_metadata' -v`

Expected: FAIL because `PhysicalQuery` does not accept scheduling fields.

- [ ] **Step 3: Add speculative scheduling fields**

In `query/models.py`, add fields after `payload` so existing positional construction remains stable:

Add these fields immediately after the existing `payload` field:

```python
scheduling_group: str | None = None
scheduling_limit: int | None = None
speculative: bool = False
```

Add these checks to the existing `__post_init__` before assigning the fingerprint:

```python
if (self.scheduling_group is None) != (self.scheduling_limit is None):
    raise ValueError("scheduling group and limit must be set together")
if self.scheduling_limit is not None and self.scheduling_limit < 1:
    raise ValueError("scheduling limit must be positive")
```

Do not put scheduling fields, `speculative`, or `payload` into `_fingerprint(...)`.

- [ ] **Step 4: Add the generic dependency-resolution protocol hook**

In `query/provider.py`, define a separate optional protocol rather than making every provider implement a new mandatory method:

```python
class QueryDependencyResolver(Protocol):
    def resolve_queries(
        self,
        plan: PhysicalPlan,
        primary_fragments: tuple[ProviderResultFragment, ...],
    ) -> tuple[PhysicalQuery, ...]: ...
```

The returned tuple is the complete set of B queries required by the successful primary fragments. A returned query may match an already-running speculative query by physical fingerprint; otherwise the coordinator starts it dynamically. Providers without this hook keep current behavior.

- [ ] **Step 5: Run model tests and static checks**

Run:

```bash
uv run pytest tests/test_query_coordinator.py -k 'scheduling_metadata' -v
uv run ruff check src/ccusage_viz/query/models.py src/ccusage_viz/query/provider.py tests/test_query_coordinator.py
uv run ty check src/ccusage_viz/query/models.py src/ccusage_viz/query/provider.py
```

Expected: all PASS.

- [ ] **Step 6: Commit the query contracts**

```bash
git add src/ccusage_viz/query/models.py src/ccusage_viz/query/provider.py tests/test_query_coordinator.py
git commit -m "feat: model speculative provider queries"
```

---

### Task 2: Resolve speculative dependencies early and atomically in QueryCoordinator

**Files:**
- Modify: `src/ccusage_viz/query/coordinator.py:20-175`
- Test: `tests/test_query_coordinator.py`

**Interfaces:**
- Consumes: Task 1's `PhysicalQuery.speculative`, scheduling fields, and optional `resolve_queries(...)` hook.
- Produces: `_start_initial(...)`, `_await_primary(...)`, `_await_required(...)`, per-coordinator scheduling semaphores, and one final `provider.assemble(...)` call after all required work succeeds.

- [ ] **Step 1: Write failing tests for speculative failure classification and early detachment**

Create a test provider whose initial plan contains primary A and speculative B. Its resolver returns B only when A says fallback is required:

```python
@dataclass(frozen=True, slots=True)
class ResolvingProvider(RecordingProvider):
    require_fallback: bool = False

    def execute(self, query: PhysicalQuery, cancelled: Event) -> PhysicalResult:
        if query.operation == "fallback-failure":
            raise QueryError("error.ccusage_failed", query=query.operation)
        return PhysicalResult(query, query.operation.encode())

    def resolve_queries(self, plan, primary_fragments):
        return tuple(
            query
            for query in plan.queries
            if query.speculative and self.require_fallback
        )
```

Add these tests:

- `test_irrelevant_speculative_failure_does_not_fail_plan`;
- `test_required_speculative_failure_fails_plan_before_assembly` (instrument `assemble` and assert it is not called);
- `test_slow_irrelevant_speculation_does_not_delay_primary_result` (B blocks, A completes, resolver returns no B, and the plan result settles before B is released).

- [ ] **Step 2: Write a failing test for dynamically discovered shared queries**

Submit two identical plans whose resolver returns the same blocking `PhysicalQuery(..., "fallback")`. Assert both results complete but the provider's fallback execution counter is `1`. This protects physical in-flight sharing for B discovered after A.

- [ ] **Step 3: Write failing concurrency tests**

Use six distinct fallback queries with:

```python
scheduling_group="project-fallback",
scheduling_limit=4,
speculative=True,
```

Track active executions under a lock, block them with an event, and assert maximum observed group activity is exactly `4` when `QueryCoordinator(max_parallel=8)` is used. Add a second test proving A starts while four remembered B queries are active.

- [ ] **Step 4: Run the new coordinator tests and verify failure**

Run:

```bash
uv run pytest tests/test_query_coordinator.py \
  -k 'speculative_failure or dynamically_discovered or scheduling_group or primary_starts' -v
```

Expected: FAIL because optional failures are currently dropped, supplemental work is serial, and no scheduling-group limit exists.

- [ ] **Step 5: Split initial work into primary and speculative futures**

Refactor `_execute_plan` to submit every initial query immediately but partition futures by `query.speculative`. Await all non-speculative futures in plan order, failing immediately on any required primary error. Normalize those results and call `resolve_queries(plan, primary_fragments)` before waiting for speculative futures.

Add `_start_initial(self, executor, run, provider, queries) -> dict[str, tuple[PhysicalQuery, Future[PhysicalResult]]]` and `_await_primary(self, initial) -> tuple[PhysicalResult, ...]`. `_start_initial` submits every query through `_run_one`; `_await_primary` visits the non-speculative entries in plan order and calls `future.result()`.

Key `initial` by `provider.fingerprint(query)` and reject duplicate fingerprints within one plan unless they refer to the same query. For providers without `resolve_queries`, preserve the existing `supplemental_queries(plan, primary_fragments)` compatibility path and existing optional-query behavior.

Do not use an executor context manager here: its implicit `shutdown(wait=True)` would reintroduce a wait for irrelevant speculative B.

- [ ] **Step 6: Reuse required speculation and launch newly required queries concurrently**

For every query returned by `resolve_queries`, look up an initial future by physical fingerprint. If present, await that exact future; a completed speculative failure now becomes fatal without rerunning B. If absent, submit the new query through `_run_one` and await all newly required queries concurrently. Keep normalized required fragments ordered by the returned query tuple.

After required results are collected, cancel pending executor futures and call `executor.shutdown(wait=False, cancel_futures=True)`. `_finish_run` then detaches this plan's remaining subscriptions; shared physical work stays alive while another plan remains subscribed.

This is the boundary between “failed or slow prefetch later proved irrelevant” and “prefetch later proved required.”

- [ ] **Step 7: Enforce scheduling-group limits without weakening sharing**

Add a coordinator-owned lock and semaphore registry:

```python
self._group_lock = Lock()
self._group_limits: dict[tuple[str, int], BoundedSemaphore] = {}
```

Subscribe to `_inflight` before applying the group semaphore so a non-owner can immediately share work already running. Only the owner execution thread acquires both the existing global execution slot and the scheduling-group semaphore. Use a helper:

```python
def _group_slot(self, query: PhysicalQuery) -> BoundedSemaphore | None:
    if query.scheduling_group is None:
        return None
    key = (query.scheduling_group, query.scheduling_limit or 0)
    with self._group_lock:
        return self._group_limits.setdefault(key, BoundedSemaphore(key[1]))
```

Acquire/release it in `_execute_bounded`. Never include group metadata in the `_WorkKey`.

- [ ] **Step 8: Ensure cancellation detaches ignored speculative subscribers**

Do not wait for unrelated speculative work after the primary result and resolver have made it irrelevant. Cancel/detach only this `_PlanRun` subscription through existing `_unsubscribe`/`_detach_run`; `_release` must leave shared work alive while `entry.subscribers > 0`.

Add a regression test with two runs sharing B: one resolver ignores B after A while the other still requires it. Assert the requiring run receives B and the provider does not observe B cancellation.

- [ ] **Step 9: Run coordinator tests**

Run:

```bash
uv run pytest tests/test_query_coordinator.py -v
uv run ruff check src/ccusage_viz/query/coordinator.py tests/test_query_coordinator.py
uv run ty check src/ccusage_viz/query/coordinator.py
```

Expected: all PASS, including existing cancellation and optional-query tests.

- [ ] **Step 10: Commit atomic coordinator execution**

```bash
git add src/ccusage_viz/query/coordinator.py tests/test_query_coordinator.py
git commit -m "feat: resolve speculative queries atomically"
```

---

### Task 3: Learn fallback agents and precompile remembered B queries

**Files:**
- Modify: `src/ccusage_viz/providers/ccusage.py:1-180,332-480`
- Test: `tests/test_ccusage_provider.py`

**Interfaces:**
- Consumes: Task 2's dependency resolver and scheduling metadata.
- Produces: `_FallbackSourceKey`, `_ProjectFallbackMemory`, `_CcusageQueryMetadata`, `_project_fallback_query(...)`, and remembered B queries in project plans.

- [ ] **Step 1: Isolate provider instances in tests**

Add a helper to `tests/test_ccusage_provider.py` so stateful tests never mutate the production singleton or leak state into unrelated tests:

```python
from ccusage_viz.providers.ccusage import CcusageProvider


def provider() -> CcusageProvider:
    return CcusageProvider()
```

Use this helper in every new learned-state test. Existing stateless tests may continue using `CCUSAGE_DEFINITION.provider`.

- [ ] **Step 2: Write failing tests for first discovery and later compilation**

Create a project-ranking intent with a distinct `ProviderRef("ccusage", "source-a")`. Compile once and assert no `project_fallback_sessions:*` query exists. Normalize an A payload containing exceptional `pi` and `future-agent`, call `resolve_queries(plan, (observation_fragment,))`, and assert it returns both fallback queries sorted by agent with:

```python
query.speculative is False
query.scheduling_group == "ccusage-project-fallback"
query.scheduling_limit == 4
```

Compile the next intent for the same source and assert its initial plan contains A plus speculative remembered B queries for both agents.

- [ ] **Step 3: Write failing tests for source isolation and period reuse**

Assert:

- `source-a` remembers agents but `source-b` does not;
- the same source with a new date range precompiles remembered agents using the new `--since/--until` values;
- execution contexts with a different executable or environment do not share memory even when `ProviderRef.source_id` is equal.

Define source identity exactly as:

```python
(provider.source_id, context.executable, context.environment)
```

Timeout and output-limit differences do not define another data source.

- [ ] **Step 4: Write failing tests for dynamic removal and addition**

Seed memory with `pi` and `old-agent`. Feed a later A result containing exceptional `pi` and `new-agent`. Assert resolver behavior:

- requires/uses prefetched Pi B;
- ignores `old-agent` success or failure;
- returns a new required B for `new-agent`;
- next compile includes only `pi` and `new-agent`.

Then feed A with no exceptions and assert the following compile contains A but no B.

- [ ] **Step 5: Run provider memory tests and verify failure**

Run:

```bash
uv run pytest tests/test_ccusage_provider.py \
  -k 'fallback_memory or remembered_fallback or fallback_source or dynamic_fallback' -v
```

Expected: FAIL because the provider has no learned state or initial B compilation.

- [ ] **Step 6: Add focused thread-safe memory types**

In `providers/ccusage.py`, add the following implementation, with `Lock` imported from `threading`:

```python
@dataclass(frozen=True, slots=True)
class _FallbackSourceKey:
    source_id: str | None
    executable: str
    environment: tuple[tuple[str, str], ...]


class _ProjectFallbackMemory:
    def __init__(self) -> None:
        self._lock = Lock()
        self._agents: dict[_FallbackSourceKey, frozenset[str]] = {}

    def agents(self, source: _FallbackSourceKey) -> frozenset[str]:
        with self._lock:
            return self._agents.get(source, frozenset())

    def replace(self, source: _FallbackSourceKey, agents: frozenset[str]) -> None:
        with self._lock:
            if agents:
                self._agents[source] = agents
            else:
                self._agents.pop(source, None)
```

Attach one memory object to each `CcusageProvider` instance using a dataclass field excluded from comparison/repr. Do not use module-global learned state.

- [ ] **Step 7: Tag A and B with provider-private metadata**

Use existing `PhysicalQuery.payload`, which is intentionally outside the fingerprint:

```python
@dataclass(frozen=True, slots=True)
class _CcusageQueryMetadata:
    source: _FallbackSourceKey
    role: Literal["project-observation", "project-fallback"]
    agent: str | None = None
```

Tag only project observation A and fallback B queries. Keep ordinary timeline, Claude project, and Codex queries unchanged.

- [ ] **Step 8: Extract one canonical fallback-query builder**

Implement `_project_fallback_query(observation: PhysicalQuery, source: _FallbackSourceKey, agent: str, *, speculative: bool) -> PhysicalQuery`.

It must derive coverage and `--since/--until` from A, set `required=not speculative`, attach `_CcusageQueryMetadata`, and set:

```python
scheduling_group="ccusage-project-fallback"
scheduling_limit=4
speculative=speculative
```

Use this helper for both remembered initial B and newly discovered B so their command arguments and physical fingerprints are identical.

- [ ] **Step 9: Compile remembered agents into project plans**

During `compile`, compute `_FallbackSourceKey` from the intent. For each project interval, append remembered B queries beside A. Sort agents case-insensitively for deterministic plans. Do not compile learned B for non-project charts or Monitor's Claude-only project mode.

A period switch naturally builds B with the new interval while retaining the learned agent set for this one round.

- [ ] **Step 10: Implement dependency resolution and memory replacement**

Replace ccusage's old `supplemental_queries` behavior with `resolve_queries`:

1. Find A fragments by metadata/provenance.
2. Compute the complete exception set from A records with `SourceKind.UNIFIED_DAILY` and attribution in `{"unassigned", "unverified"}`.
3. Atomically replace learned memory with that exact set before resolving B outcomes.
4. Return one required B query for every current exception agent, using the canonical builder. The coordinator reuses an already-running/completed speculative future with the same physical fingerprint and submits only newly discovered B.
5. Omit removed agents from the returned set, causing the coordinator to detach their speculative work.

Keep a compatibility `supplemental_queries` wrapper only if an existing external test/API requires it; internally it should delegate to the same classifier rather than duplicate policy.

- [ ] **Step 11: Run provider planning tests and planner regressions**

Run:

```bash
uv run pytest tests/test_ccusage_provider.py -v
uv run pytest tests/test_query_planner.py -v
uv run ruff check src/ccusage_viz/providers/ccusage.py tests/test_ccusage_provider.py
uv run ty check src/ccusage_viz/providers/ccusage.py
```

Expected: all PASS.

- [ ] **Step 12: Commit learned fallback planning**

```bash
git add src/ccusage_viz/providers/ccusage.py tests/test_ccusage_provider.py tests/test_query_planner.py
git commit -m "feat: prefetch remembered project fallbacks"
```

---

### Task 4: Directly replace A exceptions with successful normalized B results

**Files:**
- Modify: `src/ccusage_viz/providers/ccusage.py:380-525`
- Modify: `src/ccusage_viz/locales/en.py`
- Modify: `src/ccusage_viz/locales/zh.py`
- Test: `tests/test_ccusage_provider.py`

**Interfaces:**
- Consumes: Task 3's exact current exception set and normalized required B fragments.
- Produces: `_project_fallback_replacement_records(fragments) -> tuple[UsageRecord, ...]`, `error.ccusage_project_fallback_incomplete` only for a missing required fragment, and atomic direct-replacement `assemble` behavior.

- [ ] **Step 1: Write failing direct-replacement tests**

Add tests proving replacement is agent- and observation-local:

1. B records replace corresponding A exception records exactly after normalization.
2. One B is missing: assembly raises `QueryError` with key `error.ccusage_project_fallback_incomplete` and that agent.
3. A B total differing from A succeeds and is retained exactly.
4. B records with an unresolved project remain `Unverified` and succeed.
5. Empty successful B is a valid replacement.
6. Crossed totals in multiple intervals remain associated with their own B observation.

- [ ] **Step 2: Run direct-replacement tests and verify failure**

Run:

```bash
uv run pytest tests/test_ccusage_provider.py \
  -k 'fallback_replacement or missing_required_fallback or crossed_totals' -v
```

Expected: FAIL because the old strict acceptance rules reject mismatched, unresolved, and empty B results.

- [ ] **Step 3: Implement agent- and observation-local direct replacement**

Implement `_project_fallback_replacement_records(fragments)` by indexing B fragments on `(source, revision, observation_id, agent)`. For each A fragment, preserve non-exception records, then append each corresponding B fragment's `records` tuple without modification. Raise `QueryError("error.ccusage_project_fallback_incomplete", agent=agent)` only when that indexed B fragment is absent.

Filter successful speculative B fragments for removed agents before replacement so stale prefetched records are never rendered.

- [ ] **Step 4: Derive the required-agent set during assembly without global refresh state**

In `assemble`, pair each A observation with B fragments by source, revision, observation ID, and agent. Remove each exceptional agent's A records and append the paired B fragment's records unchanged. Do not compare totals or validate project resolution. Raise `error.ccusage_project_fallback_incomplete` only when the required paired B fragment is absent. Do not store per-refresh records or totals in `_ProjectFallbackMemory`.

- [ ] **Step 5: Add localized failure messages**

Add matching keys:

```python
# locales/en.py
"error.ccusage_project_fallback_incomplete": (
    "Project attribution fallback result is missing for agent {agent}."
),

# locales/zh.py
"error.ccusage_project_fallback_incomplete": (
    "缺少代理 {agent} 的项目归属回退结果。"
),
```

Do not add an attribution notice to successful results.

- [ ] **Step 6: Run provider and localization tests**

Run:

```bash
uv run pytest tests/test_ccusage_provider.py tests/test_i18n.py -v
uv run ruff check src/ccusage_viz/providers/ccusage.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_ccusage_provider.py
uv run ty check src/ccusage_viz/providers/ccusage.py
```

Expected: all PASS.

- [ ] **Step 7: Commit direct replacement semantics**

```bash
git add src/ccusage_viz/providers/ccusage.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_ccusage_provider.py
git commit -m "fix: accept successful project fallback results"
```

---

### Task 5: Prove component-level atomic retention and retry

**Files:**
- Modify: `tests/test_historical_component.py`
- Modify only if a regression is exposed: `src/ccusage_viz/historical_component.py:80-320`

**Interfaces:**
- Consumes: coordinator/provider behavior from Tasks 2–4 and existing `HistoricalChartComponent.fail`/`accept` lifecycle.
- Produces: integration coverage proving no intermediate `Unassigned` snapshot is accepted.

- [ ] **Step 1: Add a scripted ccusage execution fixture**

In `tests/test_historical_component.py`, construct a real `QueryRuntime` with a test `CcusageProvider` whose `execute` method is scripted by operation. Seed the component with an accepted project-ranking snapshot containing `project-a`. On the next generation:

- A returns a large exceptional-agent total;
- required B raises `QueryError`;
- the submission result raises;
- call the normal component `fail(...)` path.

Assert identity/equality of `chart.snapshot`, `chart.model`, `accepted_options`, and `accepted_at` with their pre-refresh values, and assert no accepted ranking entry is `Unassigned`.

- [ ] **Step 2: Add successful retry coverage**

First prove a successful B with a mismatched total completes and is accepted atomically. Separately fail a required B command and assert the exact old state is retained, then retry with a successful B and assert the old snapshot is replaced in one operation. Assert there is no accepted revision containing A-only `Unassigned` data.

- [ ] **Step 3: Add period-switch cleanup coverage**

After learning an exception in one date range, configure another range. Assert the first refresh in the new range prefetches remembered B. Script A with no exception, allow prefetched B to fail, and assert the refresh succeeds from A. Compile/submit once more and assert no B command is called.

- [ ] **Step 4: Run component integration tests**

Run:

```bash
uv run pytest tests/test_historical_component.py \
  -k 'project_fallback or unassigned or period_switch' -v
```

Expected: PASS. If existing component behavior already retains the prior snapshot, do not edit `historical_component.py`.

- [ ] **Step 5: Run all focused project-query tests**

Run:

```bash
uv run pytest \
  tests/test_query_coordinator.py \
  tests/test_ccusage_provider.py \
  tests/test_query_planner.py \
  tests/test_historical_component.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit integration coverage**

```bash
git add tests/test_historical_component.py
# Add src/ccusage_viz/historical_component.py only if the tests required a production fix.
git commit -m "test: cover atomic project fallback refresh"
```

---

### Task 6: Full validation and live ccusage acceptance

**Files:**
- Modify only for defects exposed by validation: files already listed in Tasks 1–5.

**Interfaces:**
- Consumes: complete implementation.
- Produces: verified formatting, typing, full regression coverage, and local behavioral evidence.

- [ ] **Step 1: Run formatting and lint checks**

Run:

```bash
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check src
```

Expected: all PASS. Fix only issues introduced by this feature.

- [ ] **Step 2: Run the full test suite**

Run: `uv run pytest`

Expected: all PASS. If unrelated baseline failures exist, record the exact test names and verify the focused suites from Task 5 still pass; do not weaken assertions to hide them.

- [ ] **Step 3: Verify first-round local replacement**

Run a project ranking for a range containing Pi usage with query diagnostics enabled by the project's existing mechanism. Verify:

- A executes first when provider memory is empty;
- discovered exception B commands fan out immediately;
- the displayed result contains attributed projects rather than a temporary 1.1B `Unassigned` row;
- interrupting/failing required B retains the previous rendering and surfaces `error.ccusage_project_fallback_incomplete` or the original command error.

Do not inspect or print session transcript content; inspect only command names, agent IDs, totals, and project locator metadata already used by ccuv.

- [ ] **Step 4: Verify learned prefetch and cleanup**

Within the same ccuv process:

1. Refresh the same range and verify A and remembered B start concurrently.
2. Open multiple equivalent panes and verify identical A/B fingerprints execute once while in flight.
3. Switch to a period where an agent is no longer exceptional; verify one speculative round may occur.
4. Refresh again and verify the removed agent's B is absent.

- [ ] **Step 5: Review the final diff for scope and accidental files**

Run:

```bash
git diff --check HEAD~4..HEAD
git status --short
git diff --stat HEAD~4..HEAD
```

Confirm no unrelated untracked document or pre-existing user change was staged.

- [ ] **Step 6: Commit validation fixes if needed**

If validation required code changes:

Stage only validation fixes within the feature's known files, then commit:

```bash
git add src/ccusage_viz/query/models.py src/ccusage_viz/query/provider.py \
  src/ccusage_viz/query/coordinator.py src/ccusage_viz/providers/ccusage.py \
  src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py \
  tests/test_query_coordinator.py tests/test_ccusage_provider.py \
  tests/test_query_planner.py tests/test_historical_component.py
git commit -m "fix: harden project fallback prefetch"
```

If no fixes were required, do not create an empty commit.
