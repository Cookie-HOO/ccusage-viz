# WeRead Dataset Release Protocol Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild and prevent regression of WeRead Dataset release archives so current ccuv can register them through the `ccuv.custom/v2` protocol.

**Architecture:** Keep the existing V2 Dataset implementation unchanged. Extend archive verification from tar topology to strict V2 static-Probe manifest validation, then add a native-package acceptance command that executes the packaged binary's V2 Probe. Regenerate all WeRead repository release archives and copy the verified darwin-arm64 artifact to ccuv's local Dataset fixture directory.

**Tech Stack:** Go standard library, Bash, JSON, tar/gzip archives, existing ccuv Python/pytest protocol tests.

**Spec:** `docs/superpowers/specs/2026-10-10-weread-release-protocol-design.md`

## Global Constraints

- Require `schema: "ccuv.dataset/v1"` and `protocol: "ccuv.custom/v2"` in every generated WeRead manifest.
- Keep archive contents exactly `manifest.json` plus its declared executable.
- Do not require `WEREAD_API_KEY` for Probe/package validation.
- Build the release matrix exactly for `darwin/arm64`, `darwin/amd64`, `linux/amd64`, and `windows/amd64`.
- Do not change WeRead metric meanings, API behavior, or Router Dataset behavior.
- Do not publish, tag, or push either repository.

---

## File Structure

### WeRead Dataset repository: `/Users/bytedance/Projects/go/ccuv-dataset-weread`

- `internal/packageverify/verify.go` — validate exact archive topology plus V2 static manifest and descriptor fields.
- `internal/packageverify/verify_test.go` — unit fixtures for accepting V2 manifest archives and rejecting V1/malformed static Probe archives.
- `cmd/archiveverify/main.go` — continue structural verification and expose an optional native V2 Probe check command, if retained as the one release verification entrypoint.
- `cmd/archiveverify/main_test.go` — add archive extraction/Probe round-trip coverage using an executable fixture or test helper.
- `scripts/package.sh` — call the native acceptance check only for the host-matching target.
- `scripts/package-release.sh` — rebuild all four artifacts and checksums without manual archive mutation.
- `dist/ccuv-dataset-weread-*.tar.gz`, `dist/checksums.txt` — regenerated release outputs.

### ccuv repository

- `dist/datasets/ccuv-dataset-weread-darwin-arm64.tar.gz` — copied, verified native WeRead V2 release artifact.
- `tests/test_datasets_archive.py` — assert the checked-in WeRead fixture parses/installs as a V2 static-Probe archive when existing archive fixtures support this without network access.

## Task 1: Enforce a V2 Static Probe Manifest in Archive Verification

**Files:**
- Modify: `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/packageverify/verify.go`
- Modify: `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/packageverify/verify_test.go`

**Interfaces:**
- Consumes: an archive path through `packageverify.Verify(name string) error`.
- Produces: `Verify` rejects V1 manifests and accepts only complete V2 static-Probe manifests with a valid declared entrypoint.

- [ ] **Step 1: Write failing V2-manifest tests**

Replace `validMembers()` with a full minimal valid V2 static-Probe manifest fixture:

```go
const validManifest = `{
  "schema":"ccuv.dataset/v1",
  "protocol":"ccuv.custom/v2",
  "entrypoint":"bin/ccuv-dataset-weread",
  "platform":{"os":"darwin","arch":"arm64"},
  "probe":{"dataset_id":"weread","descriptor":{
    "revision":"weread-2","version":"0.0.1","source_timezone":"Asia/Shanghai",
    "default_metric_id":"reading_time",
    "dataset":{"title":{"en":"WeRead","zh-CN":"微信读书"},"description":{"en":"Metrics","zh-CN":"指标"}},
    "metrics":[{"id":"reading_time","title":{"en":"Reading","zh-CN":"阅读"},"description":{"en":"Daily","zh-CN":"每日"},"unit":{"id":"minute","label":{"en":"minutes","zh-CN":"分钟"},"placement":"suffix","decimal_places":2},"aggregation":"sum","summary":"comparisons","capabilities":{"group_by":[],"charts":{"timeline":{"granularities":["day"],"group_by":[]}}},"defaults":{}}],
    "environment":[]
  }}
}`
```

Add tests that `Verify` rejects each independent protocol regression:

```go
func TestVerifyRejectsV1Manifest(t *testing.T) {
    members := validMembers()
    members[0].contents = strings.Replace(validManifest, `"ccuv.custom/v2"`, `"ccuv.custom/v1"`, 1)
    if err := Verify(archive(t, members)); err == nil { t.Fatal("accepted V1 manifest") }
}

func TestVerifyRejectsMissingStaticProbeDescriptor(t *testing.T) {
    members := validMembers()
    members[0].contents = strings.Replace(validManifest, `"descriptor":{`, `"descriptor_missing":{`, 1)
    if err := Verify(archive(t, members)); err == nil { t.Fatal("accepted manifest without Probe descriptor") }
}
```

Import `strings` in the test file.

- [ ] **Step 2: Verify the new cases fail under the current verifier**

Run:

```bash
cd /Users/bytedance/Projects/go/ccuv-dataset-weread
go test ./internal/packageverify -run 'TestVerifyRejects(V1Manifest|MissingStaticProbeDescriptor)' -v
```

Expected: FAIL because current `Verify` only unmarshals `entrypoint` and wrongly accepts both fixtures.

- [ ] **Step 3: Parse and validate the full V2 static manifest**

In `verify.go`, replace the anonymous entrypoint-only manifest with explicit structural types containing schema, protocol, entrypoint, platform, and `probe.dataset_id` / `probe.descriptor`. Require all of the following before topology validation succeeds:

```go
manifest.Schema == "ccuv.dataset/v1"
manifest.Protocol == "ccuv.custom/v2"
manifest.Entrypoint != ""
manifest.Platform.OS != "" && manifest.Platform.Arch != ""
manifest.Probe.DatasetID == "weread"
len(manifest.Probe.Descriptor.Metrics) > 0
```

Reuse the Dataset protocol package types and parser where possible. If package imports would create a dependency cycle, define a narrow JSON validation helper in `packageverify` that verifies required V2 descriptor fields (`revision`, `version`, bilingual dataset title/description, non-empty metrics, each metric ID/title/description/unit/aggregation/capabilities/defaults, and `environment`) and rejects unknown/missing Probe envelope fields. Do not accept V1 fallback shapes.

Return specific errors beginning with `invalid V2 manifest` for schema/protocol/static-Probe failures.

- [ ] **Step 4: Run package verifier unit tests**

Run:

```bash
cd /Users/bytedance/Projects/go/ccuv-dataset-weread
go test ./internal/packageverify -v
```

Expected: PASS. `TestVerifyValidArchive` passes with the V2 fixture; V1 and missing-descriptor fixtures fail verification.

- [ ] **Step 5: Commit the verifier contract**

```bash
cd /Users/bytedance/Projects/go/ccuv-dataset-weread
git add internal/packageverify/verify.go internal/packageverify/verify_test.go
git commit -m "fix: require v2 manifest in dataset archives"
```

## Task 2: Validate the Native Packaged Binary's V2 Probe

**Files:**
- Modify: `/Users/bytedance/Projects/go/ccuv-dataset-weread/cmd/archiveverify/main.go`
- Create: `/Users/bytedance/Projects/go/ccuv-dataset-weread/cmd/archiveverify/main_test.go`
- Modify: `/Users/bytedance/Projects/go/ccuv-dataset-weread/scripts/package.sh`

**Interfaces:**
- Consumes: `archiveverify ARCHIVE --probe` for a host-runnable archive.
- Produces: exit status zero only if the archive passes `packageverify.Verify`, its entrypoint runs with `ccuv`, and a V2 Probe response matches the static manifest's Dataset ID and descriptor.

- [ ] **Step 1: Write a failing native-Probe acceptance test**

Add a test-only helper in `cmd/archiveverify/main_test.go` that creates an executable shell fixture and packages it with a valid manifest. The fixture must emit the request-correlated V2 Probe response:

```sh
#!/bin/sh
read request
printf '%s\n' '{"protocol":"ccuv.custom/v2","request_id":"package-probe","request_kind":"probe","dataset_id":"weread","status":"ok","descriptor": ... }'
```

Use the same `validManifest` descriptor fixture as Task 1. Test an `acceptProbe(archive string) error` helper:

```go
func TestAcceptProbeRejectsMismatchedDatasetID(t *testing.T) {
    archive := archiveWithProbeExecutable(t, `"dataset_id":"wrong"`)
    if err := acceptProbe(archive); err == nil { t.Fatal("accepted mismatched Probe Dataset ID") }
}
```

Also test a valid V2 archive succeeds. Keep the helper unexported in the command package.

- [ ] **Step 2: Verify the command test fails before implementation**

Run:

```bash
cd /Users/bytedance/Projects/go/ccuv-dataset-weread
go test ./cmd/archiveverify -run TestAcceptProbe -v
```

Expected: FAIL because `acceptProbe` does not exist.

- [ ] **Step 3: Implement safe archive extraction and Probe comparison**

Implement `acceptProbe(archive string) error` in `cmd/archiveverify/main.go`:

1. Call `packageverify.Verify(archive)`.
2. Read the archive manifest to obtain `entrypoint`, `probe.dataset_id`, and its raw descriptor.
3. Extract exactly `manifest.json` and the declared executable to `os.MkdirTemp`; preserve executable mode; defer cleanup.
4. Execute the extracted entrypoint with argument `ccuv`, write exactly:

```json
{"protocol":"ccuv.custom/v2","request_id":"package-probe","request_kind":"probe"}
```

5. Reject non-zero exit, malformed JSON, non-`ok` status, mismatched protocol/request identity, mismatched dataset ID, or a descriptor JSON value unequal to manifest `probe.descriptor` after decoding both into `any`.

Add flag parsing with `--probe`:

```go
probe := flag.Bool("probe", false, "execute the packaged V2 Probe")
flag.Parse()
if flag.NArg() != 1 { /* existing usage and exit 2 */ }
if *probe { err = acceptProbe(flag.Arg(0)) } else { err = packageverify.Verify(flag.Arg(0)) }
```

Keep normal archive verification behavior and SHA-256 output unchanged when `--probe` is absent.

- [ ] **Step 4: Invoke native Probe acceptance only for the build host target**

After the existing `go run ./cmd/archiveverify "$out"` in `scripts/package.sh`, append:

```sh
host_os=$(go env GOOS)
host_arch=$(go env GOARCH)
if [ "$target_os" = "$host_os" ] && [ "$target_arch" = "$host_arch" ]; then
  go run ./cmd/archiveverify --probe "$out"
fi
```

This ensures cross-compiled archives receive static validation while the native artifact receives an executable V2 protocol check.

- [ ] **Step 5: Run command and package tests**

Run:

```bash
cd /Users/bytedance/Projects/go/ccuv-dataset-weread
go test ./cmd/archiveverify ./cmd/ccuv-dataset-weread ./internal/dataset -v
./scripts/package.sh darwin arm64 /tmp/ccuv-dataset-weread-darwin-arm64.tar.gz
```

Expected: PASS. The package script prints a digest from structural verification and succeeds through the native Probe check without `WEREAD_API_KEY`.

- [ ] **Step 6: Commit release acceptance coverage**

```bash
cd /Users/bytedance/Projects/go/ccuv-dataset-weread
git add cmd/archiveverify/main.go cmd/archiveverify/main_test.go scripts/package.sh
git commit -m "test: probe packaged weread dataset"
```

## Task 3: Produce and Validate Every WeRead Release Artifact

**Files:**
- Modify: `/Users/bytedance/Projects/go/ccuv-dataset-weread/dist/ccuv-dataset-weread-darwin-arm64.tar.gz`
- Modify: `/Users/bytedance/Projects/go/ccuv-dataset-weread/dist/ccuv-dataset-weread-darwin-amd64.tar.gz`
- Modify: `/Users/bytedance/Projects/go/ccuv-dataset-weread/dist/ccuv-dataset-weread-linux-amd64.tar.gz`
- Modify: `/Users/bytedance/Projects/go/ccuv-dataset-weread/dist/ccuv-dataset-weread-windows-amd64.tar.gz`
- Modify: `/Users/bytedance/Projects/go/ccuv-dataset-weread/dist/checksums.txt`

**Interfaces:**
- Consumes: `scripts/package-release.sh` and Task 1/2 validation.
- Produces: four V2 release archives and matching SHA-256 checksums.

- [ ] **Step 1: Build the release matrix**

Run:

```bash
cd /Users/bytedance/Projects/go/ccuv-dataset-weread
./scripts/package-release.sh
```

Expected: four archives are recreated and `checksums.txt` is regenerated. The host-native archive also completes the V2 Probe acceptance check.

- [ ] **Step 2: Inspect every manifest protocol and checksum coverage**

Run:

```bash
cd /Users/bytedance/Projects/go/ccuv-dataset-weread
for archive in dist/ccuv-dataset-weread-*.tar.gz; do
  temp=$(mktemp -d)
  tar -xzf "$archive" -C "$temp"
  jq -e '.schema == "ccuv.dataset/v1" and .protocol == "ccuv.custom/v2" and .probe.dataset_id == "weread"' "$temp/manifest.json"
  rm -rf "$temp"
done
shasum -a 256 -c dist/checksums.txt
```

Expected: every `jq` command exits zero and all checksum entries report `OK`.

- [ ] **Step 3: Smoke-test the just-built native archive directly**

Run:

```bash
cd /Users/bytedance/Projects/go/ccuv-dataset-weread
temp=$(mktemp -d)
tar -xzf dist/ccuv-dataset-weread-darwin-arm64.tar.gz -C "$temp"
printf '%s\n' '{"protocol":"ccuv.custom/v2","request_id":"release-probe","request_kind":"probe"}' \
  | "$temp/bin/ccuv-dataset-weread" ccuv \
  | jq -e '.protocol == "ccuv.custom/v2" and .dataset_id == "weread" and .status == "ok" and (.descriptor.metrics | length == 2)'
rm -rf "$temp"
```

Expected: `true`; no credentials or API calls are needed.

- [ ] **Step 4: Run the complete WeRead test suite**

Run:

```bash
cd /Users/bytedance/Projects/go/ccuv-dataset-weread
go test ./...
```

Expected: PASS.

- [ ] **Step 5: Commit rebuilt release artifacts**

```bash
cd /Users/bytedance/Projects/go/ccuv-dataset-weread
git add dist/ccuv-dataset-weread-darwin-arm64.tar.gz \
  dist/ccuv-dataset-weread-darwin-amd64.tar.gz \
  dist/ccuv-dataset-weread-linux-amd64.tar.gz \
  dist/ccuv-dataset-weread-windows-amd64.tar.gz dist/checksums.txt
git commit -m "fix: rebuild weread v2 dataset archives"
```

## Task 4: Refresh ccuv's Local Managed-Dataset Fixture

**Files:**
- Modify: `dist/datasets/ccuv-dataset-weread-darwin-arm64.tar.gz`
- Modify: `tests/test_datasets_archive.py`

**Interfaces:**
- Consumes: WeRead `dist/ccuv-dataset-weread-darwin-arm64.tar.gz` from Task 3.
- Produces: ccuv's local WeRead fixture is a current V2 archive and is verified by the same Dataset archive parser used for managed installation.

- [ ] **Step 1: Write a failing fixture contract test**

In `tests/test_datasets_archive.py`, add a test that reads the checked-in fixture with `tarfile`, parses `manifest.json` using `DatasetManifest.parse`, and asserts its V2 identity:

```python
def test_checked_in_weread_archive_is_a_v2_static_probe_fixture() -> None:
    fixture = Path("dist/datasets/ccuv-dataset-weread-darwin-arm64.tar.gz")
    with tarfile.open(fixture, "r:gz") as archive:
        manifest_member = archive.getmember("manifest.json")
        payload = json.loads(archive.extractfile(manifest_member).read())
    manifest = DatasetManifest.parse(payload)
    assert manifest.protocol == CUSTOM_V2_PROTOCOL
    assert manifest.probe_dataset_id == "weread"
    assert manifest.descriptor is not None
    assert {metric.id for metric in manifest.descriptor.metrics} == {"reading_time", "total_notes"}
```

Use the existing imports/constants in that test module; add only `json`, `tarfile`, and `Path` imports if absent.

- [ ] **Step 2: Verify the test reflects the existing fixture deliberately**

Run:

```bash
uv run pytest tests/test_datasets_archive.py::test_checked_in_weread_archive_is_a_v2_static_probe_fixture -q
```

Expected: PASS if the current main-repository fixture is already V2. This test protects the artifact from being replaced later by the stale WeRead-repository V1 archive.

- [ ] **Step 3: Copy the verified native release artifact into ccuv**

Run:

```bash
cp /Users/bytedance/Projects/go/ccuv-dataset-weread/dist/ccuv-dataset-weread-darwin-arm64.tar.gz \
  dist/datasets/ccuv-dataset-weread-darwin-arm64.tar.gz
```

Do not copy release checksums into ccuv; this repository maintains only the local archive fixture.

- [ ] **Step 4: Run ccuv Dataset integration coverage**

Run:

```bash
uv run pytest tests/test_custom_protocol.py tests/test_datasets_models.py tests/test_datasets_archive.py tests/test_datasets_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the ccuv fixture and regression test**

```bash
git add dist/datasets/ccuv-dataset-weread-darwin-arm64.tar.gz tests/test_datasets_archive.py
git commit -m "test: verify weread dataset archive fixture"
```

## Final Verification

- [ ] **Step 1: Confirm no stale V1 WeRead release manifests remain**

```bash
cd /Users/bytedance/Projects/go/ccuv-dataset-weread
for archive in dist/ccuv-dataset-weread-*.tar.gz; do
  temp=$(mktemp -d)
  tar -xzf "$archive" -C "$temp"
  jq -e '.protocol == "ccuv.custom/v2"' "$temp/manifest.json"
  rm -rf "$temp"
done
```

Expected: four `true` lines.

- [ ] **Step 2: Confirm worktree scopes before handoff**

Run:

```bash
git status --short
cd /Users/bytedance/Projects/go/ccuv-dataset-weread && git status --short
```

Expected: only the committed repair changes in their respective repositories; preserve pre-existing uncommitted changes in the ccuv main repository and Router repository.

## Plan Self-Review

- **Spec coverage:** Task 1 rejects stale V1 release manifests; Task 2 validates a host-runnable packaged binary's V2 Probe without credentials; Task 3 regenerates all four release artifacts and checksums; Task 4 refreshes/protects ccuv's local native fixture. Router and WeRead metric semantics remain untouched.
- **Placeholder scan:** No TBD/TODO or deferred implementation steps remain.
- **Type consistency:** `packageverify.Verify`, `acceptProbe`, `DatasetManifest.parse`, `CUSTOM_V2_PROTOCOL`, and the archive paths are used consistently across all tasks.
