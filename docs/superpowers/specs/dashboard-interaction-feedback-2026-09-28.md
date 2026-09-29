# Dashboard Interaction Feedback — 2026-09-28

Notes captured from a hands-on session; discuss and refine each item before implementation.

## 1. Pane selection should require double-click

In the dashboard, a single click on a pane too easily causes unintended selection—especially when someone is already in selection mode and instinctively clicks another pane to leave it.

Desired behavior:

- Double-click a pane to enter selection mode or switch the selection directly to that pane.
- Single-click a different pane or empty space while a pane is selected to return to browse mode.
- Single-clicking a pane in browse mode does not change selection or mode.

## 2. Undo and redo pane and layout operations

Add dashboard shortcuts for reversible editing:

- `u`: undo
- `U`: redo

The history should be session-scoped (not persisted across restart) and should cover:

- Insert before
- Insert after
- Replace
- Delete
- Layout adjustments, recorded once only when the new layout is successfully applied with `Enter`

`Esc` cancels a pending layout edit without creating history. History is a bounded, session-scoped timeline of at most 100 user-edit states, not a record of synthetic inverse actions: after edits `A → B → C`, `u` moves the active state back to `B` and places `C` on the redo branch; `U` returns to `C`. If the user then makes a new edit `D`, the `C` redo branch is discarded and the timeline becomes `A → B → D` (not `A → B → C → D`). When capacity is exceeded, discard the oldest retained history state.

Undo/redo uses one unified dashboard-session history across dashboard and pane edits. Any user-initiated operation that persistently changes the displayed dashboard or pane configuration enters this history, including pane insertion/replacement/deletion, layout changes, and pane-level display/configuration changes. `u` and `U` are available and persistently shown in the bottom action bar in every non-text-input mode, including global browse mode. In text-input modes, they are ordinary input characters and are neither displayed as actions nor intercepted.

Do not record transient runtime effects: selection/focus/navigation, scrolling, help, copying/exporting, animation playback/frame progression, clock ticks, or refreshes that only fetch new data without changing configuration.

To keep deliberately repeated visual cycling practical, consecutive changes to the same logical action family and target within one second are coalesced into a single history edit. This applies to repeated theme/style/view cycles and repeated row or column weight changes. Changing target or action family, or pausing for more than one second, starts a new history edit.

The dashboard action-bar layout remains contextual: pane adjustment uses state and quick/advanced controls followed by pane content and position rows; global adjustment uses state plus global controls. To avoid overlong rows, show common actions in a dedicated, persistent final row titled **全局操作**: `u` undo · `U` redo · `h` help. Display that row in every non-text-input dashboard mode, including global browse mode. Global browse currently contains only a runtime-status row; extend it with a separate browse-actions row followed by this final global-operations row. Use `c` (control bar) to show/hide the browse action bar; `h` no longer toggles it. `h` opens one fixed, non-mutating dashboard help overlay from every non-text-input mode, and `Esc` (or `h` again) closes it.

The help has these sections:

1. **模式** — introduce all three modes and visually emphasize the currently active one. **浏览模式** is the default read-only dashboard state (`m` or pane double-click enters Pane adjustment; `g` enters global adjustment). **Pane 调整模式** changes only the selected Pane; `Enter`, `Esc`, or a single click outside the selected Pane returns to browse. **全局调整模式** changes dashboard-wide presentation and layout; `Enter`/`Esc` returns to browse. Any non-browse adjustment mode automatically returns to browse after three minutes without input.
2. **当前模式快捷键** — show only the active mode's shortcuts in functional groups. In Pane adjustment, show both quick and advanced groups and visually emphasize the active page while listing the available actions for both. Keep the key column compact; place a concise English mnemonic in parentheses in the explanation column (for example, `m` — enter Pane adjustment (`Mode`), `g` — enter global adjustment (`Global`), `u` — undo (`Undo`), `U` — redo (`Redo`), `h` — help (`Help`), `c` — show/hide the control bar (`Controls`)). Keep explanations compact and do not add separate example rows. Describe `v` in one line as switching views (`View；图表/命令/数据`) without listing the exact cycle. Retain concise, direct labels for Pane structure edits (`N`/`n` insert before/after; `r` replaces; `x` removes) and visual cycles (`t`/`T` move forward/backward through themes; `s`/`S` do the same for styles). The same help also includes the universally valid global-operations group and mode-relevant mouse behavior. The current bottom control bar remains the authoritative source for pane-type-specific advanced actions.
3. **限制与说明** — include a concise, always-visible undo/redo note in the help overlay: history retains the most recent 100 edits, evicts older edits, is session-only, is unavailable during text input, and discards the redo branch after a new edit. Do not add implementation-oriented behavior, refresh scope, layout validation, pane geometry, animation fallback, or other internal operational details to the user-facing help.

The help is a modal overlay over the current Dashboard frame: it does not alter or pause the underlying mode, selection, data refresh, or animation playback. `h` or `Esc` closes it and restores the exact prior mode, selected Pane, and quick/advanced page. While open, all other keyboard shortcuts are consumed by help and never reach the underlying Dashboard. A mouse click outside the help panel closes it; a click inside does nothing. If terminal height requires it, the help supports `↑`/`↓` scrolling, while the global-operations and limitations sections remain prioritized in the visible composition. Help is unavailable during custom-layout text input, where `h` remains ordinary typed text.

Help has its own five-minute idle timer. Help scrolling or any future help-local interaction resets that timer. If `h`/`Esc` closes help before expiry, resume the pre-help Pane/global-adjustment mode with its original remaining three-minute timer. If help itself is idle for five minutes, close it and return directly to browse mode instead. Show a quiet footer note that five minutes of inactivity returns to browse mode; do not show a live countdown.

Reassign the conflicting global Header-style cycle from `h` to `H`, and the conflicting global `u` action for the header summary to `p`, displayed as **摘要周期** (summary period). Where `h` currently means text-view scroll-to-top, it is superseded by the global help action; retain top navigation through `Home`.

## 3. Improve layout (`a×b`) input

The layout-entry interaction is unfriendly.

Desired behavior after entering `Z`:

- Focus moves directly to the layout input.
- The existing `a×b` layout value is cleared, ready for replacement typing.
- `x` and `X` remain accepted input separators.
- `Enter` validates and applies the draft, records one history state only if it differs from the active layout, then returns to global adjustment mode.
- An empty or invalid draft remains open with an error so it can be corrected.
- `Esc` cancels without changing the active layout or history.

## 4. Change the wide-clock default table style

Use the circular clock presentation—`animate analog-clock`—as the default first Pane of the `wide-clock` preset. Adopt the tested `wide-clock` dashboard command's row weights: `(9, 13, 12)`, so the circular clock has adequate vertical room. This changes the clock Pane's content and `wide-clock` row weights only, not the dashboard frame/structure style. `narrow-clock` remains unchanged with its digital-clock default.

Investigate and fix time-display animation wall-time drift: the animation currently derives wall time from a process-start wall-time origin plus accumulated *active animation* monotonic time. Any interval during which the animation is not viable, hidden, or otherwise frozen makes the displayed time lag behind actual wall time. Every time-related animation (including digital and analog clocks) must receive the actual current local wall-clock time at every projection, independently of animation playback/freeze state. Preserve effective-time semantics only for non-time-display effects whose visual progression needs them.

## 5. Add reverse actions for `s` and `t`

Support uppercase counterparts as reverse-direction behavior:

- `S`: reverse of `s`
- `T`: reverse of `t`

## 6. Make global browse-mode `m` enter selection

In global browse mode, `m` should enter pane selection and immediately open the first Pane's quick-adjustment controls, matching standalone's direct local-control meaning. It replaces the current dashboard browse-mode `s` entry shortcut; no intermediate, selection-only state is introduced.
