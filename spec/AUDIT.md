# Technical Audit — `mstr-tableau-migrator`

**Role:** Principal BI Migration Architect & Senior Systems Engineer  
**Scope:** Full spec review — `architecture.md`, `agents.md`, `expression-compiler.md`, `ir-schema.md`, `database.md`, `api.md`  
**Date:** 17 August 2026  

---

## Part 1: Top 5 Critical Flaws / Fatal Assumptions

### Flaw 1: MSTR Auth Token Expiry Is a Pipeline-Killer

The spec is completely silent on session lifecycle. The MSTR REST API issues `X-MSTR-AuthToken` tokens with server-configured TTLs — typically 30 minutes on cloud environments, sometimes as short as 15. Your HyperAgent paginated extraction loop for a large cube reads as:

```python
while True:
    page = await self.mstr.get_cube_data(instance, offset=offset, limit=10000)
```

A cube with 500k rows takes at minimum 50 network round trips. If the total extraction time crosses the token TTL boundary — which it will for large estates — every call after expiry returns 401 and your code either propagates an exception (crashing the wave) or silently swallows it and writes partial data to the Hyper file. Neither outcome is logged in your current schema in a way that tells you *which page failed*.

More insidious: MSTR Cloud also expires *cube instances* (`/api/v2/cubes/{id}/instances`) separately from auth tokens. Instance TTL is typically 10 minutes idle. A slow network or GIL-blocked event loop pausing between pages can expire the instance mid-pagination, and the API will return a 404 on the instance ID — not a 401. Your retry logic (which only mentions 429/5xx in the DiscoveryAgent) doesn't cover 404-on-instance-expiry at all.

**Required fix:** Implement a `MSTRSession` wrapper that (a) stores token creation time and proactively re-authenticates when within 60 seconds of estimated TTL, (b) re-creates cube instances on 404 with `offset` state preserved, and (c) persists `last_successful_page_offset` to SQLite so a crashed extraction can resume from the last committed page rather than page 0.

---

### Flaw 2: `LOOKUP()` for Transformation Metrics Is Mathematically Wrong in 95% of Dashboards

The spec maps `Sum(Revenue){Year-1}` to `LOOKUP(SUM([Revenue]), -1)` and assigns confidence 0.65. The real confidence should be 0.10. Here's why:

`LOOKUP()` in Tableau is a *table calculation* — it navigates the result set that's already been rendered in the visualization. It doesn't reach back to the raw data. This means:

1. If a user drops the field onto a bar chart with no Year dimension on the axes, `LOOKUP(SUM([Revenue]), -1)` returns `NULL` because there's nothing to look back across.
2. If a user filters the Year dimension to show only 2026 (a single-select quick filter), `LOOKUP` has only one row in scope — again `NULL` or zero.
3. `LOOKUP` is sensitive to the table calc partition (addressing/partitioning settings). The emitter would need to explicitly set the `compute_along` XML attribute in the TWB to `[Year]`, and that setting is per-worksheet and overridable by the user. The spec has no mechanism for this.
4. MSTR's `{Year-1}` uses *physical transformation tables* or analytical lag functions to fetch the prior year's fact rows regardless of what's on the report grid. The semantics are fundamentally different.

The only correct translation that preserves the semantics across arbitrary dashboard configurations is a `{FIXED}` LOD that pre-aggregates at the Year grain and then self-joins, or more practically: materializing both the current-year and prior-year rows into the Hyper extract as distinct fields during extraction. The spec's HyperAgent extracts data "as MSTR users see it," meaning you're already computing in MSTR — you could pull `Revenue` and `Revenue_Prior_Year` as separate columns directly from a transformation-enabled cube, then reference them as `[Revenue_Prior_Year]` in Tableau with no table calc at all. This is safer, simpler, and doesn't break when users change the view.

**Required fix:** The expression-compiler.md pattern catalog for `{Year-1}` style transformations must be split into two paths: (a) if the cube is MTDI/Intelligent Cube with transformation attributes, extract the prior-period value as a named field during HyperAgent extraction; (b) if it's a derived metric-only scenario, emit `{FIXED [Year] : SUM([Revenue])} / {FIXED [DATEADD('year',-1,[Year])] : SUM([Revenue])} - 1` style LODs, not LOOKUP. The confidence column in the pattern catalog should reflect 0.10 for the current `LOOKUP` approach, flagging it as a mandatory review item.

---

### Flaw 3: Shared Published Datasource Architecture Breaks Workbook-Level Calculated Fields

ADR-012 mandates one shared published Tableau datasource per MSTR project. The spec then says dossier-specific derived metrics are compiled into the IR as measures and emitted into the TWB as calculated fields. The collision is fatal:

When a Tableau workbook references a published datasource (`.tdsx`), you can create *local calculated fields* in the workbook that reference the published datasource's fields — but those local calculations exist only in the workbook. If two dossiers both derive a metric called `Profit Margin` but with different expressions (one uses gross profit, one uses net), and both workbooks reference the same published datasource, you cannot have two different `[Profit Margin]` calculated fields on the shared datasource without one overwriting the other at publish time.

The spec's IR correctly models this per-workbook (calculated fields are in `Measure` entities linked to workbook-level content), but the TableauEmitterAgent's XML injection does not distinguish between datasource-level calculations (shared, reusable) and workbook-local calculations (dossier-specific). If the emitter puts everything into the shared datasource's `<column>` elements, the last workbook to publish overwrites shared calculated fields from prior workbooks. If it puts everything into workbook-local `<column>` elements, the TWB XML won't resolve field references to the published datasource correctly (Tableau requires the `datasource` attribute on each column reference to match the `remote-name` in the published datasource).

**Required fix:** The IR must distinguish between `scope: "shared"` measures (facts, attributes, base aggregations that belong in the shared datasource) and `scope: "local"` measures (dossier-specific derivations that belong in the workbook as local calcs referencing the shared datasource). The TableauEmitterAgent must emit shared measures into the `.tdsx` and local measures into individual `.twb` files with the correct `datasource="[shared_ds_name]"` binding syntax. The current IR `Measure` schema has no `scope` field.

---

### Flaw 4: The Single-Process FastAPI Architecture Has a Concrete Deadlock Scenario

The spec runs Hyper extraction and creation inside FastAPI `BackgroundTasks`. The `tableauhyperapi` `HyperProcess` is a *subprocess* that communicates over a local socket — it spawns a native binary. The `tableauserverclient` (TSC) publish operations are synchronous HTTP with chunked multipart upload. Neither is async-native.

Here's the deadlock: FastAPI's event loop is single-threaded. When `BackgroundTasks` runs `await HyperAgent(...).run()`, and `HyperAgent.run()` calls `HyperProcess(...)` (a blocking subprocess spawn) followed by large `Inserter.add_rows()` calls (blocking writes), this blocks the event loop for the duration of the Hyper build. Meanwhile, the Next.js frontend polls `GET /api/v1/jobs/{job_id}` every few seconds. Those poll requests queue behind the blocked event loop and time out, making the UI appear frozen. On a large extract (say, 2M rows across 5 tables), the Hyper build alone can take 5-15 minutes.

The spec says "no Celery, no Redis, no separate worker processes" (ADR). That's fine, but `BackgroundTasks` is not the right primitive for CPU/IO-bound blocking work. The correct solo-developer solution is `asyncio.to_thread()` for blocking sync code, or `loop.run_in_executor(ThreadPoolExecutor())`, which pushes the blocking call off the event loop while keeping the poll endpoints responsive.

**Required fix:** Wrap all blocking calls (HyperProcess, TSC publish, large `Inserter` operations) in `asyncio.to_thread()`. This is a one-line change per call site and is exactly what it was designed for. The architecture section should document this explicitly so it doesn't get implemented naively as sync calls inside `BackgroundTasks`.

---

### Flaw 5: Entitlement Table RLS Has a Row Duplication Defect by Design

The spec's SecurityPolicy implementation (ADR-011) uses a `SECURITY_ENTITLEMENTS` table in the Hyper extract with columns `FULLNAME` (matching the Tableau `FULLNAME()` function) and `ALLOWED_REGION`. Tableau joins this entitlement table to the fact tables, filtering to rows where `FULLNAME() = ENTITLEMENTS.FULLNAME`. This pattern is standard Tableau RLS. The defect is in the data model:

If `SECURITY_ENTITLEMENTS` has multiple rows for one user (e.g., a regional manager who can see both East and West), the join between fact tables and the entitlement table is a *many-to-many* fan — every fact row is duplicated once per matching entitlement row. A user with access to 3 regions gets every aggregate triple-counted. Tableau's relationship model (noodles) deduplicates in logical table relationships, but only if the join is set up as a *relationship* (not a physical join/blend) and only if the fact table is on the many side. The TWB XML for a physical join here will silently multiply your KPIs.

The spec notes "how does the model avoid row duplication" as a question to answer but never actually answers it.

**Required fix:** Structure the entitlement table as a *many-to-one* join by collapsing multi-region users into a delimited string or using a set-based approach: `ALLOWED_REGIONS` as a pipe-delimited string, and the Tableau filter as `CONTAINS([ALLOWED_REGIONS], [Region])`. This avoids fan joins entirely. Alternatively, use Tableau's relationship model (not physical joins) where the entitlement table relates to the dimension table, not the fact table — Tableau's LOD-aware aggregation then handles the fan-out correctly. Document this choice explicitly in the SecurityPolicy IR schema.

---

## Part 2: Semantic Engine Deep-Dive — MSTR ↔ Tableau Traps

### Trap 1: Dimty `{~+}` with Filtering Attributes

The expression-compiler.md maps `Sum(Fact){~+}` to `SUM([Fact])` at confidence 0.95 with the note "report level, no LOD needed." This is correct *only* when the metric has `filtering: "standard"` and no dimensionality units. When `{~+}` appears alongside filtering attributes in MSTR's dimty block — specifically `dimtyUnits` with `aggregation: "normal"` and `filtering: "standard"` — the metric aggregates at the report template grain AND is filtered by the report's attribute qualification. In Tableau, `SUM([Fact])` with a dimension on the viz shelf achieves the same result. But if the MSTR metric has `filtering: "absolute"` (non-smart filtering — the metric ignores the report's attribute filter and always aggregates over the full dataset), the correct Tableau translation is a `{FIXED : SUM([Fact])}` with no grain — a grand total that ignores all dimension filters. Mapping `filtering: "absolute"` to plain `SUM([Fact])` produces numerically different results whenever the user applies any dimension filter to the Tableau view. The spec doesn't extract or parse the `filtering` flag from the MSTR dimty payload at all — it's not in the `ASTNode` schema.

**Fix:** Add a `filtering_mode` field to `ASTNode` and the IR `Measure` schema. In the rule compiler, emit `{FIXED : SUM([Fact])}` when `filtering_mode == "absolute"`, and plain `SUM([Fact])` when `filtering_mode == "standard"`.

---

### Trap 2: Tableau LOD Order of Operations vs. MSTR Context Filters

The spec correctly calls out that `{FIXED [Year] : SUM([Revenue])}` can return wrong results due to Tableau's order of operations, but never specifies what to actually do about it. The concrete problem:

Tableau evaluates filters in this order: Extract → Data Source → Context → Fixed LODs → Dimension filters → Include/Exclude LODs → Table Calcs. A `{FIXED [Year]}` LOD ignores dimension filters but *respects* context filters. If a user adds a Region quick filter (not a context filter), the `{FIXED [Year]}` computes over all regions regardless of that filter — which matches MSTR's behavior. But if the developer or the emitter accidentally promotes the Year filter to a context filter (by right-clicking and selecting "Add to Context" in Tableau Desktop, or if the TWB XML emits a `<customized-flag>` on that filter), the LOD now respects only the filtered years — changing the denominator of any year-over-year calculation.

The ValidationAgent's golden dataset approach won't catch this because golden tests run in a controlled filter state. The bug only manifests when an end user interacts with the published dashboard in unexpected ways.

**Fix:** The TWB XML emitter must never emit a `<customized-flag>` on Year/Date dimension filters in worksheets that contain `FIXED` LODs. The TWB review must include a check: for every `{FIXED}` LOD calc in a worksheet, assert that no filter in that worksheet's `<filter-mappings>` has `action="include"` on the same dimension as the `FIXED` grain.

---

### Trap 3: Conditional Metrics — Pre vs. Post-Aggregation Filter Position

The pattern catalog maps `Sum(Fact) {Filter}` to `SUM(IF [Filter_Field] = 'Value' THEN [Fact] END)` at confidence 0.88. This is a row-level filter applied *before* aggregation — the fact rows that don't match the condition contribute NULL to the sum, which SUM ignores. This is correct when the MSTR metric conditionality operates at the row level.

But MSTR also supports *post-aggregation conditionality* via metric joint elements and `ApplySimple()` with `HAVING`-style semantics: the metric aggregates over all rows, then a condition on the *aggregated result* determines whether that cell displays. An example: "Show Revenue only for Regions where Revenue > 1,000,000." In MSTR this is a metric condition on the aggregated value, equivalent to SQL `HAVING SUM(Revenue) > 1000000`. In Tableau, the equivalent is a *Measure filter* (which filters after aggregation) or a `{FIXED}` LOD in a `CASE` that computes `NULL` when the aggregate condition isn't met. The spec's compiler will emit `SUM(IF [Revenue] > 1000000 THEN [Revenue] END)` — which is a *row-level* pre-aggregation filter, returning only revenue from individual transactions over 1M (almost always zero unless you have very large single transactions). The result is completely wrong.

**Fix:** The MSTR expression tree parser must identify whether the condition is on the metric's `conditionality` (post-aggregation, a `HAVING`-style qualifier) vs. an element filter in the metric definition (pre-aggregation). The IR must model this distinction — the `Measure.conditionality` field exists in the schema but is typed as `null | dict` with no structure specified. Define the structure. The rule compiler then emits either `SUM(IF pre_condition THEN [Fact] END)` or wraps in a `{FIXED} > threshold` check with a `ZN(IF {FIXED : SUM([Fact])} > threshold THEN {FIXED : SUM([Fact])} END)` pattern.

---

### Trap 4: Compound Attribute Keys and Cartesian Join Risk

The IR `Relationship` schema models relationships as single-column FK joins (`fromColumn`, `toColumn`). MSTR attributes frequently have compound keys — two or more physical columns that together form the primary key of a lookup table (e.g., a product attribute with `(Category_ID, Product_ID)` as a compound key). When the Hyper emitter builds multi-table Hyper relationships using the IR's single-column join model, it silently produces a *cross-join* between the fact table and the lookup table on whatever column it picks — most likely generating wildly inflated row counts that your row-count validation catches but only after the fact.

The `Dimension` schema captures `fields[].sourceColumn` as an array, but `Relationship` has scalar `fromColumn`/`toColumn`. There's no mechanism to express compound join keys.

**Fix:** Change `Relationship.fromColumn` and `Relationship.toColumn` to `list[str]`. The Hyper builder must emit multi-condition join XML: `<relation join="inner"><clause><expression...><column>[col1]</column></expression> ... </clause></relation>`. The SemanticAgent must extract compound key expressions from MSTR's `/api/model/attributes/{id}` response — the `forms` array contains expressions that reference multiple columns; parse them to identify multi-column keys.

---

### Trap 5: Multi-Pass Aggregation (Nested Metrics)

MSTR supports nested metrics — a metric whose expression references another metric. For example, `Profit Rate = Profit / Revenue` where `Profit` and `Revenue` are themselves metrics with their own expressions. MSTR's engine computes this in multiple SQL passes: first compute `SUM(Revenue)` per grain, then compute `SUM(Profit)` per grain, then divide.

In Tableau, a calculated field `[Profit Rate] = [Profit] / [Revenue]` where `[Profit]` and `[Revenue]` are themselves calculated fields does not do multiple aggregation passes. Tableau evaluates all calculated fields in a *single pass* over the underlying row-level data, then applies aggregation to the outer expression. The expression `[Profit] / [Revenue]` at the row level before aggregation is equivalent to MSTR's behavior only when Profit and Revenue have no LODs or conditionality — i.e., they're simple `SUM(fact)` expressions. As soon as either constituent metric has a `{FIXED}` LOD or conditionality, the single-pass Tableau evaluation produces a different number than MSTR's multi-pass SQL.

The expression-compiler's "multi-pass aggregation" row in the unsupported patterns table lists this as "Attempt nested LOD, else review" — but the nested LOD approach only works for specific cases and the spec provides no guidance on when it applies.

**Fix:** The IRCompilerAgent must detect nested metric references in the AST (`fieldRef` pointing to another measure entity) and resolve whether the nesting introduces aggregation-order issues. A safe heuristic: if any constituent measure has `translationMethod != "rule_compiler"` or `confidence < 0.90`, flag the parent metric as `Issue(severity=warning, category=multi_pass_aggregation)` and send to review. In the golden test suite, add cases specifically for nested metrics.

---

## Part 3: Tableau XML Generation and Hyper API Gotchas

### Gotcha 1: `<datasource>` Remote-Name Binding for Published Datasources

When a Tableau workbook references a *published* datasource (as opposed to an embedded connection), the TWB XML `<datasource>` element must use a specific structure:

```xml
<datasource name='[Published DS Name]' 
            caption='[Display Name]'
            version='[Tableau Version]'
            inline='true'
            hasconnection='false'>
  <connection class='sqlproxy' dbname='[Tableau Site]/[Project]/[DS Name]' server=''/>
  <column ... remote-name='[field_name_on_published_DS]' ... />
</datasource>
```

The `remote-name` attribute must exactly match the field name as published on the Tableau Server datasource — including capitalization, spaces, and bracket conventions. The spec's TableauEmitterAgent description says "inject datasource — connection XML, column definitions, calculated fields" with no detail on this binding. If the emitter naively writes `<column local-name='Revenue' remote-name='Revenue' ...>` and the published datasource has the field as `Revenue (sum)` or `SUM(Revenue)` (as Tableau sometimes renames measures), every field reference in every worksheet will return `Field does not exist in datasource` on the server — not caught by XSD validation, and not caught by the structural score check.

**Fix:** After publishing the shared datasource (Agent 10, step 3), the PublishAgent must query the Tableau Server REST API (`GET /api/{api-version}/sites/{site-id}/datasources/{datasource-id}/fields`) to retrieve the canonical published field names, and write them back to the IR cross-reference. The TableauEmitterAgent must read these canonical names from the cross-reference rather than deriving them from the IR's `Measure.name` field.

---

### Gotcha 2: Tableau Logical Tables vs. Physical Joins in Hyper TDS XML

The spec says "build multi-table Hyper with assumed FKs" and the visualization in `ir-schema.md`'s `Datasource` entity lists `tables` and `relationships`. In Tableau 2020.2+, the data model has two layers: the *physical layer* (actual SQL joins or explicit table joins) and the *logical layer* (relationships between logical tables). The TWB/TDS XML syntax for these is completely different.

For the physical layer (explicit joins):
```xml
<relation join="inner" type="join">
  <clause type="join-condition">
    <expression op="=">
      <column>[Table1].[col1]</column>
      <column>[Table2].[col1]</column>
    </expression>
  </clause>
  <relation name="Table1" type="table"/>
  <relation name="Table2" type="table"/>
</relation>
```

For the logical layer (relationships, Tableau's recommended model):
```xml
<logical-tables>
  <logical-table id="Table1" caption="Table1">
    <base-table-spec>...</base-table-spec>
  </logical-table>
</logical-tables>
<relationships>
  <relationship .../>
</relationships>
```

The spec never specifies which model to use. Physical joins on a multi-table Hyper with a star schema produce Cartesian products if the join cardinalities aren't right (and the spec explicitly says "assumed FKs" — meaning it's guessing). The logical relationship model is safer for star schemas because Tableau handles the join-cardinality problem internally. But logical tables require a different XML structure and are not available in all Tableau Desktop versions.

**Fix:** Target the *logical relationship model* exclusively. Document the TWB XML schema for `<logical-tables>` and `<relationships>` in the spec. Add a note that Tableau Server 2020.2+ is required. The blank template `.twb` must be saved with a logical-table connection (not a physical join connection) so the emitter has the correct namespace and structure to inject into.

---

### Gotcha 3: Calculated Field Names with Special Characters in TWB XML

MSTR metric names frequently include characters that are legal in MSTR but must be XML-escaped in TWB, and also illegal in Tableau calculated field identifiers. Specifically: `&`, `<`, `>`, `%`, `/`, and parentheses in names. The spec's emitter uses `lxml` for XML generation, which will escape `&` → `&amp;` in text content automatically. But the Tableau field *reference syntax* — `[Field Name]` in a calculated field string — does not escape these characters. If your Tableau calc string contains `[Gross Margin %]` and the published datasource field is named `Gross Margin %`, Tableau's calc parser accepts the brackets and the `%` — but some TWB XML serializers will double-escape the `%` when it appears inside an XML attribute value, producing `Gross Margin %25` which breaks field resolution.

Additionally, if a metric name contains `]` — perfectly legal in MSTR — the `[Metric Name with ] bracket]` Tableau field reference syntax is ambiguous (the first `]` closes the reference). The spec has no sanitization step.

**Fix:** Add a `sanitize_field_name(name: str) -> str` function to the emitter that: (a) strips or replaces `]` with `)` in field names, (b) replaces `&` with `and` and `%` with `pct` in names used as Tableau identifiers, and (c) maintains a `name_mapping` dict (MSTR name → sanitized Tableau name) persisted to the SQLite cross-reference table so the field name used in calc expressions matches the field name in the column definition.

---

### Gotcha 4: XSD Validation Is Insufficient — Tableau Semantically Rejects Valid XML

The spec uses `tableau-document-schemas` XSD validation as a publish gate. This only catches structural XML errors. Tableau Desktop/Server performs a *second* semantic validation pass that XSD cannot catch, including:

- A `<column>` with `datatype="integer"` that is referenced in a calculated field expecting a `string` type — valid XML, runtime type mismatch error.
- A worksheet shelf referencing a field from a datasource by name that doesn't match any `<column local-name>` in the datasource — valid XML, "field does not exist" error.
- A `<filter>` using `include` mode on a measure (measures can only use `range` mode in Tableau) — valid XML, silent discard of the filter.
- A `<mark>` type of `"pie"` with a measure on the `rows` shelf instead of `angle` — valid XML, renders as a bar chart silently.

The validation scorecard in the spec has "TWB opens — Attempt open via Tableau Server API (if possible) or structural check." The Tableau REST API has no endpoint that validates a workbook without publishing it. The only real test is to actually publish to a staging Tableau Server project and call `GET /api/{v}/sites/{site-id}/workbooks/{id}` to confirm it loads without error.

**Fix:** Add a staging Tableau Server project (`_migration_staging`) to the deployment model. Before final publish, PublishAgent uploads the TWBX to staging, then calls the workbook-view REST API (`GET /api/{v}/sites/{site-id}/workbooks/{id}/views`) which forces server-side rendering and semantic validation. If that returns 200, the workbook is semantically valid. Then delete from staging and publish to the production project. This is the only reliable pre-publish validation gate.

---

## Part 4: Missing Edge Cases Matrix

| MSTR Object / Pattern | Risk Level | What Goes Wrong Under Current Spec | Recommended Fix |
|---|---|---|---|
| Compound attribute key (multi-column PK) | **Critical** | Single-column FK join produces Cartesian products; row counts wildly inflated | `Relationship.fromColumn` → `list[str]`; extract compound key from MSTR attribute form expressions |
| Metric with `filtering: "absolute"` dimty | **Critical** | Maps to `SUM([Fact])` when correct output is `{FIXED : SUM([Fact])}` | Add `filtering_mode` to AST and IR; compile accordingly |
| Transformation metrics (`{Year-1}`) with single-year dashboard filter | **Critical** | `LOOKUP()` returns NULL; KPI disappears | Materialize prior-period as named Hyper column during extraction; reference directly |
| Multi-region user in entitlement table | **Critical** | Fan join multiplies aggregates by N regions | Use delimited string or relationship model for entitlement join |
| Dossier with selector (MSTR equivalent of a Tableau parameter) | **High** | Selectors are tagged as "prompts" and deferred (ADR-013) but selectors ≠ prompts — they're in-dossier dimension selectors | Selectors should map to Tableau Quick Filters or Parameters; separate them from prompts in the spec |
| Report with metric-level subtotals | **High** | The `Worksheet` IR schema has no `subtotals` field; crosstab totals are silently dropped | Add `subtotals: bool` and `subtotal_fields: list[str]` to the `Report` IR entity; emit Tableau `<total>` XML element |
| MSTR compound metric (references metrics from multiple cubes) | **High** | Single cube extraction strategy; cross-cube metrics fail extraction or get wrong scope | Flag cross-cube metrics in SemanticAgent; require manual Hyper assembly |
| `ApplySimple()` wrapping a stored procedure call | **High** | Spec says "attempt RAWSQL(), else review" — but `RAWSQL()` in Tableau requires live DB connection, not Hyper | If FFSQL and Hyper path, this is impossible; must flag as blocker immediately, not attempt RAWSQL |
| Attribute hierarchy (e.g., Year → Quarter → Month) | **Medium** | IR has `Dimension.hierarchy: null` — hierarchy structure is not extracted or emitted | Extract MSTR hierarchy definitions; emit Tableau `<group>` or date hierarchy XML |
| MSTR security filter using `BETWEEN` or `IN_LIST` with dynamic values | **Medium** | Spec's entitlement table model only handles equality matching (`FULLNAME()` = value) | Add `filterType: "between"` and `filterType: "set"` to the `SecurityPolicy` predicate IR |
| Dossier-level filter that targets multiple datasets | **Medium** | A chapter filter in MSTR can apply across multiple datasets on the same page; Tableau dashboard filters only apply to worksheets using the same datasource | Flag cross-datasource chapter filters as `Issue(warning)`; document workaround |
| MSTR metric with non-aggregatable format (e.g., smart metric showing "N/A") | **Medium** | Tableau has no native "N/A" number format for zero-division; will show `Null` or `0` | Handle zero-division in the compiled calc with explicit `IF [Denominator] = 0 THEN NULL END` |
| RSD document with nested grids | **Medium** | Spec says "best-effort — treat grids/graphs as independent reports" — but nested grids share datasets and filters | Track nested RSD grid dependencies; emit as separate worksheets with shared filter context |
| Attribute form with locale-specific collation | **Low** | English-only per MVP, but MSTR can have UTF-8 attribute form expressions with non-ASCII column names | Add column name sanitization to the Hyper schema builder |
| MSTR custom group (set-like attribute qualifier) | **Medium** | Not mentioned in the spec at all | Custom groups map to Tableau Sets; extract `customGroupElements` from MSTR attribute API and emit Tableau `<group>` XML |

---

## Part 5: Concrete Action Plan — Spec Errata

### `architecture.md` — Required Changes

**ADR-004** ("Single blank TWB template per version"): Add a requirement that the blank templates be saved with *logical table connections* (not physical joins) and with an empty published datasource reference (not an embedded connection). The current wording implies structure only, not connection type.

**ADR-006** ("Partial publishing"): Add a clause: "Failed worksheets are hidden via `<worksheet-visibility>` XML in the dashboard zone, not removed from the TWB. This preserves the dashboard layout for future re-attempts." Currently ambiguous.

**ADR-011** ("Entitlement tables"): Correct the join model. Add: "Entitlement table joins to dimension tables via Tableau's logical relationship model (not physical joins) to prevent fan-out row duplication. For multi-value permissions, the allowed values are stored as a delimited string with `CONTAINS()` filtering."

**Technology stack — add:** `asyncio.to_thread()` for wrapping all blocking Hyper and TSC calls within the `BackgroundTasks`/asyncio context.

---

### `agents.md` — Required Changes

**DiscoveryAgent:** Add step 3.5: "For each attribute, call `/api/model/attributes/{id}` during discovery (not just during SemanticAgent) to pre-extract compound key structure. Persist to `objects.compound_key_json` column." Also add: "Detect and distinguish MSTR Selectors from Prompts. Selectors (type 60) map to Tableau Quick Filters; tag them separately in the catalog."

**HyperAgent:** Rewrite the `extract_cube_data` pseudocode to include: (a) `MSTRSession` wrapper with proactive re-authentication and instance re-creation on 404, (b) `checkpoint_manager.save(offset)` after each successful page, (c) `checkpoint_manager.resume()` at function start to skip already-extracted pages, (d) wrapping the entire loop in `asyncio.to_thread()`.

**ValidationAgent:** Add a new check type: `staged_publish_test`. Description: "Publish TWBX to `_migration_staging` project, request workbook views via REST API to trigger server-side semantic validation, delete from staging. Pass/fail recorded in Scorecard." This is the only meaningful structural validation beyond XSD.

**PublishAgent:** Add step 2.5: "After publishing the shared datasource, call `GET .../datasources/{id}/fields` to retrieve canonical published field names. Write `{ir_field_name → published_field_name}` mapping to the `cross_reference` table. Pass this mapping to all subsequent TableauEmitterAgent invocations."

---

### `expression-compiler.md` — Required Changes

**Pattern 3.4 (Level Metrics):** The confidence for `{Year-1}` → `LOOKUP()` must be corrected from 0.65 to 0.10 with a `MANDATORY_REVIEW` flag. Add a new pattern row: `{Year-1}` with transformation-materialized prior-period column → `[Revenue_Prior_Year]` at confidence 0.92 — this is the preferred path when the cube supports transformation attributes.

**Pattern 3.3 (Conditional Metrics):** Split into two rows: (a) Pre-aggregation condition (row-level filter) → `SUM(IF ... THEN [Fact] END)` at 0.88; (b) Post-aggregation condition (HAVING-style, metric conditionality) → `ZN(IF {FIXED : SUM([Fact])} > threshold THEN {FIXED : SUM([Fact])} END)` at 0.60. The `ASTNode` schema must add `condition_phase: "pre_agg" | "post_agg"` populated by the MSTR expression tree parser.

**Section 7 (Unsupported Expressions):** Add: (a) `ApplySimple()` with stored procedure calls in Hyper path → `Issue(blocker, reason="stored_proc_incompatible_with_hyper")`; no RAWSQL attempt. (b) Cross-cube compound metrics → `Issue(blocker, reason="cross_cube_scope")`; (c) Custom groups → new supported pattern, not unsupported.

---

### `ir-schema.md` — Required Changes

**Relationship entity:** Change `fromColumn: string` and `toColumn: string` to `fromColumns: list[string]` and `toColumns: list[string]` to support compound keys.

**Measure entity:** Add the following fields:
- `scope: "shared" | "local"` — whether this measure belongs in the shared published datasource or in a per-workbook local calculation.
- `condition_phase: "pre_agg" | "post_agg" | null` — for conditional metrics.
- `filtering_mode: "standard" | "absolute" | null` — from MSTR dimty unit's `filtering` flag.
- `transformation_type: "none" | "time_lag" | "time_lead" | "ytd" | "mtd" | null` — to route transformation metrics to the materialization path vs. the LOD path.

**Datasource entity:** Add `field_name_mapping: dict[str, str]` — populated by PublishAgent after publishing; contains `{ir_field_id → published_canonical_name}`.

**New entity: Selector** — MSTR Selectors are distinct from Prompts and currently have no IR representation. Add:
```json
{
  "id": "sel:year_selector",
  "name": "Year Selector",
  "selectorType": "attribute_selector",
  "targetAttribute": "dim:year",
  "defaultValue": 2026,
  "multiSelect": false,
  "tableauMapping": "quick_filter",
  "confidence": 0.80
}
```

**Validation rule 8 (new):** "For every `Measure` with `scope: 'local'`, verify the containing `Datasource` entity is a published datasource reference (not embedded). Local measures on embedded connections are emitted as workbook calculated fields."

---

### `database.md` — Required Changes

The `objects` table needs two new columns: `compound_key_json TEXT` (stores the compound key column list as JSON for attributes) and `scope TEXT` (stores `"shared" | "local"` for measures). The `cross_reference` table needs `published_field_name TEXT` alongside the existing `tableau_field_name` to distinguish the IR-derived name from the server-canonical name. Add an `extraction_checkpoints` table:

```sql
CREATE TABLE extraction_checkpoints (
    id          TEXT PRIMARY KEY,
    job_id      TEXT NOT NULL REFERENCES jobs(id),
    object_id   TEXT NOT NULL,
    page_offset INTEGER NOT NULL DEFAULT 0,
    rows_written INTEGER NOT NULL DEFAULT 0,
    completed   BOOLEAN DEFAULT FALSE,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

This is the foundation for the HyperAgent resume-on-crash capability.

---

## Final Observation: Confidence Scoring Model

One final observation that cuts across all documents: the spec's confidence scoring system treats confidence as a property of individual objects in isolation. In practice, the confidence of a *dashboard* is a function of the lowest-confidence component it depends on, not the average. A dossier with 9 metrics at 0.99 and one metric at 0.50 should have an effective confidence of 0.50 — because that one metric, if wrong, corrupts the entire dashboard's trustworthiness for its users. The Orchestrator's `auto_publish_ok` gate checks `numericScore >= 0.98 AND blockerIssues == 0`, where `numericScore` is presumably an average. Switch the gate to use `min(confidence)` across all measures in the wave's scope for the auto-publish decision, and use the average only for the reporting scorecard displayed to the reviewer.

---

*End of audit.*
