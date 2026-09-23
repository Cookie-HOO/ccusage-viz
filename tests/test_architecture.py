from __future__ import annotations

import ast
from dataclasses import fields, replace
from pathlib import Path

from ccusage_viz.bootstrap import build_chart_registry
from ccusage_viz.configuration import default_pane, standalone_from_pane
from ccusage_viz.options import (
    DENSITIES,
    ChartPresentation,
    DashboardHostConfig,
    DashboardLaunch,
    ProcessConfig,
)

PACKAGE_ROOT = Path(__file__).parents[1] / "src" / "ccusage_viz"


def _forbidden_imports(root: Path, forbidden_imports: set[str]) -> list[str]:
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            imported = (
                tuple(alias.name for alias in node.names)
                if isinstance(node, ast.Import)
                else tuple(
                    ".".join(filter(None, (node.module, alias.name))) for alias in node.names
                )
                if isinstance(node, ast.ImportFrom)
                else ()
            )
            for module in imported:
                if any(
                    module == forbidden or module.startswith(f"{forbidden}.")
                    for forbidden in forbidden_imports
                ):
                    violations.append(f"{path.name}: {module}")
    return violations


def test_chart_registry_contains_only_the_four_presentation_charts() -> None:
    registry = build_chart_registry()

    assert [definition.chart_id for definition in registry] == [
        "timeline",
        "calendar",
        "stack",
        "ranking",
    ]
    assert not any(
        isinstance(node, ast.ClassDef) and node.name == "MonitorDefinition"
        for path in (PACKAGE_ROOT / "charts").rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text()))
    )


def test_density_contract_is_three_state_and_pane_owned() -> None:
    assert DENSITIES == ("minimal", "compact", "full")
    assert "standard" not in DENSITIES
    assert ChartPresentation().density == "full"
    assert "density" not in {field.name for field in fields(DashboardHostConfig)}

    dashboard = DashboardLaunch(ProcessConfig(), DashboardHostConfig(), ())
    pane = default_pane("timeline", dashboard=dashboard)

    assert pane.chart.presentation.density == "compact"
    assert standalone_from_pane(dashboard, pane).chart.presentation == pane.chart.presentation


def test_dashboard_globals_do_not_rewrite_pane_presentation() -> None:
    dashboard = DashboardLaunch(
        ProcessConfig(),
        DashboardHostConfig(theme="nord", style="accent", header_style="compact"),
        (),
    )
    pane = default_pane("ranking", dashboard=dashboard)
    presentation = ChartPresentation(
        theme="dracula",
        style="dot",
        legend="inside",
        density="minimal",
    )
    pane = replace(pane, chart=replace(pane.chart, presentation=presentation))

    assert standalone_from_pane(dashboard, pane).chart.presentation == presentation


def test_query_package_does_not_import_host_or_presentation_layers() -> None:
    assert (
        _forbidden_imports(
            PACKAGE_ROOT / "query",
            {
                "ccusage_viz.cli",
                "ccusage_viz.options",
                "ccusage_viz.render",
                "ccusage_viz.tui",
                "ccusage_viz.watch",
            },
        )
        == []
    )


def test_chart_catalog_does_not_import_hosts_or_data_adapters() -> None:
    assert (
        _forbidden_imports(
            PACKAGE_ROOT / "charts",
            {
                "ccusage_viz.acquisition",
                "ccusage_viz.application",
                "ccusage_viz.cli",
                "ccusage_viz.dependency",
                "ccusage_viz.monitor",
                "ccusage_viz.providers",
                "ccusage_viz.query",
                "ccusage_viz.terminal",
                "ccusage_viz.tui",
                "ccusage_viz.watch",
            },
        )
        == []
    )


def test_providers_do_not_import_monitor_or_presentation_layers() -> None:
    assert (
        _forbidden_imports(
            PACKAGE_ROOT / "providers",
            {
                "ccusage_viz.chart_models",
                "ccusage_viz.monitor",
                "ccusage_viz.monitor_component",
                "ccusage_viz.processing.monitor",
                "ccusage_viz.render",
            },
        )
        == []
    )


def test_renderers_do_not_import_monitor_runtime_or_data_adapters() -> None:
    assert (
        _forbidden_imports(
            PACKAGE_ROOT / "render",
            {
                "ccusage_viz.monitor",
                "ccusage_viz.monitor_component",
                "ccusage_viz.processing.monitor",
                "ccusage_viz.providers",
                "ccusage_viz.query",
            },
        )
        == []
    )


def test_monitor_hosts_do_not_import_the_removed_query_client() -> None:
    for name in ("monitor.py", "tui.py"):
        assert (
            _forbidden_imports(
                PACKAGE_ROOT / name,
                {"ccusage_viz.query.client"},
            )
            == []
        )
    assert not (PACKAGE_ROOT / "query" / "client.py").exists()


def test_dashboard_composes_notices_inside_their_source_panes() -> None:
    source = (PACKAGE_ROOT / "tui.py").read_text()

    assert "def _local_pane_content(" in source
    assert "_local_pane_content(" in source[source.index("def run_tui(") :]
    assert "def _unique_notices(" not in source


def test_historical_component_owns_incremental_comparison_state() -> None:
    tree = ast.parse((PACKAGE_ROOT / "historical_component.py").read_text())
    component = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "HistoricalChartComponent"
    )
    slots = next(
        node.value
        for node in component.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__slots__" for target in node.targets
        )
    )
    assert isinstance(slots, ast.Tuple)
    slot_names = {element.value for element in slots.elts if isinstance(element, ast.Constant)}
    methods = {
        node.name
        for node in component.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert {"snapshot", "supplemental_error"} <= slot_names
    assert {"required_coverage", "missing_comparison_coverage"} <= methods


def test_dashboard_panes_do_not_mirror_component_business_state() -> None:
    tree = ast.parse((PACKAGE_ROOT / "tui.py").read_text())
    pane = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "TuiPane"
    )
    fields = {
        target.id
        for statement in pane.body
        if isinstance(statement, ast.AnnAssign)
        and isinstance((target := statement.target), ast.Name)
    }

    assert fields.isdisjoint(
        {
            "options",
            "snapshot",
            "observer",
            "error",
            "generation",
            "render_revision",
            "accepted_options",
            "submitted_generation",
            "submitted_options",
            "requested_options",
            "rebaseline_pending",
            "value_changes",
            "rank_changes",
        }
    )


def test_async_hosts_own_operations_through_the_shared_lifecycle() -> None:
    for name, owners in {
        "watch.py": ("standalone",),
        "monitor.py": ("standalone:monitor",),
        "tui.py": ("dashboard:header",),
    }.items():
        source = (PACKAGE_ROOT / name).read_text()
        assert "LifecycleCoordinator(" not in source
        assert "LifecycleOperation(" in source
        assert "take_completed(" in source
        assert all(owner in source for owner in owners)

    tui = ast.parse((PACKAGE_ROOT / "tui.py").read_text())
    host_fields = {
        class_name: {
            target.id
            for node in tui.body
            if isinstance(node, ast.ClassDef) and node.name == class_name
            for statement in node.body
            if isinstance(statement, ast.AnnAssign)
            and isinstance((target := statement.target), ast.Name)
        }
        for class_name in ("TuiPane", "DashboardHeader")
    }
    forbidden = {
        "future",
        "operation",
        "submission",
        "token",
        "submitted_generation",
        "submitted_options",
        "requested_options",
    }
    assert host_fields["TuiPane"].isdisjoint(forbidden)
    assert host_fields["DashboardHeader"].isdisjoint(forbidden)


def test_monitor_demo_bootstrap_is_the_only_submit_outside_operation_starters() -> None:
    allowed_starters = {"start", "start_pane_submission", "_await_monitor_warmup"}
    direct_submissions: list[tuple[str, str, int]] = []

    class SubmitVisitor(ast.NodeVisitor):
        def __init__(self, name: str) -> None:
            self.name = name
            self.functions: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.functions.append(node.name)
            self.generic_visit(node)
            self.functions.pop()

        def visit_Call(self, node: ast.Call) -> None:
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "submit"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "component"
                and self.functions[-1] not in allowed_starters
            ):
                direct_submissions.append((self.name, self.functions[-1], node.lineno))
            self.generic_visit(node)

    for name in ("monitor.py", "tui.py", "watch.py"):
        SubmitVisitor(name).visit(ast.parse((PACKAGE_ROOT / name).read_text()))

    assert [(name, function) for name, function, _line in direct_submissions] == [
        ("monitor.py", "run_monitor")
    ]
    monitor_source = (PACKAGE_ROOT / "monitor.py").read_text()
    assert "if options.host.demo_size:" in monitor_source
    assert "component.submit(QueryTrigger.STARTUP, sample_ordinal=ordinal)" in monitor_source
    assert "detect_gap=False" in monitor_source


def test_hosts_compose_complete_frames_and_only_painter_writes_rows() -> None:
    terminal = (PACKAGE_ROOT / "terminal.py").read_text()
    assert "class Frame:" in terminal
    assert "class FramePainter:" in terminal
    assert "def paint_status" not in terminal

    for name in ("monitor.py", "tui.py", "watch.py"):
        source = (PACKAGE_ROOT / name).read_text()
        assert "compose_frame(" in source
        assert "paint_status(" not in source


def test_reusable_historical_views_do_not_import_watch_host() -> None:
    violations = _forbidden_imports(PACKAGE_ROOT, {"ccusage_viz.watch"})

    assert [
        violation
        for violation in violations
        if violation.split(":", 1)[0] in {"data_view.py", "historical_render.py", "tui.py"}
    ] == []


def test_processing_package_does_not_import_runtime_or_adapter_layers() -> None:
    assert (
        _forbidden_imports(
            PACKAGE_ROOT / "processing",
            {
                "ccusage_viz.monitor",
                "ccusage_viz.providers",
                "ccusage_viz.query",
                "ccusage_viz.render",
                "ccusage_viz.terminal",
                "ccusage_viz.tui",
                "ccusage_viz.watch",
            },
        )
        == []
    )
