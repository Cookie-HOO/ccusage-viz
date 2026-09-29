# ccusage-viz

[简体中文](README.zh-CN.md) · [Usage guide](docs/usage.md) · [Design philosophy](docs/design-philosophy.md) · [Architecture](docs/architecture.md) · [Versioning](docs/versioning.md)

[![PyPI](https://img.shields.io/pypi/v/ccusage-viz.svg)](https://pypi.org/project/ccusage-viz/) [![Python](https://img.shields.io/pypi/pyversions/ccusage-viz.svg)](https://pypi.org/project/ccusage-viz/) [![License: GPL v3](https://img.shields.io/badge/License-GPL%20v3-blue.svg)](LICENSE) [![CI](https://github.com/Cookie-HOO/ccusage-viz/actions/workflows/ci.yml/badge.svg)](https://github.com/Cookie-HOO/ccusage-viz/actions/workflows/ci.yml)

> **Alpha · 0.2.1** — interfaces may change before 1.0. See the [roadmap](ROADMAP.md) for current direction.

`ccusage-viz` is an independent, unofficial terminal visualizer for
[`ccusage`](https://github.com/ryoppippi/ccusage) token data. It turns
`ccusage` command output into interactive terminal charts without creating a
second usage database. It currently relies primarily on `ccusage` for real
data; `ccusage` is required and is **not** bundled with this project.

## Quick start

```bash
uv tool install ccusage-viz
ccuv dashboard
```

## Supported agents

Agent coverage follows `ccusage`. Its current supported agents include Claude
Code, Codex, OpenCode, Amp, Droid, Codebuff, Hermes Agent, pi-agent, Goose,
OpenClaw, Kilo, Kimi, Qwen, GitHub Copilot CLI, Gemini CLI, Antigravity, Grok
Build CLI, and ZCode. See the [ccusage support list](https://ccusage.com/) for
the authoritative and up-to-date list, plus setup and source-specific details.

## Product scope

ccusage-viz focuses exclusively on **token consumption** and metrics derived
from token consumption, such as observed tokens per minute (TPM). It does not
provide session analytics, request counts, elapsed-time metrics, costs,
pricing, balances, quotas, allowances, or other non-token account analytics.

> This project is not affiliated with or endorsed by the `ccusage` project or
> its maintainers.

## Dashboard presets

`dashboard` composes independently configured charts in one terminal. The default
preset is `wide-clock`:

```bash
ccuv dashboard
```

| Preset | Command | Layout | Preview |
| --- | --- | --- | --- |
| 【Recommended—wide terminal】 `wide-clock` **(default)** | `ccuv dashboard wide-clock` | Best for an all-purpose overview with a live clock. Clock + balanced 2×2. | <img src="docs/assets/readme/dashboard-wide-clock.png" alt="Preview" width="180"> |
| 【Recommended—sidebar】 `narrow-clock` | `ccuv dashboard narrow-clock` | Best for a sidebar with a live clock. Clock + vertical 4×1. | <img src="docs/assets/readme/dashboard-narrow-clock.png" alt="Preview" width="180"> |
| `wide` | `ccuv dashboard wide` | Best for a balanced data-only overview. Balanced 2×2. | <img src="docs/assets/readme/dashboard-wide.png" alt="Preview" width="180"> |
| `narrow` | `ccuv dashboard narrow` | Best for a compact, narrow-terminal overview. Vertical focus. | <img src="docs/assets/readme/dashboard-narrow.png" alt="Preview" width="180"> |
| `all` | `ccuv dashboard all` | Best for comparing many pane types at once. Broad gallery. | <img src="docs/assets/readme/dashboard-all.png" alt="Preview" width="180"> |
| `spotlight-wide` | `ccuv dashboard spotlight-wide` | Best for prioritizing Timeline trends. Timeline-led. | <img src="docs/assets/readme/dashboard-spotlight-wide.png" alt="Preview" width="180"> |
| `spotlight-wide2` | `ccuv dashboard spotlight-wide2` | Best for prioritizing Timeline and Stack together. Timeline + Stack-led. | <img src="docs/assets/readme/dashboard-spotlight-wide2.png" alt="Preview" width="180"> |

> [!TIP]
> Both shipped clock presets display a localized time-state Overlay at bottom-right
> by default. It follows the local wall clock and can be adjusted for the current
> Dashboard session.

> [!TIP]
> Dashboard coordinates pane queries: identical in-flight provider requests are
> shared, avoiding duplicate work while multiple panes refresh.

## Animation overlays

Add run-local context to a standalone animation or an explicit Dashboard Animation
Pane: place static text, show a localized time state, or render output from a
trusted local command.

```bash
ccuv animate rain --overlay-text "Focus time"
ccuv animate analog-clock --overlay-command "ccuv text time-state --run"
ccuv animate rain --overlay-command "date"
```

> [!WARNING]
> `--overlay-command` runs user-supplied local shell code. It inherits every
> environment variable visible to `ccuv` at launch, so treat commands and their
> execution environment as trusted local code.

See the [usage guide](docs/usage.md) for Overlay options, refresh behavior, and
Dashboard Animation Pane syntax.

## Standalone views

Choose a standalone view when you need to focus on one question rather than an
overview composed from multiple panes.

| Category | View | Command | Use it for | Preview |
| --- | --- | --- | --- | --- |
| Trends `timeline` | Timeline — 14 days | `ccuv timeline` | Recent daily token trends grouped by model, agent, or project. | <img src="docs/assets/readme/standalone-timeline-14d.png" alt="Preview" width="180"> |
| Trends `timeline` | Timeline — 13 months | `ccuv timeline --period 13mo` | Longer-term changes at a coarser scale. | <img src="docs/assets/readme/standalone-timeline-13mo.png" alt="Preview" width="180"> |
| Activity heatmap `calendar` | Calendar | `ccuv calendar` | Active days, streaks, and concentrated usage over a longer period. | <img src="docs/assets/readme/standalone-calendar.png" alt="Preview" width="180"> |
| Token composition `stack` | Stack — composition | `ccuv stack` | Overall input, output, and cache-token composition over time. | <img src="docs/assets/readme/standalone-stack-composition.png" alt="Preview" width="180"> |
| Token composition `stack` | Stack — cache split | `ccuv stack --cache split` | Cache reads versus cache creation over time. | <img src="docs/assets/readme/standalone-stack-cache-split.png" alt="Preview" width="180"> |
| Historical ranking `ranking` | Ranking | `ccuv ranking --by project` | Projects, models, or agents with the most tokens in a range. | <img src="docs/assets/readme/standalone-ranking.png" alt="Preview" width="180"> |
| Terminal animations `animate` | Animation gallery | `ccuv animate --gallery` | Provider-free presentation-only animations; optionally specify a style, for example `ccuv animate digital-clock --gallery`. Space pauses or resumes playback; `m` opens local style and theme controls. | <img src="docs/assets/readme/standalone-animation-gallery.gif" alt="Preview" width="180"> |
| Usage monitoring `monitor` | Monitor — throughput | `ccuv monitor` | Process-local throughput from repeated cumulative snapshots, not reconstructed hourly history. The observation begins after its sampling baseline; Timeline marks the invocation start while visible. | <img src="docs/assets/readme/standalone-monitor-throughput.png" alt="Preview" width="180"> |
| Usage monitoring `monitor` | Monitor — cumulative bars | `ccuv monitor --style cumulative-bars` | Retained local-day token increments. Press `w` for Today/Yesterday and `g` for hourly/half-hour buckets; unobserved periods remain distinct from observed zero values. | <img src="docs/assets/readme/standalone-monitor-cumulative-bars.png" alt="Preview" width="180"> |
| Usage monitoring `monitor` | Monitor — grouped ranking | `ccuv monitor --by project` | The selected dimension ranked within its observed window. | <img src="docs/assets/readme/standalone-monitor-ranking.png" alt="Preview" width="180"> |
| Usage monitoring `monitor` | Monitor — list | `ccuv monitor` | Process and item detail alongside the observation. | <img src="docs/assets/readme/standalone-monitor-list.png" alt="Preview" width="180"> |
| Usage monitoring `monitor` | Monitor animation attachment | In Monitor `ranking` or `list`: press `m`, then `s` | Optional animation below the data. Disabled by default; `s`/`S` cycles eligible effects and ccuv-local `none`, while `t`/`T` changes only its theme. It waits for a comparable accepted interval and never causes another usage query. | <img src="docs/assets/readme/standalone-monitor-animation.gif" alt="Preview" width="180"> |

> [!TIP]
> Project Ranking uses conservative **Name** aggregation by default: an unambiguous
> Claude–Codex pair becomes one chart project. Press `v` for its data views: they
> show the safe source rows before aggregation, and equal non-empty `merge_group`
> values identify the rows summed into one chart project. Use
> `--project-aggregation exact` to disable cross-Agent aggregation.

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

> [!TIP]
> The published `ccusage` package does not include DeepSeek Harness (DSH)
> statistics. The unofficial [`oksure/ccusage` DSH branch](https://github.com/oksure/ccusage/tree/contrib/dsh-usage-adapter)
> adds `ccusage dsh` reports; it may drift from upstream. ccuv has no DSH
> collector of its own.

## Further reading

`ccusage-viz` is token-only and stateless: it does not analyze Agent transcripts,
store a usage database, or calculate cost, quota, QPM, or rate-limit metrics. For Codex
project attribution only, it may read the matching local session's `session_meta.cwd`; it
never stores or displays session-log content.
These documents answer the deeper questions:

| Document | What it answers |
| --- | --- |
| [Usage guide](docs/usage.md) | How do I install, configure, compose, and adjust charts and Dashboards? |
| [Design philosophy](docs/design-philosophy.md) | Which product boundaries, ownership rules, and presentation principles are intentional? |
| [Architecture](docs/architecture.md) | How do CLI routes, hosts, panes, providers, processing, and renderers fit together for maintainers? |
| [Roadmap](ROADMAP.md) | What is planned, deferred, or open for feedback? |
| [Known issues](docs/known-issues.md) | Which intermittent `ccusage` problems are recognized, and how can I recover safely? |

Report reproducible problems with the [bug report form](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=bug_report.yml), or propose improvements through the [feature request form](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=feature_request.yml).

Licensed under the [GNU General Public License v3.0 only](LICENSE).
