# WeRead Dataset Release Protocol Repair

## Goal

Ensure every distributable WeRead Dataset archive is compatible with current ccuv `ccuv.custom/v2` Dataset registration and query protocols, eliminating the stale V1 release artifact that currently fails when ccuv sends a V2 Probe.

## Context

The WeRead source repository at `/Users/bytedance/Projects/go/ccuv-dataset-weread` already implements the V2 Probe and V2 query-snapshot contract. Its source binary accepts a Probe with `protocol: "ccuv.custom/v2"` and successful chart responses add a complete `descriptor` plus `runtime: {"filters": []}`.

However, the repository's existing `dist/ccuv-dataset-weread-*.tar.gz` release archives were made before that migration. The darwin-arm64 archive declares `ccuv.custom/v1` and includes a V1 executable, so it rejects a V2 Probe with `invalid_request`. The V2 source and stale V1 distribution artifact diverged.

## Scope

- Rebuild the four existing WeRead release archives for darwin/arm64, darwin/amd64, linux/amd64, and windows/amd64 from the current V2 source.
- Regenerate `dist/checksums.txt` from those rebuilt archives.
- Strengthen release archive verification so it validates the manifest's V2 static Probe contract, not only tar layout.
- Add a package integration check that runs the packaged executable's V2 Probe when the archive target is runnable on the build host, and validates the successful chart snapshot shape using an in-process fake gateway where network credentials are not needed.
- Replace the ccuv main-repository local fixture `dist/datasets/ccuv-dataset-weread-darwin-arm64.tar.gz` with the rebuilt darwin-arm64 archive.

## Non-goals

- Do not change WeRead source metric semantics, API calls, environment setup, or current V2 descriptor content.
- Do not publish a GitHub Release, create a tag, or push either repository.
- Do not modify Router Dataset behavior or add real-time Monitor observations to Dashboard Header summaries.
- Do not require `WEREAD_API_KEY` while validating Probe or package structure.

## Design

### Package verification

`internal/packageverify` remains responsible for archive-side validation. It will parse the manifest from the tar archive as a strict `ccuv.dataset/v1` static-Probe manifest, require `protocol: "ccuv.custom/v2"`, require a valid `probe.dataset_id`, and parse the embedded descriptor with the same V2-compatible structural validation used by the Dataset implementation. It will continue checking the exact two-member archive topology and declared executable.

The verifier must reject the stale V1 archive before attempting to execute its binary. This makes protocol incompatibility a deterministic release-build failure rather than an end-user registration failure.

### Runnable archive acceptance check

The package script already creates each target archive and invokes `cmd/archiveverify`. It will additionally run the package acceptance command only when the archive target OS/architecture matches the build host. That acceptance command extracts the archive into a temporary directory, executes the declared entrypoint with `ccuv`, sends a V2 Probe, and asserts that the response has the same Dataset ID and descriptor as the static manifest.

Cross-compiled archives cannot run on the packaging machine. They receive strict static manifest/topology verification; the native archive receives the executable protocol smoke check. The Go test suite will separately test chart snapshot fields with the FakeGateway so source protocol behavior remains covered without credentials or a live WeRead API.

### Artifacts

`package-release.sh` remains the single way to produce the four release artifacts and checksums. The repository's `dist/` artifacts and ccuv's local darwin-arm64 Dataset fixture will be regenerated using this script rather than patched manually.

## Validation

1. `go test ./...` passes in the WeRead repository.
2. `scripts/package-release.sh` succeeds and validates each generated archive.
3. The rebuilt darwin-arm64 package accepts a V2 Probe and returns `dataset_id: "weread"`, `protocol: "ccuv.custom/v2"`, and the V2 descriptor.
4. A successful fake-gateway chart response retains `descriptor` and `runtime.filters` in the serialized wire response.
5. In ccuv, Dataset protocol/model/service tests pass and the copied main-repository fixture parses as a V2 managed Dataset archive.
