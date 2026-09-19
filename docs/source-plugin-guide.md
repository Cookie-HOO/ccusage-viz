# Source Plugin Guide

> **Status:** Future Source plugin data contract. The plugin system is not implemented; this document constrains its later protocol design.

A Source plugin converts an external Token data source into standard facts that ccuv can combine and chart. It supplies data; it does not own charts, TPM calculation, filtering, grouping, or terminal rendering.

## Admission requirements

A Source must:

1. provide cumulative Token usage by natural day;
2. keep the current day's cumulative values updated as usage occurs—a later record for the same identity is the complete current value, not another increment;
3. provide concrete `agent`, `model`, and `project` values on every record;
4. provide standard Token values and explicit date Coverage;
5. disclose the products, files, services, or APIs from which it obtains data.

A data source that cannot meet these requirements should not be integrated as a Source plugin.

## Dimensions and names

| Dimension | When a concrete value exists | When subdivision is unavailable |
| --- | --- | --- |
| `agent` | Provide the real, stable Agent name. Use the same name as ccusage when aggregate output should share a label. | Use one stable, Source-owned value for all records. |
| `model` | Provide the real, stable Model name. | Use one stable, Source-owned value for all records. |
| `project` | Provide the real, stable Project name. | Use one stable, Source-owned value for all records. |

The complete identity of one cumulative fact is `Source ID + natural day + agent + model + project`. When the same Source later returns the same identity, the new cumulative value replaces the old value; snapshots must not be added together. Current facts from different Sources remain separate. ccuv adds enabled Sources in final aggregation only when the user has confirmed that their underlying data does not overlap.

Dimension names use exact identity. Different names remain separate; ccuv does not infer aliases, use fuzzy matching, or correct Source-provided names.

For example, these values share the `claude` aggregate label:

```text
ccusage: agent = claude
plugin:  agent = claude
result:  displayed under claude
```

These values remain separate:

```text
ccusage: agent = claude
plugin:  agent = claudecode
result:  claude and claudecode remain separate
```

A Source that cannot distinguish Models could use one stable value such as `my-source-model`. A developer who wants its values to remain visibly Source-specific should choose stable names that identify that Source.

The plugin developer is responsible for dimension naming, stability, and the semantic consequences of shared aggregate labels.

## Data provenance and duplicate counting

ccuv combines enabled Sources, but it does not infer whether records describe the same Token usage and does not perform event-level deduplication.

A Source plugin must not collect data from sources officially covered by ccusage. Those inputs belong to the built-in ccusage Provider; collecting them again can count the same Token usage twice.

A plugin must clearly disclose its inputs, for example:

```text
Data sources:
- Example Router local event database
- Records produced after 2026-01-01
- Does not read Claude Code or Codex logs handled by ccusage
```

The plugin developer is responsible for accurate disclosure and known-overlap warnings. The user is responsible for confirming that simultaneously enabled Sources do not cover the same usage. Duplicate counting caused by overlapping Sources is the user's responsibility once the overlap has been disclosed.

## Responsibility boundary

A Source plugin is responsible for:

- reading its own data source;
- returning daily cumulative Token facts that update during the current day;
- providing all three standard dimensions;
- maintaining stable dimension names;
- disclosing its inputs and known overlap.

ccuv is responsible for:

- retaining the latest cumulative fact for each complete Source identity;
- combining current facts from separately enabled Sources;
- applying user-configured filtering, grouping, Top, and Other;
- deriving Monitor increments and TPM from changing cumulative snapshots;
- producing Chart Models and terminal output.

ccuv is not responsible for:

- guessing whether dimension names are equivalent;
- correcting Source naming;
- deciding whether different Sources counted the same event;
- automatically deduplicating overlapping data.
