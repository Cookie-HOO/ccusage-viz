# Known issues

[简体中文](known-issues.zh-CN.md)

This page tracks known behavior in supported `ccusage-viz` and `ccusage`
combinations. Update or remove an entry when the relevant upstream behavior
changes.

## Dashboard may become unresponsive after running for a while

### Symptoms and scope

After the Dashboard has been running for some time, keyboard input and refreshes
may stop responding. The terminal may need to be closed and reopened before the
Dashboard can be used again.

### Recovery

Close the affected terminal, open a new terminal session, and start the Dashboard
again. If possible, record how long it ran, the Dashboard layout, refresh or
sampling intervals, and any sanitized output before reopening it.

## Active Monitor observations can temporarily disappear and later resume

### Symptoms and scope

Monitor derives current throughput from compatible pairs of cumulative samples. After
an initial sample, a pause or resume, a long scheduling or sleep gap, a Monitor scope
change, or an invalid or reset interval, the current observation or ranking may
briefly show no data. A later compatible sample pair can restore the observation.

### What this means

This is intentional protection against fabricating a rate across unobserved time or
a different data scope. Monitor establishes a fresh baseline and waits for a later
compatible sample before showing current values again. Retained compatible history
may remain, but this behavior does not guarantee that every historical bucket remains
available indefinitely.

### Recovery

Wait for enough scheduled samples to establish a baseline and then a compatible pair.
In an interactive view, press `r` to request a manual refresh. Confirm that `ccusage`
and the source Agent are functioning normally. Restart the Monitor or Dashboard only
if the observation does not recover after subsequent samples.

### Reporting safely

If the behavior persists, include the `ccusage-viz` and `ccusage` versions, operating
system, command shape, sampling interval, whether the observation resumed, and only
sanitized diagnostics. Remove local paths, usernames, tokens, cookies, account data,
and other private identifiers from output before sharing it.

## Intermittent `unified_daily` local-agent-database access failure

### Symptoms and scope

Charts, Dashboard panes, and Monitor samples that depend on `unified_daily` can
occasionally fail when `ccusage` cannot read a local Agent database. The failure
is not reliably reproducible, and a later refresh can succeed without changing
configuration.

### What this means

The owning Agent may be initializing, restarting, upgrading, rotating data, or
holding a database lock. In those situations, `ccusage` may temporarily be
unable to open or read its local database.

This is an upstream/local-state availability condition. It is not evidence that
`ccusage-viz` created or corrupted a second usage database.

### Recovery

1. Wait for the next configured refresh and check whether it succeeds.
2. In an interactive view, press `r` to request a manual refresh.
3. Confirm that the Agent which owns the local database is running normally.
4. If the failure persists or becomes reproducible, update `ccusage` and the
   relevant Agent, then report the issue with the information below.

### Reporting safely

Error output can include local paths or other private diagnostic details. Before
filing an issue, remove paths, usernames, tokens, cookies, account data, and
other private identifiers from any stderr or logs.

Include the `ccusage-viz` version, `ccusage` version, operating system, command
shape, whether a later retry succeeded, and only sanitized diagnostic output.
Use the [bug report form](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=bug_report.yml)
for persistent or reproducible cases.
