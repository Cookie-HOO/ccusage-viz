# Language overrides

[简体中文](language-overrides.zh-CN.md)

`--lang-file PATH` accepts a partial JSON object whose keys are selected from the catalog below. Values replace messages from the language selected by `--lang` or system-locale detection.

```bash
ccuv timeline --lang en --lang-file examples/language-overrides.json
```

## Validation

The file may contain any subset of known keys; omitted keys inherit from the selected built-in language. The supplied subset is rejected atomically unless all of these rules pass:

- UTF-8 text containing valid JSON;
- a JSON object at the root;
- no duplicate or unknown keys;
- every value is a non-empty string;
- each value uses exactly the same placeholder names, conversions, and format specifications as the built-in message; named placeholders may be reordered.

Placeholder names, conversions, and format specifications must match exactly; order may change. Summary fragments may also be reordered.

```json
{
  "summary.line": "[{comparisons}]",
  "summary.separator": " · ",
  "summary.current.month": "Month to date: {value}",
  "summary.sequential.month": "vs prior MTD: {relation}",
  "summary.year_over_year.month": "vs last year: {relation}"
}
```

A Watch process loads the file once. Invalid-file diagnostics use the selected built-in language; after a valid load, runtime diagnostics use the active overrides.

Values supplied by `ccusage`—including Agent, model, project, and raw stderr text—are not translated by this catalog.

## Complete key reference

`—` means the value must contain no placeholders. Literal wording and punctuation may change; placeholder names, conversions, and format specifications must remain the same.

| Key | Placeholders |
| --- | --- |
| `app.description` | — |
| `help.command` | — |
| `help.timeline` | — |
| `help.calendar` | — |
| `help.stack` | — |
| `help.ranking` | — |
| `help.monitor` | — |
| `help.dashboard` | — |
| `help.panel` | — |
| `help.grid` | — |
| `help.header_style` | — |
| `help.header_summary` | — |
| `help.header_interval` | — |
| `help.period` | — |
| `help.since` | — |
| `help.until` | — |
| `help.timezone` | — |
| `help.aggregate` | — |
| `help.weekdays` | — |
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
| `help.legend_position` | — |
| `help.window` | — |
| `help.interval` | — |
| `help.monitor_by` | — |
| `help.monitor_top` | — |
| `help.lang` | — |
| `help.lang_file` | — |
| `help.ccusage_bin` | — |
| `help.ascii` | — |
| `error.arguments` | `{detail}` |
| `error.top_positive` | — |
| `error.watch_min` | `{minimum}` |
| `error.top_requires_by` | — |
| `error.monitor_pick` | — |
| `error.monitor_demo_pick` | — |
| `error.interval_min` | `{minimum}` |
| `error.style_incompatible` | `{mode}`, `{style}` |
| `error.show_other_requires_top` | — |
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
| `error.npm_missing` | — |
| `error.ccusage_install_start` | `{detail}` |
| `error.ccusage_install_failed` | `{code}` |
| `error.ccusage_install_path` | — |
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
| `notice.model_overattributed` | — |
| `notice.other_not_needed` | `{count}`, `{top}` |
| `notice.summary_excludes_session_agent` | `{agent}` |
| `prompt.ccusage_install` | `{command}` |
| `prompt.ccusage_install_confirm` | — |
| `status.loading` | — |
| `status.refreshing` | — |
| `status.paused` | — |
| `status.updated` | `{time}` |
| `status.refresh_every` | `{seconds}` |
| `status.query_time` | `{seconds}` |
| `status.demo` | `{size}` |
| `status.appearance_picker` | `{style}`, `{style_count}`, `{style_index}`, `{theme}`, `{theme_count}`, `{theme_index}` |
| `status.appearance_picker_adjust_timeline_quick` | `{grouping}`, `{style}`, `{style_count}`, `{style_index}`, `{theme}`, `{theme_count}`, `{theme_index}`, `{top}` |
| `status.appearance_picker_adjust_timeline_advanced` | `{legend_position}`, `{other}`, `{summary}`, `{weekday}` |
| `status.appearance_picker_adjust_calendar_quick` | `{style}`, `{style_count}`, `{style_index}`, `{theme}`, `{theme_count}`, `{theme_index}` |
| `status.appearance_picker_adjust_calendar_advanced` | `{summary}` |
| `status.appearance_picker_adjust_stack_quick` | `{style}`, `{style_count}`, `{style_index}`, `{theme}`, `{theme_count}`, `{theme_index}` |
| `status.appearance_picker_adjust_stack_advanced` | `{cache}`, `{legend_position}`, `{summary}`, `{weekday}` |
| `status.appearance_picker_adjust_ranking_quick` | `{grouping}`, `{style}`, `{style_count}`, `{style_index}`, `{theme}`, `{theme_count}`, `{theme_index}`, `{top}` |
| `status.appearance_picker_adjust_ranking_advanced` | `{other}`, `{summary}` |
| `status.appearance_picker_keys_timeline` | — |
| `status.appearance_picker_keys_calendar` | — |
| `status.appearance_picker_keys_stack` | — |
| `status.appearance_picker_keys_ranking` | — |
| `status.appearance_picker_style_keys` | — |
| `status.command_copied` | — |
| `status.command_copy_failed` | — |
| `status.project_preview_missing` | — |
| `status.keys` | — |
| `status.demo_keys` | — |
| `status.monitor_controls` | — |
| `status.tui` | `{state}` |
| `status.tui_pane_controls` | — |
| `status.tui_running` | — |
| `status.tui_adjust_quick` | — |
| `status.tui_adjust_advanced` | — |
| `status.tui_adjust_timeline_quick_controls` | — |
| `status.tui_adjust_timeline_advanced_controls` | — |
| `status.tui_adjust_calendar_quick_controls` | — |
| `status.tui_adjust_calendar_advanced_controls` | — |
| `status.tui_adjust_stack_quick_controls` | — |
| `status.tui_adjust_stack_advanced_controls` | — |
| `status.tui_adjust_ranking_quick_controls` | — |
| `status.tui_adjust_ranking_advanced_controls` | — |
| `status.tui_adjust_monitor_quick_controls` | — |
| `status.tui_adjust_monitor_advanced_controls` | — |
| `status.tui_adjust_management` | — |
| `status.tui_dashboard` | `{layout}` |
| `status.tui_adjust_history` | — |
| `status.tui_dashboard_adjust` | — |
| `status.tui_dashboard_adjust_multiple` | — |
| `status.tui_finish` | — |
| `status.tui_adjust_monitor` | — |
| `status.tui_adjust_monitor_pending` | — |
| `status.tui_layout_prompt` | `{value}` |
| `status.tui_layout_controls` | — |
| `status.tui_hidden` | — |
| `status.tui_add_title` | — |
| `status.tui_add_controls` | — |
| `status.tui_adjust_title` | — |
| `status.tui_adjust_controls` | — |
| `status.tui_inline_adjust` | — |
| `error.tui_grid` | `{value}` |
| `error.tui_grid_runtime` | `{count}`, `{value}` |
| `error.tui_grid_full` | `{layout}` |
| `error.tui_panel` | `{value}` |
| `status.monitor_sampling` | `{interval}`, `{seconds}` |
| `status.monitor_sampling_prefix` | `{interval}`, `{seconds}` |
| `status.monitor_sampling_active` | — |
| `status.monitor_source` | `{interval}`, `{source}`, `{state}` |
| `status.monitor_paused` | `{interval}`, `{source}`, `{state}` |
| `status.monitor_adjust_quick` | `{interval}`, `{mode}`, `{style}`, `{theme}`, `{top}`, `{window}` |
| `status.monitor_adjust_advanced` | `{legend_position}` |
| `status.monitor_adjust_quick_keys` | — |
| `status.monitor_adjust_advanced_keys` | — |
| `message.no_data` | — |
| `message.monitor_empty` | — |
| `label.monitor_title` | `{agents}`, `{mode}`, `{state}`, `{window}` |
| `label.monitor_growth_title` | `{agents}`, `{mode}`, `{state}`, `{window}` |
| `label.monitor_baseline` | — |
| `label.monitor_samples` | — |
| `label.monitor_observed` | — |
| `label.monitor_total_mode` | — |
| `label.monitor_agent_mode` | — |
| `label.monitor_model_mode` | — |
| `label.monitor_project_mode` | — |
| `label.monitor_growth` | — |
| `label.monitor_all` | — |
| `label.total` | — |
| `label.all` | — |
| `label.on` | — |
| `label.off` | — |
| `label.other` | — |
| `label.legend_below_title` | — |
| `label.legend_inside` | — |
| `label.legend_hidden` | — |
| `label.legend_values` | — |
| `label.weekday_auto` | — |
| `label.weekday_show` | — |
| `label.weekday_hidden` | — |
| `label.tokens` | — |
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
| `label.dashboard` | — |
| `label.timeline` | — |
| `label.calendar` | — |
| `label.stack` | — |
| `label.ranking` | — |
| `label.by` | `{dimension}` |
| `label.agent` | — |
| `label.model` | — |
| `label.project` | — |
| `label.date_range` | `{since}`, `{until}` |
| `summary.line` | `{comparisons}` |
| `summary.separator` | — |
| `summary.current.day` | `{value}` |
| `summary.current.day.all_agents` | `{value}` |
| `summary.current.day.current_filter` | `{value}` |
| `summary.current.month` | `{value}` |
| `summary.current.month.all_agents` | `{value}` |
| `summary.current.month.current_filter` | `{value}` |
| `summary.current.quarter` | `{value}` |
| `summary.current.quarter.all_agents` | `{value}` |
| `summary.current.quarter.current_filter` | `{value}` |
| `summary.current.year` | `{value}` |
| `summary.current.year.all_agents` | `{value}` |
| `summary.current.year.current_filter` | `{value}` |
| `summary.chart_top` | `{summary}`, `{top}` |
| `summary.sequential.day` | `{relation}` |
| `summary.sequential.month` | `{relation}` |
| `summary.sequential.quarter` | `{relation}` |
| `summary.sequential.year` | `{relation}` |
| `summary.year_over_year.day` | `{relation}`, `{weekday}` |
| `summary.year_over_year.month` | `{relation}` |
| `summary.year_over_year.quarter` | `{relation}` |
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
