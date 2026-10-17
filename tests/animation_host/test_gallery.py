
from dataclasses import replace

import pytest
from term_animate.api import curated_catalog
from term_animate.catalog import Catalog
from term_animate.models import Pack, ProjectedFrame, StyledCell, StyledRow

from ccusage_viz.animation import (
    AnimationRenderer,
    animation_spec,
    animation_style_choices,
    default_animation_spec,
)
from ccusage_viz.animation_host.gallery import GalleryState, _gallery_geometry, _gallery_rows
from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import display_width
from ccusage_viz.terminal import Terminal


def test_default_animation_spec_rejects_empty_catalog(monkeypatch) -> None:
    monkeypatch.setattr("ccusage_viz.animation.animation_style_choices", lambda _target: ())

    with pytest.raises(UsageError):
        default_animation_spec()

def test_catalog_is_discovered_from_term_animate() -> None:
    styles = animation_style_choices()

    assert styles
    assert set(animation_style_choices("monitor")).issubset(styles)
    assert animation_spec(styles[0]).style == styles[0]
    with pytest.raises(UsageError):
        animation_spec("not-an-animation")

def test_gallery_catalog_refresh_preserves_valid_selection_and_handles_removal() -> None:
    state = GalleryState(("rain", "snow"), "snow")
    snow = state.session_for("snow", now=1.0)
    snow.set_viable(True, 1.0)

    assert state.refresh_catalog(("rain", "snow", "digital-clock"), now=2.0) is True
    assert state.selected_style == "snow"

    assert state.refresh_catalog(("rain",), now=3.0) is True
    assert state.selected_style == "rain"
    assert state.sessions == {}

    assert state.refresh_catalog((), now=4.0) is True
    assert state.selected_style == ""
    assert state.selected_index() == 0

def test_gallery_hides_off_page_sessions_without_idle_catch_up() -> None:
    state = GalleryState(("rain", "snow"), "rain")
    rain = state.session_for("rain", now=1.0)
    rain.set_viable(True, 1.0)
    assert rain.clock.elapsed(3.0) == 2.0

    state.set_visible_styles(("snow",), now=3.0)

    assert not rain.visible
    assert rain.clock.elapsed(100.0) == 2.0

def test_gallery_projects_all_visible_previews_between_deadlines(monkeypatch, translator) -> None:
    state = GalleryState(("rain", "snow"), "rain")
    terminal = Terminal(60, 12, False, False)
    renderer = AnimationRenderer()
    calls: list[str] = []
    frame = ProjectedFrame((StyledRow((StyledCell("x"),)),), 0, 9.0, "full")
    monkeypatch.setattr(
        "ccusage_viz.animation.project",
        lambda effect, **_kwargs: calls.append(effect.id) or frame,
    )

    _gallery_rows(state, renderer, terminal, translator, now=1.0)
    _gallery_rows(state, renderer, terminal, translator, now=2.0)

    assert calls == ["rain", "snow"]

def test_gallery_uses_two_columns_tall_cards_and_paginates_by_selection(translator) -> None:
    state = GalleryState(("rain", "snow", "digital-clock", "mole-cat"), "rain")
    terminal = Terminal(80, 24, False, False)

    columns, rows, card_width, card_height = _gallery_geometry(terminal)
    rendered, sessions = _gallery_rows(state, AnimationRenderer(), terminal, translator, now=1.0)

    assert (columns, rows, card_width, card_height) == (2, 1, 40, 21)
    assert len(sessions) == 2
    assert all(session.clock.playing for session in sessions)
    assert rendered[0] == "┌" + "─" * 38 + "┐" + "┌" + "─" * 38 + "┐"
    assert any("rain" in row and "snow" in row for row in rendered)
    state.select(2)
    rendered, sessions = _gallery_rows(state, AnimationRenderer(), terminal, translator, now=2.0)
    assert len(sessions) == 2
    assert all(
        session.visible and session.playback_requested and session.clock.playing
        for session in sessions
    )
    assert any("digital-clock" in row and "mole-cat" in row for row in rendered)

def test_gallery_uses_ascii_card_borders(translator) -> None:
    state = GalleryState(("rain",), "rain")

    rows, _ = _gallery_rows(
        state, AnimationRenderer(), Terminal(40, 24, False, True), translator, now=1.0
    )

    assert rows[0] == "+" + "-" * 18 + "+"
    assert any(row.startswith("|") and row.endswith("|") for row in rows)

def test_gallery_cards_keep_ansi_display_width_safe(monkeypatch, translator) -> None:
    state = GalleryState(("rain",), "rain")
    terminal = Terminal(60, 12, True, False)
    renderer = AnimationRenderer()
    frame = ProjectedFrame((StyledRow((StyledCell("你", foreground=(1, 2, 3)),)),), 0, None, "full")
    monkeypatch.setattr("ccusage_viz.animation.project", lambda *_args, **_kwargs: frame)

    rows, _ = _gallery_rows(state, renderer, terminal, translator, now=1.0)

    assert all(display_width(row) <= terminal.width for row in rows)

def test_catalog_extension_is_discovered_without_a_ccuv_catalog_change(monkeypatch) -> None:
    catalog = curated_catalog()
    source = catalog.effects()[0]
    added = replace(source, id="new-cat", style="new-cat", name="New Cat")
    monkeypatch.setattr(
        "ccusage_viz.animation.curated_catalog",
        lambda: Catalog((Pack("extended", "Extended", (*catalog.effects(), added)),)),
    )

    assert animation_style_choices()[-1] == "new-cat"
    assert animation_spec("new-cat").display_name == "New Cat"
