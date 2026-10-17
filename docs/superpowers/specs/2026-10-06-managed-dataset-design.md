# Managed Dataset Design

**Status:** proposed

**Date:** 2026-10-06

## Goal

Make a Dataset a user-managed, durable source that Dashboard can consume without
also becoming an installer or command editor. The first implementation must make
local command registration usable end to end; it must also establish the shared
manager flows and records which official and GitHub sources will use when their
release/catalog work is ready.

The public command surface is intentionally small:

```text
ccuv dataset
ccuv dataset list
```

`ccuv dataset` opens the Dataset Manager TUI. `ccuv dataset list` prints its
registered-record overview without fetching a catalog or executing a Dataset.
The existing `datasets` command surface is superseded by this product surface as
the implementation migrates its source-specific operations into the manager.

## Product Boundaries

A managed Dataset is one current registration keyed by the Dataset's canonical
`dataset_id`. A registration has exactly one current source:

1. a signed official catalog artifact;
2. a discovered GitHub repository release; or
3. a local command argv.

The Dataset Manager owns source registration, installation, probe snapshots,
availability, enabling, disabling, replacement, and removal. Dashboard owns
Pane creation and chart selection. Dashboard never shows a local-command editor,
official catalog browser, or GitHub installer.

An unmanaged one-shot command remains valid for development, but it no longer
asks the user for a Dataset ID. It probes the command first to discover its ID
and descriptor:

```text
ccuv chart timeline --command 'my-reader ccuv'
```

## Dataset Manager TUI

The default screen is a compact list grouped by state, in the same terminal
vocabulary as ccuv Dashboard: stable rows, `j`/`k` focus, a title/status region,
and a concise control footer. It does not use an application-management or
card-based visual style.

```text
ccuv - Datasets  3 registered
Last refresh: 2 minutes ago

Ready
> WeRead             0.1.0      official
  Build cost          0.4.2      local command

Needs attention
  GitHub Activity     0.2.0      setup required

Disabled
  Legacy metrics      0.1.1      GitHub

j/k select · i details · + add · r refresh · d disable · x remove · q quit
```

All host strings have English and Simplified Chinese translations. A running
screen selects exactly one language through the existing `Translator`; it does
not mix translations.

Keys:

- `j`/`k`: select a record.
- `i`: toggle a fixed details region while retaining the list. The compact list
  is the default; narrow terminals keep details collapsed.
- `+`: add a Dataset. `n`/`N` remain Dashboard Pane insertion keys, `a` remains
  available to Dashboard adjustment flows, and `+` is isolated from those
  contexts.
- `r`: explicitly refresh all enabled registered Datasets.
- `d`: disable an enabled Dataset or enable a disabled Dataset.
- `x`: remove a Dataset only after confirmation.
- `q`: leave the manager.

Details use the last successful descriptor snapshot and provenance, for example:

```text
WeRead
Ready · Official · v0.1.0

Daily reading time from your WeRead activity.
Minutes · Asia/Shanghai

Supports
Timeline · Calendar · Stack · Ranking

Environment
WEREAD_API_KEY · present

Source
Cookie-HOO/ccuv-dataset-weread
Last refreshed 2 minutes ago
```

## Add Sources

`+` opens a source chooser. All three entries are product capabilities and carry
no development-stage labels:

```text
> Browse official datasets...
  Install from GitHub repository...
  Register local command...
```

The chooser reuses and moves the existing Dashboard source flows rather than
copying their archive validation, catalog fetching, GitHub discovery, command
editing, and confirmation logic into a second implementation.

### Official Source

The manager fetches and verifies the signed official catalog only after the user
chooses this source. Its list rows show a localized title and a terse localized
`summary`, so users can understand a candidate before downloading an archive.
Selecting an entry resolves the artifact for the current OS/architecture,
downloads it to a staging directory, verifies size, SHA-256, archive layout, and
manifest, then displays manifest-descriptor details before confirmation. The
manager probes the staged executable after confirmation and commits only if the
probe and manifest agree.

If the catalog is unavailable, invalid, expired, or has no artifact for the
current platform, the corresponding source flow shows the existing localized
failure/empty state. The source chooser itself remains unchanged.

### GitHub Source

The user enters `OWNER/REPOSITORY` or a canonical `https://github.com/OWNER/REPOSITORY`
URL. Arbitrary asset URLs are not accepted. The manager discovers the latest
stable release, requires one current-platform archive and a GitHub digest or
supported checksum asset, and applies the same staging, manifest, probe, and
confirmation rules as official installation.

Before GitHub discovery, the manager checks the verified official catalog. When
the repository matches a catalog entry, it follows the catalog artifact and
records the source as `official`; a pasted official repository link must not
create a separate GitHub registration.

### Local Command Source

The local command editor has a single command argv field. The user enters a
human command string; ccuv parses it with `shlex.split` and never runs a shell.
There is no Dataset ID input. The manager runs a metadata-only probe to discover
the command's declared `dataset_id` and descriptor, then shows the same
descriptor details before registration confirmation.

No local binary is copied, moved, upgraded, or removed by ccuv.

## Registration and Conflict Rules

Each source follows this logical sequence:

```text
resolve source
-> obtain canonical dataset_id and descriptor
-> present candidate details
-> confirm source registration/installation
-> detect record conflict
-> create, leave unchanged, or replace atomically
```

Canonical identity comes from:

- a local command's probe response `dataset_id`;
- an official/GitHub archive manifest descriptor `dataset_id`, confirmed by the
  staged executable's probe response.

When a record with the same ID already exists:

- the same source and immutable release/argv identity is a no-op; the manager
  reports that it is already registered;
- a different source, command, or release opens a conflict choice:

```text
Dataset "weread" is already registered.

> Cancel
  Replace existing registration
```

- replacing a local command changes only ccuv's registration record;
- replacing an installed source stages, validates, and probes the candidate
  first; only then does it atomically activate the new artifact and remove the
  prior ccuv-managed artifact;
- cancellation preserves both the predecessor and candidate-free state.

There is deliberately no "choose another ID" action. A Dataset ID is its
canonical registration slot, not a user-created alias. This lets a local test
command naturally replace a later official or GitHub release with the same ID.

## Probe Protocol

The current protocol places `dataset_id` in the request and requires a response
to echo it. Managed discovery changes only probe identity ownership:

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "probe-request-id",
  "request_kind": "probe"
}
```

The probe response retains the existing outer field location, but its
`dataset_id` is the Dataset's required declaration:

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "probe-request-id",
  "request_kind": "probe",
  "dataset_id": "weread",
  "status": "ok",
  "descriptor": {}
}
```

Probe remains metadata-only: it must not read business data, validate
credentials, modify state, construct a business-data gateway, or make network
requests. A failed probe never creates or replaces a registration.

Once an ID has been discovered, ccuv uses it internally for the Provider ref,
request coalescing, copied command identity, one-source-per-ID Dashboard rule,
and Header summary deduplication. Chart and summary requests may carry that ID
as host context, but their responses are not required to echo or match a
host-supplied ID. `request_id`, `request_kind`, process ownership, and lifecycle
generation remain the response association checks.

## Manifest

`ccuv.dataset/v1` makes `manifest.json` the static form of a probe response, so
the manager can show Dataset identity, description, units, capabilities,
defaults, and environment declarations before it executes the binary.

```json
{
  "schema": "ccuv.dataset/v1",
  "protocol": "ccuv.custom/v1",
  "entrypoint": "bin/ccuv-dataset-weread",
  "platform": { "os": "darwin", "arch": "arm64" },
  "probe": {
    "dataset_id": "weread",
    "descriptor": {
      "revision": "weread-1",
      "version": "0.1.0",
      "source_timezone": "Asia/Shanghai",
      "dataset": {},
      "capabilities": {},
      "defaults": {},
      "environment": []
    }
  }
}
```

The staged probe must return exactly the same `dataset_id` and descriptor as the
manifest. A mismatch rejects installation. The schema stays at v1 because this
is a consolidation of existing static fields into the existing package contract,
not a separately supported package generation.

The unit in the common descriptor is retained. It determines custom chart title
and axis labels, decimal precision, prefix/suffix value formatting, custom
summary formatting, and exported data-view metadata. Chart and summary responses
remain authoritative for an individual query's effective unit; normally they
match the static descriptor.

## Descriptor Content and WeRead

The descriptor is the single static Dataset self-description shared by manifest
and probe. It includes localized title, description, unit, source timezone,
capabilities, defaults, and environment declaration. It does not contain a
catalog browsing summary, credentials, secret values, business data, or stderr.

For WeRead, update the descriptor description to:

```text
en: Daily reading time from your WeRead activity. Ranking can show supported periods by book or category.
zh-CN: 基于微信读书活动统计每日阅读时长；在支持的周期内，排行可按书籍或分类查看。
```

Its environment declaration should make the acquisition path actionable without
exposing credentials:

```text
en: Follow the authorization instructions in weread-skills, then export WEREAD_API_KEY in the shell that starts ccuv.
zh-CN: 请先按 weread-skills 的授权说明获取凭据，再在启动 ccuv 的 Shell 中导出 WEREAD_API_KEY。
help_url: https://weread.qq.com/r/weread-skills
```

## Official Catalog

The signed catalog remains a discovery/trust index. Each official entry includes
a localized title and a localized one-line `summary`, repository identity, and
current platform artifacts. It does not duplicate the full descriptor.

```json
{
  "id": "weread",
  "title": { "en": "WeRead", "zh-CN": "微信读书" },
  "summary": {
    "en": "Visualize your WeRead reading time and book activity.",
    "zh-CN": "将微信读书的阅读时长和书籍活动可视化。"
  },
  "repository": "Cookie-HOO/ccuv-dataset-weread",
  "artifacts": []
}
```

Catalog `summary` is solely for the pre-download browse list. The manifest/probe
descriptor description explains the installed Dataset's actual metric and
capabilities. The catalog remains protected by the existing fixed URL, pinned
public key, RFC 8785 canonical JSON, Ed25519 signature, and expiry validation.

## Persistent State

Use the existing per-user Dataset state root. Store registration metadata
separately from ccuv-managed downloaded artifact versions. One minimal record per
canonical Dataset ID contains:

```text
schema
dataset_id
source_kind: local | official | github
enabled
created_at
updated_at

provenance:
  local: command argv
  official/github: repository, release tag, asset, hashes and managed path

last successful probe snapshot:
  dataset_id, descriptor, refreshed_at

health metadata:
  last non-sensitive probe diagnostic
  discovered available version for managed remote sources, if known
```

Availability is derived, not blindly trusted from a stale flag:

- `ready`: enabled source resolves and required declared environment names are
  present;
- `setup_required`: enabled source is intact but a required environment name is
  absent;
- `unavailable`: enabled source cannot resolve or its last explicit refresh
  failed;
- `disabled`: explicit user state; it is never probed or shown in Dashboard;
- removal deletes the record entirely.

Persist neither environment values, credentials, stderr, query responses,
business data, chart data, Dashboard layouts, nor raw protocol stdout.

`r` re-probes every enabled record. It refreshes a successful descriptor snapshot
and remote version availability without auto-updating. A failure retains the last
successful snapshot and surfaces a localized warning such as "WeRead capability
probe failed: <reason>"; the record becomes unavailable until a later successful
refresh. The manager does not background-poll Datasets.

`d` toggles enabled state. `x` requires confirmation and deletes only ccuv-owned
state: it preserves a local target command/binary, while it removes downloaded
official/GitHub artifacts after the record is removed.

## Dashboard Consumption

Dashboard's existing Datasets branch is narrowed to registered, enabled, ready
records. It does not have source-installation entries.

```text
Datasets

> WeRead              Reading time · minutes       ready
  Build cost           Build cost · USD             ready
```

After selecting a Dataset, Dashboard shows only chart types declared by that
record's last successful probe snapshot:

```text
WeRead · Choose chart

> Timeline
  Calendar
  Stack
  Ranking
```

This list is not a hard-coded four-item list. A Dataset which declares only
Timeline exposes only Timeline. Disabled, setup-required, unavailable, corrupt,
or descriptor-less records cannot create a Pane.

Pane creation preserves the existing initial runtime sequence:

```text
probe -> apply Dataset defaults -> chart
```

The latest probe snapshot filters choices before a Pane is created; its runtime
probe and chart response remain authoritative. WeRead Ranking therefore keeps
its declared `1y`, `book`, and `top=10` defaults.

## Acceptance

Before any WeRead release or catalog publication, verify locally with the
existing WeRead binary:

1. Register a local command successfully.
2. Register a local command whose probe returns the same `dataset_id`; choose
   Cancel or Replace and observe the correct result.
3. Browse all registered records in the Dataset Manager and inspect details.
4. Add a Dashboard Dataset Pane from a registered record, select only supported
   chart types, and observe the selected type's defaults.
5. Disable a registered command, re-enable it in the manager, and delete it.
   Deleting a local command must not delete its local target file.

No WeRead artifact, official catalog entry, GitHub release, or remote repository
publication is part of this implementation/acceptance step.
