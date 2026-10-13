import pytest

from ccusage_viz.custom_filter_draft import (
    CustomFilterDraft,
    _custom_filter_controls,
    _filter_index_at,
    _matching_options,
    _render_custom_filter_draft,
    _render_custom_filter_help,
    _tab_layout,
    filter_tab_counts,
    run_custom_filter_editor,
)
from ccusage_viz.custom_models import CustomFilter, CustomFilterOption, LocalizedText
from ccusage_viz.formatting import display_width, strip_ansi
from ccusage_viz.i18n import load_translator
from ccusage_viz.tui_input import KeyEvent, MouseEvent, PasteEvent

CHOICES = (
    CustomFilter(
        "category",
        LocalizedText("Category", "分类"),
        (
            CustomFilterOption("fiction", LocalizedText("Fiction", "小说")),
            CustomFilterOption("history", LocalizedText("History", "历史")),
        ),
    ),
    CustomFilter(
        "source",
        LocalizedText("Source", "来源"),
        (CustomFilterOption("app", LocalizedText("App", "应用")),),
    ),
)

WRAPPED_CHOICES = (
    *CHOICES,
    CustomFilter(
        "kind",
        LocalizedText("Kind", "类型"),
        (CustomFilterOption("novel", LocalizedText("Novel", "小说")),),
    ),
)


def test_custom_filter_controls_full_line() -> None:
    translator = load_translator("en")

    controls = _custom_filter_controls(translator, 200)

    assert controls == (
        "h Help · ←/→ switch filter · ↑/↓ or j/k select · / search · Space toggle · "
        "c clear current · C columns · Enter apply · Esc cancel"
    )


@pytest.mark.parametrize(
    ("language", "left", "right"),
    (
        ("en", "h Help · ←/→ switch filter", "Enter apply · Esc cancel"),
        ("zh", "h 帮助 · ←/→ 切换筛选", "Enter 应用 · Esc 取消"),
    ),
)
def test_custom_filter_controls_preserve_ends_without_wrapping(
    language: str, left: str, right: str
) -> None:
    controls = _custom_filter_controls(load_translator(language), 58)

    assert controls.startswith(left)
    assert controls.endswith(right)
    assert controls.count("…") == 1
    assert "\n" not in controls
    assert display_width(controls) <= 58


def test_custom_filter_controls_very_narrow_fallback_is_one_bounded_line() -> None:
    controls = _custom_filter_controls(load_translator("zh"), 12)

    assert "\n" not in controls
    assert display_width(controls) <= 12


def test_custom_filter_help_lists_every_active_shortcut() -> None:
    help_body = _render_custom_filter_help(load_translator("en"), 100, 20)

    assert help_body.splitlines() == [
        "Custom filter help",
        "←/→ switch filter",
        "↑/↓ or j/k select",
        "/ search · Type · Backspace · Enter done · Esc clear",
        "Space toggle · c clear current · C columns",
        "Enter apply · Esc cancel",
        "h/Esc back",
    ]


def test_custom_filter_tabs_wrap_without_splitting_and_share_mouse_geometry() -> None:
    translator = load_translator("en")
    layout = _tab_layout(WRAPPED_CHOICES, translator, active_index=0, accepted=(), width=18)

    assert [(tab.text, tab.x_start, tab.x_end, tab.y) for tab in layout] == [
        ("[Category 0/2]", 1, 15, 1),
        ("Source 0/1", 1, 11, 2),
        ("Kind 0/1", 1, 9, 3),
    ]
    assert _filter_index_at(MouseEvent(0, 4, 2, True, 0), layout) == 1
    assert _filter_index_at(MouseEvent(0, 4, 3, True, 0), layout) == 2
    assert _filter_index_at(MouseEvent(0, 16, 1, True, 0), layout) is None
    assert _filter_index_at(MouseEvent(0, 14, 2, True, 0), layout) is None


def test_custom_filter_tab_layout_uses_localized_display_width() -> None:
    layout = _tab_layout(WRAPPED_CHOICES, load_translator("zh"), active_index=0, accepted=(), width=12)

    assert [(tab.x_start, tab.x_end, tab.y) for tab in layout] == [
        (1, 11, 1),
        (1, 9, 2),
        (1, 9, 3),
    ]


def test_custom_filter_option_click_accounts_for_wrapped_tab_rows() -> None:
    events = iter((MouseEvent(0, 2, 5, True, 0), KeyEvent("\r")))

    result = run_custom_filter_editor(
        (), WRAPPED_CHOICES, load_translator("en"), width=18, height=10,
        paint=lambda _body, _controls: None, read_key=lambda: next(events),
    )

    assert result == (("category", ("fiction",)),)


def test_single_select_replaces_then_clears_the_draft_value() -> None:
    choice = CustomFilter(
        "seed_book",
        LocalizedText("Based on book", "基于图书"),
        (
            CustomFilterOption("a", LocalizedText("A", "甲")),
            CustomFilterOption("b", LocalizedText("B", "乙")),
        ),
        "single_select",
    )
    draft = CustomFilterDraft((("seed_book", ("a",)),))

    assert draft.toggle(choice, "b").filters == (("seed_book", ("b",)),)
    assert draft.toggle(choice, "b").toggle(choice, "b").filters == ()


def test_multi_select_preserves_existing_toggle_behavior() -> None:
    choice = CHOICES[0]
    draft = CustomFilterDraft((("category", ("fiction",)),))

    assert draft.toggle(choice, "history").filters == (("category", ("fiction", "history")),)


def test_tab_rows_render_accepted_counts_without_using_unsubmitted_draft() -> None:
    choice = CHOICES[0]
    accepted = (("category", ("fiction",)),)
    draft = CustomFilterDraft(accepted).toggle(choice, "history")

    rendered = _render_custom_filter_draft(
        draft, (choice,), load_translator("en"), 80, accepted=accepted
    )

    assert "[Category 1/2]" in rendered
    assert "Selected 2 / 2" in rendered


def test_color_rendering_distinguishes_current_and_effective_filter_tabs() -> None:
    rendered = _render_custom_filter_draft(
        CustomFilterDraft((("category", ("fiction",)),)),
        CHOICES,
        load_translator("en"),
        80,
        accepted=(("category", ("fiction",)),),
        color=True,
        color_scheme="classic",
    )

    assert "\x1b[" in rendered
    assert "[Category 1/2]" in strip_ansi(rendered)
    assert "Source 0/1" in strip_ansi(rendered)
    assert "Selected 1 / 2" in strip_ansi(rendered)


def test_tab_counts_describe_accepted_filters_not_draft_filters() -> None:
    choice = CHOICES[0]
    accepted = (("category", ("fiction",)),)
    draft = CustomFilterDraft(accepted).toggle(choice, "history")

    assert filter_tab_counts(accepted, (choice,)) == ((1, 2),)
    assert draft.selected("category") == ("fiction", "history")


def test_custom_filter_editor_toggles_declared_option_ids_and_drops_empty_filters() -> None:
    events = iter((" ", "\x1b[C", " ", "\r"))

    result = run_custom_filter_editor(
        (("category", ("fiction",)),),
        CHOICES,
        load_translator("en"),
        width=80,
        paint=lambda _body, _controls: None,
        read_key=lambda: next(events),
    )

    assert result == (("source", ("app",)),)


def test_custom_filter_editor_switches_tabs_only_with_horizontal_arrows() -> None:
    arrow_events = iter(("\x1b[C", " ", "\r"))
    non_arrow_events = iter(("l", "\t", " ", "\r"))

    arrow_result = run_custom_filter_editor(
        (), CHOICES, load_translator("en"), width=80,
        paint=lambda _body, _controls: None, read_key=lambda: next(arrow_events),
    )
    non_arrow_result = run_custom_filter_editor(
        (), CHOICES, load_translator("en"), width=80,
        paint=lambda _body, _controls: None, read_key=lambda: next(non_arrow_events),
    )

    assert arrow_result == (("source", ("app",)),)
    assert non_arrow_result == (("category", ("fiction",)),)


def test_custom_filter_help_ignores_inputs_and_preserves_the_complete_draft() -> None:
    choice = CustomFilter(
        "many",
        LocalizedText("Many", "多个"),
        tuple(
            CustomFilterOption(f"option-{index}", LocalizedText(f"option-{index}", f"选项-{index}"))
            for index in range(8)
        ),
    )
    frames: list[tuple[str, str]] = []
    events = iter(
        (
            "\x1b[C", "C", "j", "j", "j", " ", "/", PasteEvent("option"), "\r", "h",
            KeyEvent(" "), MouseEvent(0, 2, 3, True, 0), PasteEvent("c"), PasteEvent("\x03"),
            "h", "\r",
        )
    )

    result = run_custom_filter_editor(
        (), (CHOICES[0], choice), load_translator("en"), width=48, height=6,
        paint=lambda body, controls: frames.append((body, controls)),
        read_key=lambda: next(events),
    )

    help_frames = [frame for frame in frames if "Custom filter help" in frame[0]]
    first_help_index = next(
        index for index, (body, _controls) in enumerate(frames) if "Custom filter help" in body
    )
    assert result == (("many", ("option-6",)),)
    assert frames[first_help_index - 1][0] == frames[-1][0]
    assert help_frames
    assert all(controls == "h/Esc back" for _body, controls in help_frames)
    assert all("\n" not in controls and display_width(controls) <= 48 for _, controls in frames)
    help_body = help_frames[0][0]
    assert "←/→ switch filter" in help_body
    assert "↑/↓ or j/k select" in help_body
    assert "/ search" in help_body
    assert "Space toggle · c clear current · C columns" in help_body
    assert "Enter apply · Esc cancel" in help_body


def test_custom_filter_editor_pasted_ctrl_c_raises_keyboard_interrupt() -> None:
    with pytest.raises(KeyboardInterrupt):
        run_custom_filter_editor(
            (), CHOICES, load_translator("en"), width=80,
            paint=lambda _body, _controls: None, read_key=lambda: PasteEvent("\x03"),
        )


def test_custom_filter_help_ignores_pasted_ctrl_c() -> None:
    events = iter(("h", PasteEvent("\x03"), "h", "\r"))

    result = run_custom_filter_editor(
        (), CHOICES, load_translator("en"), width=80,
        paint=lambda _body, _controls: None, read_key=lambda: next(events),
    )

    assert result == ()


def test_custom_filter_editor_search_h_does_not_open_help() -> None:
    frames: list[str] = []
    events = iter(("/", "h", "\r", "\r"))

    result = run_custom_filter_editor(
        (), CHOICES, load_translator("en"), width=80,
        paint=lambda body, _controls: frames.append(body), read_key=lambda: next(events),
    )

    assert result == ()
    assert any("Search: h" in frame for frame in frames)
    assert all("Custom filter help" not in frame for frame in frames)


def test_custom_filter_help_escape_returns_before_editor_escape_cancels() -> None:
    frames: list[str] = []
    events = iter(("h", "\x1b", "\x1b"))

    result = run_custom_filter_editor(
        (), CHOICES, load_translator("en"), width=80,
        paint=lambda body, _controls: frames.append(body), read_key=lambda: next(events),
    )

    assert result is None
    assert any("Custom filter help" in frame for frame in frames)
    assert "[Category 0/2]" in frames[-1]


def test_custom_filter_editor_renders_protocol_localized_labels() -> None:
    rendered: list[str] = []
    events = iter(("\x1b",))

    result = run_custom_filter_editor(
        (),
        CHOICES,
        load_translator("zh"),
        width=80,
        paint=lambda body, _controls: rendered.append(body),
        read_key=lambda: next(events),
    )

    assert result is None
    assert "[分类 0/2]" in rendered[0]
    assert "小说" in rendered[0]


def test_custom_filter_editor_searches_localized_labels_and_clears_current_tab() -> None:
    draft = CustomFilterDraft((("category", ("fiction",)), ("source", ("app",))))

    assert [option.id for option in _matching_options(CHOICES[0], "FI", load_translator("en"))] == [
        "fiction"
    ]
    assert draft.clear("category").filters == (("source", ("app",)),)


def test_custom_filter_editor_cycles_one_to_three_columns() -> None:
    draft = CustomFilterDraft(())

    assert draft.cycle_columns().columns == 2
    assert draft.cycle_columns().cycle_columns().columns == 3
    assert draft.cycle_columns().cycle_columns().cycle_columns().columns == 1


def test_custom_filter_editor_search_retains_enter_and_escape_clears_query() -> None:
    frames: list[str] = []
    keys = iter(("/", "f", "i", "\r", "\x1b", "\r"))

    result = run_custom_filter_editor(
        (),
        CHOICES,
        load_translator("en"),
        width=80,
        height=12,
        paint=lambda body, _controls: frames.append(body),
        read_key=lambda: next(keys),
    )

    assert result == ()
    assert "Search: fi" in frames[3]
    assert "Search: fi" not in frames[5]


def test_custom_filter_editor_moves_vertically_in_columns_with_incomplete_final_row() -> None:
    choice = CustomFilter(
        "many",
        LocalizedText("Many", "多个"),
        tuple(
            CustomFilterOption(f"option-{index}", LocalizedText(f"option-{index}", f"选项-{index}"))
            for index in range(5)
        ),
    )
    draft = CustomFilterDraft((), option_index=1, columns=2)

    assert draft.move_option(1, (choice,), load_translator("en")).option_index == 3
    assert draft.move_option(2, (choice,), load_translator("en")).option_index == 4
    assert draft.move_option(-4, (choice,), load_translator("en")).option_index == 1


def test_custom_filter_editor_click_switches_filter_tab() -> None:
    events = iter((MouseEvent(0, 20, 1, True, 0), KeyEvent(" "), KeyEvent("\r")))

    result = run_custom_filter_editor(
        (),
        CHOICES,
        load_translator("en"),
        width=80,
        height=12,
        paint=lambda _body, _controls: None,
        read_key=lambda: next(events),
    )

    assert result == (("source", ("app",)),)


def test_custom_filter_editor_clicks_full_rendered_tab_but_not_separator() -> None:
    layout = _tab_layout(CHOICES, load_translator("en"), 0, (), width=80)

    assert _filter_index_at(MouseEvent(0, 20, 1, True, 0), layout) == 1
    assert _filter_index_at(MouseEvent(0, 16, 1, True, 0), layout) is None


def test_custom_filter_editor_renders_radio_marks_for_single_select() -> None:
    single = CustomFilter(
        "seed_book",
        LocalizedText("Book", "图书"),
        (CustomFilterOption("a", LocalizedText("A", "甲")),),
        "single_select",
    )

    rendered = _render_custom_filter_draft(
        CustomFilterDraft((("seed_book", ("a",)),)),
        (single, CHOICES[0]),
        load_translator("en"),
        80,
    )

    multi_rendered = _render_custom_filter_draft(
        CustomFilterDraft(()),
        (CHOICES[0],),
        load_translator("en"),
        80,
    )

    assert "(●) A" in rendered
    assert "[ ] Fiction" in multi_rendered


def test_custom_filter_editor_click_toggles_visible_option() -> None:
    clicks = iter((MouseEvent(0, 2, 3, True, 0), KeyEvent("\r")))

    result = run_custom_filter_editor(
        (),
        CHOICES,
        load_translator("en"),
        width=80,
        height=12,
        paint=lambda _body, _controls: None,
        read_key=lambda: next(clicks),
    )

    assert result == (("category", ("fiction",)),)


def test_custom_filter_editor_clicks_scrolled_second_column_option() -> None:
    choice = CustomFilter(
        "many",
        LocalizedText("Many", "多个"),
        tuple(
            CustomFilterOption(f"option-{index}", LocalizedText(f"option-{index}", f"选项-{index}"))
            for index in range(8)
        ),
    )
    events = iter(("C", "j", "j", MouseEvent(0, 17, 5, True, 0), "\r"))

    result = run_custom_filter_editor(
        (),
        (choice,),
        load_translator("en"),
        width=30,
        height=6,
        paint=lambda _body, _controls: None,
        read_key=lambda: next(events),
    )

    assert result == (("many", ("option-5",)),)


def test_custom_filter_editor_renders_counts_columns_and_scrolled_options() -> None:
    choice = CustomFilter(
        "many",
        LocalizedText("Many", "多个"),
        tuple(
            CustomFilterOption(f"option-{index}", LocalizedText(f"option-{index}", f"选项-{index}"))
            for index in range(7)
        ),
    )
    body = _render_custom_filter_draft(
        CustomFilterDraft(
            (("many", ("option-0",)),), option_index=6, query="option", columns=2, viewport_row=2
        ),
        (choice,),
        load_translator("en"),
        width=40,
        height=6,
    )

    assert "Selected 1 / Matching 7 / 7" in body
    assert "↑ More options above" in body
    assert "option-6" in body


def test_custom_filter_editor_clears_only_active_tab_and_cycles_columns() -> None:
    keys = iter(("C", "C", "C", "c", "\r"))

    result = run_custom_filter_editor(
        (("category", ("fiction",)), ("source", ("app",))),
        CHOICES,
        load_translator("en"),
        width=80,
        height=12,
        paint=lambda _body, _controls: None,
        read_key=lambda: next(keys),
    )

    assert result == (("source", ("app",)),)


def test_custom_filter_editor_hides_duplicate_dataset_option_labels() -> None:
    choices = (
        CustomFilter(
            "stars",
            LocalizedText("Star range", "Star 区间"),
            (
                CustomFilterOption("0-1k-primary", LocalizedText("[0, 1K)", "[0, 1K)")),
                CustomFilterOption("0-1k-duplicate", LocalizedText("[0, 1K)", "[0, 1K)")),
                CustomFilterOption("1k-10k", LocalizedText("[1K, 10K)", "[1K, 10K)")),
            ),
        ),
    )
    rendered: list[str] = []
    events = iter(("j", " ", "\r"))

    result = run_custom_filter_editor(
        (),
        choices,
        load_translator("en"),
        width=80,
        paint=lambda body, _: rendered.append(body),
        read_key=lambda: next(events),
    )

    assert result == (("stars", ("1k-10k",)),)
    assert rendered[0].count("[0, 1K)") == 1
