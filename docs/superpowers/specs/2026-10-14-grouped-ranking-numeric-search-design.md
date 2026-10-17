# Grouped Ranking Numeric Search Crash Design

## Problem

Grouped Ranking recalculates shared column widths after every search edit. During incremental input such as `gpt4`, an intermediate or final query may leave `visible` empty. Several width calculations use this form:

```python
max(existing_width, *(candidate for group in visible))
```

With no visible groups, this becomes `max(existing_width)`. Python interprets the integer as the single iterable argument and raises `TypeError: 'int' object is not iterable`. The numeric character is valid search text and is not itself converted to an integer.

## Design

Change each grouped heading width reduction (`current`, `delta`, `share`, and `right`) to an empty-safe generator reduction:

```python
max((candidate for group in visible), default=existing_width)
```

This preserves the previous result for non-empty groups and retains the existing minimum width when no group matches. Search semantics, ranking facts, viewport identity, and input handling remain unchanged.

## Verification

Add regressions covering:

- direct grouped viewport rendering with a zero-match query;
- Dashboard incremental input `/gpt4`, including repaint after every character;
- the resulting query remains the string `gpt4`;
- an empty result renders normally rather than raising.
