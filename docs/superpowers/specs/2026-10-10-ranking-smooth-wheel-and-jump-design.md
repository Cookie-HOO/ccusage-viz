# Ranking Smooth Wheel And Rank Jump Design

**Date:** 2026-10-10

## Goal

Make direct Ranking scrolling easier to visually follow during sustained wheel input and provide debounced numeric jumps to a rank.

## Smooth Direct Wheel Scrolling

- The base wheel movement is one rendered row.
- Same-direction reports received less than 80ms apart step through multipliers `1, 1, 2, 2, 3`, then remain at `3`.
- A direction reversal or a gap of 80ms or more resets the multiplier to `1`.
- Buffered reports are reduced to a bounded net move of at most three rendered rows for a host input turn; excess input is dropped rather than replayed later.
- There is no velocity, scheduled animation, timer-driven movement, or post-input scroll tail.
- Arrow keys remain direct base-step scrolling.

## Numeric Rank Jump

- Only a focused historical Ranking in ordinary Dashboard chart browsing accepts digit keys.
- Digits accumulate into a rank number and show a fixed line above Ranking content: `Jump to rank: <digits>_`.
- The screen does not jump until 400ms after the latest digit.
- On debounce expiry, jump to the selected rank, clamped to the last available rank. The jump targets ordinal Ranking entries, not rendered lines, so descriptions/wrapping do not change its meaning.
- There is no cancellation command. Any direction key, wheel input, focus/view/data change, or other non-digit interaction commits the currently entered rank first, then performs its own behavior.
- The input state is ephemeral, does not query or persist, and is mutually exclusive with existing search/modal/editor input.

## Scope

The wheel policy applies to native and Custom historical Rankings in Dashboard and standalone hosts. Numeric rank jump is Dashboard-focused Ranking browsing only.
