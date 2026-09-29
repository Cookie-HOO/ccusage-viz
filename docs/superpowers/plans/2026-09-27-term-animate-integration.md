# Term-animate Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add provider-free, host-owned `term-animate` content as `ccuv animate`, an explicit Dashboard Pane, and a consumption-gated attachment below Monitor ranking/list output.

**Architecture:** Animation remains outside ccuv's chart/provider pipeline. A new `animation.py` is the sole `term_animate` integration boundary: it owns the supported catalog, effective-time clock, isolated state, projection adapter, palette mapping, and Monitor attachment transitions. CLI, standalone, Dashboard, and Monitor hosts retain terminal I/O, keyboard ownership, scheduling, and all provider work.

**Tech Stack:** Python 3.11+, uv, pytest, ruff, ty, plotext, local editable `term-animate` 0.1.x.

**Spec:** `docs/superpowers/specs/2026-09-27-term-animate-integration-design.md`

## Global Constraints

- Add `term-animate>=0.1.0,<0.2.0` as a normal runtime dependency and temporarily resolve `../term-animate` through an editable `[tool.uv.sources]` entry.
- Import only `term_animate.api` and host-facing model values; never invoke its CLI, gallery, scheduler, terminal output, or keyboard handling.
- Do not add animation to `ChartConfig`, a chart registry, Provider work, query planning, Coverage, chart components, or lifecycle operations.
- Standalone `ccuv animate` defaults to `rain`; Dashboard fragments require `animate <style>` and reject bare `animate`.
- Expose exactly `mole-cat`, `campy-cat`, `rain`, `analog-clock`, and `digital-clock`, in that order.
- Theme/style/clock state is per-process and per-instance. It is never persistent and runtime changes never appear in copied commands.
- A frame deadline may only reproject and repaint. It must never submit work, refresh charts, query providers, or create executor work.
- Monitor activity is only an accepted observation's `total_delta > 0`. Pending work, errors, discarded results, elapsed time, and current rows cannot change attachment playback.
- A too-small viewport shows one compact localized hint with no deadline and retains state for resize recovery.
- ccuv owns all keys in every integration; no term-animate gallery control is active.

---

## File Map

| File | Responsibility |
| --- | --- |
| `pyproject.toml`, `uv.lock` | Temporary editable runtime dependency. |
| `src/ccusage_viz/animation.py` | Catalog, clock, local state, projection and row adapter, theme conversion, attachment state. |
| `src/ccusage_viz/animate.py` | Provider-free standalone animation host. |
| `src/ccusage_viz/options.py` | Separate animation launch and typed Dashboard pane union. |
| `src/ccusage_viz/cli.py` | `animate` parser and Dashboard pane parser validation. |
| `src/ccusage_viz/application.py` | Animation route before provider dependency resolution. |
| `src/ccusage_viz/configuration.py`, `command_copy.py` | Chart-only pane materialization and mixed-pane serialization. |
| `src/ccusage_viz/monitor_component.py` | Authoritative accepted token delta property. |
| `src/ccusage_viz/monitor.py`, `tui.py` | Standalone/Dashboard host composition, controls, scheduling, and pane isolation. |
| `src/ccusage_viz/locales/en.py`, `src/ccusage_viz/locales/zh.py` | New user-visible copy. |
| `tests/test_animation.py` | Animation subsystem tests. |
| Existing CLI, application, options, monitor, terminal, TUI, architecture tests | Integration and regression coverage. |

## Shared Interfaces

Task 1 introduces these stable interfaces in `animation.py`:

```python
@dataclass(frozen=True, slots=True)
class AnimationSpec:
    style: str
    display_name: str
    category: str
    minimum_columns: int
    minimum_rows: int

@dataclass(slots=True)
class AnimationClock:
    accumulated_active_seconds: float = 0.0
    resumed_at: float | None = None

    def elapsed(self, now: float) -> float: ...
    def resume(self, now: float) -> None: ...
    def freeze(self, now: float) -> None: ...

@dataclass(slots=True)
class AnimationSessionState:
    spec: AnimationSpec
    theme: str
    clock: AnimationClock
    wall_origin: datetime
    playback_requested: bool = True
    host_paused: bool = False
    visible: bool = True
    viable: bool = False
    next_deadline: float | None = None

@dataclass(frozen=True, slots=True)
class AnimationRenderResult:
    rows: tuple[str, ...]
    next_deadline: float | None
    viable: bool
    error: str | None = None

class AnimationRenderer:
    def render(
        self, session: AnimationSessionState, *, width: int, height: int,
        color: bool, ascii: bool, now: float, translator: Translator,
    ) -> AnimationRenderResult: ...

@dataclass(slots=True)
class MonitorAnimationAttachment:
    session: AnimationSessionState
    latest_accepted_active: bool | None = None

    def accept_total_delta(self, delta: float | None, now: float) -> None: ...
    def set_monitor_style(self, style: str, now: float) -> None: ...
    def set_host_paused(self, paused: bool, now: float) -> None: ...
```

`AnimationSessionState` additionally has `set_style`, `set_theme`, `set_visible`, `set_viable`, `set_playback_requested`, `set_host_paused`, and `reconcile_clock`. Its clock plays exactly when playback is requested, it is not host-paused, it is visible, and its viewport is viable. `virtual_wall_time(session, now)` is `session.wall_origin + timedelta(seconds=session.clock.elapsed(now))`.

### Task 1: Add the dependency and host-neutral animation primitives

**Files:**
- Modify: `pyproject.toml:1-54`
- Modify: `uv.lock`
- Create: `src/ccusage_viz/animation.py`
- Create: `tests/test_animation.py`

**Consumes:** `term_animate.api.select_effect`; `term_animate` host models.

**Produces:** Supported catalog lookup/cycling, `AnimationClock`, `AnimationSessionState`, `new_animation_session`, and `virtual_wall_time`.

- [ ] **Step 1: Write catalog and effective-clock tests.**

```python
def test_catalog_is_explicit_and_stable() -> None:
    assert animation_style_choices() == (
        "mole-cat", "campy-cat", "rain", "analog-clock", "digital-clock",
    )
    assert animation_spec("rain").display_name == "Rain"
    with pytest.raises(UsageError):
        animation_spec("snow")


def test_clock_freezes_without_idle_catch_up() -> None:
    clock = AnimationClock()
    assert clock.elapsed(10.0) == 0.0
    clock.resume(10.0)
    assert clock.elapsed(12.5) == 2.5
    clock.freeze(12.5)
    clock.freeze(99.0)
    assert clock.elapsed(99.0) == 2.5
    clock.resume(100.0)
    assert clock.elapsed(101.0) == 3.5
```

- [ ] **Step 2: Run the focused test to establish the missing-module failure.**

Run: `uv run pytest tests/test_animation.py -q`

Expected: collection fails because `ccusage_viz.animation` does not yet exist.

- [ ] **Step 3: Add and lock the local runtime dependency.**

Change the dependencies entry to:

```toml
dependencies = [
  "plotext>=6.1,<7",
  "term-animate>=0.1.0,<0.2.0",
]

[tool.uv.sources]
term-animate = { path = "../term-animate", editable = true }
```

Run `uv lock`. Verify the lock contains the editable source and its `cairosvg`, `pillow`, and `wcwidth` dependencies.

- [ ] **Step 4: Implement catalog and state primitives.**

Create immutable `_ANIMATION_SPECS` entries in the required order. Use `animal`, `animal`, `nature`, `time`, `time` categories. Give every entry a conservative tested minimum viewport; the renderer, not parser startup, enforces the minimum. `animation_spec` raises project `UsageError` with the standard valid choices detail and validates the category/style mapping with `select_effect`.

Implement idempotent clock methods. New sessions start frozen (`viable=False`) and capture `datetime.now().astimezone()` as `wall_origin`. A style change updates only `spec`, preserving elapsed time. `reconcile_clock` freezes and clears `next_deadline` whenever a required playback condition is false.

- [ ] **Step 5: Add virtual-clock tests and implement the method contract.**

```python
def test_virtual_wall_time_stops_while_frozen() -> None:
    session = new_animation_session(animation_spec("digital-clock"), theme="classic")
    session.set_viable(True, 10.0)
    session.set_playback_requested(True, 10.0)
    assert virtual_wall_time(session, 15.0) == session.wall_origin + timedelta(seconds=5)
    session.set_playback_requested(False, 15.0)
    assert virtual_wall_time(session, 3600.0) == session.wall_origin + timedelta(seconds=5)
```

- [ ] **Step 6: Run checks and commit the coherent primitive boundary.**

Run:

```bash
uv run pytest tests/test_animation.py -q
uv run ruff check src/ccusage_viz/animation.py tests/test_animation.py
uv run ty check
```

Commit:

```bash
git add pyproject.toml uv.lock src/ccusage_viz/animation.py tests/test_animation.py
git commit -m "feat: add animation session primitives"
```

### Task 2: Project frames through a safe ccuv adapter

**Files:**
- Modify: `src/ccusage_viz/animation.py`
- Modify: `tests/test_animation.py`
- Modify: `tests/test_terminal.py`

**Consumes:** Task 1 state; `term_animate.api.project_curated`; `render.palette.get_color_scheme`; existing string-row `FramePainter`.

**Produces:** `AnimationRenderer`, `animation_theme_tokens`, width-safe ANSI rows, compact/error fallback, and local frame deadlines.

- [ ] **Step 1: Add adapter, monochrome, and small-viewport tests.**

```python
def test_small_viewport_never_projects_or_schedules(monkeypatch, translator) -> None:
    session = new_animation_session(animation_spec("rain"), theme="classic")
    monkeypatch.setattr("ccusage_viz.animation.project_curated", pytest.fail)
    result = AnimationRenderer().render(
        session, width=1, height=1, color=False, ascii=True, now=1.0, translator=translator,
    )
    assert result.next_deadline is None
    assert not session.clock.playing
    assert "rain" in result.rows[0]
    assert "\x1b[" not in result.rows[0]


def test_color_disabled_adapter_emits_plain_rows(monkeypatch, translator) -> None:
    frame = ProjectedFrame((StyledRow((StyledCell("x", foreground=(1, 2, 3)),)),), 0, 9.0, "full")
    monkeypatch.setattr("ccusage_viz.animation.project_curated", lambda *args, **kwargs: frame)
    session = new_animation_session(animation_spec("rain"), theme="classic")
    result = AnimationRenderer().render(
        session, width=80, height=24, color=False, ascii=False, now=1.0, translator=translator,
    )
    assert result.rows == ("x",)
    assert result.next_deadline is not None
```

- [ ] **Step 2: Run these tests and confirm the missing renderer failure.**

Run: `uv run pytest tests/test_animation.py -q`

Expected: import or attribute error for `AnimationRenderer`.

- [ ] **Step 3: Implement host-owned projection.**

Import `project_curated`, `LogicalState`, `TerminalCapabilities`, `ThemeTokens`, and `Viewport` only in `animation.py`. Construct `Viewport(columns=width, rows=height)` and capabilities with `color="truecolor"` or `"none"`. Pass effective elapsed monotonic time and virtual wall time. For Rain, use `LogicalState.ACTIVE` only while the session effective clock plays and `LogicalState.IDLE` while a visible but frozen Rain session is projected.

If the viewport is below `spec` minimums, call `set_viable(False, now)`, return exactly the localized compact hint row, and skip `project_curated`. If projection raises, return one localized failure row and no deadline. Do not re-raise in a host render path.

- [ ] **Step 4: Implement palette and styled-cell conversion.**

Resolve ccuv semantic colors through `get_color_scheme(session.theme)`. Convert xterm colors using: direct RGB lookup for 0–15; `55 + 40*n` cube channels for 16–231; and `8 + 10*n` grayscale for 232–255. Build `ThemeTokens(background=(0, 0, 0), foreground=other, accent=highlight, secondary_accent=cache_creation, artwork=first categorical color, muted=other)`.

For colored terminals, render each `StyledCell` using `\x1b[38;2;r;g;bm` and, when available, `\x1b[48;2;r;g;bm`, following text with `\x1b[0m`. For no-color terminals concatenate text only. Use `formatting.display_width` and existing width truncation utilities to ensure stripped rows fit the provided width.

Store a frame deadline only when state is actively playing and viable. The stored host deadline is the projected deadline; clear it for frozen or failed projection.

- [ ] **Step 5: Add repaint regression coverage and run quality checks.**

Add a `tests/test_terminal.py` test that paints two different converted animation rows through `FramePainter` and asserts the second output uses the existing changed-row escape update (`\x1b[1;1H\x1b[2K`) rather than introducing a second painter API.

Run:

```bash
uv run pytest tests/test_animation.py tests/test_terminal.py -q
uv run ruff check src/ccusage_viz/animation.py tests/test_animation.py tests/test_terminal.py
uv run ty check
```

- [ ] **Step 6: Commit the adapter.**

```bash
git add src/ccusage_viz/animation.py tests/test_animation.py tests/test_terminal.py
git commit -m "feat: adapt term animate frames to ccuv"
```

### Task 3: Introduce a separate animation CLI launch and provider-free route

**Files:**
- Modify: `src/ccusage_viz/options.py:141-208`
- Modify: `src/ccusage_viz/cli.py`
- Modify: `src/ccusage_viz/application.py:10-36`
- Modify: `src/ccusage_viz/terminal.py`
- Modify: `tests/test_cli.py`, `tests/test_options.py`, `tests/test_application.py`, `tests/test_terminal.py`

**Consumes:** Task 1 `AnimationSpec` and catalog lookup.

**Produces:** `AnimationLaunch`, `AnimationRoute`, standalone parse behavior, and dispatch before provider initialization.

- [ ] **Step 1: Write parser and route tests.**

```python
def test_animate_defaults_to_rain() -> None:
    options = parse_options(["animate"])
    assert isinstance(options, AnimationLaunch)
    assert options.animation.style == "rain"


def test_dashboard_default_injection_preserves_animate() -> None:
    assert _inject_default_command(["animate", "rain"]) == ["animate", "rain"]


def test_animation_route_skips_provider_dependencies(monkeypatch, translator, animation_launch) -> None:
    monkeypatch.setattr(application, "ensure_provider_dependencies", pytest.fail)
    monkeypatch.setattr("ccusage_viz.animate.run_animation", lambda options, tr: 0)
    assert application.run(animation_launch, translator) == 0
```

- [ ] **Step 2: Run parser tests to establish the failure.**

Run: `uv run pytest tests/test_cli.py tests/test_application.py -q`

Expected: parser does not recognize `animate` and launch types are unavailable.

- [ ] **Step 3: Add typed options and routes without changing charts.**

In `options.py`, add:

```python
@dataclass(frozen=True, slots=True)
class AnimationLaunch:
    process: ProcessConfig
    host: StandaloneHostConfig
    animation: AnimationSpec
    explicit: frozenset[str] = frozenset()

    def was_explicit(self, field: str) -> bool:
        return field in self.explicit

@dataclass(frozen=True, slots=True)
class AnimationRoute:
    launch: AnimationLaunch
```

Widen `LaunchConfig` and `LaunchRoute`. Do not put `animate` in `ChartConfig`, `COMMAND_STYLES`, `adjust_chart`, or chart compatibility functions.

- [ ] **Step 4: Implement CLI parser and terminal preflight.**

Add `animate` to `_COMMANDS`, but not `_TUI_COMMANDS`. Create one positional optional `style` argument with default `rain`; convert it through `animation_spec` in option materialization. Make invalid styles fail before terminal entry. Keep chart-only flags unavailable on this parser.

Update terminal inspection/preflight so animation validates interactive streams and `TERM=dumb`/`--ascii`, but does not reject based on chart `MINIMUM_SIZES`; effect fitting is handled by the renderer fallback.

- [ ] **Step 5: Dispatch animation before providers.**

Use this order in `application.run`:

```python
_preflight_runtime(options)
if isinstance(options, AnimationLaunch):
    from ccusage_viz.animate import run_animation
    return run_animation(options, translator)
ensure_provider_dependencies(options, build_provider_registry(), translator)
```

Keep existing Dashboard, Monitor, and historical routes unchanged after the dependency guard.

- [ ] **Step 6: Run tests and commit the route.**

```bash
uv run pytest tests/test_cli.py tests/test_options.py tests/test_application.py tests/test_terminal.py -q
uv run ty check
git add src/ccusage_viz/options.py src/ccusage_viz/cli.py src/ccusage_viz/application.py src/ccusage_viz/terminal.py tests
git commit -m "feat: add provider-free animate command route"
```

### Task 4: Build the standalone animation terminal host

**Files:**
- Create: `src/ccusage_viz/animate.py`
- Modify: `src/ccusage_viz/locales/en.py`, `src/ccusage_viz/locales/zh.py`
- Modify: `tests/test_animation.py`, `tests/test_cli.py`, `tests/test_i18n.py`

**Consumes:** Task 2 renderer and Task 3 `AnimationLaunch`; existing `FramePainter`, raw-terminal/input utilities, and appearance UI conventions from `monitor.py`.

**Produces:** `run_animation(options: AnimationLaunch, translator: Translator) -> int`.

- [ ] **Step 1: Add the standalone host behavior tests.**

Mock input events and monotonic time to verify: `q`, Escape, and Ctrl-C leave terminal mode cleanly; Space freezes/resumes without resetting elapsed time; quick `t`/`T` change only session theme; quick `s` cycles only the five styles; `a` switches adjustment pages but exposes no first-release advanced animation setting.

Use a focused assertion rather than timing sleeps:

```python
def test_space_freezes_elapsed_time(monkeypatch, translator, animation_launch) -> None:
    rendered = []
    monkeypatch.setattr("ccusage_viz.animate.read_adjustment_event", scripted_events(["space", "q"]))
    monkeypatch.setattr("ccusage_viz.animate.AnimationRenderer.render", record_elapsed(rendered))
    run_animation(animation_launch, translator)
    assert rendered[-1] == rendered[0]
```

- [ ] **Step 2: Implement a deadline-aware ccuv-owned loop.**

Create one session with `theme="classic"`, one renderer, and one `FramePainter`. Render a frame before blocking. On each loop calculate `timeout=min(0.05, max(0.0, session.next_deadline - now))` when a deadline exists, otherwise `0.05`; read only through ccuv input helpers. Re-render when a key changes state, size changes, or the deadline is due. Do not construct a provider registry, query runtime, scheduler, component, lifecycle, or executor.

Map Space to `session.set_playback_requested(not session.playback_requested, now)`. Map `m` and `a` through the same ccuv adjustment-page state and labels used by other standalone TUIs. In quick mode map `t`/`T` to `COLOR_SCHEMES` cycling and `s` to `cycle_animation_style`. Render content through existing terminal row/frame logic.

- [ ] **Step 3: Add translations.**

Add paired English and Chinese keys for: command help, compact hint, projection failure, animation style, animation theme, paused/running status, and quick adjustment labels. Use `tests/test_i18n.py`'s existing parity convention to prove both catalogs declare the same keys.

- [ ] **Step 4: Run checks and commit.**

```bash
uv run pytest tests/test_animation.py tests/test_cli.py tests/test_i18n.py -q
uv run ruff check src/ccusage_viz/animate.py src/ccusage_viz/animation.py
uv run ty check
git add src/ccusage_viz/animate.py src/ccusage_viz/locales tests
git commit -m "feat: add standalone animation host"
```

### Task 5: Create the Dashboard pane union and explicit pane syntax

**Files:**
- Modify: `src/ccusage_viz/options.py:150-195`
- Modify: `src/ccusage_viz/cli.py`
- Modify: `src/ccusage_viz/configuration.py:20-66`
- Modify: `src/ccusage_viz/command_copy.py:134-201`
- Modify: `tests/test_cli.py`, `tests/test_options.py`, `tests/test_tui.py`

**Consumes:** `AnimationSpec` and the new route/launch types.

**Produces:** `ChartPaneConfig | AnimationPaneConfig` and type-safe conversion/serialization.

- [ ] **Step 1: Write Dashboard fragment and command-copy tests.**

```python
def test_dashboard_accepts_explicit_animation_pane() -> None:
    config = parse_options(["dashboard", "--pane", "timeline", "--pane", "animate rain"])
    assert isinstance(config.panes[1], AnimationPaneConfig)
    assert config.panes[1].animation.style == "rain"


def test_dashboard_rejects_bare_animation_pane() -> None:
    with pytest.raises(UsageError):
        parse_options(["dashboard", "--pane", "animate"])


def test_dashboard_command_copy_preserves_configured_animation_style(dashboard) -> None:
    command = format_full_dashboard_command(dashboard)
    assert "animate rain" in command
```

- [ ] **Step 2: Replace the chart-only pane configuration.**

Replace the current `PaneConfig(chart: ChartConfig)` with:

```python
@dataclass(frozen=True, slots=True)
class ChartPaneConfig:
    chart: ChartConfig

@dataclass(frozen=True, slots=True)
class AnimationPaneConfig:
    animation: AnimationSpec

PaneConfig: TypeAlias = ChartPaneConfig | AnimationPaneConfig
```

Make `default_pane` return `ChartPaneConfig`. Rename `standalone_from_pane` to `standalone_from_chart_pane`, require `ChartPaneConfig`, and preserve its current interval/ascii semantics.

- [ ] **Step 3: Parse animation fragments explicitly.**

In `parse_pane_fragment`, split shell text first. If the first token is `animate`, accept exactly two tokens and validate the second with `animation_spec`; any other shape raises the existing `error.tui_panel`. For all non-animation fragments, retain the existing `_TUI_COMMANDS` parser path. Bare `animate` is therefore rejected instead of borrowing standalone's default.

- [ ] **Step 4: Serialize mixed panes safely.**

In `format_full_dashboard_command`, inspect each pane variant:

```python
if isinstance(pane_config, AnimationPaneConfig):
    fragment = f"animate {pane_config.animation.style}"
else:
    fragment = shlex.join(_chart_args(standalone_from_chart_pane(options, pane_config), full=True, pane=True))
```

Do not serialize mutable runtime theme/style state.

- [ ] **Step 5: Run tests and commit.**

```bash
uv run pytest tests/test_cli.py tests/test_options.py tests/test_tui.py -q
uv run ty check
git add src/ccusage_viz/options.py src/ccusage_viz/cli.py src/ccusage_viz/configuration.py src/ccusage_viz/command_copy.py tests
git commit -m "feat: add explicit dashboard animation panes"
```

### Task 6: Render and schedule animation-only Dashboard panes

**Files:**
- Modify: `src/ccusage_viz/tui.py`
- Modify: `tests/test_tui.py`, `tests/test_architecture.py`

**Consumes:** Task 5 pane union and Task 2 renderer.

**Produces:** Runtime `TuiChartPane | TuiAnimationPane`, frame-deadline waiting, render-only panes, and focused-pane adjustment mapping.

- [ ] **Step 1: Add runtime construction and no-query tests.**

```python
def test_animation_pane_has_no_component_scheduler_or_lifecycle(dashboard, runtime) -> None:
    pane = _new_pane(dashboard, AnimationPaneConfig(animation_spec("rain")), "dashboard:pane:0", runtime)
    assert isinstance(pane, TuiAnimationPane)
    assert not hasattr(pane, "component")


def test_animation_deadline_never_refreshes_or_submits(monkeypatch, dashboard) -> None:
    monkeypatch.setattr("ccusage_viz.tui.refresh", pytest.fail)
    monkeypatch.setattr("ccusage_viz.tui.QueryRuntime", pytest.fail)
    assert next_dashboard_wait_seconds(now=10.0, default_poll_seconds=0.05,
        header_deadline=None, chart_deadlines=(), animation_deadlines=(10.01,)) == 0.01
```

- [ ] **Step 2: Introduce the runtime union and factory dispatch.**

Split current `TuiPane` into `TuiChartPane` (existing component, scheduler, lifecycle, and state fields) and `TuiAnimationPane(session, renderer, render_revision=0)`. Make the `panes` collection a union. Factory dispatch must instantiate an animation pane without touching the passed query runtime, and materialize charts only via `standalone_from_chart_pane`.

- [ ] **Step 3: Render animation interiors through Dashboard geometry.**

Leave `dashboard_layout.py` rectangle/layout logic unchanged. In TUI pane rendering, calculate the interior width and height after title/border rows. Feed those values to `AnimationRenderer`. Put returned rows into the pane's existing `PaneRender`/layout path, preserving border/title/focus behavior. A compact row is normal pane content and must not crash a narrow layout.

- [ ] **Step 4: Make input waits deadline-aware.**

Implement:

```python
def next_dashboard_wait_seconds(
    *, now: float, default_poll_seconds: float, header_deadline: float | None,
    chart_deadlines: Iterable[float | None], animation_deadlines: Iterable[float | None],
) -> float:
    deadlines = [value for value in (header_deadline, *chart_deadlines, *animation_deadlines) if value is not None]
    return min(default_poll_seconds, max(0.0, min(deadlines) - now)) if deadlines else default_poll_seconds
```

Pass this timeout into the existing decoder read operation. When an animation deadline reaches `now`, invalidate/repaint the dashboard only; skip `refresh`, lifecycle creation, query plans, and executors. Global `r` skips animation panes. Global Space calls `set_host_paused` on every animation session alongside existing chart pause behavior.

- [ ] **Step 5: Implement focused animation-pane adjustments.**

For `TuiAnimationPane` quick settings, `t`/`T` cycle only its `session.theme` and `s` cycles only its `session.spec`. Its advanced page has no animation-specific controls. Do not list or consume chart density/filter/grouping/top controls for it. Add an isolation test with two animation panes proving one pane's style/theme/elapsed time never changes the other.

- [ ] **Step 6: Run tests and commit.**

```bash
uv run pytest tests/test_tui.py tests/test_architecture.py -q
uv run ty check
git add src/ccusage_viz/tui.py tests/test_tui.py tests/test_architecture.py
git commit -m "feat: render animation panes in dashboard"
```

### Task 7: Surface the Monitor accepted-token-delta contract

**Files:**
- Modify: `src/ccusage_viz/monitor_component.py`
- Modify: `tests/test_monitor_component.py`

**Consumes:** Existing `ObservedTPM.current_interval` behavior in `processing/monitor.py`.

**Produces:** `MonitorComponent.accepted_total_token_delta: float | None`.

- [ ] **Step 1: Write public-contract tests.**

Test first baseline (`None`), accepted positive delta, accepted zero delta, reset/rebaseline (`None`), and rejected/discarded completion retaining no new usable signal.

```python
def test_accepted_total_delta_uses_only_current_accepted_interval(component) -> None:
    accept(component, total=100)
    assert component.accepted_total_token_delta is None
    accept(component, total=125)
    assert component.accepted_total_token_delta == 25
    accept(component, total=125)
    assert component.accepted_total_token_delta == 0
```

- [ ] **Step 2: Implement the narrow property.**

```python
@property
def accepted_total_token_delta(self) -> float | None:
    interval = self.observer.current_interval
    return None if interval is None else interval.total_delta
```

Do not derive this from rendering deltas, query status, or grouped values.

- [ ] **Step 3: Run tests and commit.**

```bash
uv run pytest tests/test_monitor_component.py -q
git add src/ccusage_viz/monitor_component.py tests/test_monitor_component.py
git commit -m "feat: expose accepted monitor token delta"
```

### Task 8: Attach animation to standalone Monitor ranking/list output

**Files:**
- Modify: `src/ccusage_viz/animation.py`, `src/ccusage_viz/monitor.py`
- Modify: `src/ccusage_viz/locales/en.py`, `src/ccusage_viz/locales/zh.py`
- Modify: `tests/test_monitor.py`

**Consumes:** Tasks 2 and 7.

**Produces:** One standalone `MonitorAnimationAttachment`, host-composed rendering, accepted-sample playback, and conditional advanced controls.

- [ ] **Step 1: Add attachment transition tests.**

```python
def test_monitor_attachment_plays_only_after_positive_accepted_delta() -> None:
    attachment = MonitorAnimationAttachment(new_animation_session(animation_spec("rain"), theme="classic"))
    attachment.set_monitor_style("ranking", 0.0)
    attachment.accept_total_delta(None, 1.0)
    assert not attachment.session.clock.playing
    attachment.accept_total_delta(1.0, 2.0)
    assert attachment.latest_accepted_active is True
    attachment.accept_total_delta(0.0, 3.0)
    assert not attachment.session.clock.playing
```

Also test pending/error/discarded completions preserve the current attachment, host pause resumes only a previously active attachment, and switching away from ranking/list disables scheduling without replacing state.

- [ ] **Step 2: Implement attachment state transitions.**

`accept_total_delta(None)` stores unknown and keeps the initial frame frozen. Positive values request playback; zero or negative values freeze. `set_monitor_style` sets session visibility based on `{"ranking", "list"}`. `set_host_paused` applies only an override; unpausing restores playback only if `latest_accepted_active is True`.

- [ ] **Step 3: Bind the attachment directly after accepted completion.**

Construct exactly one attachment at Monitor host startup with `rain` and the monitor's initial chart theme. Immediately after `component.accept(...)` returns `True`, call:

```python
attachment.accept_total_delta(component.accepted_total_token_delta, time.monotonic())
```

Do not call it for pending operations, exceptions, discarded completion, keystrokes, or a refresh request alone.

- [ ] **Step 4: Compose attachment after the core body.**

Keep ranking/list renderer code unchanged. In Monitor host composition reserve notices/status/controls first, then preserve all normal ranking/list body lines. Render the attachment only from remaining rows and only when current chart style is ranking/list. Put its rows after body and before notices/controls. If it cannot fit, set attachment visible false and omit it before truncating any core rows. It will retain clock/theme/style and recover when space returns.

- [ ] **Step 5: Route advanced controls precisely.**

Quick `t`/`T` and `s` continue to call chart `adjust_chart` for every Monitor style. Only when current style is ranking/list and appearance page is advanced: `t`/`T` cycle attachment theme and `s` cycles attachment style. These actions must not call `component.configure`, refresh, sample, or modify chart configuration. Non-ranking/list advanced panels do not display or consume those three keys.

- [ ] **Step 6: Run tests and commit.**

```bash
uv run pytest tests/test_monitor.py tests/test_monitor_component.py -q
uv run ty check
git add src/ccusage_viz/animation.py src/ccusage_viz/monitor.py src/ccusage_viz/locales tests/test_monitor.py
git commit -m "feat: attach rain animation to monitor ranking"
```

### Task 9: Give Dashboard Monitor panes equivalent isolated attachments

**Files:**
- Modify: `src/ccusage_viz/tui.py`
- Modify: `tests/test_tui.py`

**Consumes:** Tasks 6–8.

**Produces:** One monitor attachment per Dashboard chart pane and common composition/control semantics.

- [ ] **Step 1: Add per-pane behavior tests.**

Verify two Dashboard Monitor ranking panes own distinct attachment instances; an accepted positive delta resumes only its owner; advanced `t`/`T`/`s` changes only focused owner; global pause freezes every animation pane and every Monitor attachment; resume awakens only attachments whose stored accepted state is active.

- [ ] **Step 2: Add attachments only to runtime Monitor chart panes.**

Give `TuiChartPane` an optional `monitor_attachment`. Initialize it only when `component` is `MonitorComponent`, with default rain and the pane's initial chart presentation theme. Never allocate it for historical charts or `TuiAnimationPane`.

- [ ] **Step 3: Bind accepted Dashboard Monitor completions.**

At the branch where a Dashboard Monitor completion is accepted, call `pane.monitor_attachment.accept_total_delta(pane.component.accepted_total_token_delta, now)`. Do not change state in any other completion branch.

- [ ] **Step 4: Reuse standalone composition rules.**

Extract a small host-neutral helper from `monitor.py` or `animation.py` with inputs `(body_lines, attachment_rows, available_height)` and outputs `(composed_lines, attachment_visible)`. Both standalone and Dashboard call it. Its invariant is that all existing body lines are selected before any attachment row; attachment is after body and before host notices.

- [ ] **Step 5: Add Dashboard advanced key routing and pause handling.**

For a focused Monitor chart pane, retain quick chart theme/style behavior. In advanced mode only ranking/list maps `t`/`T`/`s` to that pane's attachment. Global dashboard Space forwards host pause to every animation pane and every existing monitor attachment. A chart theme change after the attachment is explicitly adjusted must not overwrite attachment theme.

- [ ] **Step 6: Run tests and commit.**

```bash
uv run pytest tests/test_tui.py tests/test_monitor.py -q
uv run ty check
git add src/ccusage_viz/tui.py tests/test_tui.py
git commit -m "feat: add dashboard monitor animation attachments"
```

### Task 10: Document the feature and run full validation

**Files:**
- Modify: user-facing command documentation under `README.md`, `README.zh-CN.md`, and `docs/usage*.md` where current commands are described
- Modify: affected test/localization files if full-suite failures identify omissions

**Consumes:** Completed feature behavior.

**Produces:** Accurate bilingual usage documentation and release-quality validation.

- [ ] **Step 1: Add explicit user documentation.**

Document:

```bash
ccuv animate
ccuv animate mole-cat
ccuv dashboard --pane "animate rain"
ccuv dashboard --pane "monitor --style ranking --by model" --pane "animate rain"
```

List the five styles. Explain Dashboard requires explicit style, animation choices are temporary and pane-local, Monitor attachment appears only below ranking/list, and Rain freezes after accepted zero-consumption intervals. State that ccuv—not term-animate—owns all keys. Describe compact fallback for small terminals.

- [ ] **Step 2: Run focused automated checks.**

```bash
uv run pytest tests/test_animation.py tests/test_cli.py tests/test_options.py tests/test_application.py -q
uv run pytest tests/test_terminal.py tests/test_tui.py tests/test_monitor.py tests/test_monitor_component.py -q
uv run pytest tests/test_architecture.py tests/test_i18n.py -q
```

- [ ] **Step 3: Run repository quality gates.**

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run ty check
```

- [ ] **Step 4: Perform real-terminal verification.**

Run:

```bash
uv run ccuv animate
uv run ccuv animate mole-cat
uv run ccuv monitor --style ranking
uv run ccuv monitor --style list
uv run ccuv dashboard --pane "timeline --by model" --pane "animate rain"
uv run ccuv dashboard --pane "monitor --style ranking --by model" --pane "animate rain"
```

Verify `q`, Escape, Ctrl-C, Space, `m`, `a`, `t`, `T`, and `s`; resize below/above viable dimensions; test a no-color/ascii run; verify that animation repaint causes no Provider activity; verify zero delta freezes Rain and positive accepted delta resumes it; and change one Dashboard pane to prove another does not change.

- [ ] **Step 5: Commit documentation and validation changes.**

```bash
git add README.md README.zh-CN.md docs src/ccusage_viz/locales tests
git commit -m "docs: document ccuv animation integration"
```

## Self-Review

**Spec coverage:**

- Dependency strategy, catalog restriction, pure projection boundary, no gallery controls, terminal capability mapping, and compact fallback are Tasks 1–2.
- Standalone defaults, provider-free route, input, and local state are Tasks 3–4.
- Explicit Dashboard syntax, no default pane, union model, serialization, local deadlines, pause, focus, and isolation are Tasks 5–6.
- Accepted-delta semantics, ranking/list-only placement, preservation of core body, and conditional advanced controls are Tasks 7–9.
- Documentation, localization parity, automated gates, and manual terminal checks are Task 10.

**Placeholder scan:** No deferred work markers, unspecified implementations, or generic test instructions remain. Each task names its exact files, stable interface additions, test assertions, commands, and commit boundary.

**Type consistency:** `AnimationLaunch` remains separate from `StandaloneLaunch`; `ChartPaneConfig | AnimationPaneConfig` replaces the former chart-only pane type; `TuiChartPane | TuiAnimationPane` mirrors it at runtime; every host consumes the same `AnimationRenderer` and `MonitorAnimationAttachment` interfaces.
