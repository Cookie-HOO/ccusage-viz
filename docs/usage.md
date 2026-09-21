# Usage guide

<!-- guide:overview -->

## Overview and prerequisites

This is the operational reference for `ccusage-viz` and its short command,
`ccuv`. The installed commands are equivalent; you can also run the module:

```bash
ccuv --help
ccusage-viz --help
python -m ccusage_viz --help
```

Install the program as described in the [README](../README.md). For real data,
install [`ccusage`](https://github.com/ryoppippi/ccusage) separately and make it
available on `PATH`; it is not bundled with `ccusage-viz`. Use
`--ccusage-bin` when its executable has another name or location.

The charts are intended for an interactive terminal. They can also use
repeatable deterministic sample data: `--demo` means `--demo medium`, while
`--demo small` and `--demo large` select the other datasets. Demo mode neither
runs `ccusage` nor saves data.

`timeline` is the implicit command. These are equivalent:

```bash
ccuv
ccuv timeline
ccuv --demo
ccuv --lang zh --demo
```

Use the README for installation and a visual overview. See the
[architecture document](architecture.md) for implementation and maintainer
background rather than as a command reference.

<!-- guide:command-map -->

## Quick start and command map

Start with demo data when exploring the program:

```bash
ccuv timeline --demo
ccuv calendar --demo
ccuv stack --demo --cache split
ccuv ranking --demo --by project
ccuv monitor --demo --by model
ccuv dashboard wide --demo
```

| Route | Data model | Terminal composition | Main question |
| --- | --- | --- | --- |
| `timeline` | Historical date range | One standalone chart | How does token usage change over time? |
| `calendar` | Historical date range | One standalone chart | Which days were active and intense? |
| `stack` | Historical date range | One standalone chart | How are input, output, and cache tokens composed? |
| `ranking` | Historical date range | One standalone chart | Which Agent, model, or project used the most tokens? |
| `monitor` | Rolling observation window | One standalone chart | What throughput has this process observed since it started? |
| `dashboard` | Host-wide cadence plus independent panes | Multi-pane Dashboard | How do several configured charts compare at once? |

Historical routes query a date range. `monitor` instead samples repeated
cumulative snapshots while the current process runs; it cannot reconstruct
throughput from before it started. A standalone chart fills the terminal.
Dashboard is a separate multi-pane host built from the same chart components,
not a wrapper around a standalone chart.

<!-- guide:shared-standalone-options -->

## Shared standalone CLI reference

The following options apply to standalone charts as shown. Values in the
**Default** column are parser defaults; command-specific defaults are listed in
later tables.

### Presentation and process options

| Option | Accepted values | Default | Applies to | Behavior |
| --- | --- | --- | --- | --- |
| `--demo [SIZE]` | `small`, `medium`, `large` | off; bare flag is `medium` | All | Use deterministic in-process data instead of `ccusage`. |
| `--lang LANG` | `en`, `zh` | System-detected language | All | Select English or Simplified Chinese messages/help. It may precede a command. |
| `--ccusage-bin PATH` | Command name or path | `ccusage` | All | Executable used for live queries. |
| `--query-timeout SECONDS` | Positive finite number | `30` | All | Maximum live-query time. This advanced supported option is deliberately hidden from normal `--help`. |
| `--ascii` | Flag | off | All | Prefer ASCII-safe rendering. Cannot be combined with an explicitly supplied `--theme`. |
| `--theme THEME` | `classic`, `vivid`, `contrast`, `dracula`, `catppuccin`, `solarized`, `gruvbox`, `nord`, `github`, `mono`, `no-color` | `classic` | All | Chart color scheme; `no-color` disables chart color. |
| `--density DENSITY` | `minimal`, `compact`, `full` | `full` | All standalone charts | Amount of chart detail and decoration. |
| `--style STYLE` | Route-specific; see chart tables | Route-specific | All | Rendering style for the selected chart. |
| `--legend POSITION` | Timeline: `below-title`, `inside`, `hidden`; Stack: `below-title`, `hidden`; Monitor: `below-title`, `inside`, `hidden`, `values` | `below-title` | Timeline, Stack, Monitor | Legend placement/content. |

`--ascii --theme classic` is invalid just as `--ascii --theme no-color` is:
the conflict is caused by explicitly specifying a theme. `--ascii` without a
`--theme` is valid.

### Historical range, filters, and scheduling

| Option | Accepted values | Default | Applies to | Behavior |
| --- | --- | --- | --- | --- |
| `--period PERIOD` | Positive integer followed by `d`, `mo`, `q`, or `y` (for example `14d`, `13mo`, `1q`) | Timeline/Stack/Ranking: `14d`; Calendar: `365d` | Historical routes | Rolling range ending today in the selected timezone. |
| `--since YYYY-MM-DD` | ISO date | unset | Historical routes | First date in a fixed or open-ended range. |
| `--until YYYY-MM-DD` | ISO date | unset | Historical routes | Final date in a fixed range. Requires `--since`. |
| `--timezone IANA_ZONE` | Valid IANA timezone, for example `Asia/Shanghai` | Local timezone | Historical routes | Resolves “today” and relative boundaries. |
| `--agent VALUE` | Repeatable text | none | Historical routes and Monitor | Filter by Agent. |
| `--model VALUE` | Repeatable text | none | Historical routes and Monitor | Filter by model. |
| `--project VALUE` | Repeatable text | none | Historical routes and Monitor | Filter by project. |
| `--project-aggregation MODE` | `name`, `exact`; default `name` | `name` | Timeline/Ranking with `--by project` | Project presentation mode; it never broadens exact project filters. |
| `--interval SECONDS` | Finite number; at least `2` for historical charts | `10` | Historical routes | Refresh cadence while watching. |
| `--no-watch` | Flag | off | Historical routes | Query once and exit instead of watching. |

Repeat a selector to accept any of its values in that dimension, then combine
dimensions together. For example, the following means **Agent A or B**, using
**model X**, in **project one or two**:

```bash
ccuv timeline --agent A --agent B --model X --project one --project two
```

Matching is case-insensitive. An exact match wins; a unique containment match
is accepted; an ambiguous containment match must be narrowed. Project identity
is Agent-scoped, so identical displayed project names can still identify
different projects.

<!-- guide:historical-rules -->

## Historical range, refresh, and presentation rules

### Ranges and refresh

`--period` selects a rolling range. `14d`, `3mo`, `1q`, and `1y` are valid;
`0d`, `2w`, and `month` are not. When an explicit `--since` has no `--until`,
the end is today's date when the command starts. A range with both dates is
fixed; relative periods can advance as the local natural day changes.

The following combinations are rejected:

| Invalid combination | Reason |
| --- | --- |
| `--period` with `--since` or `--until` | Choose a relative period or explicit dates, not both. |
| `--until` without `--since` | An end date needs a start date. |
| `--since` later than `--until` | Date order is invalid. |
| Future `--until` | Historical data cannot end in the future. |
| Invalid timezone | `--timezone` must name an installed IANA timezone. |
| `--interval` with `--no-watch` | A one-shot invocation has no scheduling interval. |
| Historical `--interval` below `2` | Historical watching has a two-second minimum. |

Historical charts watch by default. Press `Space` to pause/resume them during a
session, or pass `--no-watch` for a one-shot query.

### Density, styles, and grouping

- `minimal` keeps the most compact chart presentation; `compact` is suitable
  for panes; `full` is the standalone default.
- Timeline styles are `linear`, `step`, `no-line`, `points`, `line-points`,
  `stem`, and `area`. A grouped Timeline (`--by ...`) cannot use `area`.
- Calendar styles are `relative` and `grid`.
- Stack styles are `stacked`, `stacked-pattern`, `grouped`, `grouped-thin`, and
  `normalized`.
- Ranking styles are `bar`, `dot`, and `dots`.
- Monitor styles are `bars`, `line`, `step`, `points`, `line-points`, `ranking`,
  and `list`. A grouped Monitor cannot use `bars`.

Grouping happens after filters. For Timeline and Monitor, `--top` requires a
`--by` dimension and defaults to `3` when grouping is selected without an
explicit Top count. Ranking always groups (default `--by project`) and defaults
to `--top 10`. Top must be a positive integer. `--other show|hide` controls
whether Timeline and Ranking display the remaining grouped values as **Other**.

### Project aggregation and attribution coverage

`--project-aggregation name` is the default for historical Timeline and Ranking
views grouped by project. It combines only an unambiguous Claude–Codex pair and
never merges projects within one Agent. It first compares safe final names; when
Codex has colliding basenames, it may use private parent suffixes solely to
select a conservative one-to-one pair. Those suffixes are grouping keys, not
shown labels or reconstructed paths. The concise merged label is a presentation
label, not evidence that the records came from one filesystem checkout. Filtering
always remains against the exact source project identity before this presentation
aggregation is applied.

Use `--project-aggregation exact` to retain every upstream `(agent, project)`
source identity separately. Exact-mode data tables and JSON provide a separate
`agent` field alongside `project`; charts keep compact project labels. This does
not expose raw paths or opaque upstream identifiers. Name-mode groups that span
agents intentionally have no manufactured single-agent value.

The following compatibility baseline was verified on macOS with **ccusage
20.0.23**. Token totals mean that ccusage reports an agent in unified usage data;
historical project attribution additionally requires a stable, real project
identity for each record.

| Agent | Token totals | Historical project attribution | Agent version | ccusage version | Evidence |
| --- | --- | --- | --- | --- | --- |
| Claude Code | Verified | Verified | 2.1.278 | 20.0.23 | `claude daily --instances --json` provides project records. |
| Codex | Verified | Verified | 0.139.0 | 20.0.23 | Uses ccusage `cwd`/project fields when present; otherwise resolves only matching local `session_meta.cwd` metadata. |
| OpenCode | Verified | Unsupported (verified) | 1.17.20 | 20.0.23 | Real session output has no project identity field. |
| Antigravity | Verified | Unsupported (verified) | 2.0.10 | 20.0.23 | Real `projectPath` values were the generic constant `Antigravity`, not workspaces. |

For Codex sessions, ccusage `cwd`/project fields are authoritative. When current output
contains only a session ID and storage `directory`, ccusage-viz reads only the matching local
session's `session_meta.cwd`; `directory` is never a project identity. If neither source
provides a cwd, the usage remains visible as **Unassigned Codex** and a generic notice marks
project attribution as incomplete. No transcript, tool, or message content is analyzed,
stored, or displayed.

A historical project request warns when OpenCode, Antigravity, or another
unsupported agent occurs in the selected range. Its project usage can be absent
or incomplete because ccusage-viz does not manufacture project rows. This warning
does not change project totals, coverage, or filtering, and does not apply to
Monitor's separate cumulative project behavior.

Move an agent to **Verified** only in a change that includes a sanitized,
non-empty real-data fixture, parser/provider coverage, project-ranking end-to-end
validation, reconciliation with unified daily token totals, and the exact tested
agent plus ccusage version.

<!-- guide:standalone-charts -->

## Standalone chart reference

### Timeline

```bash
ccuv timeline --period 30d --by model --top 5 --style line-points
```

| Option | Values/default | Meaning |
| --- | --- | --- |
| `--by` | `agent`, `model`, `project`; default total | Group time-series values. |
| `--top` | Positive integer; default `3` after choosing `--by` | Number of displayed groups. Requires `--by`. |
| `--other` | `show` (default), `hide` | Show/hide the remainder after Top selection. |
| `--granularity` | `day` (default), `month`, `quarter`, `year` | Bucket the historical range. |
| `--weekdays` | `show` (default), `hide` | Show/hide weekday labels where relevant. |
| `--legend` | `below-title` (default), `inside`, `hidden` | Legend placement. |
| `--project-aggregation` | `name` (default), `exact`; only with `--by project` | Use safe cross-agent same-name presentation or preserve each exact source. |
| `--style` | Timeline styles | `area` is unavailable when grouped. |

### Calendar

```bash
ccuv calendar --period 1y --style grid
```

| Option | Values/default | Meaning |
| --- | --- | --- |
| `--style` | `relative` (default), `grid` | Calendar heatmap presentation. |
| Historical shared options | See above | Range, filters, locale/process/presentation, and watch behavior. |

Calendar has no grouping, Top, Other, granularity, weekday-label, or legend
option.

### Stack

```bash
ccuv stack --period 30d --granularity month --cache split
```

| Option | Values/default | Meaning |
| --- | --- | --- |
| `--cache` | `combined` (default), `split` | Combine cache tokens or show cache reads and creation separately. |
| `--granularity` | `day` (default), `month`, `quarter`, `year` | Bucket the historical range. |
| `--weekdays` | `show` (default), `hide` | Show/hide weekday labels where relevant. |
| `--legend` | `below-title` (default), `hidden` | Legend visibility. |
| `--style` | Stack styles | Select stack/group/normalized rendering. |

For example:

```bash
ccuv stack --demo --cache split --style stacked-pattern
```

### Ranking

```bash
ccuv ranking --period 30d --by project --top 15 --other hide --style dots
```

| Option | Values/default | Meaning |
| --- | --- | --- |
| `--by` | `project` (default), `agent`, `model` | Ranking dimension. |
| `--top` | Positive integer; default `10` | Number of ranked values. |
| `--other` | `show` (default), `hide` | Show/hide values outside Top. |
| `--project-aggregation` | `name` (default), `exact`; only with `--by project` | Use safe cross-agent same-name presentation or preserve each exact source. |
| `--style` | `bar` (default), `dot`, `dots` | Ranking representation. |

### Monitor

```bash
ccuv monitor --window 30m --by model --top 5 --style ranking
```

Monitor observes throughput from repeated cumulative snapshots during this
invocation. The first accepted snapshot establishes its baseline; observed
history is process-local and goes away when the process exits. Timeline styles mark the
invocation's start while it remains in the visible rolling window, making earlier time explicitly
unobserved rather than zero usage. The line is shown at every density; its label appears at full
and compact density when space permits. Ranking and list styles do not show this timeline marker.

| Option | Values/default | Meaning |
| --- | --- | --- |
| `--window` | `Nm` or `Nh`, from `5m` through `24h`; default `1h` | Rolling observation window. |
| `--interval` | At least `5` seconds live, at least `1` second in demo | Sampling cadence. Default is `15` seconds live or `1` second in demo when not explicitly supplied. |
| `--by` | `agent`, `model`, `project`; default total | Group observed throughput. |
| `--top` | Positive integer; default `3` after choosing `--by` | Number of displayed groups. Requires `--by`. |
| `--legend` | `below-title` (default), `inside`, `hidden`, `values` | Legend mode. |
| `--style` | Monitor styles | Grouped Monitor cannot use `bars`; `list` includes process/item detail. |

`--no-watch` is accepted by the parser for compatibility but hidden from normal
help and rejected for Monitor: Monitor is always continuous. In total mode it
reports total tokens per minute. Grouped `model` reports model throughput;
grouped Agent and project views use observed latest-pair token growth.

<!-- guide:dashboard-startup -->

## Dashboard startup and composition

Dashboard is the multi-pane host. A bare invocation starts the `wide` preset:

```bash
ccuv dashboard
ccuv dashboard wide
ccuv dashboard wide --demo
```

### Presets

| Preset | Pane composition | Grid/layout | Dashboard style |
| --- | --- | --- | --- |
| `wide` | Timeline, Stack, Ranking, Monitor grouped by model | `2x2` | `framed` |
| `spotlight-wide` | Timeline, Stack, Ranking | `2x2` with `spotlight-wide` | `framed` |
| `spotlight-wide2` | Timeline, Stack, Ranking, Monitor grouped by model | `2x2` with `spotlight-wide2` | `framed` |
| `narrow` | 14-day Timeline, project Ranking, model Monitor | `3x1` | `framed` |
| `all` | Two Timelines, Calendar, Ranking, two Stacks, and four Monitor variants | `5x2` | `split` |

The default `wide` panes use compact density and deliberately use separate
chart themes/styles. `spotlight-wide` gives its first pane the leading wide
area; `spotlight-wide2` gives the first two panes consecutive wide rows.

Presets are startup templates. They are not values for `--grid`. Repeated
`--pane` values append panes after a preset's panes, and the host expands a
preset grid where required to make room.

### Build a custom Dashboard

A pane fragment is one safely quoted chart command plus chart options:

```bash
ccuv dashboard \
  --pane 'timeline --period 30d --by model --top 5 --style line-points' \
  --pane 'ranking --by project --top 10 --style dots' \
  --pane 'monitor --window 1h --by model --style ranking' \
  --grid 2x2
```

For a named layout, omit `--grid`:

```bash
ccuv dashboard \
  --pane 'timeline --by model' \
  --pane 'stack --cache split' \
  --pane 'ranking --by project' \
  --layout spotlight-wide
```

Supported `--layout` values are `auto`, `spotlight-wide`, and
`spotlight-wide2`. A grid is `ROWSxCOLUMNS`; it must have enough cells for all
panes.

A custom pane defaults to `compact` density unless the fragment explicitly
contains `--density`.

### Dashboard-host options

| Option | Values/default | Host-owned behavior |
| --- | --- | --- |
| `--demo [SIZE]`, `--lang`, `--ccusage-bin`, `--query-timeout` | Same semantics as standalone; bare demo is `medium`; timeout default `30` | Provider/process/input configuration for all panes. `--query-timeout` is hidden advanced configuration. |
| `--timezone IANA_ZONE` | Local timezone unless given | Historical time interpretation for host panes. |
| `--ascii` | off | ASCII rendering for the host and panes. It conflicts with an explicit Pane `--theme`. |
| `--theme THEME` | `classic` | Dashboard shell theme, distinct from each Pane chart theme. |
| `--grid ROWSxCOLUMNS` | Custom construction only | Logical grid for the selected pane count. |
| `--layout NAME` | Custom construction only | Named layout; cannot be combined with a preset or `--grid`. |
| `--column-weight WEIGHT` | Repeated positive integers | Hidden advanced startup-only logical column shares. Count must match layout columns. |
| `--row-weight WEIGHT` | Repeated positive integers | Hidden advanced startup-only logical row shares. Count must match layout rows. |
| `--refresh-interval SECONDS` | `15`; presets may supply their own default | Dashboard-wide historical refresh cadence; minimum `1`. |
| `--sampling-interval SECONDS` | `15`; presets may supply their own default | Dashboard-wide Monitor sampling cadence; minimum `1`. |
| `--header-style STYLE` | `hidden`, `compact`, `banner`, `panel`; default `panel` | Dashboard header rendering. |
| `--header-summary SUMMARY` | `day`, `month`, `quarter`, `year`, `none`; default `day` | Header aggregate period. |
| `--header-interval SECONDS` | `60` | Header refresh cadence; minimum `1`. |
| `--style STYLE` | `minimal`, `split`, `framed`, `accent`; default `split` unless preset supplies one | Dashboard shell/chrome style, not a chart style. |

Weights must be positive and their count must match the resolved logical row or
column bands. The host normalizes equivalent shares when serializing a full
command. Runtime resizing changes only session-local logical weights.

### Host-owned and Pane-owned configuration

A Dashboard host owns its layout, shell theme/style, headers, input loop, and
cadences. A Pane owns chart selection, range/window, grouping, Top/Other,
filters, chart theme/style/density, and chart-specific configuration.

Pane fragments may contain only a chart command (`timeline`, `calendar`,
`stack`, `ranking`, or `monitor`) plus chart settings. They must not include
host/lifecycle options such as:

```text
--interval --no-watch --watch --timezone --ascii --demo --lang
--ccusage-bin --query-timeout --pane --grid --refresh-interval
--sampling-interval --header-style --header-summary --header-interval
--help --version -h
```

A Dashboard header deliberately runs an unfiltered, all-Agent aggregate query;
it does not become a summary of the focused Pane's filters. Likewise, Dashboard
`--style` controls Dashboard chrome while a Pane's `--style` controls that
chart. Dashboard's sampling cadence is host-wide, so Monitor Pane adjustment
does not expose standalone Monitor's `i` interval control.

<!-- guide:interactive-controls -->

## Interactive controls and standalone adjustments

### Common standalone controls

These controls apply while the standalone TUI is running unless a view/mode
restriction is stated:

| Key | Behavior |
| --- | --- |
| `Ctrl-C` | Exit. |
| `r` | Refresh a historical query or request a Monitor sample immediately. |
| `h` | Show/hide the session-only control footer. |
| `v` | Cycle chart, compact command, full command, Markdown table, JSON, then chart. |
| `y` | Copy the current command/data text from a non-chart view. |
| `Space` | Pause/resume scheduling. |
| `m` | Open adjustment only from the chart view. |
| `s` / `d` / `l` | In supported adjustment pickers: style / density / legend controls. |

The compact command view omits defaults and private project paths. The full
command view includes effective settings, including private project paths,
selected binary path, and query timeout. Copying is not persistence: the
program writes no configuration automatically. Runtime changes last only for
the current process; save a copied command yourself if you want to reuse it.

### Historical adjustment flow

For Timeline, Calendar, Stack, and Ranking, press `m` in chart view. The
picker previews changes, `a` switches **Quick** and **Advanced** pages, and
`Enter`/newline commits the current candidate. `Esc` cancels the picker.
Visual-only changes update the preview immediately; data-affecting changes are
used by the subsequent configuration refresh after commit.

| Chart | Quick page | Advanced page |
| --- | --- | --- |
| Timeline | `p/P` period; `g` granularity; `b` grouping; `+/-` Top; `d` density; `t/T` theme; `s` style | `f` filters; `o` Other; `A` project aggregation when grouped by project; `l` legend; `k` weekday labels |
| Calendar | `p/P` period; `d` density; `t/T` theme; `s` style | `f` filters |
| Stack | `p/P` period; `g` granularity; `d` density; `t/T` theme; `s` style | `f` filters; `c` cache mode; `l` legend; `k` weekday labels |
| Ranking | `p/P` period; `b` grouping; `+/-` Top; `d` density; `t/T` theme; `s` style | `f` filters; `o` Other; `A` project aggregation when grouped by project |

`p` cycles trailing presets (`7d`, `14d`, `30d`, `365d`). `P` cycles natural
presets (`1mo`, `1q`, `1y`). Neither changes a fixed explicit-date range.
Grouping/style changes retain a compatible style; for example changing
Timeline to grouped mode will replace `area` with a compatible style.

### Candidate data while querying

A chart title gains a muted `querying` marker as soon as its controls select a
candidate whose facts are not yet available. The control state changes
immediately; the marker explains the intentionally incomplete interim render.
It belongs to the affected chart only, not to the Dashboard title or unrelated
panes. A normal background refresh of an already accepted configuration can
show `refreshing`, but does not show `querying`.

| Control change | Interim chart render |
| --- | --- |
| Historical period, filter, or grouping | The candidate title and summary appear immediately. The old chart is hidden because its dates, scope, or ranking are not facts for the candidate; unavailable values use `??` until the matching query completes. |
| Timeline/Stack granularity | Accepted daily records are reprojected immediately. If only out-of-range comparison coverage is missing, the chart and current values remain visible; only comparison values show `??` with `querying`. |
| Historical visual controls | Existing accepted facts are immediately restyled or reprojected; no `querying` marker. |
| Monitor grouping or filters | The pane enters an empty safe sampling view with `querying`; prior observations are not relabeled as the candidate grouping/filter. |
| Monitor window, Top, interval, or visual controls | Retained observations are immediately reprojected or restyled; no `querying` marker. |

`??` therefore means that the specific displayed fact is not yet verified for
the active candidate. When the matching result is accepted, the marker and its
unknown values disappear together. A failed supplemental comparison refresh
keeps its existing failure notice and `??`; it is no longer labeled
`querying`.

### Filter editor

The Advanced `f` editor drafts filters before committing them:

| Key | Behavior |
| --- | --- |
| `h` / `Left` | Previous dimension |
| `l` / `Right` / `Tab` | Next dimension |
| `k` / `Up` | Previous value |
| `j` / `Down` | Next value |
| `Space` | Toggle the selected value |
| `Enter` | Commit the draft |
| `Esc` | Cancel the draft |

### Monitor adjustment picker

Press `m` or `M` from Monitor's chart view. `a` switches pages;
`Enter`, newline, or `Esc` closes the picker. Its controls are:

| Page | Controls |
| --- | --- |
| Quick | `w` window; `i` sampling interval; `b` grouping; `+/-` Top; `d` density; `t/T` theme; `s` style |
| Advanced | `f` filters; `l` legend |

Grouping and filters require a fresh matching observation baseline; window
changes reproject retained observations immediately. When the interval changes,
Monitor rebuilds its scheduler. Appearance-only changes apply without
pretending to recreate prior observation history.

### Dashboard controls

Dashboard has separate navigation and ownership rules. In browse mode:

| Key | Behavior |
| --- | --- |
| `r` | Refresh all panes. |
| `s` | Adjust the first pane. |
| Mouse click | Adjust the clicked pane. |
| `g` | Open global Dashboard adjustment. |
| `h` | Toggle Dashboard footer. |
| `v` | Show the full Dashboard command. |
| `y` | Copy from command view. |
| `Space` | Pause/resume Dashboard scheduling. |
| `Ctrl-C` | Exit. |

While adjusting a Pane, `v` cycles its view; `r` replaces it; `N` inserts
before; `n` inserts after; `x` deletes it when more than one Pane remains;
`[`/`]` reorder it; and `Tab` moves focus to the next Pane. `{`/`}` adjust
logical column shares; `_`/`=` adjust logical row shares. Focused Pane Quick
keys are the historical/Monitor chart controls listed above, except Monitor
has no `i` because sampling belongs to the Dashboard host. Global Dashboard
adjustment uses `t/T` for shell theme, `s` for shell style, `h` for header
style, `u` for header summary, and `z` for layout.

<!-- guide:troubleshooting -->

## Constraints and troubleshooting

| Situation | What to do |
| --- | --- |
| Live query cannot find `ccusage` | Install `ccusage`, put it on `PATH`, or pass `--ccusage-bin`. Use `--demo` to explore without it. |
| A chart is too small or clipped | Enlarge the terminal, reduce density, or use a narrower Dashboard preset/layout. Chart renderers enforce minimum useful sizes. |
| Grouped Timeline rejects `area` | Choose another Timeline style or remove grouping. |
| Grouped Monitor rejects `bars` | Choose a line/ranking/list Monitor style or remove grouping. |
| `--top` is rejected | Supply a positive value and a grouping dimension where required. |
| `--ascii` and theme conflict | Omit the explicit `--theme`; for Dashboard, also omit explicit Pane themes. |
| Dashboard command is rejected | Use a preset, or supply at least one quoted `--pane`; do not mix a preset with `--grid`, or `--layout` with a preset/grid. |
| Pane fragment is rejected | Keep host/lifecycle options at Dashboard level; the fragment should only describe a chart. |
| Monitor does not show old historical throughput | This is expected: it observes only snapshots gathered by the current process. |
| Runtime adjustment disappeared after exit | This is expected: adjustments are session-local. Reuse a copied command by saving it yourself. |

Use `ccuv --help` for the route list and `ccuv <command> --help` for
localized parser help, for example `ccuv --lang zh dashboard --help`. The
normal help intentionally omits advanced `--query-timeout`, Dashboard weight
options, and Monitor's parser-accepted-but-invalid `--no-watch`; this guide
records them so their constraints are clear.
