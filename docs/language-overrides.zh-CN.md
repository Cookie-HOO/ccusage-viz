# 语言覆盖

[English](language-overrides.md)

`--lang-file PATH` 接受一个局部 JSON 对象，Key 必须来自下方目录。值会覆盖由 `--lang` 或系统 Locale 检测选中的内置语言文案。

```bash
ccusage-viz timeline --lang zh --lang-file examples/language-overrides.json
```

## 校验规则

文件可以只提供任意一部分已知 Key；未提供的 Key 继承所选内置语言。所提供的部分只有全部满足以下规则才会原子生效：

- 内容为 UTF-8 文本和有效 JSON；
- JSON 顶层为对象；
- 不含重复或未知 Key；
- 每个值都是非空字符串；
- 每个值使用与内置文案完全相同的占位符名称、转换和格式说明；命名占位符可以调整顺序。

占位符名称、转换和格式说明必须完全匹配；顺序可以调整。摘要片段也可以重新排序。

```json
{
  "summary.line": "{week_over_week} · {today} · {day_over_day}",
  "summary.today": "今日：{value}",
  "summary.day_over_day": "较昨日：{relation}",
  "summary.week_over_week": "较上周{weekday}：{relation}"
}
```

Watch 进程只加载一次文件。覆盖文件自身无效时，诊断使用所选内置语言；文件成功加载后，运行时诊断使用当前覆盖文案。

`ccusage` 提供的 Agent、模型、项目和原始 stderr 等值不由此目录翻译。

## 完整 Key 参考

`—` 表示值中不能有占位符。文字与标点可调整；占位符名称、转换和格式说明必须保持一致。

| Key | 占位符 |
| --- | --- |
| `app.description` | — |
| `help.command` | — |
| `help.timeline` | — |
| `help.calendar` | — |
| `help.stack` | — |
| `help.ranking` | — |
| `help.monitor` | — |
| `help.days` | — |
| `help.since` | — |
| `help.until` | — |
| `help.timezone` | — |
| `help.agent` | — |
| `help.model` | — |
| `help.project` | — |
| `help.by` | — |
| `help.top` | — |
| `help.show_other` | — |
| `help.theme` | — |
| `help.split_cache` | — |
| `help.no_summary` | — |
| `help.watch` | — |
| `help.demo` | — |
| `help.pick` | — |
| `help.style` | — |
| `help.window` | — |
| `help.interval` | — |
| `help.monitor_by` | — |
| `help.monitor_top` | — |
| `help.lang` | — |
| `help.lang_file` | — |
| `help.ccusage_bin` | — |
| `help.no_color` | — |
| `help.ascii` | — |
| `error.arguments` | `{detail}` |
| `error.days_positive` | — |
| `error.top_positive` | — |
| `error.watch_min` | `{minimum}` |
| `error.top_requires_by` | — |
| `error.monitor_pick` | — |
| `error.monitor_demo_pick` | — |
| `error.interval_min` | `{minimum}` |
| `error.style_incompatible` | `{mode}`, `{style}` |
| `error.window_invalid` | `{value}` |
| `error.window_range` | — |
| `error.date_invalid` | `{value}` |
| `error.date_conflict` | — |
| `error.date_order` | — |
| `error.future_until` | — |
| `error.timezone` | `{value}` |
| `error.tty` | — |
| `error.terminal_size` | `{command}`, `{height}`, `{minimum_height}`, `{minimum_width}`, `{width}` |
| `error.stack_grouped_width` | `{width}` |
| `error.ccusage_missing` | `{binary}` |
| `error.ccusage_start` | `{detail}`, `{query}` |
| `error.ccusage_failed` | `{code}`, `{query}`, `{stderr}` |
| `error.ccusage_timeout` | `{query}`, `{seconds}` |
| `error.ccusage_cancelled` | `{query}` |
| `error.ccusage_utf8` | `{query}` |
| `error.ccusage_json` | `{query}` |
| `error.schema` | `{path}`, `{reason}` |
| `error.selector_no_match` | `{dimension}`, `{selector}` |
| `error.selector_ambiguous` | `{candidates}`, `{dimension}`, `{selector}` |
| `error.selector_ambiguous_more` | `{candidates}`, `{dimension}`, `{remaining}`, `{selector}` |
| `error.lang_file_read` | `{detail}`, `{path}` |
| `error.lang_file_json` | `{detail}`, `{path}` |
| `error.lang_file_object` | — |
| `error.lang_file_duplicate` | `{key}` |
| `error.lang_file_unknown` | `{key}` |
| `error.lang_file_value` | `{key}` |
| `error.lang_file_placeholders` | `{key}`, `{placeholders}` |
| `notice.daily_project_omitted` | `{agent}` |
| `notice.project_agent_omitted` | `{agent}` |
| `notice.selected_no_data` | `{dimension}`, `{values}` |
| `notice.model_breakdown_missing` | — |
| `notice.other_not_needed` | `{count}`, `{top}` |
| `status.loading` | — |
| `status.refreshing` | — |
| `status.paused` | — |
| `status.updated` | `{time}` |
| `status.refresh_every` | `{seconds}` |
| `status.query_time` | `{seconds}` |
| `status.demo` | `{size}` |
| `status.appearance_picker` | `{style}`, `{style_count}`, `{style_index}`, `{theme}`, `{theme_count}`, `{theme_index}` |
| `status.appearance_picker_keys` | — |
| `status.command_copied` | — |
| `status.command_copy_failed` | — |
| `status.keys` | — |
| `status.demo_keys` | — |
| `status.monitor_controls` | — |
| `status.monitor_sampling` | `{seconds}` |
| `status.monitor_source` | `{seconds}`, `{source}` |
| `status.monitor_paused` | `{seconds}`, `{state}` |
| `status.monitor_adjust` | `{interval}`, `{mode}`, `{style}`, `{theme}`, `{top}`, `{window}` |
| `status.monitor_adjust_keys` | — |
| `message.no_data` | — |
| `message.monitor_empty` | — |
| `label.monitor_title` | `{agents}`, `{mode}`, `{state}`, `{window}` |
| `label.monitor_baseline` | — |
| `label.monitor_samples` | — |
| `label.monitor_observed` | — |
| `label.monitor_total_mode` | — |
| `label.monitor_model_mode` | — |
| `label.monitor_all` | — |
| `label.total` | — |
| `label.other` | — |
| `label.input` | — |
| `label.output` | — |
| `label.cache` | — |
| `label.cache_read` | — |
| `label.cache_creation` | — |
| `label.active_days` | `{count}` |
| `label.current_streak` | `{count}` |
| `label.longest_streak` | `{count}` |
| `label.peak` | `{date}`, `{value}` |
| `label.average` | `{value}` |
| `label.timeline` | — |
| `label.calendar` | — |
| `label.stack` | — |
| `label.ranking` | — |
| `label.by` | `{dimension}` |
| `label.agent` | — |
| `label.model` | — |
| `label.project` | — |
| `label.date_range` | `{since}`, `{until}` |
| `summary.line` | `{day_over_day}`, `{today}`, `{week_over_week}` |
| `summary.today` | `{value}` |
| `summary.day_over_day` | `{relation}` |
| `summary.week_over_week` | `{relation}`, `{weekday}` |
| `summary.change.increase` | `{percent}` |
| `summary.change.decrease` | `{percent}` |
| `summary.change.unchanged` | — |
| `summary.change.from_zero` | `{value}` |
| `calendar.month.1` | — |
| `calendar.month.2` | — |
| `calendar.month.3` | — |
| `calendar.month.4` | — |
| `calendar.month.5` | — |
| `calendar.month.6` | — |
| `calendar.month.7` | — |
| `calendar.month.8` | — |
| `calendar.month.9` | — |
| `calendar.month.10` | — |
| `calendar.month.11` | — |
| `calendar.month.12` | — |
| `calendar.weekday.0` | — |
| `calendar.weekday.1` | — |
| `calendar.weekday.2` | — |
| `calendar.weekday.3` | — |
| `calendar.weekday.4` | — |
| `calendar.weekday.5` | — |
| `calendar.weekday.6` | — |

权威内置文案位于 `src/ccusage_viz/locales/en.py` 和 `src/ccusage_viz/locales/zh.py`。测试要求两个目录公开相同的 Key 与占位符签名。
