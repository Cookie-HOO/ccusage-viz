from __future__ import annotations

import ast
from pathlib import Path

QUERY_ROOT = Path(__file__).parents[1] / "src" / "ccusage_viz" / "query"
FORBIDDEN_QUERY_IMPORTS = {
    "ccusage_viz.cli",
    "ccusage_viz.options",
    "ccusage_viz.render",
    "ccusage_viz.tui",
    "ccusage_viz.watch",
}


def test_query_package_does_not_import_host_or_presentation_layers() -> None:
    violations: list[str] = []
    for path in sorted(QUERY_ROOT.rglob("*.py")):
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
                    for forbidden in FORBIDDEN_QUERY_IMPORTS
                ):
                    violations.append(f"{path.name}: {module}")

    assert violations == []
