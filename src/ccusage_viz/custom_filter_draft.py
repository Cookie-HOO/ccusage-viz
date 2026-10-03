"""Interactive capability-backed drafts for custom-command filters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from ccusage_viz.custom_models import CustomFilter
from ccusage_viz.formatting import clip_width
from ccusage_viz.i18n import Translator
from ccusage_viz.options import CustomFilters


@dataclass(frozen=True, slots=True)
class CustomFilterDraft:
    filters: CustomFilters
    filter_index: int = 0
    option_index: int = 0

    def current_filter(self, choices: tuple[CustomFilter, ...]) -> CustomFilter | None:
        if not choices:
            return None
        return choices[self.filter_index % len(choices)]

    def move_filter(self, step: int, choices: tuple[CustomFilter, ...]) -> CustomFilterDraft:
        return replace(
            self,
            filter_index=(self.filter_index + step) % max(1, len(choices)),
            option_index=0,
        )

    def move_option(self, step: int, choices: tuple[CustomFilter, ...]) -> CustomFilterDraft:
        current = self.current_filter(choices)
        count = len(current.options) if current is not None else 0
        return replace(self, option_index=(self.option_index + step) % max(1, count))

    def selected(self, filter_id: str) -> tuple[str, ...]:
        return dict(self.filters).get(filter_id, ())

    def toggle(self, filter_id: str, option_id: str) -> CustomFilterDraft:
        selected = self.selected(filter_id)
        updated = tuple(value for value in selected if value != option_id)
        if len(updated) == len(selected):
            updated = (*selected, option_id)
        values = dict(self.filters)
        if updated:
            values[filter_id] = updated
        else:
            values.pop(filter_id, None)
        return replace(self, filters=tuple(sorted(values.items())))


def run_custom_filter_editor(
    filters: CustomFilters,
    choices: tuple[CustomFilter, ...],
    translator: Translator,
    *,
    width: int,
    paint: Callable[[str, str], None],
    read_key: Callable[[], str | None],
) -> CustomFilters | None:
    """Edit the protocol-declared filters without discovering local values."""

    draft = CustomFilterDraft(filters)
    while True:
        paint(
            _render_custom_filter_draft(draft, choices, translator, width),
            translator.text("status.filter_controls"),
        )
        key = read_key()
        if key == "\x03":
            raise KeyboardInterrupt
        if key == "\x1b":
            return None
        if key in {"\r", "\n"}:
            return draft.filters
        if key in {"h", "\x1b[D"}:
            draft = draft.move_filter(-1, choices)
        elif key in {"l", "\x1b[C", "\t"}:
            draft = draft.move_filter(1, choices)
        elif key in {"k", "\x1b[A"}:
            draft = draft.move_option(-1, choices)
        elif key in {"j", "\x1b[B"}:
            draft = draft.move_option(1, choices)
        elif key == " ":
            current = draft.current_filter(choices)
            if current is not None and current.options:
                option = current.options[draft.option_index % len(current.options)]
                draft = draft.toggle(current.id, option.id)


def _localized(value: object, translator: Translator) -> str:
    return getattr(value, "zh_cn" if translator.language == "zh" else "en")


def _render_custom_filter_draft(
    draft: CustomFilterDraft,
    choices: tuple[CustomFilter, ...],
    translator: Translator,
    width: int,
) -> str:
    current = draft.current_filter(choices)
    tabs = " · ".join(
        f"[{_localized(choice.label, translator)}]"
        if choice == current
        else _localized(choice.label, translator)
        for choice in choices
    )
    if current is None:
        return translator.text("status.custom_filter_unavailable")
    selected = set(draft.selected(current.id))
    rows = "\n".join(
        clip_width(
            f"{'›' if index == draft.option_index % len(current.options) else ' '} "
            f"{'[x]' if option.id in selected else '[ ]'} {_localized(option.label, translator)}",
            width,
        )
        for index, option in enumerate(current.options)
    )
    return "\n".join(part for part in (clip_width(tabs, width), rows) if part)
