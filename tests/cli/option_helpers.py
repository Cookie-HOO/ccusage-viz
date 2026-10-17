from datetime import date

from ccusage_viz.custom_models import (
    CustomCapabilities,
    CustomChartCapability,
    CustomChartDefaults,
    CustomDataset,
    CustomProbeDescriptor,
    CustomUnit,
    LocalizedText,
)
from ccusage_viz.options import (
    ProcessConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
    resolve_date_range,
)


def _probe_descriptor() -> CustomProbeDescriptor:
    text = LocalizedText("WeRead", "微信读书")
    return CustomProbeDescriptor(
        "weread-1",
        "0.1.0",
        CustomDataset(text, text, CustomUnit("page", text, "suffix", 0)),
        CustomCapabilities(
            (),
            (),
            {
                "ranking": CustomChartCapability(("day",), ("book",), ()),
                "timeline": CustomChartCapability(("day",), (), ()),
            },
        ),
        {
            "ranking": CustomChartDefaults("1y", "book", 10),
            "timeline": CustomChartDefaults("14d", None, None),
        },
        (),
    )


def timeline(
    *, rolling: bool = True, by: str | None = None, top: int | None = None
) -> StandaloneLaunch:
    date_range = (
        resolve_date_range(
            "timeline", period="14d", since=None, until=None, today=date(2026, 9, 12)
        )
        if rolling
        else resolve_date_range(
            "timeline",
            period=None,
            since="2026-01-01",
            until="2026-08-31",
            today=date(2026, 9, 12),
        )
    )
    return StandaloneLaunch(
        ProcessConfig(),
        StandaloneHostConfig(interval=5),
        TimelineConfig("timeline", date_range, by=by, top=top, other="hide"),
    )
