# Interactive Terminal Refactor Plan

> **Target:** `0.3.0`, alongside the custom-functionality work and animation refactor.
>
> **Status:** Recorded design direction. This plan is intentionally not part of the
> narrow `0.2.2` terminal flicker correction.

## Goal

Centralize interactive terminal protocol ownership so animation hosts, Dashboard,
Monitor/Watch, and future custom terminal surfaces do not individually manage
cursor visibility, synchronized updates, autowrap protection, or frame cleanup.

## Motivation

`0.2.2` corrects right-edge flicker by making `FramePainter` address and clear
rows explicitly, disabling autowrap during atomic redraws, and hiding the native
cursor for animation sessions. The individual hosts currently still decide when
to pass `atomic=True`, hide/show the cursor, and call `finish()`. That leaks ANSI
lifecycle details into application-level control flow and makes cleanup behavior
harder to keep consistent as custom views are added.

## Intended architecture

Introduce one interactive-terminal session boundary, such as
`FramePainter.interactive()` or `interactive_terminal(...)`, that owns:

1. cursor hiding on entry and unconditional restoration on exit;
2. synchronized redraw transactions and temporary autowrap disable/restore;
3. safe full-frame and differential painting through `FramePainter`;
4. final cursor placement and newline emission exactly once;
5. exception, `KeyboardInterrupt`, and nested-session semantics that restore
   terminal modes in a deterministic order.

Hosts should render their frames and own their domain scheduling/input only.
They must not need to coordinate ANSI control sequences, cursor visibility, or
atomic redraw flags directly.

## Scope and constraints

- Preserve the token-metrics boundary: animation repaint deadlines and terminal
  session lifecycle must never add provider work or token queries.
- Keep `term-animate` host-neutral: ccuv owns terminal output, input, scheduling,
  clipping, and cleanup.
- Maintain no-TTY/error behavior and existing `FramePainter` differential-update
  efficiency.
- Define behavior for non-animation interactive views before migrating them; do
  not automatically hide cursors everywhere without validating user-visible
  interaction and output compatibility.
- Coordinate the API migration with the custom Dashboard/command functionality
  so new surfaces do not introduce another host-local terminal lifecycle.

## Proposed implementation sequence

- [ ] Specify the context/session public and internal API, including nesting,
      idempotent cleanup, and stream ownership.
- [ ] Move cursor lifecycle and atomic redraw policy from standalone animation,
      gallery, Dashboard, and Watch/Monitor paths into the new boundary.
- [ ] Migrate animation hosts first and verify exact ANSI output and cleanup on
      normal exit, errors, and `Ctrl-C`.
- [ ] Migrate Dashboard and custom surfaces after their runtime ownership is
      settled; retain focused regression tests for provider/query isolation.
- [ ] Decide and document which non-animation interactive commands adopt the
      session and whether behavior should remain opt-in or become the default.
- [ ] Remove duplicated host-level ANSI helpers and `atomic=True` call-site
      policy once all relevant surfaces use the shared boundary.

## Verification

- Unit tests cover session enter/exit ordering, exact terminal mode restoration,
  full-width frames, differential frames, exceptions, and repeated cleanup.
- Host integration tests prove cursor restoration for standalone animation,
  gallery, Dashboard, Monitor/Watch, and custom interactive surfaces.
- Regression tests confirm animation/terminal scheduling remains presentation
  only and does not create provider requests or executor work.
