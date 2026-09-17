from __future__ import annotations

from collections import Counter
from collections.abc import Hashable, Iterable
from dataclasses import dataclass
from hashlib import blake2b

Color = int


@dataclass(frozen=True, slots=True)
class ColorScheme:
    categorical: tuple[Color, ...]
    calendar: tuple[Color, Color, Color, Color]
    other: Color
    input: Color
    output: Color
    cache: Color
    cache_read: Color
    cache_creation: Color
    highlight: Color

    @property
    def summary_value(self) -> Color:
        return self.highlight

    @property
    def trend_increase(self) -> Color:
        return self.cache

    @property
    def trend_decrease(self) -> Color:
        return self.cache_creation

    @property
    def trend_neutral(self) -> Color:
        return self.other

    @property
    def muted(self) -> Color:
        return self.other

    def component(self, name: str) -> Color:
        return {
            "input": self.input,
            "output": self.output,
            "cache": self.cache,
            "cache_read": self.cache_read,
            "cache_creation": self.cache_creation,
            "other": self.other,
        }[name]


_SCHEMES = {
    "classic": ColorScheme(
        (33, 208, 36, 170, 69, 166, 37, 100),
        (153, 74, 32, 24),
        245,
        33,
        208,
        37,
        170,
        166,
        214,
    ),
    "vivid": ColorScheme(
        (39, 208, 46, 201, 226, 93, 51, 196),
        (117, 75, 33, 21),
        250,
        39,
        208,
        46,
        201,
        226,
        213,
    ),
    "contrast": ColorScheme(
        (21, 214, 34, 201, 226, 93, 196, 51),
        (159, 75, 27, 18),
        250,
        21,
        214,
        34,
        201,
        226,
        213,
    ),
    "dracula": ColorScheme(
        (69, 131, 35, 169, 104, 197, 132, 62),
        (189, 147, 105, 57),
        246,
        69,
        131,
        35,
        169,
        104,
        169,
    ),
    "catppuccin": ColorScheme(
        (69, 167, 68, 135, 168, 104, 169, 99),
        (189, 153, 111, 69),
        246,
        69,
        167,
        68,
        104,
        135,
        135,
    ),
    "solarized": ColorScheme(
        (32, 167, 100, 168, 136, 31, 166, 62),
        (159, 75, 33, 24),
        244,
        32,
        167,
        100,
        31,
        136,
        136,
    ),
    "gruvbox": ColorScheme(
        (104, 167, 136, 169, 166, 132, 197, 130),
        (223, 179, 136, 94),
        245,
        104,
        167,
        136,
        132,
        169,
        166,
    ),
    "nord": ColorScheme(
        (97, 168, 68, 135, 167, 104, 131, 98),
        (195, 153, 110, 67),
        245,
        97,
        168,
        68,
        104,
        135,
        135,
    ),
    "github": ColorScheme(
        (26, 166, 71, 98, 162, 160, 30, 136),
        (151, 77, 71, 23),
        245,
        26,
        166,
        71,
        30,
        98,
        26,
    ),
    "mono": ColorScheme(
        (255, 252, 249, 246, 243, 240, 237, 234),
        (250, 246, 242, 238),
        243,
        255,
        249,
        246,
        246,
        240,
        255,
    ),
    # Rendering suppresses ANSI for this explicit theme. Reusing the classic
    # semantic map keeps non-color layout and mark selection unchanged.
    "no-color": ColorScheme(
        (33, 208, 36, 170, 69, 166, 37, 100),
        (153, 74, 32, 24),
        245,
        33,
        208,
        37,
        170,
        166,
        214,
    ),
}

COLOR_SCHEMES = tuple(_SCHEMES)
CATEGORICAL = _SCHEMES["classic"].categorical
CALENDAR_LEVELS = _SCHEMES["classic"].calendar

SUMMARY_VALUE_COLOR = 45
SUMMARY_INCREASE_COLOR = 35
SUMMARY_DECREASE_COLOR = 166
WARNING_COLOR = 130


def get_color_scheme(name: str) -> ColorScheme:
    return _SCHEMES[name]


def _stable_key_bytes(key: Hashable) -> bytes:
    if isinstance(key, str):
        value = key.encode()
        return b"str:" + len(value).to_bytes(8, "big") + value
    if isinstance(key, tuple):
        parts = tuple(_stable_key_bytes(item) for item in key)
        return b"tuple:" + b"".join(len(part).to_bytes(8, "big") + part for part in parts)
    value = repr(key).encode()
    type_name = f"{type(key).__module__}.{type(key).__qualname__}".encode()
    return b"repr:" + len(type_name).to_bytes(8, "big") + type_name + value


def _slot(key: Hashable, size: int, *, person: bytes = b"ccusage") -> int:
    digest = blake2b(_stable_key_bytes(key), digest_size=8, person=person).digest()
    return int.from_bytes(digest, "big") % size


def categorical_color(key: Hashable, index: int = 0, scheme: str = "classic") -> Color:
    del index
    palette = get_color_scheme(scheme).categorical
    return palette[_slot(key, len(palette))]


def categorical_colors(keys: Iterable[Hashable], scheme: str = "classic") -> dict[Hashable, Color]:
    palette = get_color_scheme(scheme).categorical
    unique = tuple(dict.fromkeys(keys))
    homes = {key: _slot(key, len(palette)) for key in unique}
    counts = Counter(homes.values())
    slots: dict[Hashable, int] = {}
    used: set[int] = set()

    for key in sorted(unique, key=_stable_key_bytes):
        home = homes[key]
        if counts[home] == 1:
            slots[key] = home
            used.add(home)

    for key in sorted((key for key in unique if key not in slots), key=_stable_key_bytes):
        home = homes[key]
        if len(used) < len(palette):
            offset = _slot(key, len(palette), person=b"ccprobe")
            candidates = ((home + offset + step) % len(palette) for step in range(len(palette)))
            slot = next(candidate for candidate in candidates if candidate not in used)
            used.add(slot)
        else:
            slot = home
        slots[key] = slot
    return {key: palette[slots[key]] for key in unique}
