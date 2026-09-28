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
    assert "wide-clock" in EN_MESSAGES["help.dashboard_preset"]
    assert "wide-clock" in ZH_MESSAGES["help.dashboard_preset"]
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
    assert EN_MESSAGES["animation.compact"] == "{style} · expand terminal to play"
    assert ZH_MESSAGES["animation.projection_failed"] == "{style} · 动画不可用"
    assert (
        EN_MESSAGES["status.monitor_attachment_settings"] == " · ANIMATION {style} · THEME {theme}"
    )
    assert ZH_MESSAGES["status.monitor_attachment_settings"] == " · 动画 {style} · 主题 {theme}"
    assert (
        EN_MESSAGES["status.animation_gallery_controls"]
        == "Space pause/resume · t/T selected theme"
    )
    assert ZH_MESSAGES["status.animation_gallery_controls"] == "Space 暂停/继续 · t/T 切换选中主题"
    assert EN_MESSAGES["status.pause"] == "pause"
    assert ZH_MESSAGES["status.resume"] == "继续"
    assert EN_MESSAGES["status.paused"] == "paused"
    assert ZH_MESSAGES["status.paused"] == "已暂停"
    assert EN_MESSAGES["status.animation_paused"] == "paused"
    assert ZH_MESSAGES["status.animation_paused"] == "已暂停"
    assert EN_MESSAGES["status.dashboard_paused"] == "paused"
    assert ZH_MESSAGES["status.dashboard_paused"] == "已暂停"


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
