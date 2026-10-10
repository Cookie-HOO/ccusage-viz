# Ranking Kinetic Wheel Scroll Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow overflowing native and Custom historical Rankings to wheel-scroll under the pointer with bounded, screen-relative kinetic inertia.

**Architecture:** Add a pure `ranking_scroll` policy that owns fractional row offset and signed velocity measured in screens per second. Extend SGR decoding with a distinct `WheelEvent`; Dashboard and standalone hosts use the policy against existing rendered-text viewport metadata, paint only on projected row change, and never route wheel/frame work through query lifecycles.

**Tech Stack:** Python 3.12+, terminal SGR mouse reports, monotonic time, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-10-ranking-kinetic-wheel-scroll-design.md`

## Global Constraints

- Apply only to overflowing native and Custom **historical** Ranking views; do not alter monitor rankings, other charts, keyboard scrolling, click semantics, or persisted state.
- A Dashboard wheel report is eligible whenever its coordinate lies within the pointed Ranking pane rectangle, including its border; focus is not required.
- Use velocity in screens/second with exact initial constants: impulse `0.32`, maximum `2.25`, damping `22.0/s`, stop threshold `0.03`, hard inertia limit `0.110s`, maximum frame delta `0.050s`.
- Do not maintain a target offset, pending row-delta sequence, or scroll task queue.
- Coalesce reports within one ready-input turn and paint at most once for that turn; frames repaint only when the projected integer first row changes.
- A new pointed pane stops old owner inertia; reverse input brakes the old velocity before changing direction; outward boundary contact clears velocity.
- Wheel and kinetic-frame work must not query providers/custom commands, submit coordinator work, refresh schedulers, mutate focus/configuration/history, or persist state.

---

## File Structure

- Create `src/ccusage_viz/ranking_scroll.py`: pure viewport/state dataclasses and deterministic impulse/frame integration functions.
- Modify `src/ccusage_viz/tui_input.py`: expose individual SGR wheel reports as `WheelEvent` without discarding them.
- Modify `src/ccusage_viz/tui.py`: retain Ranking viewport metadata for native/Custom panes, pointer-target wheel routing, owner lifecycle, bounded kinetic frames, and Dashboard/Custom standalone integration.
- Modify `src/ccusage_viz/watch.py`: switch interactive native historical watch input to `tui_input_mode`/`read_event` and use the shared viewport/policy.
- Modify `tests/test_tui_input.py`: decoder coverage for wheel reports.
- Create `tests/test_ranking_scroll.py`: exact pure policy behavior and no-backlog invariants.
- Modify `tests/test_tui_dashboard.py`, `tests/test_tui_custom.py`, and `tests/test_watch.py`: host behavior and query-isolation coverage.

## Task 1: Decode Wheel Reports and Implement the Pure Kinetic Policy

**Files:**
- Create: `src/ccusage_viz/ranking_scroll.py`
- Modify: `src/ccusage_viz/tui_input.py`
- Modify: `tests/test_tui_input.py`
- Create: `tests/test_ranking_scroll.py`

**Interfaces:**
- Produces `WheelEvent(delta: int, x: int, y: int)` where `delta` is `-1` for SGR button code `64` and `1` for code `65`.
- Produces `RankingViewport(offset: float, total_rows: int, visible_rows: int)` with `maximum_offset: int` and `display_offset: int` properties.
- Produces `RankingKineticState(velocity_screens_per_second: float = 0.0, last_input_at: float | None = None, last_tick_at: float | None = None)`.
- Produces `apply_ranking_wheel(state, *, delta: int, now: float) -> RankingKineticState` and `advance_ranking_viewport(viewport, state, *, now: float) -> tuple[RankingViewport, RankingKineticState]`.

- [ ] **Step 1: Write failing wheel-decoding and policy tests**

```python
from ccusage_viz.ranking_scroll import (
    RankingKineticState,
    RankingViewport,
    advance_ranking_viewport,
    apply_ranking_wheel,
)
from ccusage_viz.tui_input import InputDecoder, WheelEvent


def test_decoder_emits_each_sgr_wheel_report() -> None:
    decoder = InputDecoder()
    decoder.feed("\x1b[<65;20;5M\x1b[<64;20;5M")
    assert decoder.next(now=0.0) == WheelEvent(1, 20, 5)
    assert decoder.next(now=0.0) == WheelEvent(-1, 20, 5)


def test_kinetic_velocity_is_screen_relative_and_hard_stops() -> None:
    state = apply_ranking_wheel(RankingKineticState(), delta=1, now=0.0)
    small, state = advance_ranking_viewport(
        RankingViewport(0.0, total_rows=100, visible_rows=10), state, now=0.05
    )
    large, _ = advance_ranking_viewport(
        RankingViewport(0.0, total_rows=100, visible_rows=30),
        apply_ranking_wheel(RankingKineticState(), delta=1, now=0.0), now=0.05
    )
    assert large.offset / 30 == pytest.approx(small.offset / 10)
    _, stopped = advance_ranking_viewport(small, state, now=0.111)
    assert stopped.velocity_screens_per_second == 0.0
```

Add exact tests for the `2.25` velocity cap, exponential deceleration, `0.05s` integration cap, wait-after-idle reset, reverse braking, top/bottom outward clearing, and floor-projected offset.

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `uv run pytest tests/test_tui_input.py tests/test_ranking_scroll.py -q`

Expected: FAIL because `WheelEvent` and `ranking_scroll` do not yet exist; the current decoder discards SGR wheel reports.

- [ ] **Step 3: Implement the event and policy module**

```python
# tui_input.py
@dataclass(frozen=True, slots=True)
class WheelEvent:
    delta: int
    x: int
    y: int

# in InputDecoder._control_sequence(), after parsing button/x/y:
if modifiers & _MOUSE_WHEEL:
    return WheelEvent(1 if button & 1 else -1, x, y)
```

```python
# ranking_scroll.py
WHEEL_IMPULSE_SCREENS_PER_SECOND = 0.32
WHEEL_MAX_SCREENS_PER_SECOND = 2.25
WHEEL_DAMPING_PER_SECOND = 22.0
WHEEL_STOP_SCREENS_PER_SECOND = 0.03
WHEEL_MAX_INERTIA_SECONDS = 0.110
WHEEL_MAX_FRAME_DELTA_SECONDS = 0.050


def advance_ranking_viewport(viewport, state, *, now):
    if state.last_input_at is None or now - state.last_input_at >= WHEEL_MAX_INERTIA_SECONDS:
        return viewport, replace(state, velocity_screens_per_second=0.0, last_tick_at=now)
    last_tick = state.last_tick_at if state.last_tick_at is not None else now
    dt = min(max(0.0, now - last_tick), WHEEL_MAX_FRAME_DELTA_SECONDS)
    velocity = state.velocity_screens_per_second
    offset = min(viewport.maximum_offset, max(0.0, viewport.offset + velocity * viewport.visible_rows * dt))
    velocity *= math.exp(-WHEEL_DAMPING_PER_SECOND * dt)
    if offset in {0.0, float(viewport.maximum_offset)} or abs(velocity) < WHEEL_STOP_SCREENS_PER_SECOND:
        velocity = 0.0
    return replace(viewport, offset=offset), RankingKineticState(velocity, state.last_input_at, now)
```

Implement `apply_ranking_wheel()` so it clears stale velocity after the hard limit, accumulates one signed impulse, and clamps to the named maximum. In `advance_ranking_viewport()`, only clear boundary velocity when it points outward; preserve inward velocity at a boundary.

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `uv run pytest tests/test_tui_input.py tests/test_ranking_scroll.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the independent input and policy layer**

```bash
git add src/ccusage_viz/ranking_scroll.py src/ccusage_viz/tui_input.py tests/test_ranking_scroll.py tests/test_tui_input.py
git commit -m "feat: add bounded ranking kinetic scroll policy"
```

## Task 2: Render Historical Ranking through a Reusable Viewport Contract

**Files:**
- Modify: `src/ccusage_viz/tui.py`
- Modify: `src/ccusage_viz/watch.py`
- Modify: `tests/test_tui_dashboard.py`
- Modify: `tests/test_watch.py`

**Interfaces:**
- Consumes `RankingViewport` from `ranking_scroll.py`.
- Produces a local helper in each host that takes complete accepted Ranking text, fixed chrome row count, and viewport and returns the viewport-sliced body plus refreshed metadata.
- Existing `render_text_viewport()` remains the canonical clamping/slicing utility; no Ranking-specific data-model projection is added.

- [ ] **Step 1: Write failing viewport rendering tests**

```python
def test_dashboard_ranking_viewport_keeps_chrome_and_moves_rendered_rows() -> None:
    body, viewport = tui_module._render_ranking_viewport(
        "summary\nheading\n1 one\n2 two\n3 three\n4 four",
        fixed_rows=2,
        viewport=RankingViewport(offset=1.0, total_rows=0, visible_rows=0),
        available_rows=4,
    )
    assert body.splitlines() == ["summary", "heading", "2 two", "3 three"]
    assert viewport.total_rows == 6
    assert viewport.visible_rows == 2
```

Add the same assertion at the standalone helper seam and verify a no-overflow viewport has `maximum_offset == 0`.

- [ ] **Step 2: Run the viewport tests to verify they fail**

Run: `uv run pytest tests/test_tui_dashboard.py tests/test_watch.py -k 'ranking_viewport' -q`

Expected: FAIL because the hosts have no historical Ranking viewport helper/state.

- [ ] **Step 3: Implement slice-only viewport rendering**

Add a small focused helper at the existing TUI local-pane rendering boundary. It must calculate fixed lines exactly as existing Ranking presentation does, use `render_text_viewport()` only for scrollable ranking rows, and combine fixed chrome with the sliced rows. Persist the resulting `total_rows`, `visible_rows`, and clamped fractional offset on the pane/session state. Use it only for accepted historical `RankingConfig` and Custom ranking charts; leave monitor ranking and all non-Ranking rendering unchanged.

In `watch.py`, retain `RankingViewport` beside the existing `text_offsets` state and use the same helper path before `compose_frame()`. Reset its kinetic state when the accepted result/configuration changes or when the calculated maximum becomes zero.

- [ ] **Step 4: Run the viewport tests to verify they pass**

Run: `uv run pytest tests/test_tui_dashboard.py tests/test_watch.py -k 'ranking_viewport' -q`

Expected: PASS.

- [ ] **Step 5: Commit viewport-only rendering support**

```bash
git add src/ccusage_viz/tui.py src/ccusage_viz/watch.py tests/test_tui_dashboard.py tests/test_watch.py
git commit -m "feat: retain historical ranking viewport metadata"
```

## Task 3: Integrate Dashboard Pointer Wheel Ownership and Kinetic Frames

**Files:**
- Modify: `src/ccusage_viz/tui.py`
- Modify: `tests/test_tui_dashboard.py`
- Modify: `tests/test_tui_custom.py`

**Interfaces:**
- Consumes `WheelEvent`, `RankingViewport`, `RankingKineticState`, `apply_ranking_wheel()`, and `advance_ranking_viewport()`.
- Adds session-only fields `ranking_viewport` and `ranking_kinetic` to `TuiChartPane` and `TuiCustomPane`.
- Adds a Dashboard-local `kinetic_owner: int | None` and `handle_ranking_wheel(event: WheelEvent, now: float) -> bool`.

- [ ] **Step 1: Write failing Dashboard tests for targeting, ownership, and isolation**

```python
def test_dashboard_wheel_scrolls_pointed_unfocused_ranking_without_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Build two panes where pane 0 is a long ranking and pane 1 owns focus.
    # Feed WheelEvent(1, x_in_pane_0, y_in_pane_0), then Ctrl-C.
    # Capture frames and provider submission calls.
    assert provider_submissions == startup_submissions
    assert visible_ranking_rows(frames[-1], pane=0)[0].startswith("2 ")
    assert focused_pane(frames[-1]) == 1
```

Add tests proving: Custom historical Ranking behaves identically; a non-Ranking or non-overflowing pointed pane is inert; Modal/help state rejects wheel input; a second pointed Ranking clears the previous owner velocity; and a `now=last_input+0.111` tick produces no further changed frame.

- [ ] **Step 2: Run Dashboard wheel tests to verify they fail**

Run: `uv run pytest tests/test_tui_dashboard.py tests/test_tui_custom.py -k 'wheel and ranking' -q`

Expected: FAIL because `WheelEvent` is not routed by Dashboard and no kinetic owner exists.

- [ ] **Step 3: Implement pointer routing and deadline-aware frames**

At the Dashboard main input loop, process `WheelEvent` before the existing `MouseEvent` click branch. `handle_ranking_wheel()` must recompute the current layout, convert terminal coordinates to grid coordinates, call `layout_pane_at()`, and accept only the pointed eligible `TuiChartPane`/`TuiCustomPane` viewport. It must not assign `focused`.

When changing owner, set the prior pane’s `ranking_kinetic` to a zero-velocity state. Apply the impulse, advance once at `now`, and return true only if the pane’s projected display row changed.

Add a `kinetic_deadline()` alongside the existing animation deadline. In each loop, advance only `kinetic_owner` before normal input handling. Set the read timeout to the minimum of existing adjustment/animation wait and the next short kinetic frame interval (for example `1/60` seconds), and stop scheduling it as soon as velocity is zero. Wheel and frame paths call only `paint()`; do not call `refresh()`, `collect()`, scheduler methods, or history mutation.

- [ ] **Step 4: Run Dashboard wheel tests to verify they pass**

Run: `uv run pytest tests/test_tui_dashboard.py tests/test_tui_custom.py -k 'wheel and ranking' -q`

Expected: PASS.

- [ ] **Step 5: Commit Dashboard integration**

```bash
git add src/ccusage_viz/tui.py tests/test_tui_dashboard.py tests/test_tui_custom.py
git commit -m "feat: kinetic wheel scroll dashboard rankings"
```

## Task 4: Integrate Standalone Native and Custom Historical Ranking Hosts

**Files:**
- Modify: `src/ccusage_viz/watch.py`
- Modify: `src/ccusage_viz/tui.py`
- Modify: `tests/test_watch.py`
- Modify: `tests/test_tui_custom.py`

**Interfaces:**
- `watch.py` consumes `tui_input_mode`, `read_event`, `KeyEvent`, and `WheelEvent` instead of key-only event reading in its interactive loop.
- Native and Custom standalone hosts consume the Task 1 policy and Task 2 viewport helper.

- [ ] **Step 1: Write failing standalone behavior tests**

```python
def test_native_standalone_ranking_wheel_uses_viewport_without_new_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Seed a long accepted native Ranking, then feed WheelEvent(1, 1, 1), None, Ctrl-C.
    assert submit_calls == [QueryTrigger.STARTUP]
    assert first_ranking_row(painted_frames[-1]).startswith("2 ")
```

Add the matching Custom standalone test. In both tests use deterministic monotonic times through `0.00`, `0.03`, and `0.111` to prove there is one bounded inertia repaint after input and none after the hard deadline. Assert unrelated `KeyEvent` behavior remains unchanged.

- [ ] **Step 2: Run standalone wheel tests to verify they fail**

Run: `uv run pytest tests/test_watch.py tests/test_tui_custom.py -k 'standalone and wheel and ranking' -q`

Expected: FAIL because the native loop currently reads only `read_key()` and standalone custom routing has no wheel policy.

- [ ] **Step 3: Implement standalone event and frame loops**

In `watch.py`, replace only the outer interactive input context and event read with `tui_input_mode()` and `read_event()`. Preserve every existing key branch by extracting `key = event.value` only for `KeyEvent`; ignore unrelated mouse/paste event types exactly as before. For `WheelEvent`, when `body_view == "chart"` and the accepted chart is an overflowing historical Ranking, apply and advance the shared viewport; repaint only after a visible projected movement.

In Custom standalone routing within `tui.py`, apply the same narrowing and policy behavior. Use a short read timeout only while active kinetic velocity remains; otherwise retain the current normal host timeout behavior. On a new accepted result, chart/view switch, or replacement, zero the standalone kinetic state.

- [ ] **Step 4: Run standalone wheel tests to verify they pass**

Run: `uv run pytest tests/test_watch.py tests/test_tui_custom.py -k 'standalone and wheel and ranking' -q`

Expected: PASS.

- [ ] **Step 5: Commit standalone integration**

```bash
git add src/ccusage_viz/watch.py src/ccusage_viz/tui.py tests/test_watch.py tests/test_tui_custom.py
git commit -m "feat: kinetic wheel scroll standalone rankings"
```

## Task 5: Regression Validation and Documentation Consistency

**Files:**
- Modify only if required by an identified regression: `docs/usage.md`, `docs/usage.zh-CN.md`, or relevant test/source files.

**Interfaces:**
- No new runtime interface.

- [ ] **Step 1: Run formatter/linter and all directly affected suites**

Run:

```bash
uv run ruff check src/ccusage_viz/ranking_scroll.py src/ccusage_viz/tui_input.py src/ccusage_viz/tui.py src/ccusage_viz/watch.py tests/test_ranking_scroll.py tests/test_tui_input.py tests/test_tui_dashboard.py tests/test_tui_custom.py tests/test_watch.py
uv run pytest tests/test_ranking_scroll.py tests/test_tui_input.py tests/test_tui_dashboard.py tests/test_tui_custom.py tests/test_watch.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the complete suite**

Run: `uv run pytest -q`

Expected: PASS.

- [ ] **Step 3: Inspect the final patch for scope and whitespace defects**

Run:

```bash
git diff --check
git diff -- src/ccusage_viz/ranking_scroll.py src/ccusage_viz/tui_input.py src/ccusage_viz/tui.py src/ccusage_viz/watch.py tests/test_ranking_scroll.py tests/test_tui_input.py tests/test_tui_dashboard.py tests/test_tui_custom.py tests/test_watch.py
git status --short
```

Expected: no whitespace errors; no query/scheduler changes caused by WheelEvent handling; no changes to user-owned unrelated files.

- [ ] **Step 4: Commit only follow-up fixes required by validation**

```bash
git add src/ccusage_viz/ranking_scroll.py src/ccusage_viz/tui_input.py src/ccusage_viz/tui.py src/ccusage_viz/watch.py tests/test_ranking_scroll.py tests/test_tui_input.py tests/test_tui_dashboard.py tests/test_tui_custom.py tests/test_watch.py
git commit -m "test: validate ranking kinetic wheel scrolling"
```

## Self-Review

- **Spec coverage:** Tasks 1 and 3 implement velocity units, caps, damping, hard stop, no target queue, input coalescing, pointer targeting, boundary/reversal behavior, and Dashboard ownership. Tasks 2 and 4 apply the same native/Custom historical Ranking viewport contract to Dashboard and standalone hosts. All tasks preserve data/scheduler isolation; Task 5 validates it and regressions.
- **Placeholder scan:** No TBD/TODO markers, unnamed interfaces, or unspecified test actions remain.
- **Type consistency:** All host code uses `WheelEvent`, `RankingViewport`, `RankingKineticState`, `apply_ranking_wheel()`, and `advance_ranking_viewport()` as introduced in Task 1.
