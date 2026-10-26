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

The charts are intended for an interactive terminal. `--demo`, `--demo small`,
`--demo medium`, and `--demo large` run live, asynchronous in-process
simulations: each invocation varies its synthetic activity while the size selects
the scale. Bare `--demo` means `--demo medium`. Demo mode neither runs
`ccusage` nor saves data.

`timeline` is the implicit command. These are equivalent:

```bash
ccuv
ccuv chart timeline
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
ccuv chart timeline --demo
ccuv chart calendar --demo
ccuv chart stack --demo --cache split
ccuv chart ranking --demo --by project
ccuv chart monitor --demo --by model
ccuv animate rain
ccuv dashboard wide --demo
```

| Route | Data model | Terminal composition | Main question |
| --- | --- | --- | --- |
| Timeline `timeline` | Historical date range | Focused one-Pane Dashboard | How does token usage change over time? |
| Calendar `calendar` | Historical date range | Focused one-Pane Dashboard | Which days were active and intense? |
| Stack `stack` | Historical date range | Focused one-Pane Dashboard | How are input, output, and cache tokens composed? |
| Ranking `ranking` | Historical date range | Focused one-Pane Dashboard | Which Agent, model, or project used the most tokens? |
| Monitor `monitor` | Rolling observation window | Focused one-Pane Dashboard | What throughput has this process observed since it started? |
| `dashboard` | Host-wide cadence plus independent panes | Dashboard | How do one or several configured charts compare? |
| Dataset Metrics via `chart KIND --dataset ID` | Command-returned historical values or Monitor observations | Focused Dashboard or an added Pane | How does an external Dataset Metric change, rank, or behave now? |
| `animate` | No usage data | One standalone animation | Show a local terminal animation without querying a provider. |
| `text` | No usage data | One dynamic text value | Generate provider-free text for an Overlay command. |

Historical routes query a date range. `monitor` instead samples repeated
cumulative snapshots while the current process runs; it cannot reconstruct
throughput from before it started. `ccuv chart KIND ...` adapts its arguments to
a one-Pane Dashboard with hidden header and summary; after startup it is an
ordinary Dashboard and can be expanded with more Panes.

<!-- guide:shared-standalone-options -->

## Animation

`animate` is provider-free: it does not install, invoke, or query `ccusage`.
It defaults to rain and discovers the installed `term-animate` curated catalog
at runtime. The selector is the library's stable effect ID, so newly released
host-eligible effects are available without ccuv maintaining a second catalog:

```bash
ccuv animate                 # defaults to rain
ccuv animate mole-cat
ccuv animate snow
ccuv animate night-sky
ccuv animate lightning
ccuv animate meteor-shower
```

The standalone host owns all input. `q`, Escape, and Ctrl-C exit; `m` opens the adjustment view; quick `t`/`T` cycles the ccuv theme
and `s` cycles the currently discovered standalone styles. `a` switches between
quick and advanced adjustment pages; the first advanced page has no
animation-only settings. The underlying animation library never receives
keyboard input.

Animations use the current terminal color capability and honor `--ascii`.
ccuv passes the available viewport directly to term-animate, whose projection
is responsible for bounded artwork. Animation state is in memory only: each
standalone host, Dashboard animation Pane, and Monitor attachment has
independent theme/style/playback state, and all state is discarded when ccuv
exits.

A Dashboard Pane must name its style explicitly; bare `animate` is invalid:

```bash
ccuv dashboard --pane "timeline --period 7d" --pane "animate rain"
```

Dashboard presets do not add animation Panes automatically, but the Dashboard pane
chooser can add an Animation pane with the default rain style; the pane's quick
controls cycle every currently eligible catalog effect.

For `monitor` styles `ranking` and `list`, the `mole-cat` attachment is enabled by default.
In the advanced adjustment view, `s`/`S` cycles every effect declared by
`term-animate`, followed by ccuv-local `none`. An enabled attachment starts
with the `classic` library theme, independently of the Monitor chart theme.
It stays hidden until the Monitor establishes a comparable accepted interval,
then plays only when the latest **accepted** interval has a strictly positive
aggregate token delta; a zero delta renders the eligible stateful scene idle.
Baseline/rebaseline, pending, error, and discarded samples do not advance it.
`t`/`T` changes the retained attachment theme. `none` removes only that
Monitor attachment and does not exist as a standalone `animate` or Dashboard
Animation-pane style. Other Monitor styles do not expose or consume these
attachment controls.

## Focused chart CLI reference

The following options configure the initial Pane created by `ccuv chart`. Values in the
**Default** column are parser defaults; command-specific defaults are listed in
later tables.

### Presentation and process options

| Option | Accepted values | Default | Applies to | Behavior |
| --- | --- | --- | --- | --- |
| `--demo [SIZE]` | `small`, `medium`, `large` | off; bare flag is `medium` | All | Run a live, asynchronous in-process simulation instead of `ccusage`; each invocation varies activity, and SIZE selects its scale. |
| `--lang LANG` | `en`, `zh` | System-detected language | All | Select English or Simplified Chinese messages/help. It may precede a command. |
| `--ccusage-bin PATH` | Command name or path | `ccusage` | All | Executable used for live queries. |
| `--query-timeout SECONDS` | Positive finite number | `30` | All | Maximum live-query time. This advanced supported option is deliberately hidden from normal `--help`. |
| `--ascii` | Flag | off | All | Prefer ASCII-safe rendering. Cannot be combined with an explicitly supplied `--theme`. |
| `--theme THEME` | `classic`, `vivid`, `contrast`, `dracula`, `catppuccin`, `solarized`, `gruvbox`, `nord`, `github`, `mono`, `no-color` | `classic` | All | Chart color scheme; `no-color` disables chart color. |
| `--density DENSITY` | `minimal`, `compact`, `full`, `detailed` | `detailed` (`full` for Ranking) | All focused charts | Amount of chart detail and decoration. |
| `--style STYLE` | Route-specific; see chart tables | Route-specific | All | Rendering style for the selected chart. |
| `--legend POSITION` | Timeline: `below-title`, `inside`, `hidden`; Stack: `below-title`, `hidden`; Monitor: `below-title`, `inside`, `hidden`, `values` | `below-title` | Timeline, Stack, Monitor | Legend placement/content. |

`--ascii --theme classic` is invalid just as `--ascii --theme no-color` is:
the conflict is caused by explicitly specifying a theme. `--ascii` without a
`--theme` is valid.

### Historical range, filters, and scheduling

| Option | Accepted values | Default | Applies to | Behavior |
| --- | --- | --- | --- | --- |
| `--period PERIOD` | Positive integer followed by `d`, `mo`, `q`, or `y` (for example `14d`, `13mo`, `1q`) | Timeline/Stack/Ranking: `14d`; Calendar: `365d` | Historical routes | Rolling range ending on the host machine's local date. |
| `--since YYYY-MM-DD` | ISO date | unset | Historical routes | First date in a fixed or open-ended range. |
| `--until YYYY-MM-DD` | ISO date | unset | Historical routes | Final date in a fixed range. Requires `--since`. |
| `--agent VALUE` | Repeatable text | none | Historical routes and Monitor | Filter by a complete Agent value. |
| `--model VALUE` | Repeatable text | none | Historical routes and Monitor | Filter by a complete model value. |
| `--project VALUE` | Repeatable text | none | Historical routes and Monitor | Filter by a complete safe project label. |
| `--interval SECONDS` | Finite number; at least `2` for historical charts | `10` | Historical routes | Refresh cadence while watching. |

All historical dates and natural-day boundaries use the local IANA timezone of
the host running ccuv. `--timezone AREA/LOCATION` overrides that host default,
and ccuv sends the resolved timezone explicitly with every custom Dataset
request. Dashboard panes inherit the Dashboard timezone; a pane cannot override
it. Copied commands retain `--timezone` so the same date interpretation can be
reproduced.

Repeat a selector to accept any of its values in that dimension, then combine
dimensions together. For example, the following means **Agent A or B**, using
**model X**, in **project one or two**:

```bash
ccuv chart timeline --agent A --agent B --model X --project one --project two
```

All Agent, Model, and Project selectors are **complete, case-insensitive exact
matches**. ccusage-viz never falls back to prefix, substring, containment, or
other implicit matching: `--agent "CLAUDE CODE"` matches `Claude Code`, while
`--agent claude` does not. The same rule applies to `--model` and `--project`.

Project identity is Agent-scoped, so use the safe disambiguated project label
shown by the TUI when same-named projects belong to different Agents. Claude's
opaque upstream identifiers are never recovered as filesystem paths. Timeline
and Ranking treat them only as hyphen-separated tokens, then independently
remove the deepest prefix proven shared within each branch of the complete
post-filter token tree. No token has special path-like meaning: shortening is
constrained only by a non-empty, unambiguous suffix. An ID that has no proved
shared prefix shows its complete opaque identifier. Labels can differ across
intentionally independent discovery scopes. Timeline and Ranking record the
shortest verified suffix before Top or Other selection; a later, too-narrow
Monitor sample may reuse that process-local label but never updates it.
Model names are case-insensitive throughout filtering, aggregation, Monitor,
and display, and are shown in lowercase.

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
| Historical `--interval` below `2` | Historical watching has a two-second minimum. |

Historical charts refresh continuously through the Dashboard host.

### Density, styles, and grouping

- `minimal` omits summary and audit; `compact` adds current/filter summary and
  is suitable for panes; `full` adds comparisons and observed metrics without
  an audit footer; `detailed` adds that footer and is the standalone default.
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

Project views combine only an unambiguous Claude–Codex pair and
never merges projects within one Agent. It first compares safe final names; when
Codex has colliding basenames, it may use private parent suffixes solely to
select a conservative one-to-one pair. Those suffixes are grouping keys, not
shown labels or reconstructed paths. The concise merged label is a presentation
label, not evidence that the records came from one filesystem checkout. Filtering
always remains against the exact source project identity before this presentation
aggregation is applied.

Project filters continue to apply to exact upstream identities before this
presentation aggregation. Cross-Agent groups intentionally have no manufactured
single-Agent value.

Every project data view includes `display_project` and `merge_group`.
`display_project` is the exact label currently rendered by the chart. Equal
non-empty `merge_group` values identify source projects summed into one
cross-Agent Name group; empty values mean the row is exact or otherwise unmerged.
Groups are numbered from `0` deterministically within the current output only,
not as durable project identifiers across ranges, filters, or Top choices.
Project Ranking additionally expands a Name group into its safe source rows,
which share the chart project's rank. Other remains an aggregate row without
fabricated source detail.

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

## Focused chart reference

### Timeline `timeline`

Historical headings use `Metric · chart · by dimension · period`; ungrouped
headings omit the dimension segment. Partitioned Ranking uses
`by partition → dimension`. For example:

```text
Tokens · Timeline · by model · 14d
Stars · Ranking · by language → repository · 30d
```

```bash
ccuv chart timeline --period 30d --by model --top 5 --style line-points
```

| Option | Values/default | Meaning |
| --- | --- | --- |
| `--by` | `agent`, `model`, `project`; default total | Group time-series values. |
| `--top` | Positive integer; default `3` after choosing `--by` | Number of displayed groups. Requires `--by`. |
| `--other` | `show` (default), `hide` | Show/hide the remainder after Top selection. |
| `--granularity` | `day` (default), `month`, `quarter`, `year` | Bucket the historical range. |
| `--weekdays` | `show` (default), `hide` | Show/hide weekday labels where relevant. |
| `--legend` | `below-title` (default), `inside`, `hidden` | Legend placement. |
| `--style` | Timeline styles | `area` is unavailable when grouped. |

### Calendar `calendar`

```bash
ccuv chart calendar --period 1y --style grid
```

| Option | Values/default | Meaning |
| --- | --- | --- |
| `--style` | `relative` (default), `grid` | Calendar heatmap presentation. |
| Historical shared options | See above | Range, filters, locale/process/presentation, and watch behavior. |

Calendar has no grouping, Top, Other, granularity, weekday-label, or legend
option.

### Stack `stack`

```bash
ccuv chart stack --period 30d --granularity month --cache split
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
ccuv chart stack --demo --cache split --style stacked-pattern
```

### Ranking `ranking`

```bash
ccuv chart ranking --period 30d --by project --top 15 --other hide --style dots
```

| Option | Values/default | Meaning |
| --- | --- | --- |
| `--by` | `project` (default), `agent`, `model` | Ranking dimension. |
| `--top` | Positive integer; default `10` | Number of ranked values. |
| `--other` | `show` (default), `hide` | Show/hide values outside Top. |
| `--style` | `dot` (default), `bar`, `dots` | Ranking representation. |

### Monitor `monitor`

`Monitor` is the chooser and product type. Rendered Monitor headings name the
active view instead: **Trend**, **Ranking**, **List**, or **Cumulative bars**.
For example:

```text
TPM · Trend · 1h window (collecting baseline)
```

The duration is the factual data window represented by the rendered observation,
not the local display-retention horizon or sampling cadence. A transient
parenthesized state stays muted on the same heading line; ready state is omitted.

```bash
ccuv chart monitor --window 30m --by model --top 5 --style ranking
```

Monitor observes throughput from repeated cumulative snapshots during this
invocation. The first accepted snapshot establishes its baseline; observed
history is process-local and goes away when the process exits. Timeline styles mark the
invocation's start while it remains in the visible rolling window, making earlier time explicitly
unobserved rather than zero usage. The line is shown at every density; its label appears at
compact, full, and detailed density when space permits. Ranking and list styles do not show this
timeline marker.

| Option | Values/default | Meaning |
| --- | --- | --- |
| `--window` | `Nm` or `Nh`, from `5m` through `24h`; default `1h` | Rolling observation window. |
| `--interval` | At least `5` seconds live, at least `1` second in demo | Sampling cadence. Default is `15` seconds live or `1` second in demo when not explicitly supplied. |
| `--by` | `agent`, `model`, `project`; default total | Group observed throughput. |
| `--top` | Positive integer; default `3` after choosing `--by` | Number of displayed groups. Requires `--by`. |
| `--legend` | `below-title` (default), `inside`, `hidden`, `values` | Legend mode. |
| `--style` | Monitor styles | Grouped Monitor cannot use `bars`; `list` includes process/item detail. |

Monitor is always continuous. In total mode it
reports total tokens per minute. Grouped `model` reports model throughput;
grouped Agent and project views use observed latest-pair token growth.

The `cumulative-bars` style is a separate calendar-day Token view. It shows
increments accumulated in each local natural hour (or half-hour), rather than
TPM. Press `w` to switch **Today** (default) and **Yesterday**, and `g` to
switch **Hourly** and **30 min** buckets. It uses the same grouping, Top/Other,
and stable series colors as the other Monitor styles. The current unfinished
bucket and startup fragment are visibly partial; sampling gaps and other time
without trustworthy observation are hatched/dim rather than shown as zero. An
observed zero remains a zero-valued bucket. Monitor retains minute-level aggregate
rollups for up to 50 hours for this view; it does not reconstruct intraday
history from date-only historical providers. In `ranking` and `list`, `w` is
not shown because those styles already describe the current observation.

<!-- guide:dashboard-startup -->

## Dashboard startup and composition

Dashboard is the multi-pane host. With no positional preset, a bare invocation starts the `wide-clock` preset:

```bash
ccuv dashboard
ccuv dashboard single
ccuv dashboard wide-clock
ccuv dashboard wide
ccuv dashboard --demo small
ccuv dashboard wide --demo medium
ccuv dashboard narrow --demo large
```

`--empty` instead suppresses default ccusage pane assembly, header work, and
ccusage data dependencies. The resolved default grid or explicit `--columns`/`--spotlight` topology
is filled with temporary `empty` panes. It does not add a clock; clock presets
retain their existing first clock pane.

```bash
ccuv dashboard --empty --columns 2 --spotlight 0 \
  --pane 'empty' \
  --pane 'chart timeline --dataset weread --command "weread ccuv"' \
  --pane 'empty' \
  --pane 'animate --style rain'
```

An `empty` pane has no provider, scheduler, data, or summary contribution, but
it participates in layout, focus, mouse handling, Tab navigation, insertion,
deletion, and copied-command serialization. It renders `Empty pane` and
`Double-click to select, then press r to choose a type`. Its explicit position
is retained in a copied command, including between configured panes.
Double-click enters the pane's management context; it exposes only Dashboard
structure and position controls, not chart-specific settings. `r` opens the
shared replacement chooser, while `N` and `n` open its insert-before and
insert-after forms. The bounded first-level chooser groups `ccusage` entries
(Timeline, Calendar, Stack, Ranking, Monitor), then **Custom** (Datasets…), then
**Other** (Animation, Empty); group headings are not selectable. Datasets remains
a second-level flow and lists the Local command editor,
installed executable datasets, `Browse official datasets…`, and `Install from
GitHub…`. Opening Datasets reads only local state. Opening Browse explicitly
fetches and verifies the signed official catalog, shows a cancellable loading
notice, then shows every catalog dataset for the current platform. The currently
configured official catalog URL returns unavailable until its maintainers commit
a valid signed `main/catalog/catalog.json`; ccuv deliberately does not use an
unsigned fallback. A selected available dataset shows its repository, release
tag, platform, and an explicit native-executable installation confirmation before
any download or local write. GitHub installation accepts only a repository URL
such as `https://github.com/Cookie-HOO/ccuv-dataset-weread` (or
`Cookie-HOO/ccuv-dataset-weread`): ccuv discovers a stable release's unique
platform archive and requires GitHub's SHA-256 digest or a supported checksum
asset before offering installation. Unavailable platforms remain visible but
cannot be installed. Selecting a ready installed dataset then selects Timeline,
Stack, Calendar, or Ranking. ccuv replaces the existing pane only after the
initial custom query succeeds. `x`
deletes an empty pane and compacts the rest without adding a placeholder.

### Presets

| Preset | Pane composition | Columns / spotlight | Dashboard style |
| --- | --- | --- | --- |
| `single` | Analog Clock only, without a text overlay or Dashboard frame | `1 / 0` | `minimal` |
| `wide` | Timeline, Stack, Ranking, Monitor grouped by model | `2 / 0` | `framed` |
| `wide-clock` | Digital Clock, then the standard wide panes | `2 / 1` with a compact first row | `framed` |
| `narrow` | 14-day Timeline, project Ranking, model Monitor | `1 / 0` | `framed` |
| `narrow-clock` | Digital Clock, then narrow panes | `1 / 0` with a short first row | `framed` |
| `all` | Two Timelines, Calendar, Ranking, two Stacks, and four Monitor variants | `2 / 0` | `split` |

The default `wide` panes use compact density and deliberately use separate
chart themes/styles. `single`, `wide-clock`, and `narrow-clock` are the clock
presets: their clock is a complete animation Pane, not a Dashboard header.
`single` uses Analog Clock; `wide-clock` and `narrow-clock` use Digital Clock.

Built-in presets remain startup templates, while topology is independently controlled by
`--columns` and `--spotlight`. Named built-in or
saved presets launched as `ccuv dashboard <name>` are deliberately closed: they
reject `--pane` and every configuration override except `--demo`, `--lang`,
`--empty`, and `--ccusage-bin`.

### Build a custom Dashboard

A pane fragment is one safely quoted chart command plus chart options. A Dataset
fragment is `chart <kind>` with a Dataset ID and one source mode: an installed
Dataset uses a bare `--dataset ID`, while an arbitrary developer command uses `--command`.
`empty` is a valid temporary fragment. The copied command preserves that source
choice and uses `shlex.join` for arbitrary command argv, so token boundaries and
intermediate empty pane positions round-trip:

```bash
ccuv dashboard \
  --pane 'timeline --period 30d --by model --top 5 --style line-points' \
  --pane 'ranking --by project --top 10 --style dots' \
  --pane 'monitor --window 1h --by model --style ranking' \
  --columns 2 --spotlight 0
```

The first N spotlight Panes occupy full-width rows; remaining Panes flow into the configured columns.

A custom pane defaults to `compact` density unless the fragment explicitly
contains `--density`. For example, an installed WeRead Dataset needs no binary
path or fixed dates:

```bash
ccuv dashboard --empty --columns 1 --spotlight 0 \
  --pane 'chart timeline --dataset weread'
```


### Dashboard-host options

| Option | Values/default | Host-owned behavior |
| --- | --- | --- |
| `[PRESET]` (positional, optional) | `single`, `wide`, `wide-clock`, `narrow`, `narrow-clock`, `all`; omitted defaults to `wide-clock` | Selects the startup template. Topology flags may override its layout. |
| `--demo [SIZE]`, `--lang`, `--ccusage-bin`, `--query-timeout` | Same semantics as standalone; all demo forms are live, invocation-varied asynchronous simulations, and bare demo is `medium`; timeout default `30` | Provider/process/input configuration for all panes. `--query-timeout` is hidden advanced configuration. |
| `--ascii` | off | ASCII rendering for the host and panes. It conflicts with an explicit Pane `--theme`. |
| `--theme THEME` | `classic` | Dashboard shell theme, distinct from each Pane chart theme. |
| `--columns C` | Positive integer; preset/default supplies a value | Panes per ordinary row. |
| `--spotlight N` | `0..Pane count`; preset/default supplies a value | Number of leading full-width Pane rows. |
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

Pane fragments may contain a chart command (`timeline`, `calendar`, `stack`,
`ranking`, or `monitor`), optionally prefixed by `chart`, plus `animate` with an
explicit style or `empty`. A Dataset pane always requires `--dataset`; choose
exactly one source: a bare `--dataset ID` for an installed Dataset, or `--command`
for an arbitrary command. The legacy `custom` prefix remains accepted for
historical Dataset pane fragments but is not the documented form and does not
support Monitor. Command text becomes argv with
`shlex.split` and runs without a shell. Dashboard presets remain token-consumption
startup templates; they do not become Dataset presets. All fragments must not include
host/lifecycle options such as:

```text
--interval --watch --ascii --demo --lang
--ccusage-bin --query-timeout --pane --grid --refresh-interval
--sampling-interval --header-style --header-summary --header-interval
--help --version -h
```

A Dashboard header deliberately runs an unfiltered, all-Agent aggregate query;
it does not become a summary of the focused Pane's filters. Likewise, Dashboard
`--style` controls Dashboard chrome while a Pane's `--style` controls that
chart. Dashboard's sampling cadence is host-wide, so Monitor Pane adjustment does not expose a Pane-local interval control.

<!-- guide:interactive-controls -->

## Interactive controls and Pane adjustments

### Common focused-chart controls

A `chart` command enters the normal Dashboard browse mode with one Pane. The
control footer and contextual Help show the active meaning for the current
Dashboard or Pane mode:

| Key | Behavior |
| --- | --- |
| `Ctrl-C` | Exit. |
| `r` | In chart view, refresh a historical query or request a Monitor sample immediately; it has no action in a non-chart text view. |
| `c` | In chart view, show/hide the session-only control footer. |
| `h` | Open contextual Help from the chart view. |
| `e` | In a non-chart text view, go to the final line. |
| `Up` / `Down` | In a non-chart text view, scroll one rendered line. |
| `v` / `V` | Cycle forward / backward through chart, compact command, full command, Markdown table, and JSON. |
| `y` | Copy the current command/data text from a non-chart view. |
| `m` | Open adjustment only from the chart view. |
| `s` / `d` / `l` | In supported adjustment pickers: style / density / legend controls. |
| `L` | Open bounded diagnostics Logs for custom-command charts/panes and animation history; lowercase `l` remains legend. |

The compact command view omits defaults and private project paths. The full
command view includes effective settings, including private project paths,
selected binary path, and query timeout. Copying is not persistence: the
program writes no configuration automatically. Runtime changes last only for
the current process; save a copied command yourself if you want to reuse it. Text
scrolling changes only the visible viewport: `y` always copies the complete,
unscrolled command or data payload.

### Shortcut conventions

Adjustment shortcuts are scoped to the visible page or Dashboard management mode;
the control footer always shows the active meaning. For an ordered finite control
that displays a lowercase/uppercase pair, lowercase advances, uppercase reverses,
and both directions wrap. This applies to `p/P` periods, `g/G` historical
granularity, `b/B` grouping, `t/T` theme, `s/S` style, and `v/V` views.

Capitalization is not a universal reverse rule. `N`/`n` mean insert before/after;
`u/U` mean undo/redo; `H` changes Dashboard
Header presentation; and `L` opens custom diagnostics or animation history.
`f`, `l`, `o`, `k`, and `c` remain lowercase direct actions despite appearing on
the Advanced page.

Historical `p/P` traverses the shared sequence `7d → 14d → 30d → 90d → 180d →
365d → 1w → 1mo → 1y`; at either endpoint it wraps to the other end. `1w`,
`1mo`, and `1y` mean This week, This month, and This year respectively, ending
at today. The sequence applies to every historical token or Dataset chart, not
just its current granularity. On a fixed explicit-date range it has no effect.

### Historical adjustment flow

For Timeline, Calendar, Stack, and Ranking, press `m` in chart view. The
picker previews changes, `a` switches **Quick** and **Advanced** pages, and
`Enter`/newline commits the current candidate. `Esc` cancels the picker.
Visual-only changes update the preview immediately; data-affecting changes are
used by the subsequent configuration refresh after commit.

Adjustment mode closes automatically after **three minutes** with no keyboard or
mouse interaction. Enter, `Esc`, and that timeout restore ordinary Dashboard
browse mode with the body and every Pane in chart view. Changes already applied in a picker
keep their normal close semantics, while an open filter draft is discarded just
as with `Esc`. Dashboard layout and Pane-type subpickers also cancel and return
to browse mode.

| Chart | Quick page | Advanced page |
| --- | --- | --- |
| Timeline | `p/P` period; `g/G` granularity; `b/B` grouping; `+/-` Top; `d` density; `t/T` theme; `s/S` style | `f` filters; `o` Other; `l` legend; `k` weekday labels |
| Calendar | `p/P` period; `d` density; `t/T` theme; `s/S` style | `f` filters |
| Stack | `p/P` period; `g/G` granularity; `b/B` grouping; `+/-` Top; `d` density; `t/T` theme; `s/S` style | `f` filters; `o` Other; `c` cache mode; `l` legend; `k` weekday labels |
| Ranking | `p/P` period; `b/B` grouping; `+/-` Top; `d` density; `t/T` theme; `s/S` style | `f` filters; `o` Other |
| Monitor | Timeline styles: `w` window; `i` sampling interval; `b/B` grouping; `+/-` Top; `d` density; `t/T` theme; `s/S` style. `cumulative-bars`: `w` Today/Yesterday; `g` hour/30 min; `b/B` grouping; `+/-` Top; `d` density; `t/T` theme; `s/S` style. Ranking/list omit `w`. | `f` filters; `l` legend |

`p` advances and `P` reverses through the shared historical sequence
`7d → 14d → 30d → 90d → 180d → 365d → 1w → 1mo → 1y`. `1w`, `1mo`, and `1y`
are week-to-date, month-to-date, and year-to-date periods. Both directions wrap;
neither changes a fixed explicit-date range. Grouping/style changes retain a
compatible style; for example changing Timeline to grouped mode will replace
`area` with a compatible style.

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
| Monitor window, Top, interval, distribution day/granularity, or visual controls | Retained observations are immediately reprojected or restyled; no `querying` marker. |

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
| Quick | Timeline styles: `w` window and `i` sampling interval; `cumulative-bars`: `w` Today/Yesterday, `g` hour/30 min, and `i` sampling interval; ranking/list omit `w`; all applicable styles retain `b/B` grouping, `+/-` Top, `d` density, `t/T` theme, and `s/S` style |
| Advanced | `f` filters; `l` legend |

Grouping and filters require a fresh matching observation baseline; window
changes reproject retained observations immediately. When the interval changes,
Monitor rebuilds its scheduler. Appearance-only changes apply without
pretending to recreate prior observation history.

### Dashboard controls

Dashboard has separate navigation and ownership rules. In browse mode:

| Key | Behavior |
| --- | --- |
| `r` | In chart browse mode, refresh all panes; it has no action in the full-command view. |
| `Ctrl-S` | Save the current Dashboard as a named preset. |
| `P` | Open the full-screen Dashboard preset manager. |
| Mouse click | Adjust the clicked pane. |
| `d` | Open global Dashboard adjustment. |
| `h` | Open contextual Help. In the full-command view, lowercase `h` goes to the first line. |
| `c` | In chart browse mode, show/hide the Dashboard control footer. |
| `e`, `Up` / `Down` | In the full Dashboard command view, go to the final line or scroll one rendered line. |
| `v` / `V` | Cycle forward / backward between the Dashboard chart and full-command views. |
| `y` | Copy from command view. |
| `Ctrl-C` | Exit. |

While adjusting a Pane, `v` advances and `V` reverses its view. Native and custom
Dataset panes cycle chart, compact command, full command, data table, and JSON;
custom data exports describe ccuv's currently projected data rather than a raw
Dataset process response. In a non-chart pane text view,
`Up`/`Down` scroll one line, `h` goes to the first line, and `e` goes to the
final line; the pane's notices remain fixed. Its always-visible footer contains
only reading, copying, and view-cycle actions, and only advertises scrolling
when the text overflows. `r` has no action there; chart
Quick/Advanced controls and Dashboard pane management remain unavailable while
text is shown. Enter, `Esc`, or the inactivity timeout exits adjustment and
restores every Pane to chart view. In chart view, `r` replaces it; `N` inserts
before; `n` inserts after; `x` deletes it when more than one Pane remains;
`[`/`]` reorder it; and `Tab` moves focus to the next Pane. `{`/`}` adjust
logical column shares; `_`/`=` adjust logical row shares. Focused Pane Quick
keys are the historical/Monitor chart controls listed above, except Monitor has
no `i` because sampling belongs to the Dashboard host. Global Dashboard
adjustment uses `t/T` for shell theme, `s/S` for shell style, `H` for header
style, `p/P` for header-summary scope, and `z` for layout. Pressing `z` opens the layout
chooser: use `j`/`k` or arrow keys to select a compatible layout, then `Enter`
to apply it or `Esc` to cancel. Fixed-capacity layouts that cannot fit the
current Pane count remain listed as unavailable and are skipped by navigation.

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
| Pane fragment is rejected | Keep host/lifecycle options at Dashboard level; the fragment should only describe a supported chart, `empty`, animation, or custom source. |
| Custom command fails or returns invalid protocol data | Inspect `L` Logs. The previous valid custom rendering is retained; see the [custom command protocol](custom-command-protocol.md) for the JSON contract. |
| Monitor does not show old historical throughput | This is expected: it observes only snapshots gathered by the current process. |
| Runtime adjustment disappeared after exit | This is expected: adjustments are session-local. Reuse a copied command by saving it yourself. |

For intermittent `unified_daily` local-Agent-database access failures, see [known issues](known-issues.md).

Use `ccuv --help` for the route list and `ccuv <command> --help` for
localized parser help, for example `ccuv --lang zh dashboard --help`. The
normal help intentionally omits advanced `--query-timeout` and Dashboard weight
options; this guide records them so their constraints are clear.


## Flexible Dashboard topology (0.3.5)

Dashboard presets (`single`, `wide`, `wide-clock`, `narrow`, `narrow-clock`, and `all`) are complete startup configurations. Spatial layout is independent and uses two integers:

```bash
ccuv dashboard wide --columns 3 --spotlight 2
```

The first `--spotlight N` Panes are full-width rows from top to bottom. Remaining Panes flow left-to-right into `--columns C` columns. `--column-weight` and `--row-weight` may be repeated to reproduce exact proportions. In global adjustment mode, press `z`; use Up/Down or `j`/`k` to select a field, Left/Right or `-`/`+` to change it, Enter to commit, and Escape to cancel. The live preview does not modify accepted state until commit. With a Pane selected, `{`/`}` resize its column and `J`/`K` resize its row.

`--grid`, `--layout`, `spotlight-wide`, and `spotlight-wide2` are no longer supported. Saved Dashboard presets use schema `ccuv.dashboard-presets/v2`; v1 collections are intentionally not migrated. `dashboard --empty` creates four temporary empty Panes, while topology only controls their placement.
