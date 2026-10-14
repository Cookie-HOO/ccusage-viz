# ccusage-viz

[简体中文](README.zh-CN.md) · [Usage guide](docs/usage.md) · [Custom command protocol](docs/custom-command-protocol.md) · [Design philosophy](docs/design-philosophy.md) · [Architecture](docs/architecture.md) · [Versioning](docs/versioning.md)

[![PyPI](https://img.shields.io/pypi/v/ccusage-viz.svg)](https://pypi.org/project/ccusage-viz/) [![Python](https://img.shields.io/pypi/pyversions/ccusage-viz.svg)](https://pypi.org/project/ccusage-viz/) [![License: GPL v3](https://img.shields.io/badge/License-GPL%20v3-blue.svg)](LICENSE) [![CI](https://github.com/Cookie-HOO/ccusage-viz/actions/workflows/ci.yml/badge.svg)](https://github.com/Cookie-HOO/ccusage-viz/actions/workflows/ci.yml)

> **Alpha · 0.2.2** — interfaces may change before 1.0. See the [roadmap](docs/roadmap.md) for current direction.

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

Historical date boundaries use the local IANA timezone by default. Pass
`--timezone AREA/LOCATION` to select another calendar context; copied commands
retain the resolved timezone. ccuv sends that timezone explicitly to every
custom Dataset request, while a Dataset may return a non-blocking warning if it
cannot apply the requested timezone.

> This project is not affiliated with or endorsed by the `ccusage` project or
> its maintainers.

## Interactive Help

Dashboard provides contextual Help: press `h` to see the controls for the
active surface, and press `c` in chart-browse mode to show or hide its footer.
While editing Overlay text or a command, use `Ctrl-H` instead so the literal `h`
remains available to the draft.

## Dashboard presets

`dashboard` composes independently configured charts in one terminal. Without a positional preset, `dashboard` defaults to `wide-clock`:

> [!TIP]
> To start without default ccusage panes or requests, use `ccuv dashboard --empty`.
> It fills the selected default grid or explicit `--grid`/layout with temporary
> `empty` panes. Add an installed Dataset with only its chart type and Dataset ID:
> `--pane 'chart timeline --dataset weread'`. Arbitrary commands add `--command`.
> See the [custom command protocol guide](docs/custom-command-protocol.md).

```bash
ccuv dashboard
```

| Preset | Command | Layout | Preview |
| --- | --- | --- | --- |
| `single` | `ccuv dashboard single` | A single live analog clock without a text overlay or Dashboard frame. | - |
| 【Recommended—wide terminal】 `wide-clock` **(default without a preset)** | `ccuv dashboard wide-clock` | Best for an all-purpose overview with a live analog clock. Analog clock + balanced 2×2. | <img src="docs/assets/readme/dashboard-wide-clock.png" alt="Preview" width="180"> |
| 【Recommended—sidebar】 `narrow-clock` | `ccuv dashboard narrow-clock` | Best for a sidebar with a live clock. Clock + vertical 4×1. | <img src="docs/assets/readme/dashboard-narrow-clock.png" alt="Preview" width="180"> |
| `wide` | `ccuv dashboard wide` | Best for a balanced data-only overview. Balanced 2×2. | <img src="docs/assets/readme/dashboard-wide.png" alt="Preview" width="180"> |
| `narrow` | `ccuv dashboard narrow` | Best for a compact, narrow-terminal overview. Vertical focus. | <img src="docs/assets/readme/dashboard-narrow.png" alt="Preview" width="180"> |
| `all` | `ccuv dashboard all` | Best for comparing many pane types at once. Broad gallery. | <img src="docs/assets/readme/dashboard-all.png" alt="Preview" width="180"> |
| `spotlight-wide` | `ccuv dashboard spotlight-wide` | Best for prioritizing Timeline trends. Timeline-led. | <img src="docs/assets/readme/dashboard-spotlight-wide.png" alt="Preview" width="180"> |
| `spotlight-wide2` | `ccuv dashboard spotlight-wide2` | Best for prioritizing Timeline and Stack together. Timeline + Stack-led. | <img src="docs/assets/readme/dashboard-spotlight-wide2.png" alt="Preview" width="180"> |

### Your Dashboard presets

In Dashboard browse mode, press `Ctrl-S` to save the current Dashboard under a name,
or `Ctrl-P` to open the full-screen preset manager. The manager lists built-in and
your saved presets; use arrows or `j`/`k` to select, `Enter` to load, `s` to
save, and `x` to delete a selected user preset. Built-ins can be loaded but not
deleted. Saving a user preset with a built-in name intentionally overrides it;
deleting that user preset reveals the built-in again. Saving over an existing
user preset asks whether to overwrite or cancel.

Preset names must match `^[a-z][a-z0-9-]*$`. A saved name can be launched in a
fresh terminal with `ccuv dashboard <name>`. A named launch is closed to
configuration overrides: only `--demo`, `--lang`, `--empty`, and `--ccusage-bin`
may accompany it. For example:

```bash
ccuv dashboard weekly-review
ccuv dashboard weekly-review --demo --lang zh-CN
ccuv dashboard weekly-review --empty
ccuv dashboard weekly-review --ccusage-bin /opt/bin/ccusage
```

With a named preset, `--empty` keeps its layout, weights, display settings,
refresh/sampling cadence, timezone, demo and process settings, but replaces every
pane with an empty pane in memory; it never changes the saved preset. The ordinary
unnamed `ccuv dashboard --empty` flow remains available for composing a new
temporary Dashboard. A demo-enabled preset stays demo-enabled when loaded;
Dashboard currently has no runtime control for turning demo off.

Presets persist declarative Dashboard configuration, including installed Dataset
references, local-command argv, and executable Overlay commands, but never query
results, environments, credentials, or UI/runtime state. Presets are trusted
user-local automation: load only presets you trust, because loading one can run
the commands it contains. Presets live in ccuv's private state directory under
`dashboard-presets/presets.json` (`~/Library/Application Support/ccuv` on macOS,
`%LOCALAPPDATA%/ccuv` on Windows, or `${XDG_STATE_HOME:-~/.local/state}/ccuv` on
other systems). A missing installed Dataset leaves a preset loadable and its pane
reports the unavailable source; only unreadable, malformed, or unsupported preset
storage is shown as unavailable and protected from overwrites.

> [!TIP]
> Dashboard coordinates pane queries: identical in-flight provider requests are
> shared, avoiding duplicate work while multiple panes refresh.

## Standalone views

Choose a standalone view when you need to focus on one question rather than an
overview composed from multiple panes.

| Category | View | Command | Use it for | Preview |
| --- | --- | --- | --- | --- |
| Timeline `timeline` | Timeline — 14 days | `ccuv chart timeline` | Recent daily token trends grouped by model, agent, or project. | <img src="docs/assets/readme/standalone-timeline-14d.png" alt="Preview" width="180"> |
| Timeline `timeline` | Timeline — 13 months | `ccuv chart timeline --period 13mo` | Longer-term changes at a coarser scale. | <img src="docs/assets/readme/standalone-timeline-13mo.png" alt="Preview" width="180"> |
| Calendar `calendar` | Calendar | `ccuv chart calendar` | Active days, streaks, and concentrated usage over a longer period. | <img src="docs/assets/readme/standalone-calendar.png" alt="Preview" width="180"> |
| Stack `stack` | Stack — composition | `ccuv chart stack` | Overall input, output, and cache-token composition over time. | <img src="docs/assets/readme/standalone-stack-composition.png" alt="Preview" width="180"> |
| Stack `stack` | Stack — cache split | `ccuv chart stack --cache split` | Cache reads versus cache creation over time. | <img src="docs/assets/readme/standalone-stack-cache-split.png" alt="Preview" width="180"> |
| Ranking `ranking` | Ranking | `ccuv chart ranking --by project` | Projects, models, or agents with the most tokens in a range. | <img src="docs/assets/readme/standalone-ranking.png" alt="Preview" width="180"> |
| Terminal animations `animate` | Animation gallery | `ccuv animate --gallery` | Provider-free presentation-only animations; optionally specify a style, for example `ccuv animate digital-clock --gallery`. `m` opens local style and theme controls. | <img src="docs/assets/readme/standalone-animation-gallery.gif" alt="Preview" width="180"> |
| Monitor `monitor` | Trend | `ccuv chart monitor` | Process-local throughput from repeated cumulative snapshots, not reconstructed hourly history. The observation begins after its sampling baseline; Timeline styles mark the invocation start while visible. | <img src="docs/assets/readme/standalone-monitor-throughput.png" alt="Preview" width="180"> |
| Monitor `monitor` | Cumulative bars | `ccuv chart monitor --style cumulative-bars` | Retained local-day token increments. Press `w` for Today/Yesterday and `g` for hourly/half-hour buckets; unobserved periods remain distinct from observed zero values. | <img src="docs/assets/readme/standalone-monitor-cumulative-bars.png" alt="Preview" width="180"> |
| Monitor `monitor` | Ranking | `ccuv chart monitor --style ranking --by project` | The selected dimension ranked within its observed window. | <img src="docs/assets/readme/standalone-monitor-ranking.png" alt="Preview" width="180"> |
| Monitor `monitor` | List | `ccuv chart monitor --style list` | Process and item detail alongside the observation. | <img src="docs/assets/readme/standalone-monitor-list.png" alt="Preview" width="180"> |
| Monitor `monitor` | Animation attachment | In Monitor `ranking` or `list`: press `m`, then `s` | Optional animation below the data. Disabled by default; `s`/`S` cycles eligible effects and ccuv-local `none`, while `t`/`T` changes only its theme. It waits for a comparable accepted interval and never causes another usage query. | <img src="docs/assets/readme/standalone-monitor-animation.gif" alt="Preview" width="180"> |

> [!TIP]
> Project Ranking uses conservative **Name** aggregation by default: an unambiguous
> Claude–Codex pair becomes one chart project. Press `v` for its data views: they
> show the safe source rows before aggregation, and equal non-empty `merge_group`
> values identify the rows summed into one chart project. Project views use
> conservative cross-Agent Name aggregation.

> [!TIP]
> Need several focused charts together? Compose standalone chart commands into a
> custom Dashboard and choose your own grid or named layout. See the
> [usage guide](docs/usage.md).

A declared V2 Dataset can independently rank real models within each logical
model:

```bash
ccuv chart ranking --dataset router --partition-by logical_model --group-by real_model
```

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
> adds `ccusage dsh` reports. Install that branch instead of the published npm
> package:
>
> ```bash
> npm install -g "git+https://github.com/oksure/ccusage.git#contrib/dsh-usage-adapter"
> ```
>
> It may drift from upstream. ccuv has no DSH collector of its own.

## Further reading

`ccusage-viz` is token-only and stateless: it does not analyze Agent transcripts,
store a usage database, or calculate cost, quota, QPM, or rate-limit metrics. For Codex
project attribution only, it may read the matching local session's `session_meta.cwd`; it
never stores or displays session-log content.
These documents answer the deeper questions:

| Document | What it answers |
| --- | --- |
| [Usage guide](docs/usage.md) | How do I install, configure, compose, and adjust charts and Dashboards? |
| [Custom command protocol](docs/custom-command-protocol.md) | How do I connect an additive historical dataset through a command, use empty Dashboard panes, and implement the JSON contract? |
| [Dataset developer guide](docs/dataset-developer-guide.md) | How do I build, test locally, Probe, query, package, and publish a Dataset? |
| [Dataset user guide](docs/dataset-user-guide.md) | How do I install, manage, select, and use local, official, or GitHub Datasets? |
| [Design philosophy](docs/design-philosophy.md) | Which product boundaries, ownership rules, and presentation principles are intentional? |
| [Architecture](docs/architecture.md) | How do CLI routes, hosts, panes, providers, processing, and renderers fit together for maintainers? |
| [Roadmap](docs/roadmap.md) | What is planned, deferred, or open for feedback? |
| [Known issues](docs/known-issues.md) | Which intermittent `ccusage` problems are recognized, and how can I recover safely? |

Report reproducible problems with the [bug report form](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=bug_report.yml), or propose improvements through the [feature request form](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=feature_request.yml).

Licensed under the [GNU General Public License v3.0 only](LICENSE).
