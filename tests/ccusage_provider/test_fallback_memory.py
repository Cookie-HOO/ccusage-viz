from datetime import date

from ccusage_viz.providers.ccusage import CcusageProvider
from ccusage_viz.query.models import PhysicalResult, ProviderRef

from .helpers import _observation, observation_payload, project_intent


def test_fallback_memory_learns_and_prefetches_with_preserved_source() -> None:
    provider = CcusageProvider()
    plan = provider.compile(project_intent(source_id="workspace-a"))
    assert not any(query.operation.startswith("project_fallback") for query in plan.queries)
    observation = _observation(plan)
    fragment = provider.normalize(
        PhysicalResult(observation, observation_payload("pi", "future-agent"))
    )

    required = provider.resolve_queries(plan, (fragment,))

    assert [query.arguments[0] for query in required] == ["future-agent", "pi"]
    assert all(query.provider == ProviderRef("ccusage", "workspace-a") for query in required)
    assert all(query.required and not query.speculative for query in required)
    assert all(query.scheduling_group == "ccusage-project-fallback" for query in required)
    assert all(query.scheduling_limit == 4 for query in required)
    next_plan = provider.compile(project_intent(source_id="workspace-a"))
    speculative = [q for q in next_plan.queries if q.operation.startswith("project_fallback")]
    assert [query.arguments[0] for query in speculative] == ["future-agent", "pi"]
    assert all(not query.required and query.speculative for query in speculative)
    assert [query.fingerprint for query in speculative] == [query.fingerprint for query in required]


def test_fallback_memory_isolates_source_executable_and_environment_digest() -> None:
    provider = CcusageProvider()
    seeded = provider.compile(
        project_intent(source_id="a", executable="one", environment=(("TOKEN", "secret"),))
    )
    provider.resolve_queries(
        seeded,
        (provider.normalize(PhysicalResult(_observation(seeded), observation_payload("pi"))),),
    )

    same = provider.compile(
        project_intent(source_id="a", executable="one", environment=(("TOKEN", "secret"),))
    )
    assert any(query.operation.endswith(":pi") for query in same.queries)
    for isolated in (
        project_intent(source_id="b", executable="one", environment=(("TOKEN", "secret"),)),
        project_intent(source_id="a", executable="two", environment=(("TOKEN", "secret"),)),
        project_intent(source_id="a", executable="one", environment=(("TOKEN", "other"),)),
    ):
        assert not any(
            query.operation.startswith("project_fallback")
            for query in provider.compile(isolated).queries
        )
    metadata = dict(
        provider.normalize(
            PhysicalResult(_observation(same), observation_payload("pi"))
        ).provider_metadata
    )
    assert metadata["ccusage_environment_digest"] != "secret"


def test_fallback_memory_reuses_period_then_adds_removes_and_clears() -> None:
    provider = CcusageProvider()
    first = provider.compile(project_intent())
    provider.resolve_queries(
        first,
        (
            provider.normalize(
                PhysicalResult(_observation(first), observation_payload("pi", "old-agent"))
            ),
        ),
    )
    changed = provider.compile(project_intent(since=date(2026, 2, 1), until=date(2026, 2, 5)))
    fallbacks = [q for q in changed.queries if q.operation.startswith("project_fallback")]
    assert {query.arguments[0] for query in fallbacks} == {"pi", "old-agent"}
    assert all(
        "2026-02-01" in query.arguments and "2026-02-05" in query.arguments for query in fallbacks
    )
    provider.resolve_queries(
        changed,
        (
            provider.normalize(
                PhysicalResult(_observation(changed), observation_payload("pi", "new-agent"))
            ),
        ),
    )
    updated = provider.compile(project_intent())
    assert {
        query.arguments[0]
        for query in updated.queries
        if query.operation.startswith("project_fallback")
    } == {"pi", "new-agent"}
    provider.resolve_queries(
        updated,
        (provider.normalize(PhysicalResult(_observation(updated), observation_payload())),),
    )
    assert not any(
        query.operation.startswith("project_fallback")
        for query in provider.compile(project_intent()).queries
    )


def test_out_of_order_fallback_revision_cannot_overwrite_newer_memory() -> None:
    provider = CcusageProvider()
    older = provider.compile(project_intent())
    newer = provider.compile(project_intent())
    provider.resolve_queries(
        newer,
        (provider.normalize(PhysicalResult(_observation(newer), observation_payload("new"))),),
    )
    provider.resolve_queries(
        older,
        (provider.normalize(PhysicalResult(_observation(older), observation_payload("old"))),),
    )
    latest = provider.compile(project_intent())
    assert [
        query.arguments[0]
        for query in latest.queries
        if query.operation.startswith("project_fallback")
    ] == ["new"]
