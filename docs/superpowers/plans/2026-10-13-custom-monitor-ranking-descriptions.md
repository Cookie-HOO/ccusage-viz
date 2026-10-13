# Custom Monitor Ranking Descriptions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Custom Dataset Monitor groups supply localized descriptions that render beneath their rows only in a detailed/full ranking.

**Architecture:** Add optional localized description metadata to the existing V2 monitor group value, preserving it through the custom Monitor ranking projection and shared scalar ranking model. Extend the observed-ranking renderer with the same safe, muted, width-bounded description treatment used by historical custom ranking, gated by ranking style and complete density. List and time-based Monitor renderers will retain their current scalar entries but never render descriptions.

**Tech Stack:** Python 3.12+, dataclasses, Decimal, pytest, existing terminal rendering and localization utilities.

**Spec:** `docs/superpowers/specs/2026-10-13-custom-monitor-ranking-descriptions-design.md`

## Global Constraints

- `description` is optional localized text in a V2 Monitor observation group; omitted groups remain valid.
- Empty localized text is normalized to absent; malformed present localized values raise `CustomProtocolError`.
- Descriptions render only for Custom Monitor `ranking` at `full` and `detailed` density.
- Descriptions never render in Custom Monitor `list`, bars, or timeline views.
- Synthetic `Other` and ungrouped `total` entries have no description.
- Reuse existing safe description text handling: no terminal escape interpretation and wrapping bounded to terminal width.
- Do not change built-in Monitor behavior, Monitor aggregation, ordering, windowing, or request semantics.

---

## File Structure

- `src/ccusage_viz/custom_models.py` — V2 Monitor group value transport type gains its optional source description.
- `src/ccusage_viz/custom_protocol.py` — parses and normalizes the additive observation-group field.
- `src/ccusage_viz/custom_monitor_component.py` — carries a group description from accepted observation into the sorted ranking entries and scalar view model.
- `src/ccusage_viz/chart_models.py` — lets a generic observed scalar ranking entry carry optional descriptive presentation metadata.
- `src/ccusage_viz/render/ranking.py` — renders scalar descriptions below observed ranking rows only when the active observed view is ranking at complete density.
- `docs/custom-command-protocol.md` and `docs/custom-command-protocol.zh-CN.md` — document the additive Monitor group field and presentation limit.
- `tests/test_custom_protocol.py` — protocol parsing, omission, normalization, and malformed-field tests.
- `tests/test_custom_monitor_component.py` — verifies retention/localization/sorting through the Custom Monitor ranking model.
- `tests/test_custom_monitor.py` — verifies standalone ranking output and non-ranking output behavior.

### Task 1: Parse and model optional Monitor group descriptions

**Files:**
- Modify: `src/ccusage_viz/custom_models.py:208-219`
- Modify: `src/ccusage_viz/custom_protocol.py:1333-1351`
- Test: `tests/test_custom_protocol.py:296-305` and nearby V2 Monitor response tests

**Interfaces:**
- Produces: `V2MetricValue(id: str, label: LocalizedText, value: Decimal, description: LocalizedText | None = None)`.
- Produces: `_parse_v2_monitor_observation(value: object) -> V2MonitorObservation`, where a supplied `groups[*].description` is parsed using the existing localized schema.
- Consumed by Task 2: each accepted `V2MonitorObservation.groups` item exposes `.description`.

- [ ] **Step 1: Write failing parsing tests**

Add tests near the existing V2 monitor response fixture that set a group description and assert localized retention, verify omitted descriptions remain `None`, normalize an all-whitespace `LocalizedText("   ", "\t")` description to `None`, and reject a present malformed description:

```python
def test_v2_monitor_response_parses_optional_group_description() -> None:
    payload = monitor_response()
    payload["observation"]["groups"][0]["description"] = text("Release validation", "发布验证")

    parsed = parse_custom_response(json.dumps(payload).encode(), monitor_request())

    assert parsed.observation.groups[0].description == LocalizedText("Release validation", "发布验证")


def test_v2_monitor_response_normalizes_empty_group_description() -> None:
    payload = monitor_response()
    payload["observation"]["groups"][0]["description"] = text("   ", "\t")

    parsed = parse_custom_response(json.dumps(payload).encode(), monitor_request())

    assert parsed.observation.groups[0].description is None


def test_v2_monitor_response_rejects_malformed_group_description() -> None:
    payload = monitor_response()
    payload["observation"]["groups"][0]["description"] = "not localized"

    with pytest.raises(CustomProtocolError, match="v2 monitor group description"):
        parse_custom_response(json.dumps(payload).encode(), monitor_request())
```

Use the actual nearby fixture names if they differ; preserve the test module’s existing request construction rather than adding a second response parser fixture.

- [ ] **Step 2: Run the parsing tests to verify failure**

Run: `pytest tests/test_custom_protocol.py -k 'monitor and description' -v`

Expected: FAIL because `V2MetricValue` has no `description` field and the parser ignores the supplied field.

- [ ] **Step 3: Implement the transport and parser change**

Add a defaulted field after `value` so existing positional constructor sites remain valid:

```python
@dataclass(frozen=True, slots=True)
class V2MetricValue:
    id: str
    label: LocalizedText
    value: Decimal
    description: LocalizedText | None = None
```

In `_parse_v2_monitor_observation`, parse `item.get("description")` only if the key is present. Normalize it after parsing: retain it only when either locale contains non-whitespace text; otherwise pass `None`. Do not catch `CustomProtocolError` from `_parse_localized`.

```python
raw_description = item.get("description")
description = (
    _parse_localized(raw_description, "v2 monitor group description")
    if raw_description is not None
    else None
)
if description is not None and not (description.en.strip() or description.zh_cn.strip()):
    description = None
```

Construct `V2MetricValue(id, label, value, description)`.

- [ ] **Step 4: Run protocol tests**

Run: `pytest tests/test_custom_protocol.py -v`

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/ccusage_viz/custom_models.py src/ccusage_viz/custom_protocol.py tests/test_custom_protocol.py
git commit -m "feat: parse custom monitor group descriptions"
```

### Task 2: Preserve descriptions in Custom Monitor ranking projections

**Files:**
- Modify: `src/ccusage_viz/chart_models.py:267-273`
- Modify: `src/ccusage_viz/custom_monitor_component.py:113-124,404-416,480-496`
- Test: `tests/test_custom_monitor_component.py` near existing ranking and localized label tests

**Interfaces:**
- Consumes: `V2MetricValue.description: LocalizedText | None` from Task 1.
- Produces: `CustomMonitorRankingEntry(key: str, label: LocalizedText | None, value: Decimal, description: LocalizedText | None = None)`.
- Produces: `ScalarRankingEntry(key, label, value, is_other=False, agent=None, description=None)`, with `description: str | None` localized for the requested language.
- Consumed by Task 3: observed scalar ranking entries expose `.description` without modifying rows created by built-in Monitor components.

- [ ] **Step 1: Write failing projection tests**

Create an accepted Monitor observation with deliberately reverse label/value ordering and locale-specific descriptions, then assert value sorting still governs rank while each source description remains attached and localizes correctly:

```python
def test_custom_monitor_ranking_retains_localized_group_descriptions() -> None:
    component = CustomMonitorComponent(config(style="ranking"))
    component.accept(completion_with_groups(
        ("slow", LocalizedText("Slow", "慢"), Decimal("2"), LocalizedText("slow help", "慢说明")),
        ("fast", LocalizedText("Fast", "快"), Decimal("9"), LocalizedText("fast help", "快说明")),
    ))

    english = component.ranking_model(language="en").observed_entries
    chinese = component.ranking_model(language="zh").observed_entries

    assert [(entry.key, entry.description) for entry in english] == [
        ("fast", "fast help"), ("slow", "slow help")
    ]
    assert [(entry.key, entry.description) for entry in chinese] == [
        ("fast", "快说明"), ("slow", "慢说明")
```

Also assert the ungrouped branch produces a `total` scalar entry with `description is None`, and retain one group with no description to prove backward-compatible `None` preservation.

- [ ] **Step 2: Run the projection tests to verify failure**

Run: `pytest tests/test_custom_monitor_component.py -k 'description' -v`

Expected: FAIL because the ranking entry and scalar ranking entry do not expose descriptions.

- [ ] **Step 3: Implement projection propagation**

Add defaulted optional description fields to `ScalarRankingEntry` and `CustomMonitorRankingEntry`. In `CustomMonitorComponent.ranking()`, build each sorted entry with `group.description`:

```python
CustomMonitorRankingEntry(group.id, group.label, group.value, group.description)
```

In `ranking_model()`, localize the description through the component’s existing `_localized` helper, preserving `None`:

```python
self._localized(entry.description, language) if entry.description is not None else None
```

Pass it as the sixth positional field or as `description=` to `ScalarRankingEntry`. Do not attach descriptions in `timeline_model().observed_current`, because the same scalar facts serve a non-ranking chart path and the requirement limits presentation to ranking.

- [ ] **Step 4: Run component tests**

Run: `pytest tests/test_custom_monitor_component.py -v`

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add src/ccusage_viz/chart_models.py src/ccusage_viz/custom_monitor_component.py tests/test_custom_monitor_component.py
git commit -m "feat: retain descriptions in custom monitor rankings"
```

### Task 3: Render descriptions only in detailed/full observed rankings

**Files:**
- Modify: `src/ccusage_viz/render/ranking.py:184-342`
- Test: `tests/test_custom_monitor.py` near `test_render_custom_monitor...` coverage

**Interfaces:**
- Consumes: `ScalarRankingEntry.description: str | None` from Task 2.
- Produces: `render_ranking(model, context, ...) -> str` with description rows only when `model.is_observed`, `context.style != "list"`, and `context.density in {"full", "detailed"}`.
- Uses: `_description_visible_text`, `_description_row_markup`, `wrap_width`, `display_width`, and `styled_text` already provided by `render.ranking_presentation`/formatting modules; export or add one focused public helper there if private helper access would otherwise be required.

- [ ] **Step 1: Write failing rendering tests**

Build a Custom Monitor component containing an ANSI-prefixed, long localized description and render it in ranking and each non-ranking style:

```python
def test_custom_monitor_ranking_renders_descriptions_only_at_complete_density() -> None:
    component = described_monitor_component()
    detailed = render_custom_monitor(component, context(style="dot", density="detailed", width=34))
    normal = render_custom_monitor(component, context(style="dot", density="normal", width=34))

    assert "Release validation" in detailed
    assert "\x1b[31m" not in detailed
    assert "Release validation" not in normal
    assert all(display_width(line) <= 34 for line in detailed.splitlines())


@pytest.mark.parametrize("style", ("list", "line", "bars"))
def test_custom_monitor_non_ranking_views_hide_group_descriptions(style: str) -> None:
    rendered = render_custom_monitor(described_monitor_component(style=style), context(style=style, density="detailed"))

    assert "Release validation" not in rendered
```

Use the actual presentation style identifiers accepted by the existing `config()` helper (for example `list`, `ranking`, and the existing timeline/bars identifiers). Assert the description occurs after the matching row label in detailed ranking. Add a description-free regression assertion that the current standard ranking output remains byte-for-byte unchanged when descriptions are omitted.

- [ ] **Step 2: Run the rendering tests to verify failure**

Run: `pytest tests/test_custom_monitor.py -k 'description' -v`

Expected: FAIL because observed rankings currently ignore scalar descriptions.

- [ ] **Step 3: Implement observed-ranking description rows**

In `render/ranking.py`, import the existing safe description helpers (make narrowly named public helpers in `ranking_presentation.py` if needed rather than duplicating parsing rules) and `wrap_width`. After appending an observed ranking bar row, append up to two muted wrapped description rows only under this exact gate:

```python
show_observed_description = (
    model.is_observed
    and context.style != "list"
    and context.density in {"full", "detailed"}
    and entry.description
    and not entry.is_other
)
```

Align the description under the observed label column using the existing observed row prefix width, calculate available width with `display_width`, sanitize/strip controls through the shared description helper, wrap to available width, and truncate the final visible row with an ellipsis when more than two wrapped rows exist. Apply the existing muted style (`scheme.muted` through `styled_text`) to each row. Restore only the established safe Markdown link markup if the shared helper supports it.

Do not alter the historical branch of `render_ranking()`, its layout dimensions, list branch, or `render_custom_monitor()` dispatch; the gate must make `list` description-free despite sharing the ranking model.

- [ ] **Step 4: Run rendering and regression tests**

Run: `pytest tests/test_custom_monitor.py tests/test_monitor.py tests/test_custom_component.py -v`

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add src/ccusage_viz/render/ranking.py src/ccusage_viz/render/ranking_presentation.py tests/test_custom_monitor.py
git commit -m "feat: render custom monitor ranking descriptions"
```

### Task 4: Document the additive Monitor protocol field

**Files:**
- Modify: `docs/custom-command-protocol.md:160-175` and the V2 Monitor response example section
- Modify: `docs/custom-command-protocol.zh-CN.md:74-86` and the corresponding response example section
- Test: `tests/test_architecture.py` only if documentation inventory/link checks require an update

**Interfaces:**
- Documents: optional `observation.groups[*].description` as localized text, compatibility for omitted field, malformed-value rejection, and ranking-only display behavior.
- Consumes: the parser/rendering behavior delivered by Tasks 1–3.

- [ ] **Step 1: Add protocol documentation**

In both language variants, add the same concrete Monitor group example:

```json
{
  "id": "basic",
  "label": {"en": "basic", "zh-CN": "basic"},
  "value": "69.2",
  "description": {"en": "Models sharing this pool", "zh-CN": "共享此额度池的模型"}
}
```

State exactly that the field is optional localized plain text; absent or empty descriptions do not render; malformed supplied localized values reject the response; and ccuv displays it beneath that group only in a Custom Monitor ranking when density is `full` or `detailed`, never in list, bars, or timeline views. Do not describe it as a metric description or add a new capability/default control.

- [ ] **Step 2: Run documentation-adjacent checks**

Run: `pytest tests/test_architecture.py -v && git diff --check`

Expected: PASS with no trailing whitespace or documentation inventory failure.

- [ ] **Step 3: Commit Task 4**

```bash
git add docs/custom-command-protocol.md docs/custom-command-protocol.zh-CN.md
git commit -m "docs: describe custom monitor group descriptions"
```

### Task 5: Run the focused and full validation suite

**Files:**
- No source changes expected.

**Interfaces:**
- Validates the protocol, component projection, renderer behavior, and repository-wide regressions delivered by Tasks 1–4.

- [ ] **Step 1: Run the focused feature suite**

Run:

```bash
pytest tests/test_custom_protocol.py tests/test_custom_monitor_component.py tests/test_custom_monitor.py -v
```

Expected: PASS.

- [ ] **Step 2: Run the full suite**

Run: `pytest -q`

Expected: PASS.

- [ ] **Step 3: Inspect final repository state**

Run:

```bash
git status --short
git log --oneline -4
```

Expected: only pre-existing unrelated worktree changes remain; the four feature commits are visible.

- [ ] **Step 4: Commit only if validation forced an intentional tracked correction**

If no files changed, do not create an empty commit. If an intentional correction was required, stage only the correction and commit:

```bash
git add <corrected-files>
git commit -m "test: cover custom monitor descriptions"
```
