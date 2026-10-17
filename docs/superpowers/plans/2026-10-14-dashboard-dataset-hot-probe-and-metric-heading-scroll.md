# Dashboard Dataset Hot Probe and Metric Heading Scroll Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refresh a Dashboard-selected Dataset's descriptor before Metric selection and give the first hidden group heading one Up-key reveal before Metric selection wraps.

**Architecture:** Add a small single-Dataset refresh operation to `DatasetService`; Dashboard modal code submits it through its existing executor and handles a new pending stage in `collect_dataset_modal()`. Extract the display-row-aware first-heading reveal predicate so the modal can adjust its viewport without changing the selected Metric; reuse it in the legacy blocking chooser to preserve identical selector navigation.

**Tech Stack:** Python 3.11+, dataclasses, `concurrent.futures`, terminal TUI, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-14-dashboard-dataset-hot-probe-and-metric-heading-scroll-design.md`

## Global Constraints

- Change only Dataset single-refresh support, Dashboard Dataset modal behavior, and focused TUI/Dataset-service regression tests.
- Probe only the Dataset confirmed with Enter; do not refresh every source when opening the chooser.
- A modal loading state must not block the Dashboard event loop, and a cancelled/stale result must not mutate a different modal state.
- A fresh Probe failure remains on the source chooser, retains its selection and prior snapshot, and uses existing formatted Dataset errors.
- Group headers remain ordinary scroll rows; do not introduce sticky headers or localization keys.
- First hidden leading presentation rows above the first selected Metric require one Up to reveal; only the next Up wraps to the final selectable Metric. If they are already visible, the first Up wraps immediately.

---

## File Structure

- Modify: `src/ccusage_viz/datasets/service.py` — expose one atomic, persisted refresh operation for a named registered Dataset.
- Modify: `tests/test_datasets_service.py` — prove a successful one-Dataset refresh updates only its snapshot and errors do not overwrite it.
- Modify: `src/ccusage_viz/tui.py` — add pending Dataset-probe modal collection and display-row-aware first-heading reveal behavior.
- Modify: `tests/test_tui_dashboard.py` — drive Dashboard hot-Probe success/failure through `run_tui()`.
- Modify: `tests/test_tui_custom.py` — cover pure heading-reveal semantics and the existing blocking Dataset chooser's equivalent navigation.

### Task 1: Add an atomic single-Dataset refresh service operation

**Files:**
- Modify: `src/ccusage_viz/datasets/service.py:155-202`
- Modify: `tests/test_datasets_service.py:115-215`

**Interfaces:**
- Consumes: `DatasetService.store`, `DatasetService.probe_runner`, `DatasetRegistration`, and `DatasetRegistrationStatus`.
- Produces: `DatasetService.refresh(dataset_id: str) -> DatasetRegistrationStatus`, which probes one enabled registration, persists a successful descriptor snapshot, and returns its refreshed status; it raises the original command/protocol exception without overwriting the previous snapshot on failure.

- [ ] **Step 1: Write focused failing service tests**

Add tests to `tests/test_datasets_service.py` using a temporary `DatasetService(root=tmp_path, probe_runner=...)`, register two local command sources, and drive just one source through an updated probe response:

```python
def test_refresh_updates_only_the_named_dataset_probe_snapshot(tmp_path: Path) -> None:
    responses = iter((first_router_probe(), first_books_probe(), updated_router_probe()))
    service = DatasetService(root=tmp_path, probe_runner=lambda _argv: next(responses))
    service.register_local_command(("router",))
    service.register_local_command(("books",))

    refreshed = service.refresh("router")

    assert refreshed.registration.probe.descriptor == updated_router_probe().descriptor
    assert service.store.load_registration("books").probe.descriptor == first_books_probe().descriptor
```

Also add a failure case with a runner that raises `QueryError("error.custom_command_protocol")`; assert the exception propagates and `load_registration("router").probe` is still the original snapshot.

- [ ] **Step 2: Run the focused tests to verify failure**

Run: `pytest tests/test_datasets_service.py -v`

Expected: FAIL because `DatasetService.refresh` does not exist.

- [ ] **Step 3: Implement the minimal service method**

Add this public method next to `refresh_all()` and share no UI concerns with it:

```python
def refresh(self, dataset_id: str) -> DatasetRegistrationStatus:
    current = self.store.load_registration(parse_dataset_id(dataset_id))
    if not current.enabled:
        return next(item for item in self.registrations() if item.registration.dataset_id == current.dataset_id)
    argv = (
        current.source.command_argv
        if isinstance(current.source, LocalDatasetSource)
        else self.installed_command_source(current.dataset_id).command_argv
    )
    response = self.probe_runner(argv)
    if response.dataset_id != current.dataset_id:
        raise ValueError("probe declared a different Dataset ID")
    now = datetime.now(UTC).isoformat()
    updated = replace(
        current,
        updated_at=now,
        probe=DatasetProbeSnapshot(current.dataset_id, response.descriptor, now),
        available_update=self._update_candidate(current),
        last_probe_error=None,
    )
    self.store.save_registration(updated)
    return next(item for item in self.registrations() if item.registration.dataset_id == current.dataset_id)
```

Do not catch `probe_runner` errors in this method: its caller must retain the old registration snapshot on a failed refresh. If `_update_candidate()` fails, retain `current.available_update`, matching `refresh_all()`.

- [ ] **Step 4: Run formatting and focused tests**

Run:

```bash
ruff check src/ccusage_viz/datasets/service.py tests/test_datasets_service.py
pytest tests/test_datasets_service.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit the independently usable service behavior**

```bash
git add src/ccusage_viz/datasets/service.py tests/test_datasets_service.py
git commit -m "feat: refresh one dataset descriptor"
```

### Task 2: Define and test first-heading viewport reveal helpers

**Files:**
- Modify: `src/ccusage_viz/tui.py:742-765`
- Modify: `tests/test_tui_custom.py:2053-2081`

**Interfaces:**
- Consumes: rendered `tuple[MetricChooserRow, ...]`, current selected Metric ID/index, and current viewport offset.
- Produces: `_metric_chooser_previous_offset(rows: tuple[MetricChooserRow, ...], selected_metric_index: int, offset: int) -> int | None`; returns the preceding hidden display-row offset only when the selection is the first selectable Metric and a preceding presentation row is not visible, otherwise `None`.

- [ ] **Step 1: Write failing pure helper tests**

Add a test that builds displayed rows consisting of a group, first Metric, description, and second Metric. Assert the first selected Metric at `offset=1` returns `0`, while the same selected Metric at `offset=0` returns `None`; assert selecting the second Metric returns `None` even with `offset=1`.

```python
assert tui_module._metric_chooser_previous_offset(rows, selected_metric_index=0, offset=1) == 0
assert tui_module._metric_chooser_previous_offset(rows, selected_metric_index=0, offset=0) is None
assert tui_module._metric_chooser_previous_offset(rows, selected_metric_index=1, offset=1) is None
```

- [ ] **Step 2: Run the new helper test to verify failure**

Run: `pytest tests/test_tui_custom.py -k metric_chooser_previous_offset -v`

Expected: FAIL because `_metric_chooser_previous_offset` does not exist.

- [ ] **Step 3: Implement the pure helper**

Place this directly after `_metric_chooser_display_rows()`:

```python
def _metric_chooser_previous_offset(
    rows: tuple[MetricChooserRow, ...], *, selected_metric_index: int, offset: int
) -> int | None:
    """Reveal rows before the first Metric before wrapping its selection."""
    selectable_positions = tuple(
        position for position, row in enumerate(rows) if row.metric_index is not None
    )
    if not selectable_positions or rows[selectable_positions[0]].metric_index != selected_metric_index:
        return None
    first_position = selectable_positions[0]
    return first_position - 1 if offset > 0 and first_position > 0 else None
```

The callers supply already-wrapped display rows, so a description that wraps never corrupts display-row offsets.

- [ ] **Step 4: Run the focused helper and existing display tests**

Run:

```bash
pytest tests/test_tui_custom.py -k 'metric_chooser_previous_offset or metric_chooser_display_rows' -v
ruff check src/ccusage_viz/tui.py tests/test_tui_custom.py
```

Expected: PASS.

- [ ] **Step 5: Commit the helper and tests**

```bash
git add src/ccusage_viz/tui.py tests/test_tui_custom.py
git commit -m "fix: reveal first metric group heading before wrap"
```

### Task 3: Use fresh descriptor probes in the nonblocking Dashboard modal

**Files:**
- Modify: `src/ccusage_viz/tui.py:9196-9380,9487-9610`
- Modify: `tests/test_tui_dashboard.py:2480-2560`

**Interfaces:**
- Consumes: `DatasetService.refresh(dataset_id) -> DatasetRegistrationStatus`, `DashboardDatasetModalState.future`, and its selected `dataset_id`.
- Produces: a `"source_loading"` modal stage which submits `modal.service.refresh` through `executor`, shows `status.loading`, and after collection replaces only the selected entry in `modal.statuses` before proceeding with the updated descriptor.

- [ ] **Step 1: Write a hot-Probe success integration regression**

In `tests/test_tui_dashboard.py`, make a registered V2 source whose stored descriptor has one `"old"` Metric while `DatasetService.refresh("dataset")` returns a status with an additional `"new"` Metric. Feed Dashboard events `m`, `r`, `k`, Enter, Enter, `j`, Enter, Ctrl-C (the first Enter opens source selection and the second confirms the source after modal paint cycles). Capture rendered frames and calls.

Assert all of:

```python
assert refresh_calls == ["dataset"]
assert any("new" in "\n".join(frame.rows) for frame in frames)
assert "old" in rendered
```

Use an immediate Future/handle returned by a patched `executor.submit`, so the test drives the normal `collect_dataset_modal()` path without sleeping.

- [ ] **Step 2: Run the success regression to verify failure**

Run: `pytest tests/test_tui_dashboard.py -k hot_probe -v`

Expected: FAIL because source Enter directly enters Metric selection using the stored descriptor and does not call `DatasetService.refresh`.

- [ ] **Step 3: Add a source-loading transition and completion handler**

In source-stage Enter handling, retain the selected `dataset_id`, clear transient Metric/kind fields, then set `modal.stage = "source_loading"` and submit:

```python
modal.future = executor.submit(
    cast(Callable[[str], object], modal.service.refresh), modal.draft.dataset_id
)
```

In `_paint_dataset_modal()`, render `"source_loading"` with the Dataset chooser title/controls, blank body, and `translator.text("status.loading")` notice. In `collect_dataset_modal()`, consume that Future only while `modal.stage == "source_loading"`:

```python
try:
    refreshed = modal.future.result()
except UsageError as exc:
    modal.stage = "source"
    modal.error = format_error(exc, translator)
except Exception as exc:
    modal.stage = "source"
    modal.error = str(exc)
else:
    modal.statuses = tuple(
        refreshed if item.registration.dataset_id == refreshed.registration.dataset_id else item
        for item in modal.statuses
    )
    modal.stage, modal.index, modal.offset = "source", selected_index, 0
    # invoke one extracted local transition helper that applies the fresh descriptor:
    # V2 -> metric with default selectable Metric; V1 -> installed if chart kinds exist.
finally:
    modal.future = None
```

Extract the existing source selection descriptor-to-stage body into a nested `advance_dataset_modal(status)` function. Call it after successful refresh so it performs existing V2 empty-Metric guarding, default-Metric selection, and V1 chart-kind selection exactly once. On Escape from `source_loading`, call `modal.future.cancel()`, clear it, and return to `source`; `collect_dataset_modal()` must then ignore it because the stage no longer matches.

- [ ] **Step 4: Run the success regression to verify it passes**

Run: `pytest tests/test_tui_dashboard.py -k hot_probe_success -v`

Expected: PASS, with the fresh Metric visible in the modal.

- [ ] **Step 5: Add and pass the hot-Probe failure regression**

Add a neighboring test whose `refresh()` raises `UsageError("error.custom_command_protocol")`. Drive through source confirmation and Ctrl-C; assert `refresh_calls == ["dataset"]`, rendered output contains the translated protocol error, and does not contain `status.dataset_metric_choose` / the Metric chooser prompt.

Run:

```bash
pytest tests/test_tui_dashboard.py -k hot_probe -v
```

Expected: PASS.

- [ ] **Step 6: Commit Dashboard hot-probe behavior**

```bash
git add src/ccusage_viz/tui.py tests/test_tui_dashboard.py
git commit -m "feat: refresh dataset metrics on dashboard selection"
```

### Task 4: Apply the reveal-before-wrap behavior in both Metric choosers

**Files:**
- Modify: `src/ccusage_viz/tui.py:4553-4655,9321-9356,9581-9608`
- Modify: `tests/test_tui_custom.py:2084-2180`

**Interfaces:**
- Consumes: `_metric_chooser_previous_offset(...)` and display rows made by `_metric_chooser_display_rows(...)`.
- Produces: both the blocking `_choose_dataset_pane_config()` chooser and Dashboard `modal.stage == "metric"` perform a viewport-only Up before wrapping the first Metric when its leading heading is hidden.

- [ ] **Step 1: Write Dashboard-level navigation regressions**

Add two `run_tui()` tests with a short terminal height and one grouped V2 descriptor containing at least two Metrics.

For the hidden-heading test, use enough prompt/frame rows that `_chooser_viewport()` projects the first Metric at offset `1`; drive source selection, then Up, capture a frame, then Up. Assert the first post-Up frame contains the group title and still marks the first Metric selected; assert the final captured Metric selection is the last Metric.

For the visible-heading test, use a taller terminal so initial `modal.offset == 0`; drive the same path with one Up and assert the last Metric is selected immediately.

- [ ] **Step 2: Run navigation regressions to verify failure**

Run: `pytest tests/test_tui_dashboard.py -k 'metric_heading and up' -v`

Expected: FAIL because current Up always changes `modal.index` to the last selectable Metric.

- [ ] **Step 3: Update Dashboard Metric Up handling**

Before its normal `selectable[(selectable.index(modal.index) - 1) % len(selectable)]` assignment, build `metric_rows` with the same `width` and ASCII setting used by paint, then apply:

```python
reveal_offset = _metric_chooser_previous_offset(
    _metric_chooser_display_rows(
        _dataset_metric_chooser_rows(selected, translator),
        width=_dataset_modal_size(modal.pane_index)[0],
        ascii=options.host.ascii,
    ),
    selected_metric_index=modal.index,
    offset=modal.offset,
)
if reveal_offset is not None:
    modal.offset = reveal_offset
else:
    modal.index = selectable[(selectable.index(modal.index) - 1) % len(selectable)]
```

Leave Down navigation unchanged. This intentionally moves only one display row per Up so all leading ordinary rows remain navigable.

- [ ] **Step 4: Add and implement matching blocking chooser coverage**

In the existing standalone/legacy Dataset chooser test harness, feed a grouped V2 descriptor, constrained height, and Up events. Assert the first Up reveals the group without changing its selection and the second chooses the final Metric; add a tall-height variant proving immediate wrap.

Apply the same helper before the blocking chooser's normal Up index wrap, using its already-created `metric_display_rows` and `metric_offset`.

- [ ] **Step 5: Run all focused selector tests**

Run:

```bash
pytest tests/test_tui_dashboard.py -k 'hot_probe or metric_heading' -v
pytest tests/test_tui_custom.py -k 'metric_chooser or standalone_metric_chooser' -v
ruff check src/ccusage_viz/tui.py tests/test_tui_dashboard.py tests/test_tui_custom.py
```

Expected: PASS.

- [ ] **Step 6: Commit navigation behavior**

```bash
git add src/ccusage_viz/tui.py tests/test_tui_dashboard.py tests/test_tui_custom.py
git commit -m "fix: reveal metric group heading before selector wrap"
```

### Task 5: Run complete relevant verification

**Files:**
- Verify only: `src/ccusage_viz/datasets/service.py`, `src/ccusage_viz/tui.py`, `tests/test_datasets_service.py`, `tests/test_tui_dashboard.py`, `tests/test_tui_custom.py`

**Interfaces:**
- Consumes: all completed work.
- Produces: verified Dataset refresh and selector behavior with no regressions in Dataset protocol/service, Dashboard, or custom chooser tests.

- [ ] **Step 1: Run static checks**

Run:

```bash
ruff check src/ccusage_viz/datasets/service.py src/ccusage_viz/tui.py tests/test_datasets_service.py tests/test_tui_dashboard.py tests/test_tui_custom.py
```

Expected: PASS.

- [ ] **Step 2: Run the relevant full test modules**

Run:

```bash
pytest tests/test_datasets_service.py tests/test_tui_dashboard.py tests/test_tui_custom.py -v
```

Expected: PASS.

- [ ] **Step 3: Review the working tree and commit any verification-only corrections**

Run:

```bash
git status --short
git diff --check
```

Expected: no whitespace errors; only intended source and test changes remain. If test/lint fixes are required, rerun Steps 1–2 and commit them:

```bash
git add src/ccusage_viz/datasets/service.py src/ccusage_viz/tui.py tests/test_datasets_service.py tests/test_tui_dashboard.py tests/test_tui_custom.py
git commit -m "test: verify dashboard dataset chooser refresh"
```
