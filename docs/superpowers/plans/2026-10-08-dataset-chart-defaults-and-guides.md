# Dataset Chart Defaults And Guides Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let V2 Dataset metrics declare best-effort chart defaults, make Monitor start in points mode, and publish Dataset developer/user guides.

**Architecture:** Keep `ccuv.custom/v2` and the existing `metrics[].defaults` boundary. Parse defaults as sparse metadata, then resolve them after Probe against the selected chart capability and command explicitness; invalid values are discarded per field. Historical and Custom Monitor paths use focused resolvers while retaining their existing host baselines.

**Tech Stack:** Python 3.11 dataclasses, argparse, pytest, Markdown.

**Spec:** `docs/superpowers/specs/2026-10-08-dataset-chart-defaults-and-guides-design.md`

## Global Constraints

- Keep the custom Dataset protocol identifier `ccuv.custom/v2`.
- Invalid Dataset defaults must be ignored without rejecting Probe, registration, or chart startup.
- Explicit CLI and Dashboard pane arguments override Dataset defaults per field.
- Custom Monitor `window` configures only ccuv's local display horizon; source `window_seconds` remains authoritative.
- Do not change unrelated user work already present in the tree.

---

### Task 1: Model Sparse Defaults And Round-Trip Them

**Files:**
- Modify: `src/ccusage_viz/custom_models.py`
- Modify: `src/ccusage_viz/custom_protocol.py`
- Test: `tests/test_custom_protocol.py`

**Interfaces:**
- Produces: extended immutable `CustomChartDefaults` and best-effort `_parse_v2_defaults` / `v2_probe_descriptor_to_wire` behavior.

- [ ] Write fixtures containing valid sparse historical and Monitor default objects and malformed sibling values.
- [ ] Assert parser preserves declared defaults without raising, and wire serialization emits recognized present fields.
- [ ] Extend `CustomChartDefaults` with optional period, granularity, group_by, filters, top, other, style, theme, and window fields.
- [ ] Make V2 default parsing accept historical and Monitor kinds, retain supported shaped values, and ignore invalid or unsupported fields.
- [ ] Serialize the sparse shape without introducing null filler fields.
- [ ] Run `pytest tests/test_custom_protocol.py -q`.

### Task 2: Resolve Historical Defaults Per Field

**Files:**
- Modify: `src/ccusage_viz/chart_configuration.py`
- Modify: `src/ccusage_viz/cli.py`
- Modify: `src/ccusage_viz/configuration.py`
- Test: `tests/test_options.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `CustomChartDefaults`, `CustomChartCapability`, `COLOR_SCHEMES`, and `compatible_styles`.
- Produces: `apply_custom_probe_defaults(config, descriptor, timezone)` which never raises for malformed Dataset suggestions.

- [ ] Add tests for valid fields, explicit command/pane precedence, mixed invalid defaults, partial filter-option retention, and final-style compatibility.
- [ ] Expand explicit-field capture to include `theme`, `style`, `other`, `filter`, and `granularity`.
- [ ] Resolve each default only if it is capability compatible and is not explicitly chosen.
- [ ] Preserve the existing host-provided configuration when a suggested default is invalid or absent.
- [ ] Run `pytest tests/test_options.py tests/test_cli.py -q`.

### Task 3: Resolve V2 Custom Monitor Defaults And Native Points Baselines

**Files:**
- Modify: `src/ccusage_viz/custom_monitor_component.py`
- Modify: `src/ccusage_viz/tui.py`
- Modify: `src/ccusage_viz/cli.py`
- Modify: `src/ccusage_viz/chart_configuration.py`
- Modify: `src/ccusage_viz/configuration.py`
- Test: `tests/test_custom_monitor.py`
- Test: `tests/test_tui_dashboard.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: a V2 Monitor default resolver that applies safe display state and local display window after Metric selection.

- [ ] Write tests where a Router-like V2 metric starts in ranking style with a six-hour local display horizon, and malformed defaults retain baselines.
- [ ] Apply Monitor defaults immediately after `resolve_metric` and before `set_metric` in standalone and Dashboard Probe paths.
- [ ] Respect explicit `group_by`, `top`, filter, theme, style, other, and window choices; do not modify source business `window_seconds`.
- [ ] Change native Monitor standalone and Dashboard default styles from `bars` to `points`; update affected assertions.
- [ ] Run `pytest tests/test_custom_monitor.py tests/test_tui_dashboard.py tests/test_cli.py -q`.

### Task 4: Router Fixtures And Dataset Documentation

**Files:**
- Modify: `tests/test_custom_protocol.py`
- Modify: `tests/test_datasets_service.py`
- Modify: `tests/test_datasets_models.py`
- Create: `docs/dataset-developer-guide.md`
- Create: `docs/dataset-developer-guide.zh-CN.md`
- Create: `docs/dataset-user-guide.md`
- Create: `docs/dataset-user-guide.zh-CN.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`

**Interfaces:**
- Produces: Router fixture defaults and bilingual public Dataset guides linked from README.

- [ ] Add `monitor: {"style": "ranking", "window": "6h"}` to every Router fixture metric and assert parsed values.
- [ ] Write developer guide covering local development, Probe descriptor consumer semantics, all request types, process contract, local registration, and GitHub release publication.
- [ ] Write user guide covering local registration, Dataset manager actions, official/GitHub installation availability and flows, standalone/Dashboard selection, Metric/chart choice, and runtime behavior.
- [ ] Produce Chinese counterparts with matching scope; add both guide pairs to the final Further reading tables.
- [ ] Run documentation link checks with `rg` and the relevant Dataset/model/protocol test modules.

### Task 5: Full Regression Verification

**Files:**
- Test: `tests/test_custom_protocol.py`
- Test: `tests/test_options.py`
- Test: `tests/test_custom_monitor.py`
- Test: `tests/test_datasets_models.py`
- Test: `tests/test_datasets_service.py`
- Test: `tests/test_cli.py`
- Test: `tests/test_tui_dashboard.py`

- [ ] Run the targeted Dataset-default and Monitor test selection.
- [ ] Run `pytest -q` if the focused suite is clean.
- [ ] Inspect `git diff --check` and `git status --short`; leave existing unrelated files untouched.
