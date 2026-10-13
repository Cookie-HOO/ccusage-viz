"""Interactive capability-backed drafts for custom-command filters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from ccusage_viz.custom_models import CustomFilter, CustomFilterOption
from ccusage_viz.formatting import clip_width, display_width, pad_width, truncate_middle_width
from ccusage_viz.i18n import Translator
from ccusage_viz.options import CustomFilters
from ccusage_viz.render.base import styled_text
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.tui_input import KeyEvent, MouseEvent, PasteEvent


@dataclass(frozen=True, slots=True)
class _FilterColorContext:
    color: bool


@dataclass(frozen=True, slots=True)
class _FilterTab:
    """One unstyled Custom filter tab and its terminal-cell geometry."""

    index: int
    text: str
    selected: int
    x_start: int
    x_end: int
    y: int


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
    color: bool = False,
    color_scheme: str = "no-color",
) -> CustomFilters | None:
    """Edit protocol-declared Dataset filters locally until the draft is applied."""

    draft = CustomFilterDraft(filters)
    help_visible = False
    while True:
        if help_visible:
            body = _render_custom_filter_help(translator, width, height)
        else:
            draft = _normalise_draft(draft, choices, translator, width, height, filters)
            body = _render_custom_filter_draft(
                draft,
                choices,
                translator,
                width,
                height,
                accepted=filters,
                color=color,
                color_scheme=color_scheme,
            )
        paint(body, _custom_filter_controls(translator, width, help_visible=help_visible))
        event = read_key()
        key = event.value if isinstance(event, (KeyEvent, PasteEvent)) else event
        if help_visible:
            if isinstance(event, PasteEvent):
                continue
            if key == "\x03":
                raise KeyboardInterrupt
            if key in {"h", "\x1b"}:
                help_visible = False
            continue
        if key == "\x03":
            raise KeyboardInterrupt
        if isinstance(event, MouseEvent):
            if event.pressed and event.button == 0:
                tab_index = _filter_index_at(
                    event,
                    _tab_layout(choices, translator, draft.filter_index, filters, width),
                )
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
                option_index = _option_index_at(
                    event, draft, options, choices, translator, filters, width, height
                )
                if current is not None and option_index is not None:
                    draft = draft.toggle(current, options[option_index].id)
                    draft = replace(draft, option_index=option_index)
            continue
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
        elif key == "h":
            help_visible = True
        elif key == "\x1b[D":
            draft = draft.move_filter(-1, choices)
        elif key in {"\t", "\x1b[C"}:
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


def _custom_filter_controls(
    translator: Translator, width: int, *, help_visible: bool = False
) -> str:
    """Return one display-width-bounded row of Custom filter controls."""
    if help_visible:
        return clip_width(translator.text("status.custom_filter_help_back"), width)

    left = translator.text("status.custom_filter_controls_left")
    middle = translator.text("status.custom_filter_controls_middle")
    right = translator.text("status.custom_filter_controls_right")
    full = " · ".join((left, middle, right))
    if display_width(full) <= width:
        return full

    compact = f"{left} · … · {right}"
    if display_width(compact) <= width:
        return compact
    return truncate_middle_width(f"{left} · {right}", width)


def _render_custom_filter_help(translator: Translator, width: int, height: int) -> str:
    """Render the localized, geometry-bounded Custom filter key reference."""
    keys = (
        "status.custom_filter_help_title",
        "status.custom_filter_help_filters",
        "status.custom_filter_help_options",
        "status.custom_filter_help_search",
        "status.custom_filter_help_selection",
        "status.custom_filter_help_complete",
        "status.custom_filter_help_back",
    )
    rows = (clip_width(translator.text(key), width) for key in keys)
    return "\n".join(list(rows)[: max(0, height)])


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


def _selection_mark(choice: CustomFilter, selected: bool) -> str:
    """Return a mode-appropriate, color-independent option selection mark."""
    if choice.mode == "single_select":
        return "(●)" if selected else "( )"
    return "[x]" if selected else "[ ]"


def _grid_rows(option_count: int, columns: int) -> int:
    columns = max(1, min(3, columns))
    return (option_count + columns - 1) // columns


def _chrome_rows(
    draft: CustomFilterDraft,
    choices: tuple[CustomFilter, ...],
    translator: Translator,
    accepted: CustomFilters,
    width: int,
) -> int:
    """Return rows occupied above the option viewport."""
    tab_rows = max(
        (tab.y for tab in _tab_layout(choices, translator, draft.filter_index, accepted, width)),
        default=1,
    )
    return tab_rows + 1 + int(bool(draft.query or draft.search_editing))


def _normalise_draft(
    draft: CustomFilterDraft,
    choices: tuple[CustomFilter, ...],
    translator: Translator,
    width: int,
    height: int,
    accepted: CustomFilters,
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
    visible_rows = max(1, height - _chrome_rows(draft, choices, translator, accepted, width) - 2)
    maximum_viewport = max(0, total_rows - visible_rows)
    viewport = min(draft.viewport_row, maximum_viewport)
    if focus_row < viewport:
        viewport = focus_row
    elif focus_row >= viewport + visible_rows:
        viewport = focus_row - visible_rows + 1
    return replace(draft, option_index=option_index, viewport_row=viewport)


def _tab_layout(
    choices: tuple[CustomFilter, ...],
    translator: Translator,
    active_index: int,
    accepted: CustomFilters,
    width: int,
) -> tuple[_FilterTab, ...]:
    """Return unstyled, whole-tab geometry shared by rendering and mouse input."""
    width = max(1, width)
    x, y = 1, 1
    tabs: list[_FilterTab] = []
    for index, (choice, (selected, total)) in enumerate(
        zip(choices, filter_tab_counts(accepted, choices), strict=True)
    ):
        label = _localized(choice.label, translator)
        text = f"[{label} {selected}/{total}]" if index == active_index else f"{label} {selected}/{total}"
        tab_width = min(display_width(text), width)
        separator_width = display_width(" · ") if tabs and x != 1 else 0
        if x + separator_width + tab_width - 1 > width:
            x, y, separator_width = 1, y + 1, 0
        x += separator_width
        tabs.append(_FilterTab(index, text, selected, x, x + tab_width, y))
        x += tab_width
    return tuple(tabs)


def _filter_index_at(event: MouseEvent, layout: tuple[_FilterTab, ...]) -> int | None:
    """Map a click to the tab whose shared geometry contains it."""
    for tab in layout:
        if event.y == tab.y and tab.x_start <= event.x < tab.x_end:
            return tab.index
    return None


def _option_index_at(
    event: MouseEvent,
    draft: CustomFilterDraft,
    options: tuple[CustomFilterOption, ...],
    choices: tuple[CustomFilter, ...],
    translator: Translator,
    accepted: CustomFilters,
    width: int,
    height: int,
) -> int | None:
    """Map a one-based terminal click to its visible option-grid cell."""
    if not options:
        return None
    columns = min(draft.columns, len(options))
    fixed_rows = _chrome_rows(draft, choices, translator, accepted, width)
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
    *,
    accepted: CustomFilters | None = None,
    color: bool = False,
    color_scheme: str = "no-color",
) -> str:
    current = draft.current_filter(choices)
    accepted = draft.filters if accepted is None else accepted
    context = _FilterColorContext(color)
    scheme = get_color_scheme(color_scheme)

    def tab(index: int, text: str, selected: int) -> str:
        if index == draft.filter_index:
            return styled_text(text, scheme.highlight, context, bold=True)
        if selected:
            label, count = text.rsplit(" ", 1)
            return f"{styled_text(label, scheme.muted, context, dim=True)} {styled_text(count, scheme.cache, context)}"
        return styled_text(text, scheme.muted, context, dim=True)

    layout = _tab_layout(choices, translator, draft.filter_index, accepted, width)
    tab_rows: list[str] = []
    for y in range(1, max((item.y for item in layout), default=1) + 1):
        row = ""
        for item in (item for item in layout if item.y == y):
            if row:
                row += " · "
            row += tab(item.index, item.text, item.selected)
        tab_rows.append(clip_width(row, width))
    if current is None:
        return translator.text("status.custom_filter_unavailable")

    all_options = _display_options(current)
    options = _matching_options(current, draft.query, translator)
    selected = set(draft.selected(current.id))
    selected_count = sum(option.id in selected for option in all_options)
    selected_status = translator.text("status.custom_filter_count", selected=selected_count, total=len(all_options))
    selected_prefix, selected_value, selected_suffix = selected_status.partition(str(selected_count))
    rows = tab_rows
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
                f"{styled_text(selected_prefix, scheme.muted, context, dim=True)}"
                f"{styled_text(selected_value, scheme.highlight, context, bold=True)}"
                f"{styled_text(selected_suffix, scheme.muted, context, dim=True)}",
                width,
            )
        )
    if not options:
        rows.append(clip_width(translator.text("status.custom_filter_no_matches"), width))
        return "\n".join(rows)

    columns = min(draft.columns, len(options))
    total_rows = _grid_rows(len(options), columns)
    fixed_rows = _chrome_rows(draft, choices, translator, accepted, width)
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
                    f"{_selection_mark(current, option.id in selected)} {_localized(option.label, translator)}"
                )
            entries.append(pad_width(clip_width(text, column_width), column_width))
        rows.append(clip_width(" ".join(entries).rstrip(), width))
    if show_below:
        rows.append(clip_width(translator.text("status.custom_filter_more_below"), width))
    return "\n".join(rows)
