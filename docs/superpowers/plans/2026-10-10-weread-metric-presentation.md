# WeRead Metric And Ranking Presentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade WeRead Gateway compatibility, make reading-time Rankings more intelligible, and add all-time notes composition as a grouping of the existing metric.

**Architecture:** Keep the existing V2 Dataset and two metrics. Extend typed Gateway facts with optional Book presentation data and note components, while Metric handlers remain responsible for protocol projections. No additional Gateway request is introduced: Ranking enrichment uses only `/readdata/detail`, and notebook component counts use only `/user/notebooks`.

**Tech Stack:** Go, standard-library JSON/HTTP, existing `ccuv.custom/v2` protocol types, Go tests.

**Spec:** `docs/superpowers/specs/2026-10-10-weread-metric-presentation-design.md`

## Global Constraints

- Every Gateway request must send `skill_version: "1.0.5"`.
- Preserve strict failure on non-null `upgrade_info`.
- Do not make `/book/info` or any additional request for Ranking enrichment.
- Keep `reading_time.summary` as `comparisons`.
- Set only `reading_time` Ranking `comparison` to `none`.
- Do not create a Metric or historical chart for note components.
- `total_notes.note_type` is all-time Ranking-only and contains highlight, thought-review, and bookmark facts.
- Do not tag, push, or publish a release.

---

## File Structure

- `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/weread/gateway.go` — Gateway version, optional ranking presentation parsing, and component note counts.
- `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/weread/weread.go` — typed `ReadingRanking` and `NoteCount` facts.
- `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/weread/gateway_test.go` — HTTP payload/version and parsed source-fact coverage.
- `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/metrics/readingtime/metric.go` — Ranking descriptor comparison policy and row presentation projection.
- `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/metrics/readingtime/metric_test.go` — descriptor and projected Ranking response coverage.
- `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/metrics/totalnotes/metric.go` — `note_type` descriptor and projection.
- `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/metrics/totalnotes/metric_test.go` — Book/total compatibility and `note_type` exact rows.
- `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/dataset/dataset_test.go` — serialized descriptor capability regression coverage where necessary.

## Task 1: Update Gateway Version and Preserve Optional Ranking Facts

**Files:**
- Modify: `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/weread/gateway.go`
- Modify: `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/weread/weread.go`
- Modify: `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/weread/gateway_test.go`

**Interfaces:**
- Produces `ReadingRanking{ID, Label, Seconds, Author, ReaderLink}` where optional strings are empty if unavailable.
- Produces `NoteCount{BookID, Label, Highlights, ThoughtsReviews, Bookmarks}` plus an existing total convenience method or derived calculation.

- [ ] **Step 1: Write failing Gateway tests**

Add one Book ranking parsing test with author and reader link, and one request payload assertion:

```go
func TestParseBookRankingRetainsOptionalPresentation(t *testing.T) {
    records, err := parseBookRanking(json.RawMessage(`[{"book":{"bookId":42,"title":"Book","author":"Author","readerLink":"https://weread.qq.com/web/reader/42"},"readTime":120}]`))
    if err != nil || records[0].Author != "Author" || records[0].ReaderLink == "" {
        t.Fatalf("records = %#v, err = %v", records, err)
    }
}

func TestGatewayUsesSkillVersionOneZeroFive(t *testing.T) {
    gateway := testGateway(t, func(body map[string]any) string {
        if body["skill_version"] != "1.0.5" { t.Fatalf("skill_version = %#v", body["skill_version"]) }
        return `{"errcode":0,"totalReadTime":0,"dailyReadTimes":{}}`
    })
    _, _ = gateway.DailyRecords(context.Background(), []v2.Range{{StartDate:"2026-09-17", EndDate:"2026-09-17"}})
}
```

Add a notebook test asserting individual counts rather than only aggregate total.

- [ ] **Step 2: Run focused tests and observe failure**

```bash
cd /Users/bytedance/Projects/go/ccuv-dataset-weread
go test ./internal/weread -run 'Test(ParseBookRankingRetainsOptionalPresentation|GatewayUsesSkillVersionOneZeroFive)' -v
```

Expected: FAIL because the current fact type has no `Author` / `ReaderLink`, and requests use `1.0.4`.

- [ ] **Step 3: Implement typed optional fields and version upgrade**

- Change `skillVersion` to `"1.0.5"`.
- Add `Author string` and `ReaderLink string` to `ReadingRanking`.
- Add fields `Highlights`, `ThoughtsReviews`, and `Bookmarks` to `NoteCount`.
- Parse optional `book.author` and `book.readerLink` from `readLongest`. Preserve a `readerLink` only when it parses as an absolute `https://` URL; silently omit malformed/other-scheme values.
- Map `noteCount`, `reviewCount`, and `bookmarkCount` to the three `NoteCount` fields. Keep overflow checks.

- [ ] **Step 4: Run Gateway suite**

```bash
cd /Users/bytedance/Projects/go/ccuv-dataset-weread
gofmt -w internal/weread/gateway.go internal/weread/weread.go internal/weread/gateway_test.go
go test ./internal/weread -v
```

Expected: PASS.

- [ ] **Step 5: Commit Gateway compatibility**

```bash
cd /Users/bytedance/Projects/go/ccuv-dataset-weread
git add internal/weread/gateway.go internal/weread/weread.go internal/weread/gateway_test.go
git commit -m "fix: update weread gateway skill version"
```

## Task 2: Improve Reading-Time Ranking Projection

**Files:**
- Modify: `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/metrics/readingtime/metric.go`
- Modify: `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/metrics/readingtime/metric_test.go`

**Interfaces:**
- Produces `reading_time` Ranking capability with `comparison: "none"`.
- Produces Book Ranking series with optional `description`, `display`, and `link`; Category series have only localized duration `display`.

- [ ] **Step 1: Write failing metric tests**

Add a Book Ranking test with a fake record and assert wire payload fields:

```go
func TestBookRankingAddsReadablePresentation(t *testing.T) {
    response := New(weread.FakeGateway{RankingRecords: []weread.ReadingRanking{{ID:"book:42", Label:"Book", Seconds:7440, Author:"Author", ReaderLink:"https://weread.qq.com/web/reader/42"}}}).Chart(context.Background(), rankingRequest("book"))
    encoded, _ := json.Marshal(response)
    for _, want := range []string{`"display":{"en":"2h 4m","zh-CN":"2小时4分钟"}`, `"description":{"en":"Author","zh-CN":"Author"}`, `"link":"https://weread.qq.com/web/reader/42"`} {
        if !bytes.Contains(encoded, []byte(want)) { t.Fatalf("missing %s in %s", want, encoded) }
    }
}

func TestReadingTimeRankingDisablesPriorRangeComparison(t *testing.T) {
    if Descriptor().Capabilities.Charts["ranking"].Comparison != "none" { t.Fatal("Ranking comparison remains enabled") }
}
```

Adapt expected struct fields to the protocol package's concrete `ChartCapability` representation.

- [ ] **Step 2: Run focused metric tests and observe failure**

```bash
cd /Users/bytedance/Projects/go/ccuv-dataset-weread
go test ./internal/metrics/readingtime -run 'Test(BookRankingAddsReadablePresentation|ReadingTimeRankingDisablesPriorRangeComparison)' -v
```

Expected: FAIL because the capability lacks the comparison field and projection emits only IDs, labels, and points.

- [ ] **Step 3: Implement descriptor and presentation projection**

- Extend `v2.ChartCapability` if it does not already have `Comparison string \`json:"comparison,omitempty"\``.
- Set only `reading_time` Ranking's `Comparison` to `"none"`.
- Add `formatDisplay(seconds uint64) v2.LocalizedText`, rounding down to whole minutes and formatting English `Xh Ym` / Chinese `X小时Y分钟`; include minutes even when hours are zero.
- Build each Ranking series as a `map[string]any` or protocol extension that serializes standard `id`, `label`, `points`, plus `display` for all ranking rows. Add `description` only for non-empty Book authors and `link` only for a non-empty validated ReaderLink.
- Keep Timeline/Calendar/Stack response series unchanged.

- [ ] **Step 4: Run reading-time tests**

```bash
cd /Users/bytedance/Projects/go/ccuv-dataset-weread
gofmt -w internal/protocol/v2/protocol.go internal/metrics/readingtime/metric.go internal/metrics/readingtime/metric_test.go
go test ./internal/protocol/v2 ./internal/metrics/readingtime -v
```

Expected: PASS.

- [ ] **Step 5: Commit Ranking presentation**

```bash
cd /Users/bytedance/Projects/go/ccuv-dataset-weread
git add internal/protocol/v2/protocol.go internal/metrics/readingtime/metric.go internal/metrics/readingtime/metric_test.go
git commit -m "feat: enrich weread reading rankings"
```

## Task 3: Add `note_type` to Existing Total Notes Ranking

**Files:**
- Modify: `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/metrics/totalnotes/metric.go`
- Modify: `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/metrics/totalnotes/metric_test.go`
- Modify: `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/dataset/dataset_test.go`

**Interfaces:**
- `total_notes` supports `group_by: "book" | "note_type"` only for all-time Ranking.
- `note_type` returns IDs `highlight`, `thought-review`, `bookmark` with component sums.

- [ ] **Step 1: Write failing note-type tests**

```go
func TestChartProducesNoteTypeComposition(t *testing.T) {
    gateway := weread.FakeGateway{Notes: []weread.NoteCount{
        {BookID:"1", Label:"One", Highlights:2, ThoughtsReviews:3, Bookmarks:5},
        {BookID:"2", Label:"Two", Highlights:7, ThoughtsReviews:11, Bookmarks:13},
    }}
    response := New(gateway).Chart(context.Background(), rankingRequest("note_type"))
    encoded, _ := json.Marshal(response)
    for _, want := range []string{`"id":"highlight"`, `"value":"9"`, `"id":"thought-review"`, `"value":"14"`, `"id":"bookmark"`, `"value":"18"`} {
        if !bytes.Contains(encoded, []byte(want)) { t.Fatalf("missing %s: %s", want, encoded) }
    }
}

func TestDescriptorDeclaresNoteTypeGrouping(t *testing.T) {
    // Assert dimensions are book and note_type, while the sole chart keeps periods ["all"].
}
```

Also retain/add a Book grouping assertion that confirms its value is the sum of the three components.

- [ ] **Step 2: Run focused total-notes tests and observe failure**

```bash
cd /Users/bytedance/Projects/go/ccuv-dataset-weread
go test ./internal/metrics/totalnotes -run 'Test(ChartProducesNoteTypeComposition|DescriptorDeclaresNoteTypeGrouping)' -v
```

Expected: FAIL because `note_type` is not declared or accepted.

- [ ] **Step 3: Implement note composition**

- Add `note_type` localized dimension after `book` in the Metric descriptor.
- Make validation accept exactly `book` and `note_type`; retain `period: "all"` as the only legal period.
- For `book`, return `Highlights + ThoughtsReviews + Bookmarks` per book with checked `uint64` addition.
- For `note_type`, aggregate each component across all notebook records with checked `uint64` addition and return the three fixed bilingual series.
- Keep Summary total equal to the sum of all three components.

- [ ] **Step 4: Run total-note and Dataset tests**

```bash
cd /Users/bytedance/Projects/go/ccuv-dataset-weread
gofmt -w internal/metrics/totalnotes/metric.go internal/metrics/totalnotes/metric_test.go internal/dataset/dataset_test.go
go test ./internal/metrics/totalnotes ./internal/dataset -v
```

Expected: PASS.

- [ ] **Step 5: Commit note grouping**

```bash
cd /Users/bytedance/Projects/go/ccuv-dataset-weread
git add internal/metrics/totalnotes/metric.go internal/metrics/totalnotes/metric_test.go internal/dataset/dataset_test.go
git commit -m "feat: group weread notes by type"
```

## Task 4: End-to-End Regression and Local Acceptance

**Files:**
- Modify if regenerated: `/Users/bytedance/Projects/go/ccuv-dataset-weread/manifest.json`
- Modify if regenerated: `/Users/bytedance/Projects/go/ccuv-dataset-weread/dist/*`

- [ ] **Step 1: Regenerate static manifest**

```bash
cd /Users/bytedance/Projects/go/ccuv-dataset-weread
go run ./cmd/manifest --os darwin --arch arm64 --out manifest.json
```

Expected: manifest declares `skill_version`-independent metadata where reading Ranking has `comparison: "none"` and total notes declares both groupings.

- [ ] **Step 2: Run all Go tests**

```bash
cd /Users/bytedance/Projects/go/ccuv-dataset-weread
go test ./...
```

Expected: PASS.

- [ ] **Step 3: Verify tokenread-equivalent live query**

```bash
cd /Users/bytedance/Projects/go/ccuv-dataset-weread
printf '%s\n' '{"protocol":"ccuv.custom/v2","request_id":"tokenread-check","request_kind":"chart","dataset_id":"weread","metric_id":"reading_time","timezone":"Asia/Shanghai","range":{"start_date":"2026-10-01","end_date":"2026-10-10","period":"1mo"},"query":{"filters":{},"group_by":"book","granularity":"day","top":9}}' | ./ccuv-dataset-weread ccuv | jq -e '.status == "ok"'
```

Expected: `true` with `WEREAD_API_KEY` in the environment. If no key is configured, verify the command instead returns the existing actionable source error.

- [ ] **Step 4: Package the native archive**

```bash
cd /Users/bytedance/Projects/go/ccuv-dataset-weread
./scripts/package.sh darwin arm64 dist/ccuv-dataset-weread-darwin-arm64.tar.gz
```

Expected: structural and native V2 Probe verification pass.

- [ ] **Step 5: Commit generated manifest/artifacts if tracked**

```bash
cd /Users/bytedance/Projects/go/ccuv-dataset-weread
git add manifest.json
git add -f dist/ccuv-dataset-weread-darwin-arm64.tar.gz 2>/dev/null || true
git commit -m "build: refresh weread dataset metadata"
```

## Plan Self-Review

- **Spec coverage:** Task 1 implements v1.0.5 plus strict source normalization; Task 2 implements Ranking display and per-row comparison suppression only; Task 3 adds `note_type` without extra Metric or fabricated history; Task 4 validates source, package, and live preset-equivalent behavior.
- **Placeholders:** All changes identify exact files, interfaces, commands, and expected outcomes.
- **Consistency:** `thought-review`, `comparison: "none"`, component source fields, and V2 request forms use identical names across all tasks.
