# Dataset User Guide

[简体中文](dataset-user-guide.zh-CN.md) · [Developer guide](dataset-developer-guide.md)

Datasets add metrics that do not come from `ccusage`, such as reading, CI,
build, spend, or a local service's activity. ccuv renders and controls the
charts; each Dataset executable knows how to query its own source.

## What A Dataset Can And Cannot Do

A Dataset can add separately selectable Metrics with their own units, filters,
groupings, summaries, historical chart support, and source-owned Monitor
observations. A Dataset may also put related Metrics in author-declared Metric
Groups for clearer selection and quick switching. This makes it suitable for external activity such as reading,
builds, requests, amounts, bytes, or a local service's status. ccuv still owns
the terminal UI, Dashboard layout, refresh scheduling, and built-in `ccusage`
token charts; a Dataset does not alter or merge into built-in token collection.

At present, every Dataset is an executable command that ccuv starts for each
operation. ccuv sends one JSON request to the command's stdin, reads one JSON
response from stdout, and the command exits. This is not a plugin system, a
persistent service connection, or a file-import feature. A Dataset may access
its own APIs, files, databases, or local service internally, but users install
or register the executable command rather than connecting ccuv directly to an
HTTP endpoint, socket, Python module, or data file.

## Before You Start

Run `ccuv dataset` in an interactive terminal. It opens the Dataset manager.
Run `ccuv dataset list` when you only need a text list of registrations and
their readiness.

A Dataset becomes **Available** only when it is enabled, its latest Probe
succeeded, and all required environment variables are present. `Setup required`
means a required variable is missing. `Unavailable` means a refresh could not
run its Probe successfully. `Disabled` means ccuv hides it from Dashboard
selection and skips refreshes.

## Install Or Register A Dataset

### Local command: development or a tool already on your machine

Use this when you have an executable command locally. The command may include
fixed arguments; ccuv stores the argv, not a shell string.

```bash
ccuv dataset add-local /absolute/path/to/my-dataset --profile personal
ccuv dataset list
```

The command runs its Probe immediately. The program's returned Dataset ID, not
the executable filename, is the ID you later use with `--dataset`. Re-run the
same command after a developer changes Probe metadata. If the command reports
an already registered Dataset ID, `add-local` replaces that local registration.

You can also register it through the manager: `ccuv dataset`, press `+`, choose
**Local command**, type the command exactly as you would in a shell, then press
Enter to Probe and register it. The manager uses shell-like quoting only while
splitting the typed text into argv; it does not execute a shell.

### Official Dataset

1. Run `ccuv dataset`.
2. Press `+`, select **Browse official datasets**, and press Enter.
3. Select a Dataset with `j`/`k` or arrow keys; Enter shows version, supported
   charts, environment requirements, and source details.
4. Press Enter again to download, verify, install, and register the compatible
   release asset. Escape returns without installing.

Official entries come from ccuv's signed catalog. A catalog entry can still be
unavailable when it has no archive for your operating system and architecture.

### Any GitHub repository with a compatible release

1. Run `ccuv dataset`, press `+`, choose **Install from GitHub**.
2. Enter either `OWNER/REPOSITORY` or
   `https://github.com/OWNER/REPOSITORY`, then press Enter.
3. ccuv discovers the latest release, finds your platform archive and checksum,
   and shows a confirmation.
4. Press Enter to install or Escape to edit/cancel.

The repository must publish a compatible native archive and checksum. ccuv
rejects a repository that lacks a matching platform asset, checksum, valid
manifest, or executable. GitHub installation does not imply the Dataset is
official. If the same repository is in the official catalog, ccuv uses the
verified official artifact path instead.

## Configure And Maintain Datasets

In `ccuv dataset`:

| Action | Key | Result |
| --- | --- | --- |
| Select | `j` / `k` or arrows | Moves the selected registration. |
| Details | Enter | Shows Metrics, supported charts, environment variables, source, and version. Enter/Escape returns. |
| Add | `+` | Choose official, GitHub, or local command source. |
| Refresh | `r` | Re-runs Probe for every enabled Dataset, updates safe metadata, and checks managed official/GitHub Datasets for new releases. The completion notice reports unavailable and upgradeable counts. Dashboard also performs a fresh Probe for the Dataset selected in its chooser before it advances to Metric/kind selection. |
| Enable/disable | `d` | Toggles the selected registration's availability in Dashboard and refreshes. |
| Remove | `x` | Confirms removal. Local removal deletes only ccuv's registration; managed official/GitHub removal also deletes its installed artifact. |
| Upgrade current | `u` | Confirms and upgrades only the selected Dataset when it has a detected release. |
| Upgrade all | `U` | Confirms and upgrades every Dataset with a detected release, continuing if an individual upgrade fails. The list and details show current and candidate versions. |
| Help | `h` | Explains current manager controls and required setup. |
| Exit | Ctrl-C | Closes the manager. |

Set required variables in the environment from which you launch ccuv. For
example, on macOS/Linux:

```bash
export EXAMPLE_ACTIVITY_TOKEN='...'
ccuv dataset
```

The manager displays variable names and the Dataset's setup instructions but
never prints or persists their values. After changing an environment variable,
restart ccuv and press `r` to refresh readiness.

## Use A Dataset In A Standalone Chart

Start with a chart kind that the selected Metric declares. `--dataset` is the
registered Dataset ID. Add `--metric` when the Dataset has multiple Metrics and
no default Metric, or whenever you want a non-default Metric.

```bash
# Historical Dataset Metric
ccuv chart timeline --dataset example-activity --metric events
ccuv chart ranking --dataset example-activity --metric events --period 30d

# Source-owned Custom Monitor Metric
ccuv chart monitor --dataset router --metric tokens
```

Use `ccuv dataset` details to see which chart kinds each Metric supports. A
historical Metric may support Timeline, Calendar, Stack, and/or Ranking.
Monitor is only available when that Metric declares Monitor capability.

When a Dataset declares Metric Groups, the interactive Dataset picker shows a
localized Group heading and indents its Metrics below it. Empty Groups are not
shown. Metrics without a Group remain flat entries after all Groups. A Dataset
that does not declare Groups keeps the original flat picker. In a short chooser,
Up first reveals a clipped Group heading before the selection wraps, so the
selected Metric always regains its context.

In a selected Custom chart pane, `m` and `M` cycle forward and backward among
Metrics in the current Group that support the active chart kind. ccuv keeps the
current query choices; if the next Metric's declared chart capability cannot
accept the current period, grouping, or granularity, it leaves the current
Metric unchanged and shows a short warning. A successful switch replaces the
selected Metric; a failed target request leaves the prior chart or Monitor
selected.

Dataset defaults can set an initial period, group, Top N, Other,
style, theme, and Monitor display horizon. They are suggestions. Your explicit
options override them:

```bash
ccuv chart timeline --dataset example-activity --metric events \
  --period 30d --group-by project --top 3 --filter category=work \
  --style points --theme classic
```

For custom Datasets, use `--group-by`, not the built-in `--by`; use repeated
`--filter ID=OPTION` only after the Dataset has returned the corresponding
runtime filter option. Run `ccuv chart KIND --help`
to see the accepted presentation arguments. A Dataset cannot accept built-in
`--agent`, `--model`, `--project`, or `--cache` alongside `--dataset`.

When the Dataset cannot supply an accepted request, ccuv preserves its current
view and shows its localized error. If a Dataset default itself is invalid, ccuv
ignores just that field and opens the chart with the normal standalone default.

## Use A Dataset In Dashboard

### Interactive workflow

1. Start `ccuv dashboard --empty` for a clean layout, or open your normal
   Dashboard.
2. Focus an empty Pane and press `r` (or double-click it) to choose a type.
3. Choose **Dataset**, select an Available registration, then select a Metric
   if the Dataset has more than one. When it declares Metric Groups, Metrics
   appear indented below their Group headings.
4. Select one chart kind from the kinds that Metric declared.
5. ccuv starts a fresh Probe, applies valid Dataset defaults, then queries the
   Pane. A setup or source failure appears in the Pane instead of replacing data
   with zero.

Use the Pane adjustment controls afterward: period, grouping, runtime-provided filters, Top,
Other, style, theme, and local Monitor display window are local choices. They
do not rewrite the Dataset or its registration.

### Declarative Pane command

For an installed/registered Dataset, you can build a Dashboard from the CLI:

```bash
ccuv dashboard --empty --grid 2x2 \
  --pane 'chart timeline --dataset example-activity --metric events' \
  --pane 'chart ranking --dataset example-activity --metric events --period 30d' \
  --pane 'empty' \
  --pane 'chart monitor --dataset router --metric tokens'
```

Each `--pane` is a normal chart fragment. Dataset metric capabilities still
limit what ccuv will request; command-line options remain explicit overrides of
Dataset defaults. Presets retain Custom Ranking item spacing and Monitor
attachments. Panes sharing one Dataset ID must resolve to the same command;
ccuv rejects ambiguous source commands rather than choosing one silently.

## Save And Share

Dashboard presets save Dataset identity and chart configuration, but never query
results, environment values, or credentials. They also preserve local-command
Dataset argv and command-driven overlays. A saved preset is therefore trusted
local automation: loading it can execute its stored commands. Save and load only
presets you trust; use a published GitHub or official Dataset when the setup
must be portable to another machine.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `Dataset ... is not installed` | Run `ccuv dataset`, add/register the Dataset, then use the ID Probe returns. |
| `Setup required` | Open details, set every listed required environment variable, restart ccuv, press `r`. |
| GitHub install cannot find a release | The repo needs a latest non-draft release, a platform-named `.tar.gz`, and a checksum asset. |
| A Metric or chart type is not selectable | The Metric's Probe does not declare that capability. Choose a supported Metric/kind or contact the Dataset developer. |
| A selected filter/group fails | The Dataset may have changed its capability. Refresh (`r`) and choose a declared option. |
| Dashboard shows `Unavailable` after choosing a Dataset | The fresh Probe found no selectable Metric/chart capability, or the Dataset response was invalid. Inspect the Dataset with `ccuv dataset`, correct its setup, and try again. |
| Dashboard refuses a Dataset command conflict | Panes with the same Dataset ID must use equivalent command argv (absolute-path aliases to the same files are accepted). Replace or remove the conflicting Pane. |
| Monitor looks like it covers the wrong time period | The Dataset owns the factual `window_seconds`; the local `window` control merely changes how much accepted Monitor history ccuv displays. |
| Old data remains after a failed request | ccuv retains the last accepted view for a same-query refresh. A changed query shows its candidate/error rather than facts from a different selection. |
