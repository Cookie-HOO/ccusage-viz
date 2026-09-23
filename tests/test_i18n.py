import pytest

from ccusage_viz.i18n import detect_language
from ccusage_viz.locales import EN_MESSAGES, ZH_MESSAGES


def test_catalogs_have_the_same_keys_and_placeholders() -> None:
    assert EN_MESSAGES.keys() == ZH_MESSAGES.keys()
    assert EN_MESSAGES["label.monitor_sampling"] == "sampling"
    assert ZH_MESSAGES["label.monitor_sampling"] == "采样中"
    assert EN_MESSAGES["help.grid"] == "Pane grid: ROWSxCOLUMNS"
    assert ZH_MESSAGES["help.grid"] == "Pane 网格：ROWSxCOLUMNS"
    assert "spotlight-wide2" in EN_MESSAGES["help.dashboard_preset"]
    assert "spotlight-wide2" in ZH_MESSAGES["help.dashboard_preset"]
    assert "spotlight-" + "tall" not in EN_MESSAGES["help.dashboard_preset"]
    assert "spotlight-" + "tall" not in ZH_MESSAGES["help.dashboard_preset"]
    assert "spotlight-monitor" not in EN_MESSAGES["help.dashboard_preset"]
    assert "spotlight-monitor" not in ZH_MESSAGES["help.dashboard_preset"]
    assert EN_MESSAGES["help.layout"] == "Named Pane topology: auto or a spotlight layout"
    assert ZH_MESSAGES["help.layout"] == "具名 Pane 拓扑：auto 或 Spotlight 布局"
    assert "Advanced" not in EN_MESSAGES["status.tui_global_quick_controls"]
    assert "高级" not in ZH_MESSAGES["status.tui_global_quick_controls"]
    assert "status.tui_global_advanced_controls" not in EN_MESSAGES
    assert EN_MESSAGES["label.monitor_distribution_hour"] == "Hourly"
    assert ZH_MESSAGES["label.monitor_distribution_hour"] == "每小时"
    assert EN_MESSAGES["label.monitor_distribution_half-hour"] == "30 min"
    assert ZH_MESSAGES["label.monitor_distribution_half-hour"] == "30分钟"
    assert EN_MESSAGES["label.monitor_distribution_unobserved"] == "not observed"
    assert ZH_MESSAGES["label.monitor_distribution_unobserved"] == "未观测"


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
        monkeypatch.setattr("locale.getlocale", lambda: (None))
        assert detect_language() == expected
    else:
        assert detect_language(locale_name) == expected
