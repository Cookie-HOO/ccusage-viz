# Language overrides

[简体中文](language-overrides.zh-CN.md)

`--lang-file PATH` accepts a partial JSON object whose keys are selected from the catalog below. Values replace messages from the language selected by `--lang` or system-locale detection.

```bash
ccusage-viz timeline --lang en --lang-file examples/language-overrides.json
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
  "summary.line": "{week_over_week} · {today} · {day_over_day}",
  "summary.today": "Today: {value}",
  "summary.day_over_day": "vs yesterday: {relation}",
  "summary.week_over_week": "vs last {weekday}: {relation}"
}
```

A Watch process loads the file once. Invalid-file diagnostics use the selected built-in language; after a valid load, runtime diagnostics use the active overrides.

Values supplied by `ccusage`—including Agent, model, project, and raw stderr text—are not translated by this catalog.

## Complete key reference

`—` means the value must contain no placeholders. Literal wording and punctuation may change; placeholder names, conversions, and format specifications must remain the same.

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

The authoritative built-in wording is in `src/ccusage_viz/locales/en.py` and `src/ccusage_viz/locales/zh.py`. Tests require both catalogs to expose the same keys and placeholder signatures.
