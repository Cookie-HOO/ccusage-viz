# Ranking Description Emphasis Design

## Goal

Allow Custom Dataset Ranking descriptions to use a small, safe subset of
Markdown emphasis in addition to the existing `https` link syntax.

## Supported Markup

Descriptions recognize only these additional inline forms:

- `**bold text**` renders in terminal bold.
- `*italic text*` renders in terminal italic.

The use of underscores for emphasis is not supported. Valid emphasis may occur
inside a supported link label, such as `[*release notes*](https://example.com)`.
The link remains clickable across the entire styled label.

## Safety And Compatibility

The parser operates after stripping source-supplied terminal controls. It does
not emit any raw Dataset-supplied control sequence. HTML, unsupported Markdown,
invalid, empty, nested, or unbalanced emphasis delimiters, unsafe links, and
malformed links retain their visible source text as safe plain text.

Visible description text, wrapping, two-row clipping, copy text, and search
continue to operate on the plain label text. Link URLs remain searchable as
before. Existing link-only description output remains unchanged, including its
clickable `↗` affordance.

## Testing

Renderer coverage verifies plain and linked bold/italic output, terminal style
resets, width preservation, search compatibility, and literal handling of
unsupported or malformed emphasis. English and Simplified Chinese Dataset
protocol/developer documentation lists this deliberately narrow contract.
