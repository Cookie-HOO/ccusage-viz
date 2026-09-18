from __future__ import annotations

from collections.abc import Iterator

from ccusage_viz.charts.definition import ChartDefinition


class ChartRegistry:
    """Private deterministic registry populated only by application bootstrap."""

    __slots__ = ("_definitions", "_frozen")

    def __init__(self) -> None:
        self._definitions: dict[str, ChartDefinition] = {}
        self._frozen = False

    @property
    def frozen(self) -> bool:
        return self._frozen

    def register(self, definition: ChartDefinition) -> None:
        if self._frozen:
            raise RuntimeError("chart registry is frozen")
        if definition.chart_id in self._definitions:
            raise ValueError(f"duplicate chart ID: {definition.chart_id}")
        self._definitions[definition.chart_id] = definition

    def freeze(self) -> None:
        self._frozen = True

    def get(self, chart_id: str) -> ChartDefinition:
        try:
            return self._definitions[chart_id]
        except KeyError as exc:
            raise KeyError(f"unknown chart ID: {chart_id}") from exc

    def __iter__(self) -> Iterator[ChartDefinition]:
        return iter(self._definitions.values())

    def __len__(self) -> int:
        return len(self._definitions)
