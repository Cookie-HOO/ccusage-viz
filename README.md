# ccusage-viz

[简体中文](README.zh-CN.md) · [Usage guide](docs/usage.md) · [Design philosophy](docs/design-philosophy.md) · [Architecture](docs/architecture.md)

[![PyPI](https://img.shields.io/pypi/v/ccusage-viz.svg)](https://pypi.org/project/ccusage-viz/) [![Python](https://img.shields.io/pypi/pyversions/ccusage-viz.svg)](https://pypi.org/project/ccusage-viz/) [![License: GPL v3](https://img.shields.io/badge/License-GPL%20v3-blue.svg)](LICENSE) [![CI](https://github.com/Cookie-HOO/ccusage-viz/actions/workflows/ci.yml/badge.svg)](https://github.com/Cookie-HOO/ccusage-viz/actions/workflows/ci.yml)

> **Alpha · 0.1.0** — interfaces may change before 1.0. See the [roadmap](ROADMAP.md) for planned work.

`ccusage-viz` is an independent, unofficial terminal visualizer for
[`ccusage`](https://github.com/ryoppippi/ccusage) token data. It turns
`ccusage` command output into interactive terminal charts without creating a
second usage database. `ccusage` is required for real data and is **not**
bundled with this project.

> This project is not affiliated with or endorsed by the `ccusage` project or
> its maintainers.

## Dashboard presets

`dashboard` composes independently configured charts in one terminal. Start
with the default overview:

```bash
ccuv dashboard wide
```

### `wide` (default)

A balanced 2×2 overview of Timeline, Stack, Ranking, and Monitor panes.

![Wide Dashboard preset: balanced 2×2 overview](docs/assets/readme/dashboard-wide.png)

### `narrow`

A compact, vertically focused layout for a narrower terminal.

![Narrow Dashboard preset: vertically focused compact layout](docs/assets/readme/dashboard-narrow.png)

### `all`

A broad gallery that keeps several representative pane forms visible at once.

![All Dashboard preset: broad gallery of representative panes](docs/assets/readme/dashboard-all.png)

### `spotlight-wide`

Timeline receives the leading full-width row; the remaining panes follow below.

![Spotlight-wide Dashboard preset: Timeline leads in a full-width row](docs/assets/readme/dashboard-spotlight-wide.png)

### `spotlight-wide2`

Timeline and Stack receive consecutive full-width rows before the smaller panes.

![Spotlight-wide2 Dashboard preset: Timeline and Stack lead in consecutive full-width rows](docs/assets/readme/dashboard-spotlight-wide2.png)

> [!TIP]
> Dashboard coordinates pane queries: identical in-flight provider requests are
> shared, avoiding duplicate work while multiple panes refresh.

## When to use a standalone chart

Choose a standalone view when you need to focus on one question rather than an
overview composed from multiple panes.

### Timeline

Use Timeline for daily token trends, grouped by model, agent, or project:

```bash
ccuv timeline
```

The 14-day view makes recent daily movement easy to compare.

![Timeline view: 14-day daily token trend](docs/assets/readme/standalone-timeline-14d.png)

The 13-month view makes longer-term changes visible at a coarser scale.

![Timeline view: 13-month long-range trend](docs/assets/readme/standalone-timeline-13mo.png)

### Calendar

Use Calendar to scan a longer period for active days, streaks, and concentrated
usage:

```bash
ccuv calendar
```

![Calendar view: contribution heatmap with activity intensity](docs/assets/readme/standalone-calendar.png)

### Stack

Use Stack to compare input, output, and cache-token composition over time:

```bash
ccuv stack --cache split
```

This view emphasizes the overall composition of token types.

![Stack view: token composition over time](docs/assets/readme/standalone-stack-composition.png)

This variation separates cache reads from cache creation.

![Stack view: cache reads versus cache creation](docs/assets/readme/standalone-stack-cache-split.png)

### Ranking

Use Ranking to find the projects, models, or agents with the most tokens in a
range:

```bash
ccuv ranking --by project
```

![Ranking view: projects ordered by total tokens](docs/assets/readme/standalone-ranking.png)

### Monitor

Use Monitor for process-local throughput observed from repeated cumulative
snapshots—not reconstructed hourly history:

```bash
ccuv monitor
```

An observed throughput window starts after a sampling baseline is established.

![Monitor view: observed token throughput window](docs/assets/readme/standalone-monitor-throughput.png)

The grouped view ranks the selected dimension within the observed window.

![Monitor view: grouped ranking](docs/assets/readme/standalone-monitor-ranking.png)

The list view provides process and item detail alongside the observation.

![Monitor view: process and list detail](docs/assets/readme/standalone-monitor-list.png)

> [!TIP]
> Need several focused charts together? Compose standalone chart commands into a
> custom Dashboard and choose your own grid or named layout. See the
> [usage guide](docs/usage.md).

For commands, filters, controls, styles, and data semantics, see the
[usage guide](docs/usage.md). The [architecture overview](docs/architecture.md)
is intended for maintainers.

## Install, update, and remove

Requires Python 3.11–3.13. `ccuv` is the short alias for `ccusage-viz`; both
installed commands behave the same way.

### From uv

Install the isolated command-line tool:

```bash
uv tool install ccusage-viz
ccuv --version
```

Update or remove it:

```bash
uv tool upgrade ccusage-viz
uv tool uninstall ccusage-viz
```

### From pip

Use an activated virtual environment, then install or update the package:

```bash
python -m pip install --upgrade ccusage-viz
ccuv --version
```

Remove it from that environment:

```bash
python -m pip uninstall ccusage-viz
```

### From source

Clone the repository and install an editable tool:

```bash
git clone https://github.com/Cookie-HOO/ccusage-viz.git
cd ccusage-viz
uv sync --all-groups
uv tool install -e .
ccuv --help
```

After pulling newer source, refresh or remove the editable tool:

```bash
uv tool install --reinstall -e .
uv tool uninstall ccusage-viz
```

### Missing `ccusage`?

Real-data commands need `ccusage` on `PATH` (or an explicit `--ccusage-bin`).
If the default command is missing in an interactive terminal, `ccuv` offers:

```bash
npm install -g ccusage
```

An empty **Enter** or `y`/`Y` confirms that installation. Any other input,
Ctrl-C, or EOF cancels it. Demo mode, redirected/noninteractive runs, and custom
`--ccusage-bin` runs never prompt or install automatically. Install
[`ccusage`](https://github.com/ryoppippi/ccusage) manually when npm is
unavailable.

## Further reading

`ccusage-viz` is token-only and stateless: it does not read raw Agent logs,
store a usage database, or calculate cost, quota, QPM, or rate-limit metrics.
These documents answer the deeper questions:

| Document | What it answers |
| --- | --- |
| [Usage guide](docs/usage.md) | How do I install, configure, compose, and adjust charts and Dashboards? |
| [Design philosophy](docs/design-philosophy.md) | Which product boundaries, ownership rules, and presentation principles are intentional? |
| [Architecture](docs/architecture.md) | How do CLI routes, hosts, panes, providers, processing, and renderers fit together for maintainers? |
| [Roadmap](ROADMAP.md) | What is planned, deferred, or open for feedback? |

Report reproducible problems with the [bug report form](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=bug_report.yml), or propose improvements through the [feature request form](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=feature_request.yml).

Licensed under the [GNU General Public License v3.0 only](LICENSE).
