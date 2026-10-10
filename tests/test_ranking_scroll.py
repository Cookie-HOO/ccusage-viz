from ccusage_viz.ranking_scroll import (
    RANKING_SCROLL_ACTIVE_SECONDS,
    RankingScrollQueue,
    RankingViewport,
    advance_ranking_scroll,
    enqueue_ranking_scroll,
)


def test_active_scroll_displays_one_queued_row_per_frame() -> None:
    viewport = RankingViewport(total_rows=100, visible_rows=24)
    queue = RankingScrollQueue()
    for _ in range(5):
        queue = enqueue_ranking_scroll(queue, delta=1, now=0.0)

    offsets = []
    for now in (0.0, 0.01, 0.02):
        viewport, queue = advance_ranking_scroll(viewport, queue, now=now)
        offsets.append(viewport.offset)

    assert offsets == [1, 2, 3]
    assert queue.pending_rows == 2


def test_scroll_drops_pending_rows_when_input_becomes_idle() -> None:
    viewport = RankingViewport(total_rows=100, visible_rows=24)
    queue = enqueue_ranking_scroll(RankingScrollQueue(), delta=1, now=0.0)
    queue = enqueue_ranking_scroll(queue, delta=1, now=0.0)

    unchanged, stopped = advance_ranking_scroll(
        viewport, queue, now=RANKING_SCROLL_ACTIVE_SECONDS
    )
    assert unchanged == viewport
    assert stopped == RankingScrollQueue()


def test_scroll_clamps_and_bounds_pending_rows() -> None:
    viewport = RankingViewport(offset=9, total_rows=12, visible_rows=3)
    queue = enqueue_ranking_scroll(RankingScrollQueue(), delta=1, now=0.0)
    viewport, queue = advance_ranking_scroll(viewport, queue, now=0.0)
    assert viewport.offset == 9
    assert queue.pending_rows == 0
