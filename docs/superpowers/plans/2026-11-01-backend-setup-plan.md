# Backend setup implementation plan

Approved design: ../specs/2026-11-01-backend-setup-design.md.

1. Add versioned, validated, atomic backend choice storage and read-only discovery/resolution. Keep declarative process values unchanged so presets and command copy remain portable.
2. Add release download/verification/staging installer for enhanced distribution; retain npm official install, explicit authorization, bounded probes, and failure preservation.
3. Add localized backend status/setup CLI and first-run integration, explicit override and Demo/custom-only exemptions. Resolve selected backend only in built-in execution contexts.
4. Replace legacy dependency tests with isolated backend-aware tests; add archive/checksum/platform/atomicity and CLI tests.
5. Update both READMEs with Agent instructions, backend setup and coverage/update caveats.
6. Run focused and full tests and Ruff; inspect diff without altering unrelated changes.

The writing-plans skill is not installed in this session; this plan follows the approved design directly. Independent reviewer startup failed due to an unauthenticated ambiguous configured model, so review locally before handoff.
