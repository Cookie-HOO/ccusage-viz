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
