from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from ccusage_viz.chart_models import Series, StackModel, TimeOfDaySeries
from ccusage_viz.formatting import display_width, strip_ansi
from ccusage_viz.i18n import load_translator
from ccusage_viz.processing.custom_historical import CustomProjectedSeries
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.custom import render_custom_stack
from ccusage_viz.render.legend import legend_rows
from ccusage_viz.render.monitor_distribution import render_monitor_distribution
from ccusage_viz.render.stack import render_stack
from ccusage_viz.render.timeline_presentation import (
    TimelinePresentationSeries,
    render_timeline_plot,
)

from .helpers import _distribution_model, _grouped_ranking_projection, usage


def context(width=24, height=24, **kwargs):
    return RenderContext(width, height, load_translator("en"), color=False, **kwargs)


def test_legend_keeps_one_row_when_it_fits():
    assert legend_rows(("# Alpha", "= Beta"), context()) == ("# Alpha · = Beta",)


def test_legend_wraps_whole_entries_in_order():
    entries = ("# Alpha", "= Beta", "+ Gamma", ": Delta")
    assert legend_rows(entries, context(20)) == ("# Alpha · = Beta", "+ Gamma · : Delta")


def test_legend_omission_count_accounts_for_its_own_width():
    rows = legend_rows(tuple(f"# Entry{i}" for i in range(10)), context(20))
    assert len(rows) == 2
    assert rows == ("# Entry0 · # Entry1", "# Entry2 · …(+7)")


def test_legend_height_limit_preserves_plot_space():
    rows = legend_rows(("# Alpha", "= Beta", "+ Gamma"), context(20, 10))
    assert rows == ("# Alpha · …(+2)",)
    assert len(legend_rows(("# Alpha", "= Beta", "+ Gamma"), context(20, 11))) == 2


@pytest.mark.parametrize("width", (1, 2, 6, 12, 20, 40))
@pytest.mark.parametrize("height", (8, 11, 24))
def test_legend_unicode_and_ansi_always_fit(width, height):
    entries = ("\x1b[31m█\x1b[0m 模型一", "■ 模型二 120", "● long-model-name 300", "◆ 其他")
    rows = legend_rows(entries, context(width, height))
    assert len(rows) <= 2
    assert all(display_width(row) <= width for row in rows)
    assert all("\n" not in row for row in rows)


def test_long_single_entry_is_visibly_shortened():
    assert strip_ansi(legend_rows(("# extraordinarily-long-model-name",), context(15))[0]).endswith(
        "…"
    )


def test_value_entry_is_not_split_between_name_and_number():
    assert legend_rows(("# Alpha 600", "= Beta 300"), context(16)) == ("# Alpha 600", "= Beta 300")


def test_empty_legend():
    assert legend_rows((), context()) == ()
    assert legend_rows(("Alpha",), context(0)) == ()


@pytest.mark.parametrize("position", ("below-title", "inside", "hidden"))
def test_timeline_legend_wraps_and_reserves_actual_height(position):
    ctx = context(40, 24, style="line", legend_position=position, ascii=True)
    names = ("Alpha-long", "Beta-long", "Gamma-long", "Delta-long")
    plot = render_timeline_plot(
        tuple(TimelinePresentationSeries(name, name, (1, 2, 3)) for name in names),
        x_values=(0, 1, 2),
        x_ticks=((0, 2), ("01", "03")),
        y_ticks=((0, 3), ("0", "3")),
        context=ctx,
        text_rows=1 + int(position == "below-title"),
        sole_total=False,
    )
    identities = [row for row in (plot.legend + "\n" + plot.chart).splitlines() if "-long" in row]
    assert len(identities) == (0 if position == "hidden" else 2)
    assert len(plot.chart.splitlines()) + len(plot.legend.splitlines()) == ctx.height - 1
    assert all(display_width(row) <= ctx.width for row in identities)


@pytest.mark.parametrize("position", ("below-title", "inside", "values", "hidden"))
def test_distribution_legend_two_rows_keep_full_height(position):
    ctx = context(40, 24, ascii=True, legend_position=position)
    base = _distribution_model()
    names = ("Alpha-long", "Beta-long", "Gamma-long", "Delta-long")
    model = replace(
        base,
        series=tuple(TimeOfDaySeries(name, name) for name in names),
        buckets=tuple(
            replace(bucket, values={name: 10.0 for name in names} if bucket.values else {})
            for bucket in base.buckets
        ),
    )
    rendered = render_monitor_distribution(model, ctx)
    identities = [row for row in rendered.splitlines() if "-long" in row]
    assert len(identities) == (0 if position == "hidden" else 2)
    assert len(rendered.splitlines()) == ctx.height
    assert all(display_width(row) <= ctx.width for row in rendered.splitlines())


@pytest.mark.parametrize("style", ("stacked", "grouped", "normalized"))
@pytest.mark.parametrize("position", ("below-title", "inside", "hidden"))
def test_native_stack_legend_two_rows_fit_plot(style, position):
    names = ("Alpha-long", "Beta-long", "Gamma-long", "Delta-long")
    model = StackModel(
        (date(2026, 1, 1), date(2026, 1, 2)),
        tuple(Series(("model", name), name, (usage(10), usage(20))) for name in names),
        grouping="model",
    )
    ctx = context(40, 24, ascii=True, style=style, legend_position=position)
    rendered = render_stack(model, ctx)
    identities = [row for row in rendered.splitlines() if "-long" in row]
    assert len(identities) == (0 if position == "hidden" else 2)
    assert len(rendered.splitlines()) <= ctx.height
    assert all(display_width(row) <= ctx.width for row in identities)


@pytest.mark.parametrize("style", ("stacked", "grouped"))
def test_dataset_stack_uses_the_same_legend_layout(style):
    from ccusage_viz.custom_models import LocalizedText

    projection = _grouped_ranking_projection()
    names = ("Alpha-long", "Beta-long", "Gamma-long", "Delta-long")
    projection = replace(
        projection,
        kind="stack",
        groups=None,
        series=tuple(
            CustomProjectedSeries(name, LocalizedText(name, name), (Decimal("10"),))
            for name in names
        ),
    )
    ctx = context(40, 24, ascii=True, style=style)
    rendered = render_custom_stack(projection, ctx)
    assert len([row for row in rendered.splitlines() if "-long" in row]) == 2
    assert all(display_width(row) <= ctx.width for row in rendered.splitlines())
