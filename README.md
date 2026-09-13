# ccusage-viz

[简体中文](README.zh-CN.md)

`ccusage-viz` turns [`ccusage`](https://github.com/ryoppippi/ccusage) Token data into one terminal-native chart per invocation. It is designed for people who use Claude Code, Codex, or custom models and want an on-demand view—or a lightweight live dashboard—without introducing another usage database.

> **Status:** `0.1.0` is an alpha release under local development. The code has been tested against `ccusage 20.0.20`; `ccusage` is not bundled.

## Why ccusage-viz?

- **Five focused views** — daily timeline, calendar heatmap, component stack, cumulative ranking, and observed-TPM monitor.
- **Token-only** — no cost, quota, QPM, or API rate-limit monitoring.
- **Stateless** — reads `ccusage` command output and does not scan Agent logs, create a usage database, or keep a persistent cache.
- **Live when useful** — Watch refreshes every five seconds by default; Monitor samples every 15 seconds by default, with pause and manual refresh controls.
- **Source-aware projects** — Claude and Codex projects remain separate even when their display names match.
- **Bilingual UI** — built-in English and Simplified Chinese, plus strict partial message overrides.

Every chart command requires an interactive terminal. Help and version output do not.

## Quickstart

Try the renderer safely with deterministic synthetic data. Demo mode does not invoke `ccusage` and does not write usage data:

```bash
uv run ccusage-viz timeline --demo
uv run ccusage-viz calendar --demo small
uv run ccusage-viz stack --demo large --split-cache
uv run ccusage-viz ranking --demo --by project
```

To use real data, install and configure `ccusage`, then run:

```bash
uv run ccusage-viz timeline
uv run ccusage-viz ranking --by model --days 30
```

## Installation

After the package is published to PyPI, install it with pipx:

```bash
pipx install ccusage-viz
ccusage-viz --version
ccuv --version
```

`ccuv` is a packaged command alias for `ccusage-viz`; both commands have identical behavior.


### From a source checkout

Python 3.11–3.13 and [`uv`](https://docs.astral.sh/uv/) are required for this workflow:

```bash
git clone https://github.com/Cookie-HOO/ccusage-viz.git
cd ccusage-viz
uv sync --all-groups
uv run ccusage-viz --help
```

Install the checkout as an editable command-line tool:

```bash
uv tool install -e .
ccusage-viz --version
```

`ccusage` must be available on `PATH`, or supplied with `--ccusage-bin`. The application uses `plotext` as its only runtime Python dependency.

## Commands

Each invocation renders exactly one chart.

| Command | Default range | Default grouping | Default Top N | Output |
| --- | ---: | --- | ---: | --- |
| `timeline` | 14 days | `total` | 3 for grouped views | One daily line chart; grouped views draw multiple lines on the same chart |
| `calendar` | 365 days | — | — | Monday-first GitHub-style heatmap with four positive-value quantile levels |
| `stack` | 14 days | Token components | — | Daily stacked bars for input, output, and combined cache |
| `ranking` | 14 days | `project` | 10 | Horizontal total-Token bars with the effective inclusive range in the heading |
| `monitor` | process-local 1 hour | authoritative Total TPM | — | Persistent observed Token throughput from repeated snapshots |

All date ranges are **inclusive natural days**. `--days 14` means today plus the preceding 13 days. `--until` defaults to today; use `--timezone` with an IANA name to define the natural-day boundary. `--days` cannot be combined with `--since`.

```bash
# One total line for the last 14 days
ccusage-viz timeline

# Top three models on one chart (the packaged alias is equivalent)
ccuv timeline --by model

# Top five Agents, with all remaining positive groups combined last
ccusage-viz timeline --by agent --top 5 --show-other

# A bounded range in a chosen natural-day timezone
ccusage-viz calendar --since 2026-01-01 --until 2026-03-31 \
  --timezone America/Los_Angeles

# Split cache read and cache creation instead of combining them
ccusage-viz stack --days 30 --split-cache

# Agent-scoped project ranking
ccusage-viz ranking --by project --top 20
```

`--top` must be positive. For Monitor, `--top` is valid only with `--by model`. Filters run before grouping and Top N. Groups beyond the post-filter Top N are hidden unless `--show-other` is set; only those excluded groups are combined as `Other`, which does not consume a Top slot and is always last. If no post-filter group falls beyond Top N, no empty `Other` is drawn and a notice explains why. Use a large value such as `--top 999` when you want an effectively unlimited view.

### Filters and grouping

Think of the input as a virtual table that exists only during one refresh:

```text
date | agent | model | project | input | output | cache_read | cache_creation | total
```

The ordinary metric is `SUM(totalTokens)`. `--by` acts like `GROUP BY`; `--agent`, `--model`, and `--project` act like `WHERE`; and `--top N` acts like `ORDER BY SUM(totalTokens) DESC LIMIT N`. `stack` is the exception: it aggregates Token components separately.

Selectors are repeatable:

```bash
ccusage-viz timeline --by model --agent claude --model sonnet --model opus
ccusage-viz ranking --by project --project project-a --project project-b
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

### Daily comparison summary

`calendar` and `timeline` show one localized summary for default ranges, `--days`, and ranges with only one explicit boundary. `--no-summary` suppresses that summary for timeline, calendar, and stack. A range with both `--since` and `--until` is treated as a fixed historical range and omits the summary. Calendar compares its displayed aggregate daily totals; timeline aggregates only the lines actually drawn, including a visible `Other` line while excluding groups hidden by Top N.

Summary values use fixed four-decimal compact tokens where applicable. The summary compares the range's current day with the preceding day and with the same weekday seven days earlier, using the localized “today” wording for these current-day views. Comparison dates outside a short rendered range are zero-filled like missing source dates in the chart. Positive baselines use percentage change with one decimal place; equal values are shown as unchanged, a positive value against a zero baseline is shown as “up from 0 to the current value,” and a positive baseline falling to zero is a 100% decrease. The current value uses a fixed cyan accent, increases use green, and decreases use a darker amber that remains readable on light and dark terminal backgrounds, independent of the chart scheme; `mono` remains grayscale. The complete sentence, fragments, punctuation, and placeholders can be changed through the strict language override catalog.


## Monitor

```bash
ccusage-viz monitor
ccusage-viz monitor --by model --top 2
ccusage-viz monitor --interval 20 --window 2h
ccusage-viz monitor --demo small
```

`monitor` is an always-running, process-local observation. The first successful cumulative `ccusage` snapshot establishes a baseline; later snapshots are differentiated using monotonic elapsed time. It therefore has no readings before startup and cannot reconstruct a past 24-hour chart. Native process-local history keeps minute rollups for up to 24 hours; the displayed window defaults to one hour and can be adjusted from 5 minutes to 24 hours. `--window` retains only this invocation's observed history (5m–24h, default `1h`); `--interval` is the target delay between sampling attempts (default 15 seconds for real monitoring). Demo Monitor defaults to a 1-second synthetic cadence unless `--interval` is explicitly supplied; hidden `--timeout` bounds one `ccusage` subprocess invocation.

Omitting `--by` shows authoritative **Total TPM**. `--by model` and `--by agent` show their respective TPM projections; `--by project` shows each project’s cumulative Token growth from the visible window’s left edge. Grouped Monitor modes default to Top 3 and fold the remainder into `Other`. `--agent`, `--model`, and `--project` are startup-only source filters. Monitor supports `q` quit, `r` sample now, Space pause/resume, and `m` to open the two-row runtime adjustment panel. The panel adjusts window, interval, grouping, Top, theme, and style without querying again or losing retained history; `y` copies its candidate command. Monitor x-axis labels use `HH:MM`. Use `--theme` and `--style` to choose an initial appearance; Monitor deliberately rejects startup `--pick` because real observed history does not exist yet—use `monitor --demo` for immediate style exploration instead. Demo monitor data is deterministic, starts with a fluctuating in-memory history, stays in memory, and never invokes `ccusage`.

Observed TPM is neither QPM nor API rate-limit TPM. There is no QPM metric. External QPM, when added in a future release, will count logical requests and will never infer requests from tokens or retries. It does not claim historical per-minute data, arbitrary date-range hourly distribution, or a rolling period that predates process startup. Sampling gaps, query errors, and counter decreases are not treated as zero traffic.

## Watch mode

```bash
ccusage-viz timeline --watch       # 5 seconds
ccusage-viz timeline --watch 10    # 10 seconds
```

The minimum interval is two seconds. The delay starts after a refresh completes, so refreshes do not overlap. Watch keeps a compact control reminder on the terminal’s final row; Demo mode also includes its size keys. Controls:

- `q` — quit and cancel child `ccusage` processes owned by this invocation.
- `r` — refresh now; while a refresh is running, queue at most one more.
- `Space` — pause or resume automatic refresh. Manual refresh remains available.
- `s`, `m`, `l` — switch synthetic magnitude while watching Demo mode.

Watch uses the full active terminal height and repaints without a trailing newline, preventing each refresh from scrolling the screen. The status remains on the first row, the control reminder remains on the final row, and warnings appear immediately above the controls with a warning glyph and fixed semantic foreground color. While a refresh runs, Watch preserves the previous status text and appends a dim `refreshing` hint by updating only the first line; pressing Space likewise updates that row immediately, including when a query is still running. The chart is repainted only when a result arrives. Watch emits one final newline on exit so the shell prompt starts cleanly. One-shot rendering instead reserves one terminal row for the next shell prompt and keeps notices above the chart. The previous successful chart remains visible while refreshing and after a later error. No-data and too-small-terminal states remain alive for a later refresh. Relative windows such as `--days 14` advance when the selected natural-day timezone crosses midnight; explicitly bounded ranges stay fixed. `Ctrl-C` behaves like quit and restores terminal input mode without a traceback.

Multiple Watch processes can run independently. There is no global lock, daemon, PID file, shared cache, or cross-process state; each process owns only its children. Concurrent instances also run independent `ccusage` scans, so CPU, disk, and memory costs add up.

### Deferred hourly and rolling-history views

Current `ccusage 20.0.20` JSON cannot support exact hourly history: daily rows contain dates only, session rows expose aggregate totals rather than time-bucketed usage, Claude blocks are five-hour billing windows, and there is no uniform Claude/Codex request count. The upstream hourly proposal [#724](https://github.com/ccusage/ccusage/pull/724) closed without merge, and the former `blocks --live` monitor was removed in [#782](https://github.com/ccusage/ccusage/pull/782). Consequently, ccusage-viz does not claim exact rolling 24-hour peaks, hourly usage habits, or call volume. It also does not compensate by reading raw Agent logs, sampling into a history file, running a collector, or creating a usage database. Exact hourly views remain blocked on a supported upstream hourly JSON contract.

## Demo mode

```bash
ccusage-viz timeline --demo         # medium
ccusage-viz timeline --demo small
ccusage-viz timeline --demo medium
ccusage-viz timeline --demo large
```

The generated records are deterministic. The three sizes change magnitude only—not dates, shape, or identities—and cover zero days, peaks, unit boundaries, same-name Agent-scoped projects, residual Tokens, and Top overflow. Demo mode never invokes `ccusage` and never writes usage records.

### Appearance picker and chart styles

Theme selects semantic foreground colors; Style selects the chart grammar. Both choices apply only to the current process:

```bash
ccusage-viz timeline --pick
ccusage-viz calendar --pick --theme github
ccusage-viz stack --pick --split-cache
ccusage-viz timeline --pick --demo small
ccusage-viz timeline --pick --watch 5
```

Without `--demo`, the picker performs one ordinary `ccusage` snapshot using the active date range and selectors. With `--demo [small|medium|large]`, it uses that deterministic synthetic dataset throughout and never invokes `ccusage`. Navigation rerenders only the retained in-memory snapshot; it does not query or regenerate data.

The picker keeps exactly one chart on screen. Press `n` for the next theme, `p` for the previous theme, `j` for the next style, `k` for the previous style, `y` to copy the normalized candidate command, Enter to confirm, and `q` or Ctrl-C to cancel; navigation wraps. `--theme` and `--style` select the initial appearance. It works for Ranking and remains available with `--no-color` so Style can still be selected; in that mode Theme is visually inert. Without Watch, confirmation leaves the selected chart visible and exits. With Watch, the selected snapshot becomes the initial Watch chart and the first automatic refresh waits for the interval.

Styles are command-specific: Timeline supports `linear`, `step`, `stem`, and `area`; Calendar supports `relative` and `absolute`; Stack supports `stacked`, `stacked-pattern`, `grouped`, `grouped-thin`, and `normalized`; Ranking supports `bar`, `dot`, and `dots`. `--ascii` changes glyphs and `--no-color` removes ANSI styling; neither is a Theme or Style.

## Language and terminal behavior

Use `--lang en` or `--lang zh`. Without it, Python's system locale selects Simplified Chinese for `zh_CN`, `zh_SG`, or `Hans`; Traditional Chinese locales and all other languages fall back to English.

A JSON file may override selected messages:

```bash
ccusage-viz timeline --lang en --lang-file examples/language-overrides.json
```

Override files may contain any subset of known keys; omitted keys inherit from the selected built-in language. The supplied subset is validated atomically: valid UTF-8 JSON, object root, no duplicate or unknown keys, non-empty string values, and exactly matching placeholder names, conversions, and format specifications; named placeholders may be reordered. Watch mode loads the file once. See [Language overrides](docs/language-overrides.md) for every key and placeholder.

All commands accept `--theme classic|vivid|contrast|dracula|catppuccin|solarized|gruvbox|nord|github|mono`; `classic` is the default. Dracula, Catppuccin, Solarized, Gruvbox, Nord, and GitHub are curated ANSI-256 adaptations of mature theme families rather than exact editor-theme reproductions. The GitHub theme uses a contribution-graph-inspired four-level green Calendar scale plus complete semantic colors for every command. Themes select foreground colors only. They cover timeline series and Other, calendar levels, stack components, Ranking marks, and diagnostic highlights. The application does not infer terminal brands or light/dark backgrounds, so the terminal background remains inherited. Timeline uses jointly allocated categorical colors plus distinct markers. Stack uses mixed-temperature categorical colors plus distinct component marks, so identity is not color-only. Calendar uses an ordered four-step palette, while glyph density (`░▒▓█`, or `.oO#` with `--ascii`) remains the authoritative low-to-high magnitude encoding.

Use `--no-color` (or `NO_COLOR`) to disable all styling and make the selected scheme visually inert; use `--ascii` to change chart marks without changing summary prose. `TERM=dumb` also selects conservative terminal behavior. Minimum terminal sizes are:

| Command | Minimum size |
| --- | --- |
| `timeline` | 60×18 |
| `calendar` | 72×14 |
| `stack` | 60×18 |
| `ranking` | 60×12 |

## Suggested aliases

```bash
alias cct='ccusage-viz timeline --watch'
alias ccm='ccusage-viz timeline --by model --days 30'
alias ccs='ccusage-viz stack --days 30 --split-cache'
alias ccp='ccusage-viz ranking --by project --days 30'
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
