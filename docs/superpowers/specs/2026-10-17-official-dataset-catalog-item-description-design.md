# Official Dataset Catalog Item/Description Design

## Goal

Make each official Dataset and its description visually distinct in the catalog browser, following the established Custom Ranking item/description hierarchy instead of presenting both as peer table fields.

## Scope

Change only the official Dataset catalog list rendered by `_official_catalog_rows()` and its focused tests. Installation preview, catalog data, navigation, scrolling, and help overlays remain unchanged.

## Presentation

Each Dataset occupies one item block:

```text
› 微信读书 · weread
  将微信读书的阅读时长和书籍活动可视化。
```

- The first line is the primary item and contains the localized Dataset title followed by ` · ` and the stable Dataset ID.
- The selection marker appears only on the primary line.
- The description begins on the next line, aligned with the primary item text after the selection-marker gutter.
- Description text uses the existing muted/secondary terminal treatment used for subordinate explanatory text.
- Descriptions wrap to at most two display lines and are truncated with an ellipsis when longer.
- Width calculations use display width so Chinese and styled text stay aligned and clipped within the terminal.
- The existing Name / Dataset ID / Summary table header and separator are removed because the result is no longer a columnar table.

## Viewport Behavior

An item has one primary line plus one or two description lines. Viewport geometry must keep the selected item block visible rather than assuming every item is exactly two rows. Scrolling continues to move by Dataset item, and catalog refresh continues to preserve the selected index where possible.

## Error Handling

No data or acquisition behavior changes. Empty and unavailable catalog states continue to use their existing notices. Rendering must remain safe for narrow positive widths and must not emit lines wider than the requested width.

## Tests

Focused tests will verify:

- title and Dataset ID share the primary line with the selection marker;
- description starts on a subordinate aligned line;
- table headers are absent;
- long descriptions use no more than two lines and end with an ellipsis when truncated;
- Chinese display-width alignment and narrow-width clipping remain valid;
- scrolling keeps the selected variable-height item visible while no longer relying on fixed two-row entries.
