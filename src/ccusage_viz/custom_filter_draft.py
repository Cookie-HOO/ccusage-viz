"""Interactive capability-backed drafts for custom-command filters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from ccusage_viz.custom_models import CustomFilter, CustomFilterOption
from ccusage_viz.formatting import clip_width, display_width, pad_width
from ccusage_viz.i18n import Translator
from ccusage_viz.options import CustomFilters
from ccusage_viz.tui_input import KeyEvent, MouseEvent, PasteEvent

FilterEditorInput = str | KeyEvent | MouseEvent | PasteEvent


@dataclass(frozen=True, slots=True)
class CustomFilterDraft:
    filters: CustomFilters
    filter_index: int = 0
    option_index: int = 0
    query: str = ""
    search_editing: bool = False
    columns: int = 1
    viewport_row: int = 0

    def current_filter(self, choices: tuple[CustomFilter, ...]) -> CustomFilter | None:
        if not choices:
            return None
        return choices[self.filter_index % len(choices)]

    def move_filter(self, step: int, choices: tuple[CustomFilter, ...]) -> CustomFilterDraft:
        return replace(
            self,
            filter_index=(self.filter_index + step) % max(1, len(choices)),
            option_index=0,
            query="",
            search_editing=False,
            viewport_row=0,
        )

    def move_option(
        self, step: int, choices: tuple[CustomFilter, ...], translator: Translator
    ) -> CustomFilterDraft:
        current = self.current_filter(choices)
        options = _matching_options(current, self.query, translator) if current is not None else ()
        if not options:
            return self
        columns = min(self.columns, len(options))
        current_index = self.option_index % len(options)
        row, column = divmod(current_index, columns)
        final_row = _grid_rows(len(options), columns) - 1
        target_row = min(max(0, row + step), final_row)
        # Preserve the focused column.  A partial final row can only contain
        # cells to its left, so clamp to that row's final actual cell.
        target_index = min(target_row * columns + column, len(options) - 1)
        return replace(self, option_index=target_index)

    def selected(self, filter_id: str) -> tuple[str, ...]:
        return dict(self.filters).get(filter_id, ())

    def toggle(self, choice: CustomFilter, option_id: str) -> CustomFilterDraft:
        selected = self.selected(choice.id)
        if option_id in selected:
            updated = tuple(value for value in selected if value != option_id)
        elif choice.mode == "single_select":
            updated = (option_id,)
        else:
            updated = (*selected, option_id)
        values = dict(self.filters)
        if updated:
            values[choice.id] = updated
        else:
            values.pop(choice.id, None)
        return replace(self, filters=tuple(sorted(values.items())))

    def clear(self, filter_id: str) -> CustomFilterDraft:
        return replace(self, filters=tuple(item for item in self.filters if item[0] != filter_id))

    def cycle_columns(self) -> CustomFilterDraft:
        return replace(self, columns=self.columns % 3 + 1, option_index=0, viewport_row=0)


def run_custom_filter_editor(
    filters: CustomFilters,
    choices: tuple[CustomFilter, ...],
    translator: Translator,
    *,
    width: int,
    height: int = 24,
    paint: Callable[[str, str], None],
    read_key: Callable[[], FilterEditorInput | None],
) -> CustomFilters | None:
    """Edit protocol-declared Dataset filters locally until the draft is applied."""

    draft = CustomFilterDraft(filters)
    while True:
        draft = _normalise_draft(draft, choices, translator, height)
        paint(
            _render_custom_filter_draft(draft, choices, translator, width, height),
            translator.text("status.custom_filter_controls"),
        )
        event = read_key()
        if isinstance(event, MouseEvent):
            if event.pressed and event.button == 0:
                tab_index = _filter_index_at(event, choices, translator, draft.filter_index)
                if tab_index is not None:
                    draft = replace(
                        draft,
                        filter_index=tab_index,
                        option_index=0,
                        query="",
                        search_editing=False,
                        viewport_row=0,
                    )
                    continue
                current = draft.current_filter(choices)
                options = _matching_options(current, draft.query, translator)
                option_index = _option_index_at(event, draft, options, width, height)
                if current is not None and option_index is not None:
                    draft = draft.toggle(current, options[option_index].id)
                    draft = replace(draft, option_index=option_index)
            continue
        key = event.value if isinstance(event, (KeyEvent, PasteEvent)) else event
        if key == "\x03":
            raise KeyboardInterrupt
        if key is None:
            continue
        if draft.search_editing:
            if key == "\x1b":
                draft = replace(draft, query="", search_editing=False, option_index=0, viewport_row=0)
            elif key in {"\r", "\n"}:
                draft = replace(draft, search_editing=False)
            elif key in {"\x7f", "\b"}:
                draft = replace(draft, query=draft.query[:-1], option_index=0, viewport_row=0)
            elif key.isprintable():
                draft = replace(draft, query=draft.query + key, option_index=0, viewport_row=0)
            continue
        if key == "\x1b":
            if draft.query:
                draft = replace(draft, query="", option_index=0, viewport_row=0)
                continue
            return None
        if key in {"\r", "\n"}:
            return draft.filters
        if key == "/":
            draft = replace(draft, search_editing=True)
        elif key in {"h", "\x1b[D"}:
            draft = draft.move_filter(-1, choices)
        elif key in {"l", "\x1b[C", "\t"}:
            draft = draft.move_filter(1, choices)
        elif key in {"k", "\x1b[A"}:
            draft = draft.move_option(-1, choices, translator)
        elif key in {"j", "\x1b[B"}:
            draft = draft.move_option(1, choices, translator)
        elif key == "c":
            current = draft.current_filter(choices)
            if current is not None:
                draft = draft.clear(current.id)
        elif key == "C":
            draft = draft.cycle_columns()
        elif key == " ":
            current = draft.current_filter(choices)
            options = _matching_options(current, draft.query, translator) if current is not None else ()
            if current is not None and options:
                option = options[draft.option_index % len(options)]
                draft = draft.toggle(current, option.id)


def _localized(value: object, translator: Translator) -> str:
    return getattr(value, "zh_cn" if translator.language == "zh" else "en")


def _display_options(choice: CustomFilter) -> tuple[CustomFilterOption, ...]:
    """Keep one selectable option for each Dataset-visible bilingual label."""
    unique: dict[tuple[str, str], CustomFilterOption] = {}
    for option in choice.options:
        unique.setdefault((option.label.en, option.label.zh_cn), option)
    return tuple(unique.values())


def _matching_options(
    choice: CustomFilter | None, query: str, translator: Translator
) -> tuple[CustomFilterOption, ...]:
    """Return visible options whose localized label contains the literal query."""
    if choice is None:
        return ()
    needle = query.casefold()
    return tuple(
        option
        for option in _display_options(choice)
        if not needle or needle in _localized(option.label, translator).casefold()
    )


def filter_tab_counts(
    accepted: CustomFilters, choices: tuple[CustomFilter, ...]
) -> tuple[tuple[int, int], ...]:
    """Return accepted visible selections and visible-option totals for each tab."""

    accepted_values = dict(accepted)
    counts: list[tuple[int, int]] = []
    for choice in choices:
        options = _display_options(choice)
        visible_ids = {option.id for option in options}
        selected = set(accepted_values.get(choice.id, ()))
        counts.append((len(selected & visible_ids), len(options)))
    return tuple(counts)


def _grid_rows(option_count: int, columns: int) -> int:
    columns = max(1, min(3, columns))
    return (option_count + columns - 1) // columns


def _chrome_rows(draft: CustomFilterDraft) -> int:
    return 2 + int(bool(draft.query or draft.search_editing))


def _normalise_draft(
    draft: CustomFilterDraft,
    choices: tuple[CustomFilter, ...],
    translator: Translator,
    height: int,
) -> CustomFilterDraft:
    current = draft.current_filter(choices)
    options = _matching_options(current, draft.query, translator)
    if not options:
        return replace(draft, option_index=0, viewport_row=0)
    option_index = min(draft.option_index, len(options) - 1)
    columns = min(draft.columns, len(options))
    focus_row = option_index // columns
    total_rows = _grid_rows(len(options), columns)
    # Reserve two rows conservatively for the above/below continuation indicators.
    visible_rows = max(1, height - _chrome_rows(draft) - 2)
    maximum_viewport = max(0, total_rows - visible_rows)
    viewport = min(draft.viewport_row, maximum_viewport)
    if focus_row < viewport:
        viewport = focus_row
    elif focus_row >= viewport + visible_rows:
        viewport = focus_row - visible_rows + 1
    return replace(draft, option_index=option_index, viewport_row=viewport)


def _filter_index_at(
    event: MouseEvent,
    choices: tuple[CustomFilter, ...],
    translator: Translator,
    active_index: int,
) -> int | None:
    """Map a click on the first body row to the Dataset filter tab it occupies."""
    if event.y != 1:
        return None
    position = 1
    for index, choice in enumerate(choices):
        label = _localized(choice.label, translator)
        rendered = f"[{label}]" if index == active_index else label
        end = position + display_width(rendered)
        if position <= event.x < end:
            return index
        position = end + len(" · ")
    return None


def _option_index_at(
    event: MouseEvent,
    draft: CustomFilterDraft,
    options: tuple[CustomFilterOption, ...],
    width: int,
    height: int,
) -> int | None:
    """Map a one-based terminal click to its visible option-grid cell."""
    if not options:
        return None
    columns = min(draft.columns, len(options))
    fixed_rows = _chrome_rows(draft)
    total_rows = _grid_rows(len(options), columns)
    capacity = max(0, height - fixed_rows)
    viewport = min(draft.viewport_row, max(0, total_rows - 1))
    show_above = viewport > 0
    visible_capacity = max(0, capacity - int(show_above))
    end = min(total_rows, viewport + visible_capacity)
    show_below = end < total_rows
    if show_below and visible_capacity:
        end -= 1
    first_option_screen_row = fixed_rows + int(show_above) + 1
    grid_row = event.y - first_option_screen_row + viewport
    column_width = max(1, (max(1, width) - (columns - 1)) // columns)
    column = (event.x - 1) // (column_width + 1)
    option_index = grid_row * columns + column
    if not (viewport <= grid_row < end and 0 <= column < columns and option_index < len(options)):
        return None
    return option_index


def _render_custom_filter_draft(
    draft: CustomFilterDraft,
    choices: tuple[CustomFilter, ...],
    translator: Translator,
    width: int,
    height: int = 24,
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

    all_options = _display_options(current)
    options = _matching_options(current, draft.query, translator)
    selected = set(draft.selected(current.id))
    selected_count = sum(option.id in selected for option in all_options)
    rows = [clip_width(tabs, width)]
    if draft.query or draft.search_editing:
        cursor = "_" if draft.search_editing else ""
        rows.append(clip_width(translator.text("label.custom_filter_search", query=draft.query + cursor), width))
    if draft.query:
        rows.append(
            clip_width(
                translator.text(
                    "status.custom_filter_search_count",
                    selected=selected_count,
                    matching=len(options),
                    total=len(all_options),
                ),
                width,
            )
        )
    else:
        rows.append(
            clip_width(
                translator.text("status.custom_filter_count", selected=selected_count, total=len(all_options)),
                width,
            )
        )
    if not options:
        rows.append(clip_width(translator.text("status.custom_filter_no_matches"), width))
        return "\n".join(rows)

    columns = min(draft.columns, len(options))
    total_rows = _grid_rows(len(options), columns)
    fixed_rows = len(rows)
    capacity = max(0, height - fixed_rows)
    viewport = min(draft.viewport_row, max(0, total_rows - 1))
    show_above = viewport > 0
    visible_capacity = max(0, capacity - int(show_above))
    end = min(total_rows, viewport + visible_capacity)
    show_below = end < total_rows
    if show_below and visible_capacity:
        end -= 1
    if show_above:
        rows.append(clip_width(translator.text("status.custom_filter_more_above"), width))

    column_width = max(1, (max(1, width) - (columns - 1)) // columns)
    for row in range(viewport, end):
        entries: list[str] = []
        for column in range(columns):
            index = row * columns + column
            if index >= len(options):
                text = ""
            else:
                option = options[index]
                text = (
                    f"{'›' if index == draft.option_index else ' '} "
                    f"{'[x]' if option.id in selected else '[ ]'} {_localized(option.label, translator)}"
                )
            entries.append(pad_width(clip_width(text, column_width), column_width))
        rows.append(clip_width(" ".join(entries).rstrip(), width))
    if show_below:
        rows.append(clip_width(translator.text("status.custom_filter_more_below"), width))
    return "\n".join(rows)
