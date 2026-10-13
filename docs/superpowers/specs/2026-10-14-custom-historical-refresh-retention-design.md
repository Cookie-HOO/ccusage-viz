# Custom Historical Refresh Retention Design

**Goal:** Keep the last accepted Custom Historical chart visible while its next primary query is in flight, matching built-in historical charts and Custom Monitor behavior.

## Scope

This applies to Custom Historical Timeline, Stack, Calendar, and Ranking in both Dashboard panes and standalone views. It does not alter query scheduling, accepted-result lifecycle, error handling, or rendering for Custom Monitor.

## Current behavior

`CustomHistoricalComponent` retains an accepted projection in `model` while a later query is pending. However, both Custom Historical TUI render paths prioritize `component.is_pending` and render `render_custom_pending(...)`. Consequently, a periodic Custom Ranking refresh temporarily replaces the last accepted chart with a loading placeholder.

Built-in historical panes instead keep their accepted snapshot rendered and pass refresh state to the renderer. Their audit/refresh indication is governed by existing density rules.

## Design

### Rendering decision

At each Custom Historical render boundary:

1. If no accepted `model` exists, render the existing loading/pending placeholder.
2. If an accepted `model` exists, render it even when `component.is_pending` is true.
3. Pass `pending=True` to `_render_custom_projection(...)` whenever the primary request is pending (and preserve the existing Dashboard submission-pending condition).
4. Continue using the accepted configuration, accepted timestamp, summary, viewport, and ranking-search state for that retained projection.

This preserves the last complete chart until a new result is accepted. On a successful response, the normal accepted-model replacement path redraws the new chart. Existing failure handling remains responsible for retaining or invalidating accepted facts according to query identity and error type.

### Refresh indication

The change reuses existing `RenderAudit` behavior rather than adding Custom-specific chrome or text. Whether a refresh indicator is visible remains controlled by the active density/audit-row rules. Low-density views may show no explicit indicator but still retain the chart, consistent with other chart types.

### Code boundaries

Modify only these render decision points in `src/ccusage_viz/tui.py`:

- Dashboard Custom Historical pane renderer.
- Standalone Custom Historical renderer.

`render_custom_pending()` remains the initial-load fallback. `CustomHistoricalComponent` state transitions and provider/scheduler behavior remain unchanged.

## Tests

Add focused regression coverage for both Dashboard and standalone Custom Historical rendering:

- An accepted Custom Ranking (or representative historical projection) remains visible when its component enters primary pending state.
- The rendered projection receives pending state, producing the existing refresh indication when the selected density exposes an audit row.
- A Custom Historical component with no accepted model still renders the loading placeholder while pending.
- Low-density behavior remains governed by the existing audit visibility rules; no Custom-only row is added.

Run the focused Custom TUI/render tests and the relevant full test subset after implementation.

## Non-goals

- New loading/refresh strings, icons, or Custom-only status rows.
- Changing fixed versus rolling range refresh semantics.
- Changing accepted-result retention on failures.
- Altering Custom Monitor or built-in chart rendering.
