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
    assert "H header" in EN_MESSAGES["status.tui_global_quick_controls"]
    assert "p summary period" in EN_MESSAGES["status.tui_global_quick_controls"]
    assert "H 页眉" in ZH_MESSAGES["status.tui_global_quick_controls"]
    assert "p 摘要周期" in ZH_MESSAGES["status.tui_global_quick_controls"]
    assert (
        EN_MESSAGES["status.tui_global_operations"]
        == "Global operations: u undo · U redo · h open help"
    )
    assert ZH_MESSAGES["status.tui_global_operations"] == "全局操作：u 撤销 · U 重做 · h 打开帮助"
    assert " d adjust dashboard " in EN_MESSAGES["status.tui_chart_controls"]
    assert " d 调整仪表盘 " in ZH_MESSAGES["status.tui_chart_controls"]
    assert EN_MESSAGES["status.tui_pane_management_divider"] == "━━ Dashboard Pane Management ━━"
    assert ZH_MESSAGES["status.tui_pane_management_divider"] == "━━ Dashboard 子图管理 ━━"
    assert EN_MESSAGES["label.adjust_replace"] == "replace"
    assert ZH_MESSAGES["label.adjust_replace"] == "替换"
    assert EN_MESSAGES["label.adjust_next_pane"] == "select next"
    assert ZH_MESSAGES["label.adjust_next_pane"] == "选择下一项"
    assert "status.tui_help_modes" not in EN_MESSAGES
    assert "status.tui_help_current" not in EN_MESSAGES
    for mode in ("browse", "pane", "global"):
        assert f"status.tui_help_{mode}_enter" in EN_MESSAGES
        assert f"status.tui_help_{mode}_exit" in EN_MESSAGES
        assert "—" not in EN_MESSAGES[f"status.tui_help_{mode}_label"]
        assert "—" not in ZH_MESSAGES[f"status.tui_help_{mode}_label"]
    for key in (
        "status.tui_help_mode",
        "status.tui_help_mode_pages",
        "status.tui_help_pane_settings",
        "status.tui_help_pane_content",
        "status.tui_help_pane_structure",
        "status.tui_help_dashboard_settings",
        "status.tui_help_parameter_quick",
        "status.tui_help_parameter_advanced",
        "status.tui_help_interval_dashboard",
        "status.tui_help_section_policy",
        "status.tui_help_summary_scope",
        "status.tui_help_summary_scope_fixed",
        "status.tui_help_summary_scope_filters",
        "status.tui_help_summary_comparisons",
        "status.tui_help_summary_comparisons_day",
        "status.tui_help_summary_comparisons_month_quarter",
        "status.tui_help_summary_comparisons_year",
        "status.tui_help_browse_hint",
        "status.tui_help_animation_hint",
        "status.tui_help_interval_monitor",
        "status.tui_help_animation_schedule",
        "status.tui_help_chooser_selected",
        "status.tui_help_common",
        "status.tui_help_content_insert",
        "status.tui_help_structure_move",
        "status.tui_help_layout_chooser",
        "status.tui_help_grid_editor",
        "status.tui_help_tip",
        "status.tui_help_text_navigation",
        "status.tui_help_editor_title",
        "status.tui_help_editor_close",
        "status.tui_help_editor_source",
        "status.tui_help_editor_source_text",
        "status.tui_help_editor_source_command",
        "status.tui_help_editor_source_switch",
        "status.tui_help_editor_navigation",
        "status.tui_help_editor_navigation_detail",
        "status.tui_help_editor_draft",
        "status.tui_help_editor_draft_detail",
        "status.tui_help_editor_complete",
        "status.tui_help_editor_complete_detail",
        "status.tui_help_editor_dashboard",
        "status.tui_help_editor_dashboard_height",
    ):
        assert key in EN_MESSAGES
        assert key in ZH_MESSAGES
    assert EN_MESSAGES["status.tui_help_pane_settings"] == "Pane parameter adjustment"
    assert ZH_MESSAGES["status.tui_help_pane_settings"] == "Pane 参数调整"
    assert EN_MESSAGES["status.tui_help_pane_structure"] == "Structure adjustment"
    assert ZH_MESSAGES["status.tui_help_pane_structure"] == "结构调整"
    assert EN_MESSAGES["status.tui_help_close"].startswith("Enter/Esc/h close")
    assert ZH_MESSAGES["status.tui_help_close"].startswith("Enter/Esc/h 关闭")
    assert "10 min" in EN_MESSAGES["status.tui_help_tip"]
    assert "10 分钟" in ZH_MESSAGES["status.tui_help_tip"]
    for key in (
        "status.overlay_editor_controls_navigation",
        "status.overlay_editor_controls_draft",
        "status.overlay_editor_controls_complete",
        "status.overlay_editor_controls_dashboard_overall",
    ):
        assert key in EN_MESSAGES
        assert key in ZH_MESSAGES
    assert "Ctrl-A home" in EN_MESSAGES["status.overlay_editor_controls_navigation"]
    assert "Ctrl-B previous word" in EN_MESSAGES["status.overlay_editor_controls_navigation"]
    assert "Ctrl-W next word" in EN_MESSAGES["status.overlay_editor_controls_navigation"]
    assert "Ctrl-A 行首" in ZH_MESSAGES["status.overlay_editor_controls_navigation"]
    assert "Ctrl-B 上个词" in ZH_MESSAGES["status.overlay_editor_controls_navigation"]
    assert "Ctrl-W 下个词" in ZH_MESSAGES["status.overlay_editor_controls_navigation"]
    assert "Tab switch source" in EN_MESSAGES["status.overlay_editor_controls_draft"]
    assert "Ctrl-H help" in EN_MESSAGES["status.overlay_editor_controls_draft"]
    assert "DEL delete" not in EN_MESSAGES["status.overlay_editor_controls_draft"]
    assert "Ctrl-U clear" in EN_MESSAGES["status.overlay_editor_controls_draft"]
    assert "Tab 切换来源" in ZH_MESSAGES["status.overlay_editor_controls_draft"]
    assert "Ctrl-H 帮助" in ZH_MESSAGES["status.overlay_editor_controls_draft"]
    assert "DEL 删除" not in ZH_MESSAGES["status.overlay_editor_controls_draft"]
    assert "Ctrl-U 清空" in ZH_MESSAGES["status.overlay_editor_controls_draft"]
    assert "OVERALL" in EN_MESSAGES["status.overlay_editor_controls_dashboard_overall"]
    assert "pane width" not in EN_MESSAGES["status.overlay_editor_controls_dashboard_overall"]
    assert "Ctrl-J / Ctrl-K" in EN_MESSAGES["status.overlay_editor_controls_dashboard_overall"]
    assert "整体" in ZH_MESSAGES["status.overlay_editor_controls_dashboard_overall"]
    assert "子图宽度" not in ZH_MESSAGES["status.overlay_editor_controls_dashboard_overall"]
    assert "Ctrl-J / Ctrl-K" in ZH_MESSAGES["status.overlay_editor_controls_dashboard_overall"]
    assert "status.tui_help_editor_detail" not in EN_MESSAGES
    assert EN_MESSAGES["status.tui_help_editor_source_text"] == (
        "TEXT MODE: edit literal content displayed directly"
    )
    assert "COMMAND MODE" in EN_MESSAGES["status.tui_help_editor_source_command"]
    assert (
        "shell command whose stdout is displayed"
        in EN_MESSAGES["status.tui_help_editor_source_command"]
    )
    assert ZH_MESSAGES["status.tui_help_editor_source_text"] == "文本模式：编辑直接显示的字面内容"
    assert "命令模式" in ZH_MESSAGES["status.tui_help_editor_source_command"]
    assert "输出 stdout 的 Shell 命令" in ZH_MESSAGES["status.tui_help_editor_source_command"]
    assert "Ctrl-B/Ctrl-W word" in EN_MESSAGES["status.tui_help_editor_navigation_detail"]
    assert "Ctrl-H help" in EN_MESSAGES["status.tui_help_editor_draft_detail"]
    assert "Enter apply active source" in EN_MESSAGES["status.tui_help_editor_complete_detail"]
    assert "Ctrl-B/Ctrl-W 词语" in ZH_MESSAGES["status.tui_help_editor_navigation_detail"]
    assert "Ctrl-H 帮助" in ZH_MESSAGES["status.tui_help_editor_draft_detail"]
    assert "Enter 应用当前来源" in ZH_MESSAGES["status.tui_help_editor_complete_detail"]
    assert "Ctrl-J/Ctrl-K" in EN_MESSAGES["status.tui_help_editor_dashboard_height"]
    assert "子图高度" in ZH_MESSAGES["status.tui_help_editor_dashboard_height"]
    assert EN_MESSAGES["status.overlay_editor_cleared"] == "Draft cleared"
    assert ZH_MESSAGES["status.overlay_editor_cleared"] == "草稿已清空"
    assert "Dashboard undo/redo history" in EN_MESSAGES["status.tui_help_tip"]
    assert "仪表盘撤销/重做历史" in ZH_MESSAGES["status.tui_help_tip"]
    assert "30 seconds" not in EN_MESSAGES["status.tui_help_interval_dashboard"]
    assert "30 秒" not in ZH_MESSAGES["status.tui_help_interval_dashboard"]
    assert all("30 seconds" not in EN_MESSAGES[key] for key in EN_MESSAGES if "editor" in key)
    assert all("30 秒" not in ZH_MESSAGES[key] for key in ZH_MESSAGES if "editor" in key)
    assert "30 seconds" in EN_MESSAGES["status.tui_help_browse_hint"]
    assert "30 秒" in ZH_MESSAGES["status.tui_help_browse_hint"]
    assert "Dashboard Pane adjustment" in EN_MESSAGES["status.tui_help_mode_pages_detail"]
    assert "trailing periods" not in EN_MESSAGES["status.tui_help_mode_pages_detail"]
    assert "Dashboard 子图调整" in ZH_MESSAGES["status.tui_help_mode_pages_detail"]
    assert "尾随周期" not in ZH_MESSAGES["status.tui_help_mode_pages_detail"]
    assert "p trailing presets (7d, 14d" in EN_MESSAGES["status.tui_help_parameter_period"]
    assert (
        "P cycles project label detail"
        in EN_MESSAGES["status.tui_help_parameter_project_label_context"]
    )
    assert "p 切换尾随预设（7d、14d" in ZH_MESSAGES["status.tui_help_parameter_period"]
    assert "P 切换项目名称细节" in ZH_MESSAGES["status.tui_help_parameter_project_label_context"]
    assert EN_MESSAGES["status.tui_help_section_policy"] == "STRATEGY"
    assert ZH_MESSAGES["status.tui_help_section_policy"] == "策略"
    assert EN_MESSAGES["status.tui_help_summary_scope"] == "SUMMARY SCOPE [COMPUTATION LOGIC]"
    assert ZH_MESSAGES["status.tui_help_summary_scope"] == "摘要统计 [计算逻辑]"
    assert EN_MESSAGES["status.tui_help_summary_comparisons"] == (
        "COMPARISON WINDOWS [COMPUTATION LOGIC]"
    )
    assert ZH_MESSAGES["status.tui_help_summary_comparisons"] == "对比区间 [计算逻辑]"
    assert "selected-range total only" in EN_MESSAGES["status.tui_help_summary_scope_fixed"]
    assert "grouping, Top N, and Other" in EN_MESSAGES["status.tui_help_summary_scope_filters"]
    assert "same weekday 7 days earlier" in EN_MESSAGES["status.tui_help_summary_comparisons_day"]
    assert "equal elapsed days" in EN_MESSAGES["status.tui_help_summary_comparisons_month_quarter"]
    assert (
        EN_MESSAGES["status.tui_help_summary_comparisons_year"]
        == "Year: prior-year elapsed days only"
    )
    assert "仅显示所选范围总量" in ZH_MESSAGES["status.tui_help_summary_scope_fixed"]
    assert (
        "分组、Top N 和其他仅影响展示序列" in ZH_MESSAGES["status.tui_help_summary_scope_filters"]
    )
    assert "7 天前同一星期几" in ZH_MESSAGES["status.tui_help_summary_comparisons_day"]
    assert "等长已过天数" in ZH_MESSAGES["status.tui_help_summary_comparisons_month_quarter"]
    assert ZH_MESSAGES["status.tui_help_summary_comparisons_year"] == "年：仅对比去年已过天数"
    assert "Tip" not in EN_MESSAGES["status.tui_help_tip"]
    assert "💡" not in ZH_MESSAGES["status.tui_help_tip"]
    assert EN_MESSAGES["status.tui_history_empty_undo"] == "nothing to undo"
    assert ZH_MESSAGES["status.tui_history_empty_redo"] == "没有可重做的操作"
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
        == "Space pause/resume · t/T switch selected theme"
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
