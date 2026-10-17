from __future__ import annotations

import sys
import time
from threading import Event, Lock

import pytest

from ccusage_viz.errors import QueryError
from ccusage_viz.providers.ccusage_definition import CCUSAGE_DEFINITION
from ccusage_viz.providers.demo import DEMO_DEFINITION
from ccusage_viz.query.coordinator import QueryCoordinator
from ccusage_viz.query.models import (
    ExecutionContext,
    PhysicalPlan,
    PhysicalQuery,
    ProviderRef,
)
from ccusage_viz.query.provider import ProviderDefinition

from .helpers import RecordingProvider


def test_ccusage_execution_honors_environment_and_output_limit() -> None:
    provider = CCUSAGE_DEFINITION.provider
    context = ExecutionContext(
        sys.executable,
        2,
        128,
        (("CCUSAGE_TEST_VALUE", "visible"),),
    )
    query = PhysicalQuery(
        ProviderRef("ccusage"),
        "unified_daily",
        ("-c", "import os; print(os.environ['CCUSAGE_TEST_VALUE'])"),
        context,
    )
    result = provider.execute(query, Event())
    assert result.payload == b"visible\n"

    oversized = PhysicalQuery(
        ProviderRef("ccusage"),
        "unified_daily",
        ("-c", "print('x' * 129)"),
        context,
    )
    with pytest.raises(QueryError) as caught:
        provider.execute(oversized, Event())
    assert caught.value.key == "error.ccusage_output_limit"


def test_scheduling_group_registry_is_process_wide() -> None:
    provider = RecordingProvider([], Lock(), Event(), Event())
    first = PhysicalQuery(
        provider.provider, "one", scheduling_group="global-limit-conflict", scheduling_limit=1
    )
    second = PhysicalQuery(
        provider.provider, "two", scheduling_group="global-limit-conflict", scheduling_limit=2
    )
    first_handle = QueryCoordinator().submit(PhysicalPlan("first", (first,)), provider)
    assert provider.started.wait(1)
    second_handle = QueryCoordinator().submit(PhysicalPlan("second", (second,)), provider)
    with pytest.raises(ValueError, match="conflicting scheduling limits"):
        second_handle.result(1)
    provider.release.set()
    assert first_handle.result(1).records


def test_ccusage_execution_bounds_stderr_and_times_out_pipe_holding_descendants() -> None:
    provider = CCUSAGE_DEFINITION.provider
    context = ExecutionContext(sys.executable, 0.2, 1024)
    noisy = PhysicalQuery(
        ProviderRef("ccusage"),
        "unified_daily",
        ("-c", "import os,sys; os.write(2, b'x' * 100000); sys.exit(7)"),
        context,
    )
    with pytest.raises(QueryError) as caught:
        provider.execute(noisy, Event())
    assert caught.value.key == "error.ccusage_failed"
    assert len(caught.value.values["stderr"]) == 16 * 1024

    if sys.platform != "win32":
        descendant = PhysicalQuery(
            ProviderRef("ccusage"),
            "unified_daily",
            ("-c", "import os,time; os.fork() and exit(); time.sleep(5)"),
            context,
        )
        started = time.monotonic()
        with pytest.raises(QueryError) as caught:
            provider.execute(descendant, Event())
        assert caught.value.key == "error.ccusage_timeout"
        assert time.monotonic() - started < 2


def test_registry_definitions_are_fully_executable() -> None:
    for definition in (CCUSAGE_DEFINITION, DEMO_DEFINITION):
        assert isinstance(definition, ProviderDefinition)
        assert callable(definition.provider.execute)
        assert callable(definition.provider.normalize)
        assert callable(definition.provider.assemble)
