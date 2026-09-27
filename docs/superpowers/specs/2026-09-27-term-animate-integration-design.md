# Term-animate Integration Design

**Status:** Approved for implementation planning

## Purpose

Integrate the local `term-animate` library into `ccusage-viz` (ccuv) as host-owned terminal content without starting the library's standalone gallery, CLI, event loop, or keyboard handling.

The first release adds:

1. A standalone `ccuv animate [style]` command.
2. A Dashboard animation Pane declared as `--pane "animate <style>"`.
3. A `rain` animation attachment below realtime Monitor `ranking` and `list` content, which plays only while a newly accepted Monitor sample has positive token consumption.

`term-animate` will first be tested through a local editable/path dependency. Once its package is published, the local source override will be removed without changing ccuv's animation API or behavior.

## Non-goals

This release deliberately does not add:

- Dashboard Header/banner animation or logo slots.
- An animation Pane to a default Dashboard preset.
- Animation content for Monitor styles other than `ranking` and `list`.
- Persistent animation preferences, CLI flags for transient choices, configuration-file entries, or cross-process restoration.
- Invocation or duplication of `term-animate`'s gallery/CLI controls.
- Animation-library asset preparation or editing features.

## Dependency model

ccuv will depend on the `term-animate` Python package as a normal runtime dependency. During development, uv resolves that package from the sibling checkout:

```toml
[tool.uv.sources]
term-animate = { path = "../term-animate", editable = true }
```

The package requirement remains declared in normal dependencies. After publication, remove only the uv source override and lock the published compatible version.

Both projects use GPL-3.0-only, and their supported Python range includes 3.11 through 3.13.

ccuv must import only the library's host-neutral projection API. The integration must not call `term-animate`'s CLI, gallery, input functions, scheduler, or terminal-output code.

## Supported animation catalog

ccuv maintains an explicit supported catalog rather than automatically exposing all library internals:

| ccuv style | Display name | term-animate effect |
| --- | --- | --- |
| `mole-cat` | Mole Cat | `mole-cat` |
| `campy-cat` | Campy Cat | `campy-cat` |
| `rain` | Rain | `rain` |
| `analog-clock` | Analog Clock | `analog-clock` |
| `digital-clock` | Digital Clock | `digital-clock` |

The future addition of an effect to `term-animate` does not expose it in ccuv until ccuv explicitly adds it to this catalog, validates its minimum viewport behavior, and adds relevant tests.

## Architecture

Animation is not a token chart. It has no Provider query, Coverage, token-data processor, semantic chart model, or chart lifecycle. ccuv therefore adds a small host-content subsystem rather than registering it as a Chart Definition.

```text
term-animate
  Effect + ProjectionRequest
    → ProjectedFrame(styled rows, next deadline)

ccuv animation subsystem
  AnimationSpec
  AnimationSessionState
  AnimationClock
  AnimationAdapter
  AnimationRenderer
```

### AnimationSpec

An `AnimationSpec` identifies one supported animation style and its presentation constraints, including its display name and minimum viable viewport. It is immutable configuration for a newly created animation session.

### AnimationSessionState

Each visible animation instance has an isolated, in-memory state:

```text
style
animation theme
AnimationClock
next frame deadline
visibility / viewport status
```

State isolation rules:

- A standalone `ccuv animate` session has one state.
- Every Dashboard animation Pane has one state.
- Every standalone Monitor and Dashboard Monitor Pane has its own attachment state.
- Modifying a Pane never modifies another Pane.
- Theme/style changes survive a chart-style switch away from `ranking`/`list` during the same ccuv process, but are not rendered or scheduled while unavailable.
- Exiting ccuv discards all animation state.

### AnimationClock

The library projects frames from caller-supplied clocks. ccuv provides an `AnimationClock` that advances only during playback:

```text
effective_elapsed = accumulated_active_duration + (now - resumed_at)
```

The final term is included only while the clock is playing. On freeze, ccuv settles elapsed active duration and removes the frame deadline. On resume, it establishes a new `resumed_at`; it does not replay or skip frames accrued while frozen.

A session records a virtual wall-time origin. Clock effects receive:

```text
virtual_wall_time = wall_origin + effective_elapsed
```

This freezes analog/digital clock effects as completely as scene effects.

### Adapter and renderer

The adapter owns the integration boundary:

1. Build a `ProjectionRequest` from the ccuv viewport, color capability, selected animation theme, active/idle state, and effective clocks.
2. Project the selected `term-animate` effect.
3. Convert library `StyledRow`/`StyledCell` output into ccuv `Frame` rows.
4. Return converted rows and the projected next-frame deadline.

The library remains unaware of ccuv styling, dashboard composition, screen mode, input, scheduling, terminal emissions, Providers, or data.

## Standalone animation command

### CLI

```bash
ccuv animate
ccuv animate rain
ccuv animate mole-cat
ccuv animate campy-cat
ccuv animate analog-clock
ccuv animate digital-clock
```

`ccuv animate` defaults to `rain`. An unsupported style fails during parsing/validation, before entering terminal mode or initializing data services.

It dispatches to a dedicated standalone animation host. The host does not create a Provider, Chart Component, Monitor lifecycle, query scheduler, or executor task.

### Controls

All input belongs to ccuv. `term-animate` gallery controls are never active.

| Key | Behavior |
| --- | --- |
| `q`, `Esc`, `Ctrl-C` | Exit |
| `Space` | Freeze/resume the animation clock |
| `m` | Open ccuv appearance adjustment |
| Quick `t` / `T` | Cycle animation theme forward/back |
| Quick `s` | Cycle supported animation styles |
| `a` | Switch quick/advanced page; no new first-release advanced animation controls |

Theme/style changes apply immediately and only to the current standalone process.

### Small viewport behavior

An animation must not be partially rendered into unreadable fragments. When its viewport is below the supported minimum, render a static compact hint such as `rain · expand terminal to play`, and do not maintain a frame deadline. When the viewport becomes viable again, project the current effective clock frame.

## Dashboard animation Pane

### Pane syntax

An animation Pane requires an explicit style:

```bash
ccuv dashboard --pane "animate rain"
ccuv dashboard --pane "timeline --by model" --pane "animate mole-cat"
```

`--pane "animate"` is rejected. Unlike standalone, Dashboard configuration should have no implicit animation choice whose meaning could change if standalone defaults change.

No built-in Dashboard preset adds one automatically.

### Host behavior

Dashboard Pane handling is extended to support both chart panes and render-only animation panes:

```text
Chart Pane
  existing Component + scheduler + lifecycle
Animation Pane
  AnimationSessionState + local animation deadline
```

An animation Pane participates in Dashboard-owned geometry, title/border composition, focus, resize, theme, global pause, frame painting, and cleanup. It does not have a Provider, Coverage, query refresh, lifecycle submission, or executor work.

Manual Dashboard refresh (`r`) has no effect on its clock or state.

### Scheduling

The Dashboard runtime waits on the earliest relevant deadline:

```text
input polling
header refresh scheduler
chart-pane schedulers
animation-pane frame deadlines
```

On an animation deadline, ccuv reprojects and repaints the Dashboard frame. It must never call a chart `refresh`, query planner, Provider, or executor as a consequence of animation playback.

Each animation Pane owns a separate clock and deadline. When globally paused, hidden due to viewport constraints, or not viable in its current viewport, it has no active frame deadline.

### Pane controls

With an animation Pane focused, ccuv's existing Pane quick-adjustment UI maps controls to animation state:

| Page | `t` / `T` | `s` |
| --- | --- | --- |
| Quick | animation theme | animation style |
| Advanced | no first-release animation-specific options | no first-release animation-specific options |

Controls that make sense only for data charts are omitted for animation Panes. No input is delegated to `term-animate`.

Global `Space` freezes every animation Pane clock together with the existing Dashboard pause behavior. Resuming restores each clock but does not reset its style/theme or effective elapsed time.

## Monitor ranking/list attachment

### Visibility and position

The attachment appears only when all of the following hold:

- The content is a realtime Monitor.
- Its active presentation style is `ranking` or `list`.
- The Host has sufficient residual vertical and horizontal space after preserving rank/list content and normal notices/controls.

The attachment is host-composed after the renderer's ranking/list content and before status notices and controls:

```text
ranking/list heading
ranking/list rows
optional animation attachment
notices / status / controls
```

The ranking renderer remains responsible only for ranking/list content. It must not import or invoke `term-animate`.

If height is constrained, omit the attachment before reducing the core ranking/list content. State remains intact and resumes when it becomes visible again.

### Defaults and setting scope

New Monitor attachment state begins as:

```text
style = rain
theme = current monitor chart theme
```

If the animation theme is later changed, subsequent chart theme changes do not overwrite it. Chart style/theme values and animation style/theme values are distinct session state.

The state belongs to the individual Monitor standalone or Dashboard Pane, never to all Monitor instances or the Dashboard globally.

### Activity rule

After each newly accepted Monitor observation, determine activity using the exact accepted sample's total token delta in the same consumption scope Monitor uses for its incremental/ranking semantics:

```text
has_activity = accepted_total_token_delta > 0
```

| Event | Attachment behavior |
| --- | --- |
| Initial sample without a comparable delta | Render initial frozen frame |
| Accepted positive delta | Play or resume |
| Accepted zero delta | Freeze immediately |
| Pending query | Preserve the latest accepted activity state |
| Query error | Preserve the latest accepted activity state and show normal error UI |
| Discarded completion | Do not change attachment state |
| Manual refresh | Do not reset state; reevaluate only if result is accepted |
| User/host pause | Force freeze |
| Resume | Restore the latest accepted active/idle state |
| Switch away from ranking/list | Preserve state, do not render or schedule |
| Switch back | Resume if latest accepted state is active; otherwise remain frozen |

A successful request, wall-clock passage, or a list containing historical values is not evidence of new token consumption.

### Monitor controls

For `ranking` and `list` only:

| Appearance page | `t` / `T` | `s` |
| --- | --- | --- |
| Quick | chart theme | chart presentation style |
| Advanced, selected with `a` | attachment animation theme | attachment animation style |

The advanced page displays the selected attachment theme and style. Changes are immediate, touch no Provider/query lifecycle state, and do not reset the animation clock.

For every other Monitor style, the existing quick-page chart controls remain unchanged. The advanced page hides animation settings and does not consume `t`, `T`, or `s` as animation actions.

Dashboard Monitor Pane adjustments use the same rules but mutate only that Pane's attachment state.

## Theme and capability handling

ccuv provides a one-way mapping from its selected theme/palette to `term-animate` theme tokens:

```text
ccuv chart or animation theme
  → ccuv palette tokens
  → term-animate ThemeTokens
  → ccuv Frame rows
```

The adapter must honor ccuv terminal color capability. Monochrome rendering uses the library's appropriate non-color projection and must not emit stray ANSI style state.

Standalone animation and Dashboard animation Pane sessions begin with their Host default theme. Monitor attachments begin from the owner Monitor's chart theme. The initial inheritance applies only at session creation.

## Error handling

- Invalid standalone or Dashboard Pane animation styles fail in configuration validation with valid choices.
- A projection/rendering failure renders a local animation error rather than taking down chart content or the Dashboard.
- A too-small viewport renders a static compact hint and stops scheduling frame updates.
- Animation deadlines and state changes never trigger data requests.
- Standard Monitor query errors continue to be represented by existing Monitor UI and do not mutate attachment activity unless an observation is accepted.

## Tests

### Unit tests

- Supported catalog mapping; standalone default `rain`; invalid names; missing Dashboard style rejection.
- AnimationClock initial, active, freeze, repeated freeze/resume, virtual wall time, no idle catch-up, hiding/resize behavior.
- Adapter output for color and monochrome terminals, clipping/minimum viewport, width integrity, and theme tokens.
- Monitor activity transitions: positive/zero delta, initial sample, pending/error/discarded query, manual refresh, host pause, and ranking/list style transitions.
- State isolation across standalone instances and Dashboard Panes.
- Immediate non-persistent settings changes.

### Composition and integration tests

- Ranking/list output remains unchanged without its Host attachment; attachment is placed after body content and before notices/controls.
- Attachment is excluded before core rank/list lines when pane height is insufficient.
- Non-ranking/list content never renders or schedules the attachment.
- `--pane "animate rain"` materializes with chart panes and has no query/lifecycle work.
- Animation frame deadlines trigger only repaint work, never Provider execution.
- Multiple animation Panes have independent theme/style/clock state.
- Dashboard global pause freezes/resumes animation Pane clocks.
- Dashboard Monitor advanced settings affect only the focused attachment.

### Manual terminal verification

```bash
uv run ccuv animate
uv run ccuv animate mole-cat
uv run ccuv monitor --style ranking
uv run ccuv monitor --style list
uv run ccuv dashboard --pane "timeline --by model" --pane "animate rain"
uv run ccuv dashboard --pane "monitor --style ranking --by model" --pane "animate rain"
```

Validate real input handling, terminal resize, color/no-color projection, no Provider activity caused by animation frames, `rain` freezing over zero-delta monitor intervals, continuation after a positive delta, and settings isolation between Dashboard Panes.

## Implementation order

1. Add local editable `term-animate` source and minimal adapter projection tests.
2. Implement catalog, `AnimationClock`, theme mapping, Frame-row adapter, and small-view fallback.
3. Add `ccuv animate [style]` route and standalone host.
4. Extend Dashboard Pane parsing/configuration/layout for `animate <style>` and its render-only scheduling/control flow.
5. Add Monitor attachment state, ranking/list host composition, positive-delta playback binding, and standalone settings UI.
6. Apply the same attachment controls/state to Dashboard Monitor Panes.
7. Add documentation, help/i18n strings, automated tests, and real-terminal verification.
8. Publish `term-animate`; remove the local uv source override; verify the locked published package retains identical behavior.
