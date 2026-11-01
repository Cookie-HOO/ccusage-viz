# ccuv backend selection and Agent-friendly installation

## Intent and approved direction

Users should be able to give their AI Agent `https://github.com/Cookie-HOO/ccusage-viz` and ask it to install the project. The Agent must ask whether they need DeepSeek Harness (DSH) or WorkBuddy token statistics before choosing a backend. Users should not need `--ccusage-bin` for routine use after setup.

Keep official ccusage and the unofficial Cookie-HOO/my-ccusage distribution separate. Never overwrite or uninstall the user's official ccusage command. Official remains the default for users who do not need supplemental sources or are unsure. Explain that the enhanced distribution synchronizes upstream deliberately after compatibility verification, not automatically or necessarily immediately.

Recon: official v20.0.46 and current main have no registered DSH or WorkBuddy adapter. my-ccusage provides supplemental adapters; WorkBuddy coverage is unified daily and project/session attribution, not all focused report commands. Avoid claiming full command-for-command replacement.

## Goals and non-goals

Goals: choose once; easy status and switching; same setup logic for first-run onboarding and explicit setup; deterministic noninteractive commands for Agents; safe coexistence; English and Chinese documentation and messages; Windows/macOS/Linux support on released architectures.

Non-goals: automatic upgrades, a general package manager, automatic region/language-based selection, implementing collectors in ccuv, changing Dataset management, editing shell profiles, replacing global ccusage, or storing usage data.

Existing unrelated working-tree changes must remain untouched.

## CLI contract

- `ccuv backend`: read-only status; works even when nothing is installed. Show selected distribution (official/enhanced/custom), executable location, version when available, availability, selection origin (saved versus discovered), and `ccuv backend setup` repair/switch guidance. Do not install, prompt, or create configuration. Probe only executable version with a bounded timeout, never a usage query. A missing/unusable backend is displayed as unavailable; the status command itself succeeds unless configuration cannot be read safely.
- `ccuv backend setup`: interactive setup. Ask about DSH or WorkBuddy in user language, explain official versus enhanced briefly, then show selected backend and installation source. Confirm before installation and before saving a changed selection. EOF/Ctrl-C cancels without changing selection.
- `ccuv backend setup --backend official --yes` and `ccuv backend setup --backend enhanced --yes`: Agent/automation entry points. An explicit backend and `--yes` authorize installation and selection persistence without terminal prompts. No implicit choice in noninteractive setup: require both flags or return actionable usage guidance without side effects.
- `--lang en|zh`: supported on backend and setup; nested help must describe setup accurately.
- No update/uninstall/reset subcommands in this iteration.

Interactive answer rules: yes to either source selects enhanced; no selects official; unsure/Enter selects official if no previous selection exists, otherwise preserves the saved selection. Make Enter's behavior explicit in the prompt. Invalid answers re-prompt rather than silently becoming no. Report existing configuration before asking; never use language, location, or log-directory detection to choose automatically.

Explicit setup asks about these sources even if official ccusage is already installed. When preserving a valid saved choice, no unnecessary install occurs. If its executable is missing, repair the same distribution, with confirmation; do not switch silently.

## Backend discovery and runtime resolution

Precedence:
1. Explicit command-line `--ccusage-bin`, or a custom executable pinned by a Dashboard preset.
2. Saved global backend choice.
3. Existing commands discovered on PATH (`ccusage`, `my-ccusage`). One available distribution can be reused; when both exist with no saved selection, prompt to choose in interactive real-data launches and default to official in noninteractive launches.
4. No executable: interactive real-data launch invokes the same setup flow; noninteractive launch fails with setup instructions and no installation.

A saved choice whose executable disappears must produce repair guidance and never silently fall through to another distribution. `backend setup` can repair or deliberately switch it. Switching configuration only succeeds after the new executable validates; failures preserve the previous choice.

Runtime resolution must happen before actual acquisition but must not mutate the declarative launch/process configuration to store an automatically resolved path. All built-in acquisition paths must receive the same resolved backend. Ordinary copied chart commands and presets follow global choice, rather than accidentally pinning a resolved absolute path. Explicit custom overrides continue to be copied/saved as before.

Help/version, backend status, animations, Demo, empty Dashboard, and Dataset-only launches must not trigger backend installation or unnecessary backend configuration reads. Explicit custom `--ccusage-bin` runs do not trigger setup; normal query error handling applies to that executable.

## Storage and preset compatibility

Use a small versioned backend configuration in ccuv's existing private state root (macOS `~/Library/Application Support/ccuv`, Windows `%LOCALAPPDATA%/ccuv`, Linux `${XDG_STATE_HOME:-~/.local/state}/ccuv`). Store distribution and executable locator only, no credentials, query results, or transcript data.

Builder call: official discovered/installed through npm is stored as the command locator `ccusage`, honoring the active PATH and Node environment; enhanced installed privately is stored by absolute path, avoiding PATH edits or stale parent-process PATH. Existing enhanced commands on PATH may be reused with a verified absolute path. Explain this distinction in status output and tests.

Configuration writes are atomic, with private permissions where supported. Validate schema, values, and executable locator; do not execute arbitrary configuration structures or use shell evaluation. Corrupt/unknown-schema configuration must report actionable errors and never be silently overwritten, including by setup. No silent migration is needed for this new file.

Presets whose `ccusage_bin` is the ordinary string `ccusage` follow global selection. Existing non-default custom preset paths remain pinned. New explicit `--ccusage-bin ccusage` overrides apply on that invocation, but a persisted default string is interpreted as global-following; preserving that historical distinction would require a preset schema change and is out of scope. Document this limitation. No preset schema bump in this iteration.

## Installation and verification

Official: reuse PATH ccusage if available; otherwise show and invoke `npm install -g ccusage` with argv, no shell. If npm is absent or installation fails, explain the prerequisite or failure and leave configuration unchanged. Verify the command is discoverable afterward; do not use sudo or edit PATH automatically.

Enhanced: reuse a valid existing my-ccusage or install a published release into a dedicated directory under ccuv's private tool storage. Do not execute remote shell/PowerShell source (`curl | sh`, `irm | iex`) inside ccuv. Use the upstream release artifact naming/platform matrix and SHA256SUMS; resolve a single release and use its fixed tag for both archive and checksum, avoiding latest-release races. Support macOS and Linux x64/ARM64 and Windows x64; unsupported platforms fail with manual guidance. No installation outside the owned directory.

Download with bounded timeouts and size limits; check HTTP failures; verify SHA-256 before extraction; reject unsafe archive paths, links, and unexpected executable layouts. Extract to temporary owned storage; stage and validate executable before atomically promoting it. Cleanup on failure. Builder chooses appropriate limits and storage layout, tests them, and documents relevant user-visible constraints. Release checksums detect corruption but are not independent cryptographic publisher authentication; do not claim otherwise.

Validate version and supplemental `dsh --help` / `workbuddy --help` with bounded subprocesses (no shell); do not read user logs. Official validation verifies version. Existing executable validation failures are reported; replacement/reinstallation requires explicit confirmation/--yes. Installation failure or cancelled validation must not damage a previously valid managed executable or configuration. Output supplies source repository/release and failure detail without claiming universal mainland GitHub reachability.

## Agent-friendly README

Place a prominent 'Install with your AI Agent' section in both READMEs near quick start. Give the shareable project URL and a short copyable request. Add authoritative installation steps aimed at Agents:
1. Inspect platform, Python, existing ccuv and backends. Let the Agent prepare missing prerequisites with platform-appropriate methods and user consent before environment changes; do not prescribe uv/npm bootstrap commands. Python is required; uv is the preferred installer, not a runtime dependency. npm is required only when installing a missing official backend, not when reusing a usable installation or choosing the prebuilt enhanced distribution.
2. Ask whether DSH or WorkBuddy statistics are needed, including when official is already installed.
3. Explain that enhanced is unofficial and verified upstream updates may lag. If unsure, default official with no saved choice, or preserve existing choice.
4. Obtain consent for the chosen installation/configuration; never infer consent to install enhanced merely from Chinese language.
5. Install ccuv using the documented preferred uv workflow (fallback pip where suitable), then execute explicit backend setup with `--backend ... --yes` after consent.
6. Verify `ccuv --version`, `ccuv backend`, and side-effect-free chart help (or Demo if suitable). Do not assume user usage logs exist or run a full interactive dashboard unattended.
7. Report the selected backend and say future `ccuv dashboard` needs no extra executable flag; `ccuv backend setup` switches later.

Update missing-dependency and DSH/WorkBuddy sections to use backend setup instead of requiring remote installer commands and --ccusage-bin. Preserve advanced explicit override examples. Clearly state ccuv does not bundle a collector and installation occurs only with authorization.

## Verification and rollout

Unit tests mock downloads/processes and isolate state from the user's real home. Cover CLI routing, nested help and both languages; status with absent/corrupt configuration; first-run decisions including unsure and cancellation; noninteractive flag requirements; two discovered backends; persisted missing backend; explicit overrides; Demo/empty/Dataset-only exemptions; failure atomicity; npm absent/PATH failure; supported/unsupported platforms; checksum/archive/download failures; managed executable reuse and replacement; presets and copied commands following global choice versus pinned custom paths. No real network or global install in normal tests.

Run focused tests, full suite, lint and format checks using the project's environment. Do not include unrelated pre-existing changes in commits. This document will be approved before product implementation; prepare an implementation plan after approval.
