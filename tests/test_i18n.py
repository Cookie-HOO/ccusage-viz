import json

import pytest

from ccusage_viz.errors import UsageError
from ccusage_viz.i18n import detect_language, load_translator
from ccusage_viz.locales import EN_MESSAGES, ZH_MESSAGES


def test_catalogs_have_the_same_keys_and_placeholders() -> None:
    assert EN_MESSAGES.keys() == ZH_MESSAGES.keys()


@pytest.mark.parametrize(
    ("locale_name", "expected"),
    [
        ("zh_CN", "zh"),
        ("zh-Hans-CN", "zh"),
        ("zh_SG", "zh"),
        ("zh_TW", "en"),
        ("zh-Hant", "en"),
        ("en_US", "en"),
        (None, "en"),
    ],
)
def test_locale_detection(
    locale_name: str | None, expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    if locale_name is None:
        monkeypatch.setattr("locale.getlocale", lambda: (None, None))
        assert detect_language() == expected
    else:
        assert detect_language(locale_name) == expected


def test_subcommand_help_language_override(tmp_path) -> None:
    path = tmp_path / "lang.json"
    path.write_text(json.dumps({"help.timeline": "Custom timeline help"}), encoding="utf-8")
    translator = load_translator("en", str(path))
    assert translator.text("help.timeline") == "Custom timeline help"


def test_partial_language_override(tmp_path) -> None:
    path = tmp_path / "lang.json"
    path.write_text(json.dumps({"message.no_data": "Nothing here."}), encoding="utf-8")
    translator = load_translator("en", str(path))
    assert translator.text("message.no_data") == "Nothing here."
    assert translator.text("label.total") == "Total"


def test_placeholder_order_may_change(tmp_path) -> None:
    path = tmp_path / "lang.json"
    path.write_text(
        json.dumps({"error.ccusage_failed": ("{stderr}: {query} failed with exit code {code}")}),
        encoding="utf-8",
    )
    translator = load_translator("en", str(path))
    assert (
        translator.text("error.ccusage_failed", query="daily", code=1, stderr="bad")
        == "bad: daily failed with exit code 1"
    )


def test_summary_fragments_may_be_reordered(tmp_path) -> None:
    path = tmp_path / "lang.json"
    path.write_text(
        json.dumps(
            {
                "summary.line": "{week_over_week} | {today} | {day_over_day}",
                "summary.today": "Today: {value}",
            }
        ),
        encoding="utf-8",
    )
    translator = load_translator("en", str(path))
    assert (
        translator.text(
            "summary.line",
            today="Today: 1M",
            day_over_day="day",
            week_over_week="week",
        )
        == "week | Today: 1M | day"
    )


def test_from_zero_override_requires_current_value(tmp_path) -> None:
    path = tmp_path / "lang.json"
    path.write_text(
        json.dumps({"summary.change.from_zero": "from zero to {value}"}), encoding="utf-8"
    )
    translator = load_translator("en", str(path))
    assert translator.text("summary.change.from_zero", value="1M") == "from zero to 1M"


def test_appearance_picker_placeholders_may_be_reordered(tmp_path) -> None:
    path = tmp_path / "lang.json"
    path.write_text(
        json.dumps(
            {
                "status.appearance_picker_adjust_timeline": (
                    "{style} ({style_index}/{style_count}) · {theme} ({theme_index}/{theme_count}) · {legend_position} · {grouping} · {top} · {other} · {summary}"
                )
            }
        ),
        encoding="utf-8",
    )
    translator = load_translator("en", str(path))
    assert (
        translator.text(
            "status.appearance_picker_adjust_timeline",
            theme_index=2,
            theme_count=10,
            theme="nord",
            style_index=1,
            style_count=4,
            style="linear",
            legend_position="below title",
            grouping="model",
            top=3,
            other="on",
            summary="on",
        )
        == "linear (1/4) · nord (2/10) · below title · model · 3 · on · on"
    )


def test_placeholder_mismatch_rejects_whole_file(tmp_path) -> None:
    path = tmp_path / "lang.json"
    path.write_text(
        json.dumps({"status.demo": "Demo without a placeholder"}),
        encoding="utf-8",
    )
    with pytest.raises(UsageError) as caught:
        load_translator("en", str(path))
    assert caught.value.key == "error.lang_file_placeholders"


def test_unknown_and_duplicate_keys_are_rejected(tmp_path) -> None:
    unknown = tmp_path / "unknown.json"
    unknown.write_text('{"unknown": "x"}', encoding="utf-8")
    with pytest.raises(UsageError, match="error.lang_file_unknown"):
        load_translator("en", str(unknown))

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"label.total": "a", "label.total": "b"}', encoding="utf-8")
    with pytest.raises(UsageError, match="error.lang_file_duplicate"):
        load_translator("en", str(duplicate))
