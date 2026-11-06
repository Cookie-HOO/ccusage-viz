from dataclasses import replace

import pytest

from ccusage_viz.custom_models import CustomRankingBand, LocalizedText
from ccusage_viz.i18n import load_translator
from ccusage_viz.tui.custom_adjustments import (
    _custom_pane_adjustment_keys,
    _custom_pane_adjustment_state,
)

from .test_ranking_label_color_controls import audit  # noqa: F401


@pytest.mark.parametrize("kind", ("ranking", "partitioned-ranking"))
@pytest.mark.parametrize(
    "named,represented,mode,available",
    (
        (True, True, "band", True),
        (False, True, "band", False),
        (True, False, "band", False),
        (True, True, "change", False),
        (True, True, "none", False),
    ),
)
def test_legend_control_only_when_useful(audit, kind, named, represented, mode, available):  # noqa: F811
    a = audit(kind)
    response = a.component.accepted_response
    data = response.data
    band_id = "qualified" if represented else None
    if kind == "ranking":
        data = replace(data, series=tuple(replace(e, band_id=band_id) for e in data.series))
    else:
        data = replace(
            data,
            groups=tuple(
                replace(g, series=tuple(replace(e, band_id=band_id) for e in g.series))
                for g in data.groups
            ),
        )
    a.component.accepted_response = replace(
        response,
        data=replace(
            data,
            bands=(
                CustomRankingBand(
                    "qualified", LocalizedText("Qualified", "晋级") if named else None
                ),
            ),
        ),
    )
    a.component._reproject()
    a.component.configure(
        replace(
            a.component.candidate,
            presentation=replace(a.component.candidate.presentation, label_color_mode=mode),
        ),
        data_affecting=False,
    )
    assert ("l" in _custom_pane_adjustment_keys(a.pane, "advanced")) is available
    assert (
        "Legend" in _custom_pane_adjustment_state(a.pane, "advanced", load_translator("en"))
    ) is available
    a.press("l")
    assert a.component.candidate.presentation.legend == ("hidden" if available else "below-title")
    if available:
        assert "l" in _custom_pane_adjustment_keys(a.pane, "advanced")
        a.press("u")
        assert a.component.candidate.presentation.legend == "below-title"
        a.press("U")
        assert a.component.candidate.presentation.legend == "hidden"
        a.press("l")
        assert a.component.candidate.presentation.legend == "below-title"
    assert not a.submitted
