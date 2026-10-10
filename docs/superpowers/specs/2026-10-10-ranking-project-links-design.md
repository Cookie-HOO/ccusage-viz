# Ranking Project Links Design

## Goal

Allow a Custom Dataset Ranking series to publish one optional project URL beside
its existing whole-project copy control.

## Protocol

Only Ranking `data.series[]` accepts an optional `link` string. The value must
be an absolute `https://` URL with a non-empty host. Timeline, Stack, and
Calendar reject `link` just as they reject Ranking-only description and display
fields. Locally composed `Other` never receives a link, and comparison responses
do not contribute link metadata.

## Rendering And Interaction

For a concrete Ranking row with a link, ccuv renders an action group after the
label using ` | `, then places the existing copy marker before a clickable `↗`:
`Project | ⊞ ↗`. Both actions use the label's ordinary foreground colour. The link uses the
same OSC 8 terminal hyperlink construction as description links. Rows without a
link retain the existing copy marker alone; native and `Other` rows do not show
either project control.

The copy marker remains the only TUI mouse hit target. The terminal owns clicks
on the adjacent OSC 8 link. Copying a project yields newline-separated label,
description text (including any description-link target), and the project link
when present.

## Safety And Compatibility

The URL is parser-validated before rendering; source terminal controls cannot
be emitted. Existing descriptions and their embedded links retain their current
behavior. Absence of `link` preserves current rendering and clipboard content.

## Testing

Cover parser acceptance and rejection, Ranking-only validation, projection
propagation, OSC 8 icon rendering, absent-link output, `Other` exclusion,
clipboard concatenation, and unchanged copy hit geometry.
