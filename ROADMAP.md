# Roadmap

`ccusage-viz` is currently at **0.1.0**. This roadmap describes public product contracts, not private implementation plans.

## 0.1.x

- Add a `ccuv tui` command with a useful default panel grid, optional CLI-declared panels, and a global summary. Monitoring panels will show normalized commands by default and let users toggle them with `c`.
- Add external Token and QPM data only when a supported upstream contract is available. External QPM will count logical requests and will never infer request counts from tokens or blindly count retries.
- Revisit animation only after a public design pass establishes its purpose, interaction model, terminal constraints, and maintenance boundary. It is not part of the current release contract.

## 0.2.0

A substantial release for incompatible contract changes, such as breaking CLI semantics, data-source assumptions, output guarantees, or other behavior that cannot be introduced compatibly in 0.1.x.

## 1.0

Declare 1.0 when the CLI, TUI, data-source, and output contracts are stable enough for long-term users and integrations.

## Feedback

- [Bug report](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=bug_report.yml)
- [Feature request](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=feature_request.yml)
