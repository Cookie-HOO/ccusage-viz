# ccusage-viz

[简体中文](README.zh-CN.md) · [Design philosophy](docs/design-philosophy.md)

`ccusage-viz` turns [`ccusage`](https://github.com/ryoppippi/ccusage) Token data into one terminal-native chart per invocation. It is designed for people who use Claude Code, Codex, or custom models and want an on-demand view—or a lightweight live dashboard—without introducing another usage database.

> **Status:** `0.1.0` is an alpha release under local development. Versions use `major.minor.patch`; stable compatibility begins with `1.x.x`. During `0.x.x`, CLI, TUI, data, and other public interfaces may change incompatibly. Feedback and issue reports are welcome. The code has been tested against `ccusage 20.0.20`; `ccusage` is not bundled.

## Why ccusage-viz?

- **Five focused views** — daily timeline, calendar heatmap, component stack, cumulative ranking, and observed-TPM monitor.
- **Token-only** — no cost, quota, QPM, or API rate-limit monitoring.
- **Stateless** — reads `ccusage` command output and does not scan Agent logs, create a usage database, or keep a persistent cache.
- **Live when useful** — historical charts refresh every 10 seconds by default; Monitor samples every 15 seconds by default, with pause and manual refresh controls.
- **Source-aware projects** — Claude and Codex projects remain separate even when their display names match.
- **Bilingual UI** — built-in English and Simplified Chinese.

Every chart command requires an interactive terminal. Help and version output do not.

## Quickstart

Try the renderer safely with deterministic synthetic data. Demo mode does not invoke `ccusage` and does not write usage data:

```bash
uv run ccuv timeline --demo
uv run ccuv calendar --demo small
uv run ccuv stack --demo large --cache split
uv run ccuv ranking --demo --by project
```

To use real data, install and configure `ccusage`, then run:

```bash
uv run ccuv timeline
uv run ccuv ranking --by model --period 30d
```

## Installation

After the package is published to PyPI, install it with pipx:

```bash
pipx install ccusage-viz
ccuv --version
ccuv --version
```

`ccuv` is a packaged command alias for `ccusage-viz`; both commands have identical behavior.


### From a source checkout

Python 3.11–3.13 and [`uv`](https://docs.astral.sh/uv/) are required for this workflow:

```bash
git clone https://github.com/Cookie-HOO/ccusage-viz.git
cd ccusage-viz
uv sync --all-groups
uv run ccuv --help
```

Install the checkout as an editable command-line tool:

```bash
uv tool install -e .
ccuv --version
```

`ccusage` must be available on `PATH`, or supplied with `--ccusage-bin`. If the default `ccusage` command is missing in an interactive terminal, ccuv shows the exact `npm install -g ccusage` command and runs it only after an empty Enter confirmation, then continues the original command. Ctrl-C, EOF, or any typed text cancels. Demo, redirected/noninteractive execution, and custom `--ccusage-bin` values never trigger installation; install manually if npm is unavailable or restart/update `PATH` if npm succeeds but the command is still not visible. The application uses `plotext` as its only runtime Python dependency.

## Commands

Each rendering command produces one chart; `dashboard` composes independently refreshed charts in one terminal.

| Command | Default range | Default grouping | Default Top N | Output |
| --- | ---: | --- | ---: | --- |
| `timeline` | 14 days | `total` | 3 for grouped views | One daily line chart; grouped views draw multiple lines on the same chart |
| `calendar` | 365 days | — | — | Monday-first GitHub-style heatmap with four positive-value quantile levels |
| `stack` | 14 days | Token components | — | Daily stacked bars for input, output, and combined cache |
| `ranking` | 14 days | `project` | 10 | Horizontal total-Token bars with the effective inclusive range in the heading |
| `monitor` | process-local 1 hour | authoritative Total TPM | — | Persistent observed Token throughput from repeated snapshots |
| `dashboard` | per pane | Timeline, Stack, Ranking, Monitor | per pane | One dashboard with adjustment-only pane selection and independent refresh |

All date ranges are **inclusive natural days**. `--period 14d` means today plus the preceding 13 days. Rolling ranges are headed by their canonical period (for example, `Timeline · 14d`); a range explicitly bounded by both `--since` and `--until` instead shows its resolved dates. `--until` defaults to today; use `--timezone` with an IANA name to define the natural-day boundary. `--period` cannot be combined with `--since`.

```bash
# One total line for the last 14 days
ccuv timeline

# Top three models on one chart (the packaged alias is equivalent)
ccuv timeline --by model

# Top five Agents, with all remaining positive groups combined last
ccuv timeline --by agent --top 5 --other show

# A bounded range in a chosen natural-day timezone
ccuv calendar --since 2026-01-01 --until 2026-03-31 \
  --timezone America/Los_Angeles

# Split cache read and cache creation instead of combining them
ccuv stack --period 30d --cache split

# Agent-scoped project ranking
ccuv ranking --by project --top 20
```

`--top` must be positive. For Monitor, `--top` requires `--by agent`, `--by model`, or `--by project`. Filters run before grouping and Top N. Groups beyond the post-filter Top N are hidden unless `--other show` is set; only those excluded groups are combined as `Other`, which does not consume a Top slot and is always last. If no post-filter group falls beyond Top N, no empty `Other` is drawn and a notice explains why. Use a large value such as `--top 999` when you want an effectively unlimited view. During Watch or Dashboard refreshes, Ranking separates three signals: an arrow beside the rank appears only when a stable item moves up or down; a highlighted `●` (`*` with `--ascii`) before the item marks changed activity; and `↑`, `↓`, or `—` beside the numeric value marks increase, decrease, or equality (`^`, `v`, or `=` with `--ascii`). The initial baseline is marker-free. An entry first seen after that baseline gets activity and value-up markers but no fabricated rank arrow; `Other` never claims rank movement.

### Filters and grouping

Think of the input as a virtual table that exists only during one refresh:

```text
date | agent | model | project | input | output | cache_read | cache_creation | total
```

The ordinary metric is `SUM(totalTokens)`. `--by` acts like `GROUP BY`; `--agent`, `--model`, and `--project` act like `WHERE`; and `--top N` acts like `ORDER BY SUM(totalTokens) DESC LIMIT N`. `stack` is the exception: it aggregates Token components separately.

Selectors are repeatable:

```bash
ccuv timeline --by model --agent claude --model sonnet --model opus
ccuv ranking --by project --project project-a --project project-b
```

Repeated selectors in one dimension are ORed; different dimensions are ANDed. Matching is case-insensitive and exact-first. A unique contains match is accepted; ambiguous contains matches produce candidates and require more text.

Model filtering and grouping use actual upstream model breakdowns—Token totals are never proportionally allocated. Dates or components missing inside an otherwise valid result are filled with zero. If a selected Agent, model, or project has no data in the range, the available chart still renders with a notice naming the empty selection. A positive residual between `totalTokens` and known components appears as `Other`; components exceeding the upstream total are treated as incompatible schema data.

### Project identity and capability limits

A project is identified as `(agent, opaque upstream project ID)`. Projects from different Agents are never merged automatically. When two Agents expose the same display name, project grouping still renders them separately. An exact selector such as `--project project-a` may therefore select same-name projects from both Agents; add `--agent claude` or `--agent codex` to narrow candidates.

Opaque Claude instance IDs are not decoded into guessed paths. When ccusage supplies a path-encoded opaque identifier, its final project segment is shown; otherwise the current view assigns a neutral `Project N` alias. Real path-like IDs may use their basename as a display name, but identity always retains the original upstream value.

Current `ccusage 20.0.20` capabilities differ by view:

| View | Queries per refresh | Notes |
| --- | ---: | --- |
| Ordinary non-project views | 1 | `ccusage daily --by-agent --json … --offline --no-cost` |
| `timeline`, `calendar`, or `stack` requiring project data | 1 | Claude bounded daily instances; Codex is omitted with a capability notice |
| `ranking --by project` or project-filtered ranking | 2, in parallel | Fixed Claude daily-instances query plus fixed Codex session query |

The two-query ranking path is a fixed data-source plan, not a loop over dates, Agents, models, or projects. Claude session totals are intentionally not used for bounded accounting because `ccusage 20.0.20` can include out-of-range usage from matching sessions; Codex session filtering is event-range bounded.

### Period comparison summaries

`timeline` and `stack` use `--granularity day|month|quarter|year`; runtime `g` changes Granularity without changing the selected Period or date range. `calendar` and `ranking` remain daily. Period accepts `d`, `mo`, `q`, and `y` independently, so an explicit `--period 12mo` remains valid at any Granularity. A range with both `--since` and `--until` is fixed. Summaries always aggregate the complete current filter scope, independent of Top N presentation clipping. When Top N hides groups and `Other` is off, the summary is qualified as the current-filter total and notes that the chart shows only Top N; complete charts omit that qualification.

Day compares today with yesterday and the same weekday seven days earlier. Month and quarter compare period-to-date with the same elapsed-day count in the prior period and last year; year compares year-to-date with prior-year-to-date. Calendar boundaries are used rather than fixed 30/90/365-day subtraction, and shorter periods are clamped. A summary derives only from records already loaded for its chart—standalone commands and Dashboard panes never run summary-only queries.

Coverage comes from each successful requested interval, including successful empty responses; it is never inferred from the first or last returned row. A missing row inside covered time is a real zero, while time outside coverage is unknown. Current-period coverage is required before a numeric summary appears, and each uncovered comparison is omitted independently. Equal values use a neutral marker (`—`, or `=` with `--ascii`), a positive value against zero is shown as “from 0” with an upward marker, and a positive baseline falling to zero is a 100% decrease. The complete sentence, fragments, punctuation, and placeholders are localized in the built-in English and Simplified Chinese catalogs.

Calendar’s metrics footer is always three logical rows: active days/current streak/longest streak; daily average plus an optional peak; and the heat legend. The average remains visible when no peak exists, and narrow terminals clip each row independently.


## Monitor

```bash
ccuv monitor
ccuv monitor --by model --top 2
ccuv monitor --interval 20 --window 2h
ccuv monitor --demo small
```

`monitor` is an always-running, process-local observation. The first successful cumulative `ccusage` snapshot establishes a baseline; later snapshots are differentiated using monotonic elapsed time. It therefore has no readings before startup and cannot reconstruct a past 24-hour chart. Native process-local history keeps minute rollups for up to 24 hours; the displayed window defaults to one hour and can be adjusted from 5 minutes to 24 hours. `--window` retains only this invocation's observed history (5m–24h, default `1h`); `--interval` is the target delay between sampling attempts (default 15 seconds for real monitoring). Demo Monitor defaults to a 1-second synthetic cadence unless `--interval` is explicitly supplied; hidden `--query-timeout` bounds one `ccusage` subprocess invocation.

Omitting `--by` shows authoritative **Total TPM**. `--by model` shows per-model TPM; `--by agent` and `--by project` show cumulative Token growth from the visible window’s left edge. Grouped views can use `--legend values` for a minimal, marker-free list of each visible item and its latest displayed observation. Compact Monitor ranking uses an arrow beside the rank only for real rank movement and `↑`, `↓`, or `—` beside the value for increase, decrease, or equality (`^`, `v`, and `=` with `--ascii`); it intentionally has no activity point because every Monitor series is live. The initial baseline is marker-free, while a series first seen later gets value-up but no fabricated rank arrow. Grouped Monitor modes default to Top 3 and fold the remainder into `Other`. `--agent`, `--model`, and `--project` are startup-only source filters. Monitor exits with `Ctrl-C`; `r` samples now, Space pauses/resumes, and `v` cycles chart → compact command → full command → Markdown data table → JSON data → chart. The compact command omits defaults; full command makes every effective setting explicit. Chart view permits `m` adjustment and has no copy shortcut. Every other view permits `y` copy but not adjustment. The table and JSON serialize the exact displayed buckets, including grouping, Top N, and `Other`, never raw counters. `h` hides or restores the session-only control footer to reclaim chart rows, and `m` opens the two-row runtime adjustment panel only from chart view. Its Quick page adjusts window, interval, grouping, Top, theme, and style without querying again or losing retained history; `a` switches to Advanced, where legend placement lives, and `y` copies the candidate command. Startup `--model` filters are preserved and are not runtime controls. Adjustment guides always remain visible and closing the panel restores the prior footer preference. Monitor x-axis labels use `HH:MM`. Use `--theme` and `--style` to choose an initial appearance; use `monitor --demo` for immediate style exploration because real observed history does not exist at startup. Demo monitor data is deterministic, starts with a fluctuating in-memory history, stays in memory, and never invokes `ccusage`.

Observed TPM is neither QPM nor API rate-limit TPM. There is no QPM metric. External QPM, when added in a future release, will count logical requests and will never infer requests from tokens or retries. Monitor `style=ranking` is a compact current-value view of the process-local observed window, not the cumulative historical `ranking` command: Total and Model show current observed TPM, while Agent and Project show current Token growth within the visible window. Monitor does not claim historical per-minute data, arbitrary date-range hourly distribution, or a rolling period that predates process startup. Sampling gaps, query errors, and counter decreases are not treated as zero traffic.

## Dashboard

```bash
# Wide is the default preset; narrow and all provide alternative starting points
ccuv dashboard
ccuv dashboard narrow
ccuv dashboard all

# A preset can be overridden and extended with additional panes
ccuv dashboard wide --refresh-interval 30 --pane "calendar"

# Or define the complete pane list without a preset
ccuv dashboard --pane "timeline --period 7d" --pane "stack" \
  --pane "ranking --by agent" --pane "monitor --by model --top 5" --grid 2x2

# Set Dashboard-owned Historical refresh and Monitor sampling cadences
ccuv dashboard --refresh-interval 30 --sampling-interval 5

# Choose header presentation, summary period, and independent summary cadence
ccuv dashboard --header-style panel --header-summary quarter --header-interval 90
```

`dashboard` owns one terminal input loop and compositor while each Pane keeps its latest result, failure state, and—when it is a Monitor Pane—its own in-memory observation history. It starts with a compact loading state rather than an empty framed grid. The default `wide` preset is a filled 2×2 overview: Timeline, Stack, Ranking, and Monitor grouped by Model. Bare `ccuv dashboard` is equivalent to `ccuv dashboard wide`; `narrow` provides a three-pane vertical view and `all` expands all ten representative views into a framed 5×2 grid. A preset supplies the base panes and settings, explicit Dashboard options override it, and repeated `--pane` values append. Without a preset, `--pane` defines the complete list. The generated Wide Monitor is equivalent to `monitor --by model`; standalone `monitor` and an explicit `--pane "monitor"` still show authoritative Total TPM. `--pane` takes a quoted chart fragment beginning with `timeline`, `calendar`, `stack`, `ranking`, or `monitor`; Host, process, and lifecycle options are rejected inside fragments. Dashboard owns cadence: `--refresh-interval` refreshes Historical Panes and `--sampling-interval` samples Monitor Panes. `--grid ROWSxCOLUMNS` selects the startup grid (`auto` uses up to two columns).

The Dashboard Header is independent from pane summaries. `--header-style` accepts `hidden`, `compact`, `banner`, or `panel` (the default). `--header-summary` independently selects `day`, `month`, `quarter`, `year`, or `none` (default `day`); `none` keeps the title and freshness but omits detail, while `hidden` removes the entire Header. During a cold period switch, the full localized structure appears immediately with `??` values and is replaced only by accepted data. Header data is an unfiltered all-agent total refreshed separately every 60 seconds by default (`--header-interval`). The title row right-aligns the last successfully accepted update time; failed or stale refreshes do not advance it. Dashboard `--theme` colors only the shell, title, Header summary, placeholders, and separators; every pane keeps its own `--theme`. Dashboard `--style` consolidates shell structure into `minimal`, `split` (default), `framed`, or `accent`; it never changes pane chart styles or Header Style. Press `s` to adjust pane 1 or click a pane directly; `Tab` is inert while browsing and wraps between panes during pane adjustment.

Browse mode intentionally has one concise footer row: `r` refresh all, `s`/click adjust a pane, `g` open global adjustment, `h` hide/show controls, `y` copy the Dashboard, and Space pause/resume scheduling. Details and pane-command display are not part of Dashboard. Data and capability warnings from panes appear once in a global warning block directly above this footer, rather than inside compact pane cells. Pane and global adjustment both start on **Quick** settings; `a` toggles **Advanced**. Global Quick contains Theme, Style, Header, summary, and layout. Global Advanced contains `+` add pane, `x` delete, `[`/`]` reorder, and `Tab` select pane. Pane adjustment retains each chart’s standalone-like controls and `y` copies only that pane. A copied Dashboard preserves shell Theme/Style and each pane’s independent Theme/Style. `Ctrl-C` restores the terminal and cancels active child queries.

Monitor owns an anchored, padded y-axis shared by standalone and Dashboard rendering. The bound expands immediately when data crosses it and shrinks only after sustained lower utilization, so small fluctuations move the line instead of continuously moving the axis. This changes presentation only: Total and Model remain observed TPM, while Agent and Project remain visible-window Token growth.

Dashboard child panes share no completed data. Overlapping calls with the **exact** executable string, argument tuple, and timeout use one running subprocess, then each pane receives its own decoded copy. Different commands, options, timeouts, or calls that start after a prior one finished are never merged. The independent Header alone retains a process-local unfiltered daily coverage cache: a warm period switch renders immediately, a cold wider switch queries only Header data and shows `??` for unknown detail until accepted, and accepted intervals authoritatively replace cached rows. Failed, cancelled, or stale results preserve the last accepted Header data and freshness.

## Historical lifecycle

Historical charts continuously refresh by default every 10 seconds:

```bash
ccuv timeline                # refresh every 10 seconds
ccuv timeline --interval 20  # custom cadence
ccuv timeline --no-watch     # paint one complete interactive frame, then exit
```

The minimum interval is two seconds. `--interval` cannot be combined with `--no-watch`. The delay starts after a refresh completes, so refreshes do not overlap. Continuous historical views keep a compact control reminder on the terminal’s final row; Demo mode also includes its size keys. Controls:

- `Ctrl-C` — exit and cancel child `ccusage` processes owned by this invocation.
- `r` — refresh now; while a refresh is running, queue at most one more.
- `h` — hide or restore the session-only control footer, returning its row to the chart; adjustment guides remain visible.
- `Space` — pause or resume automatic refresh. Manual refresh remains available.
- `v` — cycle chart → compact command → full command → Markdown data table → JSON data → chart; the footer names the next view.
- `y` — unavailable in chart view; copy the compact command, full command, complete Markdown table, or complete JSON payload from the corresponding text view.
- `m` — available only in chart view to adjust the active historical view; rolling ranges offer only 7, 14, 30, or 365 days. The adjustment starts on **Quick** settings; press `a` for **Advanced** settings, where Timeline/Stack expose weekday labels with `k`.
- `s`, `d`, `l` — switch synthetic magnitude while watching Demo mode (`d` selects medium there).

Watch data-table and data-json modes serialize the chart-ready post-filter, post-aggregation model: displayed date buckets, series/components, Top N, and `Other`, never pre-aggregation provider rows. The compact command omits defaults; the full command is an explicit audit command and includes local executable, timeout, and selected project-path settings. Watch uses the full active terminal height and repaints without a trailing newline, preventing each refresh from scrolling the screen. The status remains on the first row, the control reminder remains on the final row, and warnings appear immediately above the controls with a warning glyph and fixed semantic foreground color. While a refresh runs, Watch preserves the previous status text and appends a dim `refreshing` hint by updating only the first line; pressing Space likewise updates that row immediately, including when a query is still running. The selected body is repainted when a result arrives; any terminal resize also forces a full repaint. Watch emits one final newline on exit so the shell prompt starts cleanly. One-shot rendering instead reserves one terminal row for the next shell prompt and keeps notices above the chart. The previous successful chart remains visible while refreshing and after a later error. No-data and too-small-terminal states remain alive for a later refresh. Relative windows such as `--period 14d` advance when the selected natural-day timezone crosses midnight; explicitly bounded ranges stay fixed. `Ctrl-C` exits and restores terminal input mode without a traceback.

Multiple Watch processes can run independently. There is no global lock, daemon, PID file, shared cache, or cross-process state; each process owns only its children. Concurrent instances also run independent `ccusage` scans, so CPU, disk, and memory costs add up.

### Deferred hourly and rolling-history views

Current `ccusage 20.0.20` JSON cannot support exact hourly history: daily rows contain dates only, session rows expose aggregate totals rather than time-bucketed usage, Claude blocks are five-hour billing windows, and there is no uniform Claude/Codex request count. The upstream hourly proposal [#724](https://github.com/ccusage/ccusage/pull/724) closed without merge, and the former `blocks --live` monitor was removed in [#782](https://github.com/ccusage/ccusage/pull/782). Consequently, ccuv does not claim exact rolling 24-hour peaks, hourly usage habits, or call volume. It also does not compensate by reading raw Agent logs, sampling into a history file, running a collector, or creating a usage database. Exact hourly views remain blocked on a supported upstream hourly JSON contract.

## Demo mode

```bash
ccuv timeline --demo         # medium
ccuv timeline --demo small
ccuv timeline --demo medium
ccuv timeline --demo large
```

The generated records are deterministic. The three sizes change magnitude only—not dates, shape, or identities—and cover zero days, peaks, unit boundaries, same-name Agent-scoped projects, residual Tokens, and Top overflow. Demo mode never invokes `ccusage` and never writes usage records.

### Chart styles

Theme selects semantic foreground colors; Style selects the chart grammar. Use `--theme` and `--style` to select the initial appearance. In a running TUI, press `m` to adjust supported settings against the retained snapshot without starting another query.

Styles are command-specific: Timeline supports `linear`, `step`, `no-line`, `points`, `line-points`, `stem`, and `area`. `no-line` keeps each series’ distinct marker without a connecting line; `points` uses uniform filled points without lines; `line-points` connects uniform filled points with a linear line. Monitor supports `bars`, `line`, `step`, `points`, `line-points`, and `ranking`; its two uniform-point styles have the same no-line and linear-line semantics as Timeline. Calendar supports `relative` and `absolute`; Stack supports `stacked`, `stacked-pattern`, `grouped`, `grouped-thin`, and `normalized`; Ranking supports `bar`, `dot`, and `dots`. `--ascii` changes glyphs independently of Theme or Style.

## Language and terminal behavior

Use `--lang en` or `--lang zh`. Without it, Python's system locale selects Simplified Chinese for `zh_CN`, `zh_SG`, or `Hans`; Traditional Chinese locales and all other languages fall back to English.

All commands accept `--theme classic|vivid|contrast|dracula|catppuccin|solarized|gruvbox|nord|github|mono|no-color`; `classic` is the default. Dracula, Catppuccin, Solarized, Gruvbox, Nord, and GitHub are curated ANSI-256 adaptations of mature theme families rather than exact editor-theme reproductions. The GitHub theme uses a contribution-graph-inspired four-level green Calendar scale plus complete semantic colors for every command. Themes select foreground colors only. They cover timeline series and Other, calendar levels, stack components, Ranking marks, and diagnostic highlights. The application does not infer terminal brands or light/dark backgrounds, so the terminal background remains inherited. Timeline uses jointly allocated categorical colors plus distinct markers. Stack uses mixed-temperature categorical colors plus distinct component marks, so identity is not color-only. Calendar uses an ordered four-step palette, while glyph density (`░▒▓█`, or `.oO#` with `--ascii`) remains the authoritative low-to-high magnitude encoding.

Use `--theme no-color` to disable ANSI styling explicitly and reproducibly; `NO_COLOR` is not interpreted. Explicit `--ascii` cannot be combined with any explicitly supplied `--theme`, including `classic` and `no-color`; omitting `--theme` keeps the implicit default valid. `TERM=dumb` is rejected unless `--ascii` is explicitly supplied; ASCII mode is never enabled automatically. Minimum terminal sizes are:

| Command | Minimum size |
| --- | --- |
| `timeline` | 58×16 |
| `calendar` | 58×16 |
| `stack` | 58×16 |
| `ranking` | 58×16 |

## Suggested aliases

```bash
alias cct='ccuv timeline'
alias ccm='ccuv timeline --by model --period 30d'
alias ccs='ccuv stack --period 30d --cache split'
alias ccp='ccuv ranking --by project --period 30d'
```

## Stateless and privacy boundaries

During normal operation, `ccusage-viz` consumes only `ccusage` command output. It does **not**:

- read Claude Code, Codex, or other Agent raw logs directly;
- create a usage database, index, persistent cache, or application config;
- start a daemon or create a PID file;
- calculate costs, quotas, or rate limits;
- provide JSON, CSV, TSV, or table output;
- persist Demo or real usage records.

Upstream Agent, model, and project values may appear as chart labels or diagnostics. Raw `ccusage` stderr is not translated.

## Development

```bash
uv sync --all-groups
uv run ruff format --check .
uv run ruff check .
uv run ty check src/
uv run pytest
uv build
```

Python compatibility targets are 3.11, 3.12, and 3.13. The package uses a `src/` layout and the `uv_build` backend.

## Publishing metadata

No GitHub release or PyPI publication is implied by this source checkout. The intended future PyPI Trusted Publisher configuration is:

- repository: `Cookie-HOO/ccusage-viz`
- workflow: `pypi-publish.yml`
- environment: `pypi`

## Roadmap and support

The public roadmap is in [ROADMAP.md](ROADMAP.md). Please use the standard [bug report](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=bug_report.yml) or [feature request](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=feature_request.yml) forms for actionable feedback.

## License

MIT. See [LICENSE](LICENSE).
