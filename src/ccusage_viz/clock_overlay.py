"""Built-in dynamic text presets."""

from __future__ import annotations

import argparse
from datetime import datetime

from ccusage_viz.animation_overlay import time_band_key
from ccusage_viz.i18n import detect_language, load_translator


def render_time_state(language: str) -> str:
    """Return the localized status associated with the local time of day."""

    translator = load_translator(language)
    return translator.text(time_band_key(datetime.now().astimezone()))


def describe_time_state(language: str) -> str:
    """Return a localized description of the local time status preset."""

    return load_translator(language).text("text.time_state_description")


def time_state_overlay_command(launcher: str = "ccuv") -> str:
    """Return the command source used by built-in animation clock overlays."""

    return f"{launcher} text time-state --run"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("preset", choices=("time-state",))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_const", const="run", dest="mode")
    mode.add_argument("--describe", action="store_const", const="describe", dest="mode")
    parser.add_argument("--lang", choices=("en", "zh"))
    namespace = parser.parse_args(argv)
    language = namespace.lang or detect_language()
    if namespace.mode == "describe":
        print(describe_time_state(language))
    else:
        print(render_time_state(language))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
