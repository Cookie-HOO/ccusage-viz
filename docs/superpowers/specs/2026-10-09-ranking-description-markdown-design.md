# Ranking Description Markdown And Comparison Documentation Design

## Goal

Document the automatic prior-period comparison behavior for Custom Dataset
Rankings and allow their optional entry descriptions to contain clickable
Markdown links.

## Ranking Comparisons

At `full` and `detailed` density, ccuv asks a non-fixed Custom Ranking for its
current range and then its contiguous, equal-duration prior range. The Dataset
returns ordinary dated points for both requests. ccuv matches stable
`data.series[].id` values, sums each range locally, and derives the displayed
absolute value change and rank movement. A Dataset must not provide separate
delta, previous-total, or rank-change fields.

Fixed date ranges do not request a comparison range. If the prior request is
unavailable or fails, ccuv retains current Ranking values and omits its
comparison markers.

## Description Links

Descriptions remain Ranking-only localized text fields. They recognize only
the Markdown link form `[label](https://URL)`. ccuv renders `label` as visible
text and attaches `https://URL` through an OSC 8 terminal hyperlink. No URL,
link icon, or terminal control sequence is shown as visible description text.

All other Markdown syntax, HTML, malformed link markup, and arbitrary ANSI
control sequences remain safe visible plain text. Links must use the `https`
scheme; unsupported schemes remain plain text. Rendering must never emit a
Dataset-supplied terminal escape sequence.

### Search Behavior

Ranking search matches plain description text, link labels, and link URLs.

- A matching visible label span is highlighted and remains clickable.
- When only the target URL matches, ccuv appends a highlighted `↗` marker after
  the visible label. Both the label and marker link to that URL. The marker
  makes URL-only matches discoverable without falsely highlighting text that
  did not match or expanding the URL into the compact row.
- When both label and URL match, ccuv highlights the matching label span; it
  does not append a redundant `↗` marker.

Description rows retain existing muted styling, CJK/ANSI-aware wrapping, and
the two-row cap. Search highlighting has precedence over the muted description
colour while preserving the OSC 8 hyperlink around every rendered link span.

## Compatibility

Plain text remains valid and renders unchanged. Existing Dataset responses and
all non-Ranking chart response constraints remain unchanged.

## Testing

Cover link rendering, rejected/malformed syntax and ANSI escape data, two-row
clipping, label and URL search matches, preserved OSC 8 click targets, and
unchanged ordinary Ranking comparison calculations. Update the English and
Chinese protocol and Dataset developer documents with the comparison request
lifecycle and this link-only contract.
