# Technical Audit — mstr-tableau-migrator Specification

**Auditor role:** Principal BI Migration Architect & Reverse Engineering Auditor
**Scope:** `spec/architecture.md`, `spec/agents.md`, `spec/api.md`, `spec/database.md`, `spec/ir-schema.md`, `spec/expression-compiler.md`, `MSTR-Tableau-Migration-Feasibility-Report.md`, `MSTR-Tableau-Agents-Complete.md`
**Posture:** adversarial. No praise. Findings are ordered by production impact.

---

## 1. Top 5 Critical Flaws / Fatal Assumptions

### F1 — The core dimty→LOD mapping is semantically wrong under filters (data-corruption class)

The pattern catalog (`expression-compiler.md` §3.4) maps `Sum(Fact){Year}` → `{FIXED [Year] : SUM([Fact])}` at confidence 0.82, and `ir-schema.md` ships this as the canonical example. This is the single most dangerous line in the spec.

MSTR dimty semantics: a level metric with target `Year` and `filtering=standard` **still respects the report filter**, resolved at the metric's target grain by the analytical engine. Tableau's Order of Operations evaluates `{FIXED ...}` **before dimension filters** — so the moment a migrated dashboard has a dimension filter (e.g. Region = East, or any date filter below Year), the FIXED calc silently computes over the unfiltered fact table while everything else on the sheet is filtered. The KPI tile next to it says one number, the LOD-derived metric says another. No error is raised anywhere; the workbook publishes green.

The spec contains no mechanism for this: no context-filter promotion, no filter-aware LOD rewriting, no rule that dimension filters affecting a FIXED calc's inputs must be emitted as Tableau **context filters** in the worksheet XML. Confidence 0.82 on this pattern is inverted — it should be a conditional compilation that inspects the dossier's chapter/viz filters before choosing between FIXED-with-context-filters, INCLUDE, or a pre-aggregated scaffold. As specced, the most common level-metric pattern produces wrong financials with a passing scorecard.

### F2 — Transformation metrics are mistranslated by construction, and the spec's own golden example proves it

`Sum(Revenue){~+, Year-1}` is mapped to `LOOKUP(SUM([Fact]), -1)` at 0.65 confidence. `LOOKUP` is a **table calculation**: it addresses whatever rows survive into the viz pipeline. Filter the dashboard to Year = 2026 and the prior year is physically absent from the addressing set — the denominator evaluates to NULL, YoY evaluates to NULL, and the dashboard silently blanks. MSTR's `Year-1` is resolved against the warehouse via transformation tables and is completely immune to viz-level filtering.

Worse, the complex-measure example in `ir-schema.md` §3.4 emits `"compiledTableau": "SUM([Revenue]) / {FIXED [Year]: SUM([Revenue])}"` for `Sum(Revenue) / Sum(Revenue){~+, Year-1}` — **the offset is simply dropped**. That expression is identically 1.0 for every row. And the golden test in `expression-compiler.md` §6 for the fixed-year pattern lists expected results `[{Year:2025 → 3000}, {Year:2026 → 3000}]` on input where 2025 sums to 3000 and 2026 sums to 3000 — the fixture cannot distinguish a correct FIXED from a broken one because both years coincidentally equal 3000. The golden harness as authored **cannot catch the exact bug class it exists to catch.**

The correct primary strategy is a shifted-key join (join the date dimension to itself on `Year-1` key, i.e. replicate the MSTR transformation table) or a pre-computed prior-period column in the Hyper build — deterministic, filter-immune, and validatable. LOOKUP should be the last-resort fallback with a mandatory "user must not filter below the offset grain" warning, not the default template.

### F3 — ADR-012 (one shared published datasource per project) is incompatible with the calc strategy and with itself

Three contradictions:

1. **Local calcs vs. published DS.** Ten dossiers, each with dossier-specific derived metrics and renamed fields, cannot all live on one published datasource without either (a) polluting the shared DS with every dossier's local calcs — guaranteed name collisions when two dossiers define different "Profit Margin" — or (b) keeping calcs workbook-local, which the spec never wires up (workbook-local calcs on a published-DS connection require specific `<datasource caption='...'>` federation XML that is absent from the emitter spec).
2. **Security.** ADR-011 puts entitlement tables inside the Hyper extract with a `FULLNAME()` match. A single shared DS means a single unioned entitlement model for the whole project — MSTR security filters are object-scoped, and different dossiers legitimately apply different predicates. One shared DS forces the union or the intersection; both are wrong for someone.
3. **Data provenance.** HyperAgent extracts *cube result sets* (post-aggregation, post-filter, grid-shaped). A shared multi-table DS with relationships requires *base tables* at joinable grain. You cannot build `fact_sales` + `lu_region` with FK relationships out of cube JSON payloads — the spec conflates "cube extract for validation" with "base table extract for the shared model" and never reconciles them. The mixed live+Hyper strategy (`architecture.md` §2) makes this worse: which tables are live, which are extract, and how does a relationship span the boundary?

### F4 — The extraction path will not survive contact with a real Intelligence Server, and the runtime cannot survive the extraction path

- `agents.md` HyperAgent pseudocode pages `offset += 10000` against a cube instance with **no session keep-alive, no instance-refresh handling, no resume**. MSTR cube instances are server-side stateful objects tied to the session; `X-MSTR-AuthToken` expiry or I-Server recycling the instance mid-walk kills the extract, and the code restarts from row 0. There is no checkpoint table in `database.md` for extraction offsets — `jobs` tracks stage-level progress only.
- `pd.DataFrame(all_rows)` accumulates the entire cube in memory. "< 200 reports/cubes" says nothing about row counts; a single 5M-row cube instance with 40 columns is a multi-GB Python object in a single-process FastAPI app, inside an event loop.
- FastAPI `BackgroundTasks` + synchronous `tableauhyperapi` calls + in-memory DataFrame assembly = a blocked event loop. The Next.js UI polling `GET /jobs/{id}` will hang behind the Hyper build. The spec's own deployment model (§3.4) forbids the fix (no workers, no queue) without saying so.
- SQLite `check_same_thread: False` with per-log-line `SessionLocal()` commits (AuditLogger `_write` commits per event; ADR-010 mandates logging *every API call*) is a write-lock convoy under any parallelism: `database is locked` errors during exactly the heavy stages.

### F5 — The validation gate is not implementable as specced, so the auto-publish decision is unfounded

`ValidationAgent` promises "Critical KPI values: pairwise comparison under same filters, ≤ 0.1%." But:

- There is no specified mechanism to **execute** the generated Tableau artifact and read back KPI values. Hyper API can query the `.hyper` file — but that validates raw rows, not LOD calcs, table calcs, or context-filter interactions, which only resolve inside Tableau's viz engine. The only real read-back paths are Tableau Server's View Data / Export Crosstab APIs after publish — meaning the gate order in the orchestrator (VALIDATE → PUBLISH) is inverted: you must publish to a scratch project to validate, which the spec never mentions.
- "TWB opens — attempt open via Tableau Server API (if possible)" — no such API exists. Publish-failure or a headless Desktop/tabadmin round-trip are the only open tests. The scorecard has an `open_test` check type with no implementation behind it.
- Golden datasets are hand-curated JSON per dossier (`golden_tests/project_{id}/dossier_{id}/`). For a customer estate, nobody has produced these yet, and the spec has no agent that derives them from MSTR execution results. As specced, `auto_publish_ok` will be computed against an empty golden set — i.e., vacuously passing or vacuously failing depending on default handling, which is unspecified.

The entire commercial claim (≥98% numeric match, gated auto-publish) rests on this agent, and it is the least-specified agent in the document.

---

## 2. Semantic Engine Deep-Dive (MSTR ↔ Tableau Traps)

### 2.1 The full dimty→LOD failure taxonomy

| MSTR construct | Naïve Tableau translation | Why it fails |
|---|---|---|
| `Sum(F){Year}` filtering=standard + any dimension filter in the viz | `{FIXED [Year]: SUM([F])}` | FIXED bypasses dimension filters (OoP step 3 vs. step 5). Requires context-filter promotion of the interacting filters, or the number is wrong. |
| `Sum(F){~+}` "report level" | "same as simple, no LOD needed" (§3.4) | Wrong whenever the metric is nested inside another metric or conditionality. Report-level means "ignore template grouping, respect filter" — in Tableau that's a `{FIXED : SUM(...)}` with **all** report filters promoted to context. Treating it as a plain SUM changes results on any grouped sheet. |
| `Sum(F){~-Year}` | `{EXCLUDE [Year]: ...}` | EXCLUDE removes the dimension from the **viz** LOD. If Year isn't on the view, the EXCLUDE is a no-op; if the user drills Year into the view later, the number changes. MSTR's exclusion is grain-of-calculation, not viz-dependent. |
| allowAddition=false (e.g. inventory balance metrics) | ignored entirely in the IR (`dimty.allowAddition` is captured but never consumed by any rule) | Tableau will happily re-aggregate a SUM over a semi-additive measure. No guard exists. |
| `Sum(F){~+, Year-1}` | `LOOKUP(SUM([F]),-1)` | NULLs whenever the prior period is filtered out of the viz; wrong result (not just NULL) when Year is sparse or the sort order changes. |
| Nested level metrics | "Nested LOD" at 0.55 | Nested LODs in Tableau have inner/outer scoping rules (inner computed at outer context) that do not compose like MSTR's bottom-up multi-pass engine. MSTR runs multi-pass SQL (its core architectural feature); Tableau LODs are single-pass per query block. Arbitrary nesting depth is not expressible. |

### 2.2 Conditional metrics: WHERE vs. HAVING

`Sum(Fact) {Filter}` → `SUM(IF [Filter_Field]='Value' THEN [Fact] END)` (confidence 0.88) is only correct when the condition is a **row-level attribute qualification**. MSTR conditions can be:

- **Metric qualifications** (`Revenue > 1000000` applied as a HAVING on an aggregated band) — translating to a row-level IF changes the semantics entirely; needs `IF SUM(...) > ... THEN SUM(...) END` with the LOD grain explicitly resolved.
- **Metric-in-condition references** and **prompt-in-condition references** — the condition references another metric or an unanswered prompt. The IR `Filter.predicate` model (`op/field/value` with a literal `value`) has no slot for either. ADR-013 defers prompts but doesn't say what happens to the *conditional metrics that embed prompt references* — they will silently compile with a literal placeholder or fail schema validation; the spec doesn't define which.
- **Filter interaction / merge options** (MSTR lets the metric choose how report filter and metric condition merge: intersect, union, replace). Captured nowhere in the IR. `conditionality` is typed as `null` in every example and never schema'd.

### 2.3 NULL/zero semantics

`NullToZero(Fact)` → `ZN([Fact])` (§3.7) places the coalesce at row level. If the MSTR intent is post-aggregation (`NullToZero` around a Sum of an empty set → 0), the correct translation is `ZN(SUM([Fact]))`, and for an empty filtered set Tableau returns NULL before ZN ever runs on some paths. The pattern table doesn't distinguish pre- vs post-aggregation coalescing; placement changes division results (`0/x` vs `NULL/x`). Also: MSTR's default null-handling in arithmetic is configurable per project (`NULL propagation` VLDB setting) — never extracted, never modeled.

### 2.4 Compound and cross-dataset metrics — entirely absent

Dossiers routinely blend metrics from **multiple cubes** on one page. MSTR resolves this at render time via dataset joining; Tableau requires either a blended datasource (legacy, limited) or a unified model. The IR has a single `datasource` per worksheet, `DossierDef.datasets[]` is extracted but the IR `Worksheet` has no multi-dataset concept, and no agent decides a dataset-merge strategy. A compound metric whose operands live in different cubes is unrepresentable.

### 2.5 Attribute forms, compound keys, and fan-out

- Multi-form attributes (ID / DESC / ALT_DESC): the IR models forms as fields with `role: id/display`, but **DESC forms are not unique** in real warehouses (two region IDs, one DESC). If the emitter puts the DESC field on the relationship or uses it as a join/display key, you get row fan-out. The join key must always be the ID form, and DESC-only groupings must be validated for uniqueness — no such rule exists.
- **Compound attribute keys** (attribute whose key is two columns, e.g. Store = City+Store#) — the IR `Relationship` is single-column (`fromColumn`/`toColumn`). Unrepresentable as specced; forces a concatenated-key materialization step nobody specified.
- MSTR's **heterogeneous fact mapping** (same fact, different expressions on different tables at different grains) collapses to one `sourceColumn` in the IR.

---

## 3. Tableau Generation & XML Gotchas

Under-specified or missing in `TableauEmitterAgent` (the spec says "inject datasource/worksheets/dashboards" and stops):

1. **Field identity & renaming.** Worksheet XML references fields by caption (`[Revenue]`). MSTR object names are not unique per project; Tableau field captions in a datasource are. The spec has no name-disambiguation strategy, and no mapping from IR field ID → emitted caption → `remote-name` (physical column). Every worksheet `<pane>`/shelf reference, every filter `<filter class='categorical'>` member, and every calc reference must use the *post-disambiguation* caption. `database.md`'s `tableau_field_name` suggests awareness but the emitter section never states the invariant.
2. **Calculated field XML.** Each calc needs a `<column caption=... datatype=... role='measure' type='quantitative'>` **plus** a `<calculation class='tableau' formula='...'/>` child with the formula **entity-encoded** (`&gt;`, `&amp;`, quotes). LOD braces and parameter references have additional encoding traps. Not mentioned. The name-based `Calculation_##########` fallback Tableau uses internally is what produces the classic `Field '[Calculation_12345]' does not exist` open-failures when a sheet references a calc that wasn't materialized into the datasource's column list — the spec must mandate that every referenced calc exists in `<datasource><column>` before any worksheet references it, and that `formula` and references use identical captions.
3. **Logical vs. physical layer.** The spec never decides: `<relation>` "noodles" (logical layer, requires `join` clause XML with `type='Inner'` and clause expressions) or physical joins/Custom SQL. "Assumed FKs in Hyper" (repeated in agents.md, feasibility report, agent pack) is a **server-side publish-time inference** feature — it does not put relationship XML into your `.tds`. If the TDS declares no relations, you get a single-table extract view or an inference you don't control, version-dependent. The emitter must explicitly generate the relationship layer XML; "assumed FKs" as a strategy is a category error.
4. **Extract connection XML.** A `.twbx` referencing its packaged Hyper uses `<connection class='federated'>` with an `extract` sub-connection and a **relative path** into the package (`Data/Extracts/...`). Absolute local paths from `artifacts/jobs/{id}/` will produce workbooks that open with "extract not found" on any other machine. Path rewriting at ZIP time is unspecified.
5. **Dashboard zones.** Auto-tiled layout still requires a valid `<zones>` gridtree with unique zone ids, `type-v2` attributes, size nodes, and zone-per-worksheet wiring including `<zone>` param/`field` references for dashboard filters. "auto-tiled" is a layout decision, not an XML decision. A structurally valid but semantically orphaned zone (missing `id` linkage to the worksheet) opens as an empty dashboard — this is the most common XSD-passing/open-failing failure mode and the feasibility report already lists it as an open **[ASM]** experiment; the emitter spec ignores it.
6. **Number formats / fonts** are per-`<format>` attr entries on columns and per-style `style-rule` elements with `element`/`attr` scoping; MSTR thresholds (conditional formatting) are explicitly skipped in agents.md but the feasibility report's validation matrix grades formatting as "informational" — fine — yet the emitter section promises "font sizes, colors" without specifying the `style-rule` mutation sequence. Partial formatting injection is the easiest way to produce a corrupt `<style>` block (styles must be valid against the workbook's `style` element ordering).
7. **User-filter wiring (ADR-011).** The entitlement join must live in the physical/logical layer XML **and** the `FULLNAME() = [EntitlementUser]` predicate must be emitted as a datasource filter on every consumer workbook — with the entitlement fields hidden. None of these three artifacts (relation XML, DS filter XML, hidden-field flags) appear in the emission sequence.
8. **XSD coverage.** `tableau-document-schemas` validates structure, and Tableau explicitly warns it is not a semantic guarantee. The spec treats "XSD validate" (step 7) as the pre-publish gate and then offers no open test. The only honest gate: publish to a scratch project on the target server and attempt server-side render/export, then delete or promote. That step doesn't exist in the pipeline.

---

## 4. Missing Edge Cases Matrix

| # | Edge case | Where spec is silent | Risk | Engineering fix |
|---|---|---|---|---|
| 1 | Dimension filter interacting with FIXED LOD | expression-compiler §3.4, emitter filters | **Critical** (wrong numbers, silent) | Filter-interaction analysis at compile time; emit interacting filters as context filters; else block with issue |
| 2 | Transformation metric under viz filter | §3.5 | **Critical** | Shifted-key join / precomputed prior-period columns in Hyper; LOOKUP only as flagged fallback |
| 3 | Metric condition containing prompt reference | ADR-013, IR Filter schema | High | New IR node `conditionRef: prompt`; blocker-severity until prompt MVP |
| 4 | Compound attribute keys | ir-schema §3.2 Relationship | High | Multi-column `joinKeys[]`; materialize surrogate key in Hyper build |
| 5 | Non-unique DESC forms used as display/grouping | ir-schema §3.3 | High (fan-out) | Uniqueness validation on form stats during Semantic; always join on ID form |
| 6 | Heterogeneous fact expressions per table | ir-schema Fact/Table | High | `factMappings[]` per table on Measure; emit per-table columns + coalesce calc |
| 7 | Custom groups with slicing / nested derived elements | feasibility matrix only | High | Enumerate elements → Tableau Group calc (CASE); block slicing mode |
| 8 | Consolidations | "Review" row only | Medium | Explicit blocker issue + manual task template |
| 9 | Multi-dataset dossiers / compound cross-cube metrics | IR Worksheet.datasource | High | Dataset-merge strategy decision in GraphAgent; else split sheets |
| 10 | Semi-additive metrics (allowAddition=false) | captured, never consumed | High | Compile-time guard + `AGG()`-wrapping prohibition; mark measure non-reaggregatable |
| 11 | Security: user in multiple groups, overlapping entitlements | ADR-011 | High (row duplication ⇒ inflated KPIs) | Entitlement table must be distinct (user, attribute, value); join at physical layer with MIN-grain; validate row-count parity per user in golden tests |
| 12 | Security filter with ApplyComparison/apply functions | agents.md Semantic | Medium | Predicate allowlist; else blocker + human sign-off (consistent with AI policy) |
| 3 | Cube instance expiry / token refresh mid-extract | HyperAgent pseudocode | High | Session keep-alive loop, offset checkpoint table, resume-from-offset |
| 14 | FFSQL with temp tables / multi-pass SQL | issue category exists only | Medium | Capture SQL text; Custom SQL DS path; stored-proc → blocker |
| 15 | VLDB null-propagation & join-type settings per metric | nowhere | Medium | Extract VLDB settings; model `nullPropagation` in IR measure |
| 16 | MSTR name collisions → Tableau caption collisions | emitter | High | Deterministic caption disambiguation + IR→caption registry persisted in DB |
| 17 | Dossier selectors / chapter filters → dashboard actions | VisualizationAgent | Medium | Selector → dashboard filter action XML; unsupported selector types → issue |
| 18 | RSD documents | feasibility says infeasible; agents.md still walks "reports" into waves | Medium | Hard-scope exclusion in DiscoveryAgent; report-only estate → explicit banner |
| 19 | Incremental refresh / post-migration data drift | ADR-009 | Medium | At minimum emit refresh schedule recommendation; Hyper files are snapshots — state this in report |
| 20 | Audit log write convoy on SQLite | database.md §5 | Medium | Batch audit writes, WAL mode, or file-based jsonl with periodic flush |
| 21 | Empty-set conditional metrics & ZN placement | §3.7 | Medium | Pre/post-aggregation flag on null-handling patterns |
| 22 | Time intelligence on non-Gregorian/fiscal calendars | §3.5 | Medium | Fiscal calendar table in Hyper; transformation table replication, not LOOKUP |
| 23 | Table calc filters (MSTR view filters) vs. report filters | nowhere | Medium | View-filter concept missing from IR entirely; map to table-calc-filter pattern or issue |
| 24 | LLM cache poisoning: Tier-1 stores "validated" translations with no record of *which* golden suite validated them | expression-compiler §4 | Medium | Cache entry must carry golden-suite version; invalidate on suite change |

---

## 5. Concrete Action Plan & Spec Errata

Ordered; nothing in phase B should start before phase A items land.

### Phase A — Correctness-blocking errata

**`spec/ir-schema.md`**
1. Fix the YoY example (§3.4): the `compiledTableau` must include the offset mechanism, and the chosen mechanism must be the shifted-join/scaffold strategy, not a bare FIXED. Add a `transformation` block to Measure: `{strategy: "shifted_join" | "precomputed_column" | "table_calc_fallback", offset, grain, transformationTableRef}`.
2. Extend `Relationship`: `joinKeys: [{fromColumn, toColumn}]` (array, not scalar); add `cardinality` and `crossFilter` semantics decision.
3. Schema `conditionality` (currently untyped `null` everywhere): `{predicate, mergeOption: intersect|union|replace, phase: where|having, promptRefs[]}`.
4. Add `grainContract` to Measure: `allowAddition`, `semiAdditive: bool`, `nullPropagation`.
5. Add `contextFilterRequirements: [filterId]` to Measure/Worksheet — the output of the filter-interaction analysis (F1).
6. Add per-table `factMappings[]` for heterogeneous facts; add `surrogateKey` declaration for compound keys.
7. Add `viewFilters` distinct from report `filters` on Worksheet.

**`spec/expression-compiler.md`**
8. Rewrite §3.4: FIXED translation is **conditional** — legal only when no non-context dimension filter can interact; the compiler must receive the dossier filter context as input (currently `CompilationContext` is unspecified — define it: dossier filters, page filters, shelf grain).
9. Rewrite §3.5: default transformation strategy = shifted-key join against a replicated MSTR transformation table; `LOOKUP` demoted to `severity=warning` fallback with a hard "filter-above-grain only" constraint. Delete the `"{FIXED [Year]-1 : ...}"` alternative — that is not valid Tableau syntax at all (LOD dimensions are field refs, not arithmetic expressions).
10. Fix the §6 golden fixtures so expected results actually discriminate (use asymmetric input data: 2025→3000, 2026→3000 is a non-test). Mandate a fixture linter: expected values must differ across grain rows.
11. §3.7: split null handling into pre-aggregation (`ZN([F])`) vs post-aggregation (`ZN(SUM([F]))`) patterns keyed off the AST position.
12. Tier-1 cache entries carry `goldenSuiteVersion`; §4 `HashLookup.store` gains suite-version invalidation.

**`spec/agents.md`**
13. HyperAgent: add session keep-alive, token refresh, per-offset checkpoint rows (new table), streaming insert (chunked `Inserter` from paginated iterator — never a full in-memory DataFrame), and a documented memory ceiling. Fix the pseudocode accordingly.
14. ValidationAgent: specify the actual read-back mechanism — publish-to-scratch-project + Export Crosstab / View Data API for calc-level checks; Hyper direct queries for base-row checks; golden datasets are *generated by executing MSTR reports/cubes at controlled prompts*, not hand-authored. Reorder gate: EMIT → PUBLISH(staging) → VALIDATE → PROMOTE/DEMOTE.
15. Orchestrator: add per-wave/per-object resumability (artifact-addressed checkpoints keyed by object versionId), so a crash in Wave 3 never re-runs Wave 0 extraction.
16. VisualizationAgent: selector → dashboard action mapping table; unsupported selector types produce issues, not silent drops.
17. DiscoveryAgent: extract VLDB settings, project null-propagation config, fiscal calendar definition, and transformation tables into the catalog.

**`spec/architecture.md`**
18. ADR-012 revision: shared published DS **per security/folder domain**, not per project; or one shared DS + explicit workbook-local-calc federation spec with a caption-collision registry. State which and delete the other.
19. ADR-014 revision: "silently skip unused" must become "skip with an explicit inventory entry in the report" — silent deletion of security-relevant or dependency-relevant objects is an audit failure.
20. Add an ADR for execution isolation: run Hyper builds and MSTR extraction in a separate process (`ProcessPoolExecutor`/`multiprocessing` worker or a second uvicorn worker) — the single-process constraint is fine, the single-*event-loop* constraint is not; the spec conflates them.
21. Add WAL mode + batched audit writes to the SQLite decision (ADR-002 amendment).
22. Reconcile "live + Hyper mixed" (§2) with the physical model: define which IR `Table.tableType` values map to live vs. extract, and forbid relationships spanning the boundary (or specify Custom SQL bridging).

### Phase B — Hardening

23. Emitter spec (agents.md §Agent 8) needs a real mutation-sequence section: datasource columns+calcs first, relationship XML second, worksheets third, zones fourth, styles last; caption registry consulted at every step; relative-path rewrite at packaging; scratch-publish open test after XSD.
24. api.md: `POST /review/{id}/edit-ir` must re-run the full validation path (currently shows golden-test pass inline); add `POST /jobs/{id}/resume` and checkpoint inspection endpoints.
25. database.md: add `extract_checkpoints(job_id, object_id, offset, etag, updated_at)` and `caption_registry(job_id, ir_id, caption)` tables.

### Kill list (statements to delete from the spec)

- "`Sum(Fact){~+}` (report level) → `SUM([Fact])` (same as simple — no LOD needed)" — false in nested/conditional contexts.
- "`{FIXED [Year]-1 : SUM([Fact])}`" — invalid syntax presented as an alternative translation.
- "assumed FKs" as a Hyper-generation strategy — conflates a server publish-time inference with authored relationship XML.
- "TWB opens via Tableau Server API (if possible)" — no such API; replace with scratch-publish/render test.
- Golden fixture with identical expected values across years — cannot detect the bug it guards.

---

*End of audit.*
