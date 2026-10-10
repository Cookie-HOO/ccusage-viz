from ccusage_viz.ranking_scroll import (
    RankingViewport,
    RankingWheelBurst,
    advance_ranking_wheel,
    advance_ranking_wheel_burst,
)


def test_wheel_moves_one_eighth_of_visible_rows_without_retained_motion() -> None:
    viewport = RankingViewport(total_rows=100, visible_rows=24)
    moved = advance_ranking_wheel(viewport, delta=1)

    assert moved.offset == 3
    assert advance_ranking_wheel(moved, delta=-1).offset == 0
    assert moved == advance_ranking_wheel(moved, delta=0)


def test_same_direction_wheel_burst_accelerates_and_resets() -> None:
    viewport = RankingViewport(total_rows=200, visible_rows=16)
    burst = RankingWheelBurst()
    offsets = []
    for now in (0.00, 0.01, 0.02, 0.03, 0.04):
        viewport, burst = advance_ranking_wheel_burst(viewport, burst, delta=1, now=now)
        offsets.append(viewport.offset)

    assert offsets == [2, 6, 12, 20, 28]
    viewport, burst = advance_ranking_wheel_burst(viewport, burst, delta=1, now=0.13)
    assert viewport.offset == 30
    viewport, burst = advance_ranking_wheel_burst(viewport, burst, delta=-1, now=0.13)
    assert viewport.offset == 28


def test_wheel_moves_at_least_one_row_and_clamps_at_boundaries() -> None:
    viewport = RankingViewport(total_rows=12, visible_rows=3)
    assert advance_ranking_wheel(viewport, delta=1).offset == 1

    bottom = advance_ranking_wheel(RankingViewport(offset=8, total_rows=12, visible_rows=3), delta=1)
    assert bottom.offset == 9
    assert advance_ranking_wheel(bottom, delta=1) == bottom
    assert advance_ranking_wheel(RankingViewport(total_rows=12, visible_rows=3), delta=-1).offset == 0
