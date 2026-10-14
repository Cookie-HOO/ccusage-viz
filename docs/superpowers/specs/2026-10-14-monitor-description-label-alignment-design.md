# Align Monitor Descriptions With Labels

## Goal

Make each description in Monitor `ranking` and `ranking-dot` presentations begin in the same terminal column as its corresponding label. Apply the behavior equally to native Monitor and Custom Dataset Monitor.

## Approach

Keep native Monitor's observed-ranking renderer as the single layout implementation. Custom Dataset Monitor already converts its latest grouped values into a native `RankingModel`, delegates rendering to `render_ranking()`, and replaces only the heading. Historical Custom Ranking already aligns descriptions to labels and requires no change.

In the observed-ranking branch of `render_ranking()`, derive description indentation from the rendered primary-row prefix width. That prefix contains the rank and status columns immediately preceding the label, so its display width is the label's exact start column. Remove the unrelated value-column width from the indentation calculation.

Compute description wrapping width from the corrected indentation. Preserve the existing two-line limit, overflow ellipsis, muted styling, density requirements, and suppression for list and `Other` entries.

## Behavior

- Monitor `ranking` and `ranking-dot` descriptions start directly beneath their corresponding labels.
- Native and Custom Dataset Monitor retain identical row geometry because both continue using `render_ranking()`.
- Labels, values, displays, sorting, bars, titles, data handling, and list presentation are unchanged.
- Description visibility, wrapping, styling, and truncation policies remain unchanged apart from the additional width made available by the corrected left edge.

## Testing

Add an observed Monitor ranking regression test that compares the display-column offsets of a label and its description. Exercise representative ranking styles and ensure wrapped rows remain within the viewport.

Retain the existing Custom Dataset Monitor/native Monitor row-equivalence test, which proves the shared renderer propagates the alignment to Custom Monitor without a Custom-specific layout branch.
