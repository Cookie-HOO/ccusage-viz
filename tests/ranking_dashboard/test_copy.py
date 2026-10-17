from dataclasses import replace

import pytest

import ccusage_viz.tui.custom_rendering as tui_custom_rendering
import ccusage_viz.tui.datasets.chooser as tui_datasets_chooser
import ccusage_viz.tui.datasets.modal as tui_datasets_modal
import ccusage_viz.tui.events as tui_events
import ccusage_viz.tui.pane_events as tui_pane_events
import ccusage_viz.tui.pointer as tui_pointer
from ccusage_viz.tui_input import KeyEvent, MouseEvent, WheelEvent
from tests.ranking_scroll.helpers import grouped_projection


def test_grouped_dashboard_inner_series_copy_uses_group_aware_payload(dashboard):
    run, panes, frames, focuses, layouts, decoder, copied, opened, size = dashboard
    del frames, decoder, opened
    size[:] = [160, 14]
    for pane in panes:
        model = grouped_projection()
        config = replace(model.config, date_range=replace(model.date_range, fixed_bounds=True))
        pane.component.candidate = pane.component.accepted_config = config
        pane.component.model = replace(model, config=config)

    target = []

    def click_series():
        pane = panes[0]
        row, (identity, column, _) = next(
            (row, hit) for row, hit in pane.ranking_copy_rows.items() if hit[0][0] == "series"
        )
        target.append(identity)
        rect = layouts[-1].pane(0)
        framed = focuses[-1] == 0
        return MouseEvent(
            0,
            rect.left + column + 1 + framed,
            rect.top + row + 1 + framed,
            True,
            0,
        )

    def verify():
        viewport = panes[0].grouped_ranking_viewport
        assert target[0][0] == "series"
        assert copied == [viewport.clipboard_text(target[0])]
        assert copied[0].startswith("Coding Model\nSeed")
        return KeyEvent("\x03")

    run([click_series, verify])


def test_copy_all_uses_every_filtered_entry_without_focus_or_query_work(dashboard):
    run, panes, frames, focuses, layouts, decoder, copied, opened, _ = dashboard

    def click_all():
        hit = panes[0].ranking_viewport.copy_all_hit
        assert hit is not None
        row, column = hit
        rect = layouts[-1].pane(0)
        return MouseEvent(0, rect.left + column + 1, rect.top + row + 1, True, 0)

    def verify_all():
        assert copied == [panes[0].ranking_viewport.clipboard_all_text()]
        assert focuses[-1] == -1
        assert opened == []
        assert panes[0].copied_ranking_entry_id is None
        assert panes[0].copied_ranking_all_until > 0
        assert "✓" in "\n".join(frames[-1].rows)
        return KeyEvent("\x03")

    run([click_all, verify_all])


def test_copy_all_failure_does_not_show_success(dashboard):
    run, panes, frames, focuses, layouts, decoder, copied, *_ = dashboard
    run.monkeypatch.setattr(tui_events, "copy_command", lambda text: False)
    run.monkeypatch.setattr(tui_pointer, "copy_command", lambda text: False)
    run.monkeypatch.setattr(tui_pane_events, "copy_command", lambda text: False)
    run.monkeypatch.setattr(tui_datasets_chooser, "copy_command", lambda text: False)
    run.monkeypatch.setattr(tui_datasets_modal, "copy_command", lambda text: False)
    run.monkeypatch.setattr(tui_pointer, "copy_command", lambda text: False)
    run.monkeypatch.setattr(tui_datasets_chooser, "copy_command", lambda text: False)
    run.monkeypatch.setattr(tui_datasets_modal, "copy_command", lambda text: False)

    def click_all():
        hit = panes[0].ranking_viewport.copy_all_hit
        assert hit is not None
        row, column = hit
        rect = layouts[-1].pane(0)
        return MouseEvent(0, rect.left + column + 1, rect.top + row + 1, True, 0)

    def verify_failure():
        assert panes[0].copied_ranking_all_until == 0
        assert "✓" not in "\n".join(frames[-1].rows)
        return KeyEvent("\x03")

    run([click_all, verify_failure])


def test_copy_all_respects_search_and_includes_offscreen_matches(dashboard):
    run, panes, frames, focuses, layouts, decoder, copied, *_ = dashboard
    pane = panes[0]
    pane.ranking_search.query = "Project 9"

    def click_all():
        hit = pane.ranking_viewport.copy_all_hit
        assert hit is not None
        row, column = hit
        rect = layouts[-1].pane(0)
        return MouseEvent(0, rect.left + column + 1, rect.top + row + 1, True, 0)

    def verify_search():
        matches = (9, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99)
        assert copied == [pane.ranking_viewport.clipboard_all_text()]
        assert len(pane.ranking_viewport.entries) == len(matches)
        return KeyEvent("\x03")

    run([click_all, verify_search])


def test_scroll_copy_link_and_search_use_visible_stable_id(dashboard):
    run, panes, frames, focuses, layouts, decoder, copied, opened, _ = dashboard
    target_id = []
    run.monkeypatch.setattr(
        tui_custom_rendering,
        "_custom_ranking_copyable_entries",
        lambda *args: pytest.fail("full-list copy lookup"),
    )
    run.monkeypatch.setattr(
        tui_pointer,
        "_custom_ranking_copyable_entries",
        lambda *args: pytest.fail("full-list copy lookup"),
    )

    def click_visible(*, link=False):
        pane = panes[0]
        row, (entry_id, column, link_column) = next(iter(pane.ranking_copy_rows.items()))
        target_id.append(entry_id)
        rect = layouts[-1].pane(0)
        # The default Dashboard is frameless until its pane owns focus.
        framed = focuses[-1] == 0
        return MouseEvent(
            0,
            rect.left + (link_column if link else column) + 1 + framed,
            rect.top + row + 1 + framed,
            True,
            0,
        )

    def check_copy():
        assert target_id[0] == "1"
        assert copied == [panes[0].ranking_viewport.clipboard_text("1")]
        assert panes[0].copied_ranking_entry_id == "1"
        return click_visible(link=True)

    def check_link():
        assert opened == ["https://example.com/1"]
        return KeyEvent("\x03")

    run([WheelEvent(1, 2, 3), click_visible, check_copy, check_link])
