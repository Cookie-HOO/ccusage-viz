from __future__ import annotations

import ast
from pathlib import Path

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
                    ".".join(filter(None, (node.module, alias.name)))
                    for alias in node.names
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


def test_query_package_does_not_import_host_or_presentation_layers() -> None:
    assert _forbidden_imports(
        PACKAGE_ROOT / "query",
        {
            "ccusage_viz.cli",
            "ccusage_viz.options",
            "ccusage_viz.render",
            "ccusage_viz.tui",
            "ccusage_viz.watch",
        },
    ) == []


def test_chart_catalog_does_not_import_hosts_or_data_adapters() -> None:
    assert _forbidden_imports(
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
    ) == []


def test_dashboard_panes_do_not_mirror_historical_component_state() -> None:
    tree = ast.parse((PACKAGE_ROOT / "tui.py").read_text())
    pane = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "TuiPane"
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
            "error",
            "generation",
            "submitted_generation",
            "submitted_options",
            "requested_options",
        }
    )


def test_processing_package_does_not_import_runtime_or_adapter_layers() -> None:
    assert _forbidden_imports(
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
    ) == []
