# Managed Dataset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a durable Dataset Manager with local-command registration, probe snapshots, and Dashboard consumption of registered Dataset records.

**Architecture:** Keep `datasets/` as the single ownership boundary for Dataset records, artifacts, availability, and probing. The Manager is a dedicated terminal loop which consumes `DatasetService`; Dashboard only asks the service for ready registered records and then filters chart choices from the persisted probe descriptor. The existing official/GitHub chooser helpers move into the Manager flow, while local registration is implemented and tested end to end first.

**Tech Stack:** Python 3.12, dataclasses, JSON/filesystem state, argparse, existing terminal `FramePainter`/`InputDecoder`, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-10-06-managed-dataset-design.md`

## Global Constraints

- Public Dataset commands are exactly `ccuv dataset` and `ccuv dataset list`.
- Host UI strings must have `en` and `zh` translations; runtime screens show one language only.
- Probe must omit a host-provided `dataset_id`; the response's outer `dataset_id` declares the canonical Dataset identity.
- `ccuv.dataset/v1` remains the manifest schema name; its `probe` content is the static probe declaration.
- Never persist credentials, environment values, stdout protocol payloads, stderr, query data, chart data, or Dashboard layouts.
- Local removal never deletes the local command or target binary. Managed official/GitHub removal deletes only ccuv-managed artifacts.
- Do not publish a WeRead release or alter the remote official catalog during implementation or acceptance.
- Preserve unrelated dirty/untracked files and stage only task-owned files.

---

## File Structure

- `src/ccusage_viz/custom_protocol.py`: split discovery probe from ID-bound chart/summary requests and parse probe identity.
- `src/ccusage_viz/custom_models.py`: retain the descriptor model; add the discovered identity to `CustomProbeResponse`, not the descriptor.
- `src/ccusage_viz/datasets/models.py`: define one managed registration record, local/managed provenance, health/snapshot types, v1 manifest probe structure, and official catalog summary parsing.
- `src/ccusage_viz/datasets/store.py`: atomically read/write registration JSON separately from managed artifact version directories.
- `src/ccusage_viz/datasets/service.py`: register/probe/replace local commands, derive availability, toggle enabled state, remove registrations, resolve record command sources, and expose registered records.
- `src/ccusage_viz/datasets/manager.py`: dedicated Manager terminal loop and moved source chooser flows.
- `src/ccusage_viz/cli.py`: replace `datasets` parser/dispatcher with `dataset` and `dataset list`; keep chart routes resolving registered records.
- `src/ccusage_viz/tui.py`: replace the Dashboard three-source Dataset chooser with registered-record then capability-filtered chart selection.
- `src/ccusage_viz/locales/en.py`, `src/ccusage_viz/locales/zh.py`: Manager, conflict, state, source, and Dashboard picker copy.
- `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/protocol/protocol.go`, `manifest.json`, and tests: change the static/probe contract without publishing it.

## Task 1: Change Discovery Probe Identity

**Files:**
- Modify: `src/ccusage_viz/custom_protocol.py`
- Modify: `src/ccusage_viz/custom_models.py`
- Modify: `src/ccusage_viz/acquisition.py`
- Modify: `src/ccusage_viz/providers/custom_command.py`
- Test: `tests/test_custom_protocol.py`
- Test: `tests/test_query_planner.py`

**Interfaces:**
- Produces `CustomProbeRequest(request_id, command_argv=..., execution_context=...)` with no `dataset_id`.
- Produces `CustomProbeResponse(dataset_id: str, descriptor: CustomProbeDescriptor, warnings=...)`.
- Keeps `CustomChartRequest` and `CustomSummaryRequest` internally keyed by a known `dataset_id`.

- [ ] **Step 1: Write failing discovery-probe tests**

```python
def test_probe_request_omits_dataset_id_and_response_declares_it() -> None:
    request = CustomProbeRequest("probe-1", command_argv=("reader", "ccuv"))
    assert request.to_wire() == {
        "protocol": PROTOCOL_VERSION,
        "request_id": "probe-1",
        "request_kind": "probe",
    }
    result = parse_custom_response(json.dumps(probe_response()).encode(), request)
    assert result.dataset_id == "weread"

def test_chart_response_need_not_echo_dataset_id() -> None:
    response = chart_response()
    response.pop("dataset_id")
    assert parse_custom_response(json.dumps(response).encode(), chart_request())
```

- [ ] **Step 2: Run the targeted protocol tests and verify failure**

Run: `uv run pytest tests/test_custom_protocol.py -q`

Expected: failures because `CustomProbeRequest` requires `dataset_id` and response envelope validation requires echoed IDs.

- [ ] **Step 3: Implement the probe-only discovery shape**

```python
@dataclass(frozen=True, slots=True)
class CustomProbeRequest:
    request_id: str
    command_argv: tuple[str, ...] = ()
    execution_context: tuple[tuple[str, str], ...] = ()
    request_kind: Literal["probe"] = "probe"

    def to_wire(self) -> dict[str, object]:
        return {"protocol": PROTOCOL_VERSION, "request_id": self.request_id,
                "request_kind": self.request_kind}

@dataclass(frozen=True, slots=True)
class CustomProbeResponse:
    dataset_id: str
    descriptor: CustomProbeDescriptor
    warnings: tuple[CustomProtocolWarning, ...] = field(default=(), kw_only=True)
```

Make `_validate_envelope()` require `request_id` and `request_kind` for all responses. For a probe, parse and validate the response `dataset_id` with `_require_id`; for chart/summary accept an optional response `dataset_id` but do not compare it to the request. Remove `dataset_id` from `CustomProbeRequest` canonical keys and create probe `ProviderRef("custom-command", "probe")` until `DatasetService` converts the successful discovery result into an ID-bound source.

- [ ] **Step 4: Run focused protocol and query planner coverage**

Run: `uv run pytest tests/test_custom_protocol.py tests/test_query_planner.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the protocol discovery boundary**

```bash
git add src/ccusage_viz/custom_protocol.py src/ccusage_viz/custom_models.py \
  src/ccusage_viz/acquisition.py src/ccusage_viz/providers/custom_command.py \
  tests/test_custom_protocol.py tests/test_query_planner.py
git commit -m "feat: discover dataset identity through probe"
```

## Task 2: Define v1 Static Probe Manifest and Registration Records

**Files:**
- Modify: `src/ccusage_viz/datasets/models.py`
- Modify: `src/ccusage_viz/datasets/store.py`
- Test: `tests/test_datasets_models.py`
- Test: `tests/test_datasets_store.py`

**Interfaces:**
- Produces `DatasetManifest(probe_dataset_id, probe_descriptor, entrypoint, os, arch)` for v1 packages.
- Produces `DatasetRegistration` with `dataset_id`, `source`, `enabled`, timestamps, last successful snapshot, and non-sensitive diagnostic.
- Produces `DatasetStore.load_registration(dataset_id)`, `save_registration(record)`, `remove_registration(dataset_id)`, and `registration_ids()`.

- [ ] **Step 1: Add failing v1 manifest and local-registration round-trip tests**

```python
def test_manifest_v1_embeds_static_probe_declaration() -> None:
    manifest = DatasetManifest.parse(manifest_wire_with_probe())
    assert manifest.probe_dataset_id == "reading-time"
    assert manifest.probe_descriptor.defaults["ranking"].top == 10

def test_store_persists_local_registration_without_a_managed_artifact(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path / "datasets")
    registration = local_registration("weread", ("/tmp/weread", "ccuv"))
    store.save_registration(registration)
    assert store.load_registration("weread") == registration
```

- [ ] **Step 2: Run model/store tests and verify failure**

Run: `uv run pytest tests/test_datasets_models.py tests/test_datasets_store.py -q`

Expected: FAIL because manifests require `metric/charts/environment` and the store has no registration APIs.

- [ ] **Step 3: Implement static probe and minimal record schemas**

Use a strict v1 manifest wire shape:

```python
@dataclass(frozen=True, slots=True)
class DatasetManifest:
    dataset_id: str
    protocol: str
    entrypoint: str
    os: str
    arch: str
    descriptor: CustomProbeDescriptor

@dataclass(frozen=True, slots=True)
class LocalDatasetSource:
    command_argv: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class DatasetRegistration:
    dataset_id: str
    source_kind: Literal["local", "official", "github"]
    enabled: bool
    created_at: str
    updated_at: str
    probe: CustomProbeSnapshot
    source: LocalDatasetSource | ManagedDatasetSource
    last_probe_error: DatasetDiagnostic | None = None
```

Serialize records as `registrations/<dataset_id>.json` with 0600 permissions and a temporary-file replacement. Keep artifact directories under `<root>/<dataset_id>/versions/`; registration lookup must not infer local registrations from an artifact directory. Validation must reject unknown fields and secret-bearing fields.

- [ ] **Step 4: Run model/store tests**

Run: `uv run pytest tests/test_datasets_models.py tests/test_datasets_store.py -q`

Expected: PASS, including unknown-field rejection and no secret values in representation/wire data.

- [ ] **Step 5: Commit persistent record foundation**

```bash
git add src/ccusage_viz/datasets/models.py src/ccusage_viz/datasets/store.py \
  tests/test_datasets_models.py tests/test_datasets_store.py
git commit -m "feat: persist managed dataset registrations"
```

## Task 3: Implement Local Registration, State Derivation, and Source Resolution

**Files:**
- Modify: `src/ccusage_viz/datasets/service.py`
- Modify: `src/ccusage_viz/datasets/paths.py`
- Test: `tests/test_datasets_service.py`
- Test: `tests/test_datasets_store.py`

**Interfaces:**
- Produces `DatasetService.register_local_command(argv, *, replace=False) -> RegisterResult`.
- Produces `DatasetService.registrations() -> tuple[DatasetRegistrationStatus, ...]`.
- Produces `DatasetService.set_enabled(dataset_id, enabled)`, `refresh_all()`, `remove_registration(dataset_id)`, and `registered_command_source(dataset_id)`.

- [ ] **Step 1: Add failing service tests for register/replace/state/remove**

```python
def test_register_local_command_uses_probe_id_and_keeps_argv(tmp_path: Path) -> None:
    service = service_with_probe(tmp_path, dataset_id="weread")
    result = service.register_local_command(("reader", "ccuv"))
    assert result.kind == "created"
    assert result.registration.dataset_id == "weread"

def test_different_local_source_with_same_probe_id_requires_replace(tmp_path: Path) -> None:
    service = service_with_probe(tmp_path, dataset_id="weread")
    service.register_local_command(("reader-a", "ccuv"))
    assert service.register_local_command(("reader-b", "ccuv")).kind == "conflict"
    assert service.register_local_command(("reader-b", "ccuv"), replace=True).kind == "replaced"

def test_remove_local_registration_does_not_remove_target(tmp_path: Path) -> None:
    target = tmp_path / "reader"
    target.write_text("#!/bin/sh\n")
    service = service_with_probe(tmp_path, dataset_id="weread")
    service.register_local_command((str(target), "ccuv"))
    service.remove_registration("weread")
    assert target.exists()
```

- [ ] **Step 2: Run the service tests and verify failure**

Run: `uv run pytest tests/test_datasets_service.py -q`

Expected: FAIL because DatasetService exposes only artifact installation/status APIs.

- [ ] **Step 3: Implement the service state machine**

Add a small dependency-injected probe runner to `DatasetService` so tests do not spawn a process:

```python
ProbeRunner = Callable[[tuple[str, ...]], CustomProbeResponse]

def register_local_command(
    self, command_argv: tuple[str, ...], *, replace: bool = False
) -> RegisterResult:
    probe = self.probe_runner(command_argv)
    existing = self.store.find_registration(probe.dataset_id)
    # same source -> already_registered; different source -> conflict unless replace
```

The production runner must call `custom_probe_query_intent()` plus `QueryRuntime`, never build a shell command. `registrations()` derives `ready`, `setup_required`, `unavailable`, and `disabled` from enabled state, source resolvability, stored descriptor environment declarations, and last explicit probe diagnostic. `refresh_all()` skips disabled records and preserves the old snapshot if an individual command fails.

- [ ] **Step 4: Run service and protocol integration tests**

Run: `uv run pytest tests/test_datasets_service.py tests/test_datasets_store.py tests/test_custom_provider.py -q`

Expected: PASS.

- [ ] **Step 5: Commit registration behavior**

```bash
git add src/ccusage_viz/datasets/service.py src/ccusage_viz/datasets/paths.py \
  tests/test_datasets_service.py tests/test_datasets_store.py
git commit -m "feat: register local dataset commands"
```

## Task 4: Reshape Manifest/Catalog Contracts and Update WeRead Locally

**Files:**
- Modify: `src/ccusage_viz/datasets/catalog.py`
- Modify: `src/ccusage_viz/datasets/models.py`
- Modify: `src/ccusage_viz/datasets/archive.py`
- Modify: `tests/test_datasets_catalog.py`
- Modify: `tests/test_datasets_archive.py`
- Modify: `/Users/bytedance/Projects/go/ccuv-dataset-weread/manifest.json`
- Modify: `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/protocol/protocol.go`
- Modify: `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/protocol/protocol_test.go`
- Modify: `/Users/bytedance/Projects/go/ccuv-dataset-weread/cmd/ccuv-dataset-weread/main_test.go`

**Interfaces:**
- Produces catalog `CatalogEntry(id, title, summary, repository, artifacts)`.
- Produces v1 manifest `probe.dataset_id` and `probe.descriptor` matching the executable probe response.

- [ ] **Step 1: Add failing catalog/manifest agreement tests**

```python
def test_catalog_requires_localized_summary_and_repository() -> None:
    entry = CatalogEntry.parse(catalog_entry_wire())
    assert entry.summary.zh_cn
    assert entry.repository == "Cookie-HOO/ccuv-dataset-weread"

def test_staged_probe_must_match_manifest_static_probe() -> None:
    manifest = DatasetManifest.parse(manifest_wire_with_probe())
    assert validate_static_probe(manifest, probe_response("reading-time"))
```

- [ ] **Step 2: Run focused package contract tests and verify failure**

Run: `uv run pytest tests/test_datasets_catalog.py tests/test_datasets_archive.py tests/test_datasets_models.py -q`

Expected: FAIL because catalog records have `description` instead of `summary/repository` and manifest has duplicated static fields.

- [ ] **Step 3: Implement the v1 contract without a schema-version bump**

Replace `metric`, `charts`, and `environment` in a newly built manifest with:

```json
"probe": {
  "dataset_id": "weread",
  "descriptor": { "revision": "...", "version": "...", "dataset": {},
                  "capabilities": {}, "defaults": {}, "environment": [] }
}
```

Require `CatalogEntry.repository`, `CatalogEntry.title`, and `CatalogEntry.summary`, all localized where user-facing. Use the catalog repository before GitHub discovery to normalize a matching repository to official metadata. In the local WeRead repository, make probe requests omit `dataset_id`, make `NewProbeResponse` always declare `weread`, embed the same descriptor in `manifest.json`, update the description and `WEREAD_API_KEY` how-to text, and add `help_url: https://weread.qq.com/r/weread-skills`. Do not create a release, tag, push, or catalog entry.

- [ ] **Step 4: Run Python and local Go verification**

Run: `uv run pytest tests/test_datasets_catalog.py tests/test_datasets_archive.py tests/test_datasets_models.py -q && go test ./...`

Workdir for Go command: `/Users/bytedance/Projects/go/ccuv-dataset-weread`

Expected: PASS.

- [ ] **Step 5: Commit only ccuv contract changes; commit WeRead changes separately in its repository if it is a Git repository**

```bash
git add src/ccusage_viz/datasets/catalog.py src/ccusage_viz/datasets/models.py \
  src/ccusage_viz/datasets/archive.py tests/test_datasets_catalog.py \
  tests/test_datasets_archive.py tests/test_datasets_models.py
git commit -m "feat: align dataset manifests with probe descriptors"
```

In `/Users/bytedance/Projects/go/ccuv-dataset-weread`, inspect status, stage only
the listed manifest/protocol/test files, run `go test ./...`, and commit with
`git commit -m "feat: expose static dataset probe descriptor"`. Do not push.

## Task 5: Build the Dataset Manager TUI and the Public CLI Surface

**Files:**
- Create: `src/ccusage_viz/datasets/manager.py`
- Modify: `src/ccusage_viz/cli.py`
- Modify: `src/ccusage_viz/locales/en.py`
- Modify: `src/ccusage_viz/locales/zh.py`
- Test: `tests/test_cli.py`
- Create: `tests/test_dataset_manager.py`

**Interfaces:**
- Produces `run_dataset_manager(service: DatasetService, translator: Translator) -> int`.
- Produces `render_dataset_list(statuses, translator, show_details: bool) -> Frame`.
- Produces CLI route `dataset` and `dataset list`.

- [ ] **Step 1: Add failing CLI and pure-manager rendering tests**

```python
def test_dataset_command_routes_to_manager(monkeypatch, capsys) -> None:
    monkeypatch.setattr("ccusage_viz.datasets.manager.run_dataset_manager", lambda *_: 0)
    assert main(["dataset", "--lang", "en"]) == 0

def test_dataset_list_never_probes_or_fetches(monkeypatch, capsys) -> None:
    service = FakeDatasetService([ready_local("weread"), disabled_local("old")])
    monkeypatch.setattr("ccusage_viz.datasets.manager.DatasetService", lambda: service)
    assert main(["dataset", "list"]) == 0
    assert "weread" in capsys.readouterr().out
    assert service.probe_calls == service.catalog_calls == 0

def test_manager_conflict_choice_contains_cancel_and_replace() -> None:
    frame = render_registration_conflict("weread", load_translator("en"))
    assert "Cancel" in "\n".join(frame.rows)
    assert "Replace existing registration" in "\n".join(frame.rows)
```

- [ ] **Step 2: Run manager/CLI tests and verify failure**

Run: `uv run pytest tests/test_cli.py tests/test_dataset_manager.py -q`

Expected: FAIL because no `dataset` route or manager module exists.

- [ ] **Step 3: Implement manager loop and source migration seam**

Implement the stateful loop in `datasets/manager.py` using `FramePainter`,
`InputDecoder`, `compose_frame`, and `format_notice_lines`. Default to compact
state-grouped rows; toggle details with `i`; use `+`, `r`, `d`, `x`, `q` exactly
as specified. Move the existing catalog browse, GitHub repository input, and
local command editor helpers from `tui.py` into manager-owned functions with
their existing async/cancellable behavior. The local command flow must call
`register_local_command`, show descriptor details, then show none/conflict
confirmation. Add all English/Chinese keys before rendering them.

Change argparse from `datasets` subparsers to:

```python
dataset = subparsers.add_parser("dataset", ...)
dataset_subparsers = dataset.add_subparsers(dest="dataset_command")
dataset_subparsers.add_parser("list", ...)
```

No subcommand dispatches `run_dataset_manager`; `list` calls a local-only
formatter over `service.registrations()`.

- [ ] **Step 4: Run focused manager, CLI, and input tests**

Run: `uv run pytest tests/test_dataset_manager.py tests/test_cli.py tests/test_tui_input.py -q`

Expected: PASS.

- [ ] **Step 5: Commit Manager UX and commands**

```bash
git add src/ccusage_viz/datasets/manager.py src/ccusage_viz/cli.py \
  src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py \
  tests/test_cli.py tests/test_dataset_manager.py
git commit -m "feat: add dataset manager"
```

## Task 6: Restrict Dashboard Dataset Selection to Registered Capabilities

**Files:**
- Modify: `src/ccusage_viz/tui.py`
- Modify: `src/ccusage_viz/configuration.py`
- Modify: `src/ccusage_viz/options.py`
- Test: `tests/test_tui_dashboard.py`
- Test: `tests/test_options.py`

**Interfaces:**
- Produces `DatasetService.ready_registered_sources() -> tuple[RegisteredDatasetSource, ...]`.
- Produces `_choose_registered_dataset_pane_config(...) -> CustomChartPaneConfig | None`.
- Consumes descriptor `capabilities.charts` to determine the sole valid chart chooser rows.

- [ ] **Step 1: Add failing Dashboard chooser tests**

```python
def test_dashboard_dataset_picker_lists_only_ready_registered_records(monkeypatch) -> None:
    service = FakeDatasetService([ready_local("weread"), disabled_local("old")])
    frames = drive_dataset_picker(service, keys=("\r", "\x1b"))
    assert any("weread" in frame for frame in frames)
    assert not any("old" in frame for frame in frames)

def test_dashboard_picker_filters_chart_kinds_from_snapshot(monkeypatch) -> None:
    service = FakeDatasetService([ready_local("build-cost", charts=("timeline",))])
    frames = drive_dataset_picker(service, keys=("\r", "\x1b"))
    assert any("Timeline" in frame for frame in frames)
    assert not any("Calendar" in frame for frame in frames)
```

- [ ] **Step 2: Run Dashboard tests and verify failure**

Run: `uv run pytest tests/test_tui_dashboard.py tests/test_options.py -q`

Expected: FAIL because the chooser still lists local command, official browse, and GitHub installation options and `_DATASET_VIEW_KINDS` is fixed.

- [ ] **Step 3: Replace source selection with record selection**

Remove the three source entries from `_choose_dataset_pane_config()` and its
nonblocking modal equivalent. Fetch only `ready_registered_sources()` and render
localized descriptor title/metric. On selection, construct `CustomCommandSource`
from the resolved registration, then render chart choices from
`tuple(descriptor.capabilities.charts)`. Preserve the existing startup runtime
sequence: probe, `apply_custom_probe_defaults`, then chart. Ensure record
selection never exposes managed command argv.

- [ ] **Step 4: Run Dashboard, custom pane, and full option regression tests**

Run: `uv run pytest tests/test_tui_dashboard.py tests/test_tui_custom.py tests/test_options.py -q`

Expected: PASS.

- [ ] **Step 5: Commit Dashboard consumption boundary**

```bash
git add src/ccusage_viz/tui.py src/ccusage_viz/configuration.py \
  src/ccusage_viz/options.py tests/test_tui_dashboard.py tests/test_options.py
git commit -m "feat: select registered datasets in dashboard"
```

## Task 7: Documentation, Local Acceptance, and Full Verification

**Files:**
- Modify: `docs/custom-command-protocol.md`
- Modify: `docs/custom-command-protocol.zh-CN.md`
- Modify: `docs/usage.md`
- Modify: `docs/usage.zh-CN.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Test: `tests/test_application.py`

**Interfaces:**
- Documents probe discovery without host-provided IDs, `ccuv dataset`, registered-only Dashboard selection, manifest static probe, and catalog summary.

- [ ] **Step 1: Write documentation-facing regression assertions**

```python
def test_dataset_help_exposes_only_manager_and_list() -> None:
    parser = build_parser(load_translator("en"))
    with pytest.raises(SystemExit):
        parser.parse_args(["dataset", "--help"])
```

Add assertions that now-invalid `dataset install`, `dataset remove`, and `datasets` forms use the normal parser error route.

- [ ] **Step 2: Run CLI/application tests and verify expected documentation surface**

Run: `uv run pytest tests/test_cli.py tests/test_application.py -q`

Expected: PASS after updating help expectations; no legacy command is silently accepted.

- [ ] **Step 3: Update bilingual guides**

Document exactly these flows:

```text
ccuv dataset
-> Register local command
-> probe discovers the Dataset ID
-> inspect or replace conflict
-> Dashboard -> Datasets -> registered Dataset -> supported chart
```

Document the static manifest probe representation and catalog `summary` role.
State that no secrets are stored and that local removal preserves external files.
Remove examples that require `--dataset ID` alongside an arbitrary `--command`.

- [ ] **Step 4: Run full Python quality gate and local acceptance**

Run:

```bash
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
git diff --check
```

Then manually run the local WeRead command through `ccuv dataset`, register it,
attempt the same registration and exercise Cancel/Replace, create a Dashboard
Ranking Pane, verify `1y / book / top=10`, disable/re-enable, and remove it.
Do not publish, push, tag, or modify the official catalog.

- [ ] **Step 5: Commit docs and final tests**

```bash
git add docs/custom-command-protocol.md docs/custom-command-protocol.zh-CN.md \
  docs/usage.md docs/usage.zh-CN.md README.md README.zh-CN.md \
  tests/test_application.py tests/test_cli.py
git commit -m "docs: document managed datasets"
```

## Self-Review

- **Spec coverage:** Task 1 covers discovery probe semantics; Task 2 covers v1 static record structures; Task 3 covers local registration, refresh, enable/disable, conflict, and removal; Task 4 covers manifest/catalog/WeRead contracts; Task 5 covers Manager UI and public CLI; Task 6 covers Dashboard registered-record selection and capability-limited chart choice; Task 7 covers documentation and the requested local acceptance sequence.
- **Placeholder scan:** No `TODO`, `TBD`, or deferred implementation markers are used as instructions; remote release/catalog publication is explicitly excluded.
- **Type consistency:** Discovery probe returns `CustomProbeResponse.dataset_id`; `DatasetService` turns it into an ID-bound `CustomCommandSource`; Dashboard consumes only that registered source plus the persisted descriptor capabilities.
