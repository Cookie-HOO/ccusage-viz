# Custom Ranking List Group Copy Icon Design

## Goal

Restore the copy-state icon and copy hit target for group headings in Custom Ranking's `list` style. Keep icons hidden for individual series rows, preserving the compact list presentation.

## Scope

- Applies only to grouped Custom Ranking rendering.
- In `list` style, a group heading displays `⊞` before copying and `✓` after it has been copied.
- The group-heading row remains clickable/copyable in `list` style.
- Series rows and residual/other rows remain icon-free and do not gain copy hit targets in `list` style.

## Implementation

`render_grouped_custom_ranking_viewport` currently omits the group marker from the heading label in `list` style and skips all copy hit registration when that style is active. Adjust the group-heading rendering to always append its marker. Register hits for group rows regardless of style, while retaining the existing style guard for series rows.

The existing copied-entry identity and marker calculation remain the source of truth, so the label changes from `⊞` to `✓` immediately after a group copy action without introducing new state.

## Tests

Extend grouped custom-ranking viewport tests to verify that, in `list` style:

1. Group headings render the default copy marker.
2. A group heading has a copy hit target, but a series row does not.
3. The heading marker becomes the copied marker after invoking its hit action.

## Non-goals

- Do not change non-list rendering.
- Do not add copy icons or copy hit targets to list-style series rows.
- Do not alter clipboard text content or scrolling behavior.
