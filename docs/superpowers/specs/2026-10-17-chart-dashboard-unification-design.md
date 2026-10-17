# Chart-to-Dashboard Unification Design

## Goal

Remove standalone chart runtimes while retaining `ccuv chart KIND ...` as a compatible CLI surface. Every chart executes through the existing Dashboard runtime as a preconfigured one-pane Dashboard. `animate`, including `--gallery`, remains an independent provider-free runtime.

## Non-regression constraint

Existing `ccuv dashboard ...` behavior is immutable in this change: its argument parsing, defaults, lifecycle, scheduling, header behavior, rendering, interaction, and queries must not change. The only new behavior is an adapter from a parsed chart launch to a Dashboard launch.

## Command contract

`ccuv chart timeline|calendar|stack|ranking|monitor ...` retains its chart arguments and constructs a Dashboard with exactly one matching builtin or Custom Dataset Pane.

The generated host is a focused Dashboard configuration:

- one row and one column;
- `header_style="hidden"`;
- `header_summary="none"`;
- no Dashboard header summary query or lifecycle work;
- all other chart configuration is preserved in the Pane.

Historical chart `--interval` becomes the generated host's `refresh_interval`. Monitor `--interval` becomes its `sampling_interval`. Existing Dataset-owned fixed-cadence validation remains effective through the Dashboard path.

The resulting session is an ordinary Dashboard after startup: its Pane can be adjusted, inspected, copied, replaced, or expanded to multiple Panes through existing Dashboard controls. It intentionally follows Dashboard shortcuts and help rather than retaining standalone-only interaction contracts.

`--no-watch` is removed rather than emulated.

## Runtime consolidation

`application.run` dispatches all non-animation chart launches to Dashboard after adapting the launch. The standalone loops in `watch.py`, `monitor.py`, `custom_monitor.py`, and `tui.py` are removed along with their standalone-only help and tests. Shared configuration, components, render models, command formatting, data views, and Dashboard Pane helpers remain; any remaining `StandaloneLaunch` use internal to Dashboard is not renamed as part of this change.

## Testing

Tests verify:

1. Builtin historical, builtin Monitor, and Custom Dataset chart launches become equivalent one-Pane Dashboard configurations.
2. Historical and Monitor intervals map to their distinct Dashboard host cadence fields.
3. Generated focused hosts hide and disable Dashboard header work.
4. Existing Dashboard launch parsing and defaults are unchanged.
5. `animate --gallery` continues to dispatch independently.
6. Removed `--no-watch` is rejected by CLI parsing.

## Documentation

README and usage documentation describe `chart` as a focused one-Pane Dashboard shortcut. `dashboard single` remains the interactive one-Pane Dashboard starting point. `animate` remains independent, including its gallery.
