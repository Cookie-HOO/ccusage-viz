from argparse import Namespace

from ccusage_viz.options import DEFAULT_STYLES


def namespace(**overrides: object) -> Namespace:
    values: dict[str, object] = {
        "command": "timeline",
        "period": None,
        "since": None,
        "until": None,
        "agent": [],
        "model": [],
        "project": [],
        "demo": "small",
        "lang": "en",
        "ccusage_bin": "ccusage",
        "query_timeout": 30.0,
        "ascii": True,
        "by": None,
        "top": None,
        "other": "show",
        "cache": "combined",
        "color_scheme": "classic",
        "style": "linear",
        "window": "1h",
        "interval": None,
        "legend": "below-title",
        "granularity": "day",
        "weekdays": "show",
    }
    values.update(overrides)
    if "style" not in overrides:
        values["style"] = DEFAULT_STYLES[str(values["command"])]
    return Namespace(**values)
