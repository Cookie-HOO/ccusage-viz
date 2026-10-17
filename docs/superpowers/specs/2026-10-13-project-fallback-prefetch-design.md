# Project Fallback Prefetch and Atomic Refresh Design

## Goal

Prevent project charts from temporarily replacing a valid prior view with a large
`Unassigned` bucket when an agent requires a second session query for project
attribution. Preserve efficient in-flight query sharing, learn which agents need
fallback queries, and prefetch those queries on later refreshes without wasting
resources indefinitely after the primary source starts providing attribution.

## Scope

This change applies to ccusage project queries that use
`daily --by-agent` as the primary agent observation and issue an agent-specific
`session` query when that observation cannot assign an agent's usage to projects.
It is not specific to Pi. Any agent for which the provider produces a project
fallback query participates in the same behavior.

The change does not add a CLI option or persisted configuration. Learned fallback
state exists only for the lifetime of the ccuv process.

## Query roles

- **A — primary observation:** `daily --by-agent`, queried for the selected date
  range. A determines which agents currently require project fallback attribution.
- **B — agent fallback:** an agent-specific `session` query for one exception
  agent. A successful, normalized B provides the complete replacement records for
  that agent and observation, including empty results and `Unverified` records.

A project refresh is accepted only as one complete logical result. The UI never
accepts A as an intermediate rendering while required B queries are still pending.

## Learned fallback state

The ccusage provider keeps a thread-safe, process-local set of remembered fallback
agents for each ccusage source identity. The state is shared by requests using the
same source so later Dashboard panes and standalone refreshes can benefit from the
observation, but it must not leak between distinct configured sources.

The set is dynamic:

- An agent is added when A shows that the agent requires a fallback query.
- An agent remains remembered while later A results still classify it as an
  exception.
- An agent is removed as soon as a later A result no longer requires fallback
  attribution for that agent.
- If A contains no exception agents, the remembered set becomes empty. The next
  refresh submits A alone.
- Date-range or period changes reuse the current set for one speculative prefetch
  round. The new A result then removes agents that do not need fallback in the new
  range. This bounds unnecessary work to one refresh after the change.

The memory records only agent identifiers, never usage results, project paths, or
session content.

## First refresh without learned agents

When no fallback agents are remembered:

1. Submit A through the normal QueryCoordinator path.
2. Identical in-flight A queries participate in existing physical-query sharing.
3. Normalize A and determine the complete set of exception agents.
4. Add those agents to learned state.
5. Immediately submit all corresponding B queries, with no more than four B
   executions active at once.
6. Normalize every required B and replace its corresponding A exception records
   directly with B's normalized records.
7. Atomically assemble and deliver the complete provider result.

Because B cannot be known before A returns, these queries are supplemental rather
than members of the initial physical plan. They do not receive advance plan-level
sharing. They still use the existing physical-query in-flight sharing mechanism:
if concurrent requests happen to submit the same B fingerprint at the same time,
only one physical command executes.

## Later refresh with learned agents

When one or more fallback agents are remembered, compile the initial physical plan
with A and one speculative B for every remembered agent. A and these B queries
start concurrently, subject to execution limits, and identical physical queries
participate in normal in-flight sharing across panes and requests.

After A completes, classify each agent:

- **Remembered and still exceptional:** its prefetched B is required. Wait for it,
  normalize it, and use it to replace that observation's A exception records.
- **Remembered but no longer exceptional:** its prefetched B is irrelevant. Ignore
  its result or failure, remove the agent from learned state, and do not issue it
  next refresh.
- **Newly exceptional:** add it to learned state and immediately submit a
  supplemental B. It has the same opportunistic physical-query sharing as a
  first-refresh B.

The set update uses the exception set from the latest successful A classification,
even if a subsequently required B fails. This allows the next retry to prefetch the
right agents instead of repeating an avoidable serial discovery step.

## Concurrency

Agent fallback work has a fixed internal maximum concurrency of four. This limit
is not configurable and applies across the B queries belonging to a refresh.

The existing QueryCoordinator execution limit remains the final process safety
limit. The fallback limit does not create independent unbounded execution capacity:
it only ensures that a refresh never attempts to fan out more than four active B
queries at once. A and unrelated required queries continue to use their existing
coordinator scheduling and sharing semantics.

The implementation must avoid waiting for irrelevant speculative B work after A
has established that its agent no longer needs fallback. Cancellation is permitted
when it cannot detach another subscriber from shared work; otherwise the refresh
simply detaches its subscription and ignores that B.

## Atomic acceptance and failures

A, plus every B that the completed A identifies as necessary, forms one atomic
refresh result.

- A failure fails the refresh.
- A required B command failure, timeout, malformed response, or normalization
  failure fails the refresh before assembly. The owning component retains its
  previously accepted snapshot and rendering.
- The provider must not degrade a failed required B to A's `Unassigned` aggregate.
- A speculative B failure is held provisionally until A classifies its agent. It
  fails the refresh only if A confirms that B is required.
- A speculative B for an agent that A no longer classifies as exceptional is
  irrelevant; its failure does not fail the refresh.
- If assembly is invoked without a required normalized B fragment, it raises the
  internal incomplete-result error. This is the only incomplete assembly case.

Successful B normalization is authoritative for replacement. Assembly removes the
corresponding A exception records and inserts B records exactly as normalized. It
performs no token-total equality check and does not require every B record to have
a resolved project. `Unverified` B records are retained, and an empty successful B
validly replaces the A exception records with no records.

This atomicity is at provider-result acceptance, not at process execution. A and B
commands may finish in any order, but consumers observe either the prior accepted
snapshot or the complete new snapshot.

## Query sharing semantics

Physical-query sharing remains keyed by the existing provider fingerprint.

- First discovery A participates in sharing.
- B discovered only after A is supplemental and therefore cannot be part of the
  initial plan, but concurrent identical supplemental B submissions can still
  share an in-flight physical command.
- Once an agent is remembered, its B is compiled into later initial plans and can
  participate in sharing from the beginning of the refresh.
- Detaching an irrelevant speculative B must preserve work that still has another
  subscriber.

Learned state must not become part of A's physical fingerprint. The same A command
continues to coalesce regardless of which caller has already learned exception
agents.

## Component responsibilities

### ccusage provider

- Classify A records into the current exception-agent set.
- Own thread-safe learned fallback state scoped by source identity.
- Compile remembered B queries into subsequent initial plans.
- Describe supplemental B queries for newly discovered agents.
- Mark which prefetched results are required after A is known.
- Directly replace each observation's exception records with its successful,
  normalized B records.
- Raise the internal incomplete-result error only when a required B fragment is
  missing during assembly; otherwise assemble the complete atomic result.

### QueryCoordinator

- Continue to share identical in-flight physical queries.
- Execute initial A and remembered B work concurrently.
- Support the provider's dynamic supplemental B fan-out with a fixed limit of four.
- Preserve optional speculative failures until the provider can determine whether
  they are required.
- Detach ignored speculative work without cancelling another subscriber's query.

Provider-specific classification and replacement must remain outside the generic
coordinator. The coordinator supplies scheduling, sharing, cancellation, and result
collection; the provider supplies dependency decisions.

### Consumers

Historical components, Dashboard panes, and standalone views keep their existing
generation-safe acceptance behavior. They receive no partial attribution state and
require no Pi- or agent-specific logic.

## Tests

Provider tests cover:

- first A discovery records every exception agent;
- all newly discovered B queries are issued and directly replace corresponding A
  exception records after successful normalization;
- required B execution or normalization failure rejects the whole refresh;
- remembered agents are compiled into the next initial plan;
- a new exception discovered alongside remembered agents receives a supplemental B;
- an agent absent from A's new exception set is removed;
- an irrelevant prefetched B failure does not reject the refresh;
- an empty exception set clears learned state;
- source identities do not share learned agents;
- learned state is safe under concurrent compilation and completion.

Coordinator tests cover:

- first-discovery A retains existing in-flight sharing;
- concurrent identical supplemental B queries retain physical-query sharing;
- later A and remembered B queries start concurrently;
- no more than four B queries for one refresh execute concurrently;
- a speculative failure becomes fatal only when A confirms the dependency;
- ignored speculative work detaches without cancelling another subscriber;
- required failure settles the logical refresh without publishing a partial result.

Integration/component tests cover:

- a previously rendered project ranking remains unchanged when required fallback
  execution or normalization fails;
- a successful retry atomically replaces the old snapshot with normalized B
  records, including unresolved or empty results;
- no intermediate `Unassigned` rendering is accepted;
- switching period can reuse remembered agents for one round and then stop querying
  agents that the new A result no longer classifies as exceptions.

## Acceptance criteria

1. Consumers never observe A as an intermediate project result while required B
   attribution is pending.
2. A required fallback execution or normalization failure retains the previously
   accepted view; a successful normalized B is accepted without total or project-
   resolution validation.
3. Every exception agent, not only Pi, is learned and prefetched on later refreshes.
4. Learned agents are removed when A no longer requires their fallback.
5. First-discovery A and all later initial A/B physical queries retain normal
   in-flight sharing.
6. Dynamically discovered B queries retain opportunistic physical-query sharing.
7. At most four B queries for a refresh are active concurrently.
8. A period change wastes at most one prefetch round for agents no longer needed.
9. No user-facing configuration or persisted state is added.
