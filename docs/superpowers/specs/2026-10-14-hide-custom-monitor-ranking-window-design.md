# Hide Custom Monitor Ranking Window Display

## Goal

Extend the Monitor ranking window-display rule to Custom Monitor headings. `ranking`, `ranking-dot`, and `list` do not represent a temporal chart, so their headings must not show the display-view duration or source data-window duration.

## Approach

Use the existing shared `is_monitor_ranking_style()` predicate in `CustomMonitorComponent.heading()`. For those styles, return only the metric grouping and metric label. Continue adding `view {duration} · data window {duration}` (and the Chinese equivalents) for temporal styles. Preserve the current dedicated cumulative-bars heading.

## Behavior

- Custom Monitor `ranking`, `ranking-dot`, and `list` headings omit both `view/视图` and `data window/数据窗口`.
- A switch to a temporal style restores both duration facts using the retained configuration.
- `cumulative-bars` retains its dedicated day and source-window heading.
- No collection, metric, window, or projection behavior changes.

## Testing

Parameterize Custom Monitor component heading tests across the three ranking/list styles and both locales, then retain a temporal-style assertion proving duration facts remain visible.
