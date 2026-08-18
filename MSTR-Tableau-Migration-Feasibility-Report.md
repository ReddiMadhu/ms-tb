# Enterprise Feasibility Study: AI-Powered MicroStrategy → Tableau Migration Platform

**Document type:** R&D technical blueprint for commercial product investment  
**Date:** 24 July 2026  
**Classification:** Engineering / Product Decision  
**Primary question:** Can an enterprise platform automatically migrate MicroStrategy projects into Tableau with high fidelity and minimal manual intervention?

---

## Executive Summary

### Verdict

**Conditionally yes — as a high-automation migration platform with validation and human review — not as a fully unattended, pixel-perfect converter.**

| Thesis | Confidence |
|--------|------------|
| Extract semantic metadata (facts, attributes, metrics expressions, filters, hierarchies, security filters, prompts, cubes) via public APIs | **90%** |
| Generate Hyper extracts + publish without Tableau Desktop | **92%** |
| Translate calculations with deterministic AST + AI fallback | **70%** |
| Reconstruct dashboard *structure* (chapters/pages/viz/filters) | **75%** |
| Reconstruct pixel layout, themes, RSD document UX | **25–40%** |
| Commercial product ROI if sold with explicit fidelity SLAs | **72%** |

### Why this is the right product framing

1. **Documented extraction surface is strong.** Strategy’s Modeling Service and REST/JSON Data APIs expose schema objects, metric expression trees/tokens, cubes, dossiers definitions, prompts, and security filters ([Strategy REST docs](https://microstrategy.github.io/rest-api-docs/), Modeling Service help).
2. **Tableau generation path no longer depends on Desktop for core artifacts.** Official Hyper API + REST publish; official TWB XSD published (Feb 2026) as a structural baseline ([tableau-document-schemas](https://github.com/tableau/tableau-document-schemas)); Document API remains As-Is and cannot create workbooks from scratch.
3. **Industry consensus:** there is no complete one-click MSTR→Tableau converter; semantic-layer mismatch is the hard problem (Entrans, Preset, SI blogs). That gap is the commercial opportunity if the product is honest about exceptions.
4. **Hard blockers exist:** training/extreme/relationship metrics are explicitly excluded from Metric REST API; dossier definition does not expose full layout geometry; legacy Report Services Documents lack API parity with dossiers; some UX paradigms (prompt cascades, consolidations) have no clean Tableau equivalent.

### Investment recommendation

**Build** a platform positioned as:

> Automated MicroStrategy → Tableau migration with measurable numeric fidelity, confidence scoring, and a mandatory review queue for unsupported/low-confidence objects.

Do **not** market “100% automatic fidelity.” Do market “60–80% automated conversion of an average estate, 95%+ KPI numeric match on automatable content, weeks not years.”

---

## Evidence Classes & API Truth Matrix

| Tag | Classification | Meaning | Source Requirement |
|-----|----------------|---------|--------------------|
| **[OFFICIAL]** | Official Vendor API | Documented REST endpoint or public SDK with versioned stability | Official vendor docs / Swagger |
| **[OBSERVED]** | Observed in Environment | Verified operational behavior in live MSTR Strategy One instance | Server response logging |
| **[RE]** | Reverse-Engineered | Community-proven XML/TWB structure; lacks public authoring API | XML fixture test suite |
| **[ASM]** | Engineering Assumption | Logical inference; must be validated by pre-flight probe | `CapabilityDiscovery` probe |
| **[FIXTURE]** | Requires Golden Fixture | Must be mathematically proven by adversarial test suites | CI test fixture validation |

### API Capability Truth & Verification Matrix

| Capability | Source Endpoint | Status | Confidence |
| :--- | :--- | :--- | :--- |
| **Authentication & Sessions** | `POST /api/auth/login` | **[OFFICIAL]** Confirmed | High (1.00) |
| **Dossier Structure Definition** | `GET /api/v2/dossiers/{id}/definition` | **[OFFICIAL]** Version-dependent (2021+) | High (0.95) |
| **Attribute Forms & Compound Keys** | `GET /api/model/attributes/{id}` | **[OFFICIAL]** Confirmed | High (0.95) |
| **Metric Expression Tree/Tokens** | `GET /api/model/metrics/{id}?showExpressionAs=tree` | **[OFFICIAL]** Confirmed | High (0.95) |
| **Type 60 Selector Semantics** | Dossier Definition JSON | **[OBSERVED]** Map to Quick Filters | Medium (0.85) `[FIXTURE]` |
| **Pre-Execution Prompt Exclusion** | Prompt Metadata APIs | **[OFFICIAL]** Deferred per ADR-013 | High (1.00) |
| **Project VLDB Settings Extraction** | `GET /api/model/vldbSettings` | **[OFFICIAL]** Environment-dependent | Medium (0.85) `[ASM]` |
| **Transformation Table Mapping** | `GET /api/model/tables?type=transformation` | **[OFFICIAL]** Environment-dependent | Medium (0.80) `[ASM]` |
| **Tableau TWB XML Structure** | `tableau-document-schemas` XSD + Blank `.twb` | **[RE]** Template Mutation via `lxml` | High (0.90) `[FIXTURE]` |
| **Hyper Extract Creation** | `tableauhyperapi` Python C-library | **[OFFICIAL]** Confirmed | High (1.00) |
| **Tableau REST Publishing** | `tableauserverclient` (TSC) | **[OFFICIAL]** Confirmed | High (1.00) |

---

# Part 1 — Product Internals

## 1.1 MicroStrategy / Strategy

### Architecture **[DOC]**

Core tiers:

1. **Metadata repository** — RDBMS storing object definitions (GUID-keyed), ACLs, schema, project structure.
2. **Intelligence Server** — SQL generation, caching, cube management, security enforcement, job scheduling.
3. **Library / REST Server** (`MicroStrategyLibrary.war`) — REST façade including JSON Data API, Modeling proxy.
4. **Modeling Service** — Java microservice for create/read/update of schema & application objects; persists via Intelligence Server into metadata.
5. **Clients** — Workstation (primary), legacy Developer/Command Manager (mainstream support ending Dec 2026).

### How objects are stored **[DOC + ASM]**

- Each object has a **GUID**, type/subtype, version, locale, ACL, folder path.
- Definitions are persisted in metadata tables; runtime serialization historically XML via Web/XML SDK (`XMLStateSerializer`, Web Objects API).
- Modeling Service returns **JSON** definitions to Workstation/REST clients (not raw MMF blobs).
- **Knowledge gap:** exact relational table schemas of the metadata DB are not fully public. **Experiment:** export object via Modeling API + Command Manager `LIST` + package export; compare; never require direct DB reads for the product (fragile, unsupported).

### Object families relevant to migration **[DOC]**

| Family | Examples | Storage/access |
|--------|----------|----------------|
| Schema | Tables, facts, attributes, relationships, transformations | Modeling `/api/model/*` |
| Application | Metrics, filters, prompts, custom groups, consolidations, reports, documents, dossiers/dashboards | Modeling + Object/Browsing APIs |
| Analytical | Intelligent Cubes, FFSQL cubes, MDX cubes, IRRs | Cube/Report Modeling + JSON Data API |
| Security | Users, groups, security roles, security filters, ACLs | User/Security + Modeling |
| Ops | Schedules, subscriptions, caches | REST admin families |

### Reports, Documents, Dossiers **[DOC]**

- **Reports:** template (rows/columns/pages/metrics), filters, prompts; SQL Engine generates SQL.
- **Documents (RSD):** pixel layout with grids/graphs; **REST parity with dossiers is incomplete** (official REST white paper).
- **Dossiers/Dashboards:** chapters → pages → visualizations + chapter filters; definition API returns structure keys, datasets, filter expressions.

### Intelligent Cubes & SQL Engine **[DOC]**

- Cubes materialize attribute/metric working sets; DDA/MDX/FFSQL variants supported in Cube API.
- SQL view / query detail endpoints exist (incl. Data Model SQL View — Dec 2025 REST updates).
- Prompt substitution occurs before/during SQL generation inside Intelligence Server.

### Security & caching **[DOC]**

- Object ACLs + security filters (row-level predicates bound to users/groups).
- Report/document/cube caches; purge APIs available.
- Migration implication: caches are **not** migration targets; security filters **are**.

### Version note **[DOC]**

Modeling coverage expanded heavily from 2021 Update 1 onward. Target platforms: **Strategy One / 2021 Update 5+** minimum; prefer current cloud/on-prem for Data Model APIs. Older 10.x estates need upgrade or Web SDK/Command Manager fallbacks.

---

## 1.2 Tableau

### Workbook architecture **[DOC]**

| Artifact | Nature |
|----------|--------|
| `.twb` | XML workbook: datasources, worksheets, dashboards, stories, actions, parameters |
| `.twbx` | ZIP package: `.twb` + extracts/images/other |
| `.tds` / `.tdsx` | Datasource definition (+ optional extract) |
| `.hyper` | Columnar extract DB (Hyper engine) |

### Rendering model **[DOC + RE]**

1. Datasource defines connections, columns, calcs, bins, groups, relationships/joins.
2. Worksheet binds fields to shelves (rows/columns/marks encodings) + filters.
3. Dashboard composes zones (worksheets, text, images, web, containers) with layout attributes.
4. Desktop/Server parse XML → semantic model → viz engine.

### Official programmatic surfaces **[DOC]**

| API | Support | Capability |
|-----|---------|------------|
| Hyper API | Official | Create/query/update `.hyper` |
| REST API / TSC | Official | Auth, publish workbook/datasource, permissions, jobs |
| Metadata API (GraphQL) | Official | Lineage/catalog *after* publish — not authoring |
| Document API (Python) | **As-Is / unsupported** | Read/update connections & some field info; **cannot create from scratch** |
| tableau-document-schemas (XSD) | Official baseline (2026) | Structural validation of TWB; **not** semantic guarantee |

### Version differences **[DOC]**

- Multi-table Hyper publish + relationship inference from assumed FKs: Server/Cloud **2021.4+**.
- Extended/composed datasources: newer REST (API 3.29 / 2026.2 notes).
- Always emit workbook `source-build` / XML namespace compatible with target Server version.

---

# Part 2 — Internal Object Models

## 2.1 MicroStrategy object model (migration-relevant)

```
Project
 ├─ Schema
 │   ├─ Tables / Logical Tables
 │   ├─ Facts → FactExpressions → Expressions
 │   ├─ Attributes → Forms → Expressions; AttributeRelationships
 │   ├─ Transformations
 │   └─ Hierarchies (System + User)
 ├─ Public Objects
 │   ├─ Metrics (expression, dimty, conditionality, thresholds, format)
 │   ├─ Filters / Security Filters
 │   ├─ Prompts (value, element, object, expression, hierarchy, …)
 │   ├─ Custom Groups / Consolidations / Derived Elements
 │   ├─ Reports / Templates / Drill Maps
 │   ├─ Documents (RSD)
 │   ├─ Dashboards/Dossiers (chapters/pages/visualizations/datasets)
 │   └─ Cubes / Datamarts / IRRs
 └─ Configuration
     ├─ Users / Groups / Security Roles / ACLs
     └─ Schedules / Subscriptions / Devices
```

**For every object, record in the platform catalog:**

| Field | Purpose |
|-------|---------|
| `id` (GUID) | Stable identity |
| `type` / `subType` | Dispatcher |
| `name`, `path`, `versionId` | UX + change detection |
| `parents` / `children` / `dependsOn` | Graph edges |
| `definition` (JSON) | Raw Modeling/REST payload |
| `expressionAst` | Normalized from tree/tokens |
| `serialization` | `json-model` \| `xml-sdk` \| `package` |
| `apiProvenance` | Endpoint + API version |

## 2.2 Tableau object model (generation-relevant)

```
Workbook
 ├─ Datasources[]
 │   ├─ Connection(s) / Extract
 │   ├─ Columns / Calculated Fields / Parameters
 │   ├─ Relationships / Joins / Bundles
 │   └─ Hierarchies / Groups / Sets / Bins
 ├─ Worksheets[]
 │   ├─ Table (shelves, mark, encodings)
 │   ├─ Filters / Sorts / Reference lines
 │   └─ Style / Tooltip
 ├─ Dashboards[]
 │   ├─ Zones (layout tree)
 │   ├─ Device layouts
 │   └─ Dashboard actions
 ├─ Stories[] (optional)
 └─ Windows / Preferences
```

## 2.3 Dependency graph design

**Store:** PostgreSQL for catalog + Neo4j or `Apache AGE` / NetworkX for analysis (either works; Neo4j preferred at enterprise scale).

**Edge types:** `USES`, `CONTAINS`, `FILTERS`, `SECURED_BY`, `PROMPTED_BY`, `MATERIALIZES`, `PUBLISHES_TO`.

**Traversal rules:** migrate leaves (facts/attrs) → metrics → reports/cubes → dossiers → security → subscriptions.

---

# Part 3 — Reverse Engineering & API Inventory

## 3.1 MicroStrategy — what each API exposes

| Concern | Primary endpoints (representative) | Notes |
|---------|--------------------------------------|-------|
| Auth | `POST /api/auth/login` | Session token `X-MSTR-AuthToken` |
| Browse | `GET /api/folders/{id}`, search | Catalog walk |
| Object mgmt | Object Management family | Move/copy/delete/ACL |
| Attributes | `GET /api/model/attributes/{id}` | Forms, relationships |
| Facts | `GET /api/model/facts/{id}` | |
| Metrics | `GET /api/model/metrics/{id}?showExpressionAs=tree\|tokens` | **No** training/extreme/relationship metrics |
| Filters | `GET /api/model/filters/{id}` | |
| Security filters | Modeling security filter APIs | Definition + membership |
| Hierarchies | User/System hierarchy APIs | |
| Custom groups / consolidations / derived elements | Modeling (2021 U2+) | |
| Prompts | Modeling prompt APIs + answer APIs | |
| Reports | `GET /api/model/reports/{id}`; JSON Data `/api/v2/reports/...` | Definition + data |
| Cubes | `GET /api/model/cubes/{id}`; `/api/v2/cubes/...` | Incl. DDA/MDX/FFSQL |
| Dossier structure | `GET /api/v2/dossiers/{id}/definition` | Chapters/pages/viz/filters/datasets |
| Dossier data | Instance + visualization data endpoints | |
| Selectors | Selector definition endpoints | Partial interaction model |
| SQL | Query details / SQL view endpoints | Use for validation & FFSQL capture |
| Schedules/subs | Schedules & subscriptions families | |
| Packages | Migration package upload/download | Bulk acceleration |
| Lineage | Object lineage endpoints (2021+) | Seed graph |

### Example: metric definition **[DOC]**

```http
GET /api/model/metrics/{metricId}?showExpressionAs=tree
X-MSTR-AuthToken: …
X-MSTR-ProjectID: …
```

Response (shape): `information`, `expression.{text,tree}`, `dimty`, `conditionality`, `format`, `thresholds`, …

### Example: dossier definition **[DOC]**

```http
GET /api/v2/dossiers/{dossierId}/definition
```

Returns `chapters[].pages[].visualizations[]`, chapter `filters` with expression trees, `datasets[].availableObjects`.

**Gap:** full absolute positioning, theme tokens, and all formatting are not guaranteed in this payload. **[ASM]** Confirm per version with Workstation export comparison experiment.

## 3.2 Tableau — generation & publish

| Concern | API | Notes |
|---------|-----|-------|
| Extract create | Hyper API | Official |
| Publish datasource/workbook | REST / TSC | Official |
| Permissions | REST | Groups/users mapping |
| Validate TWB structure | XSD from tableau-document-schemas | Structural only |
| Mutate existing TWB | Document API | As-Is; limited |
| Author TWB from scratch | XML writer against XSD **[RE]** | Required product component; Desktop not required |
| Catalog after publish | Metadata GraphQL | Validation/lineage |

---

# Part 4 — Dashboard Extraction Strategy

## Reconstructible with high confidence **[DOC]**

- Chapter / page / visualization inventory and names
- Dataset membership (attributes/metrics on viz)
- Chapter filters & expressions; selector summaries
- Prompt presence (`hasPrompt`)
- Visualization data via JSON Data API (for validation & Hyper seeding)

## Partially reconstructible **[ASM / RE]**

- Viz type mapping (grid→text table, bar/line/pie→marks) from viz metadata where exposed; otherwise infer from executed result shape + name heuristics + AI
- Filter→Tableau filter/action wiring from `filteredTargetVisualizations`
- KPI cards via KPI object APIs where present (2021 U10+)

## Unsupported / weak via public APIs **[DOC + ASM]**

- Exact pixel layout, containers nesting, padding, responsive device layouts
- Full theme/CSS parity
- Custom viz plugins
- RSD Document freeform layouts (parity gap)
- Drill maps richness vs Tableau hierarchies/actions

**Product rule:** emit **structurally correct** dashboards (worksheets + tiled layout + filters) with `layoutConfidence`; route low scores to designer review. Prefer *Tableau-native redesign templates* over fake pixel clones.

---

# Part 5 — Semantic Layer Mapping Matrix

| MicroStrategy | Tableau target | Feasibility | Strategy |
|---------------|----------------|------------|----------|
| Fact | Measure column / calc | Fully | Hyper column or live field |
| Attribute (+ forms) | Dimension (possibly multi-column) | Fully | ID/DESC forms → fields; hide IDs if needed |
| Attribute relationship | Relationship / FK | Mostly | Assumed FKs in Hyper or relationship XML |
| Hierarchy | Hierarchy | Mostly | Native hierarchy where depth fits |
| Metric (simple agg) | Measure / calc | Fully | `SUM([Sales])` etc. |
| Derived metric | Calculated field | Mostly | Expression tree compile |
| Level metric (dimty) | LOD `FIXED`/`EXCLUDE` | AI-assisted | Pattern library + AI |
| Conditional metric | Calc + filter context | Mostly | Conditionality → filtered calc / FIXED |
| Transformation (time) | LOD / date calc / scaffold table | AI-assisted | Often push to SQL/dbt |
| Custom group | Group / Set / CASE | Review | Element lists → aliases |
| Consolidation | Calc / union scaffold | Review | Rarely 1:1 |
| Intelligent Cube | Hyper extract / published DS | Mostly | Materialize working set |
| FFSQL cube/report | Custom SQL DS / Hyper | Mostly | Capture SQL text |
| MDX cube | Live cube connection or extract | Review | Prefer extract snapshot |
| Security filter | RLS / user filters / entitlements | Mostly | Predicate compile + group map |
| Prompt | Parameter / filter action | AI-assisted | Value prompts easy; hierarchical hard |
| Drill map | Hierarchy + actions | Review | |

---

# Part 6 — SQL & Business Logic Strategy

## Options

| Approach | Pros | Cons |
|----------|------|------|
| SQL-only (capture & replay) | Fast numeric match | Loses semantic reuse; brittle prompts; poor Tableau UX |
| Metadata/object-graph only | Preserves meaning; reusable calcs | Hard metrics/dimty; incomplete layouts |
| **Hybrid (recommended)** | Best fidelity + maintainability | More engineering |

## Recommendation: **Hybrid**

1. **Source of truth for meaning:** Modeling expression trees/tokens + dimty + relationships.
2. **Source of truth for physicality:** warehouse tables + optional dbt/SQL pushdown for transformations/FFSQL.
3. **Source of truth for acceptance:** executed MSTR vs Tableau result sets under controlled prompts/filters.
4. Never treat generated SQL alone as the semantic model — it is a *projection*.

### Dynamic aggregation

MicroStrategy resolves aggregation from template + metric dimensionality at runtime. Tableau resolves via viz LOD + calc granularity. **Compiler must materialize intended grain into LOD or pre-aggregates.** **[ASM]** Build a dimty→LOD pattern catalog from 50–100 real metrics as PoC gate.

---

# Part 7 — Intermediate Representation (BI-IR)

## Why IR beats direct MSTR→Tableau

- Multiple source/target vendors (PBI, Cognos, Qlik, Looker, BO) share one compiler backend.
- Deterministic validation against a schema.
- Diff/version migrations across tool versions.
- AI operates on IR, not brittle XML.

## Object hierarchy (sketch)

```json
{
  "$schema": "https://migrator.example/schemas/bi-ir/v1.json",
  "irVersion": "1.3.0",
  "source": { "vendor": "microstrategy", "projectId": "...", "extractedAt": "..." },
  "model": {
    "tables": [],
    "relationships": [],
    "dimensions": [],
    "measures": [],
    "parameters": [],
    "securityPolicies": []
  },
  "queries": [],
  "visuals": [],
  "layouts": [],
  "navigation": [],
  "lineage": { "nodes": [], "edges": [] },
  "issues": []
}
```

### Measure example

```json
{
  "id": "mstr:metric:28B…",
  "name": "Revenue YoY",
  "dataType": "number",
  "expression": {
    "dialect": "bi-ir",
    "ast": {
      "op": "div",
      "args": [
        { "op": "agg", "fn": "sum", "field": "fact:revenue" },
        { "op": "lod", "grain": ["attr:year"], "fn": "sum", "field": "fact:revenue", "offset": { "year": -1 } }
      ]
    },
    "sourceRaw": { "vendor": "microstrategy", "tree": {} }
  },
  "grainHints": ["attr:year", "attr:region"],
  "confidence": 0.81
}
```

### Validation rules

- Acyclic `USES` graph for calcs (or explicitly marked recursive).
- Every visual field resolves to model field.
- Security policies reference existing dimensions.
- `irVersion` semver; writers may emit `1.x`; readers reject major skew.

---

# Part 8 — AI Strategy

| Task | Role of AI | Deterministic gate |
|------|------------|--------------------|
| Formula translation | Fallback when rule compiler fails; propose LOD | Golden metric tests must pass |
| SQL understanding | Annotate FFSQL → IR fields | Parser + warehouse schema match |
| Business rule extraction | Docs / glossary | Human approve for shared semantic layer |
| Viz mapping | Suggest mark type | Allowed-type allowlist |
| Layout reconstruction | Packing / template selection | Grid safety + contrast checks |
| Unsupported detection | Classify + explain | Rule engine owns hard blocks |
| Documentation | Always | Cite object GUIDs |
| Validation assistance | Explain diffs | Diff math is deterministic |

**Never let the LLM write final TWB/Hyper bytes unchecked.** LLM → IR patch → schema validate → codegen → XSD → open-in-Tableau smoke test.

---

# Part 9 — End-to-End Pipeline

```
MicroStrategy Project
        │
Metadata Discovery          → object catalog, ACL snapshot
        │
Dependency Graph Builder    → migrate order, blast radius
        │
Semantic Analyzer           → AST, dimty, relationships
        │
Intermediate Representation → BI-IR JSON (+ issues[])
        │
AI Translation Engine       → low-confidence nodes only
        │
Visualization Translator    → worksheet/dashboard specs
        │
Tableau XML Generator       → .twb against XSD
        │
Hyper Generator             → .hyper (+ assumed FKs)
        │
Validation Engine           → numeric/layout/security scores
        │
Publishing Engine           → REST publish + permissions
        │
Tableau Server / Cloud
```

Each stage: idempotent, retryable, writes artifacts to object storage, emits OpenTelemetry spans.

---

# Part 10 — Tableau Generation Strategy

### Desktop required?

**No for the happy path.** **[DOC]** Hyper API + REST publish are official. **[DOC]** TWB XSDs enable structural authoring. **[RE]** Community libraries (e.g. pytableau) demonstrate full workbook build without Desktop.

**Yes optionally** for: visual QA, exotic mark types, or repairing semantic validation failures XSD cannot catch (Tableau explicitly warns structural ≠ semantic validity).

### Generation recipe

1. Build multi-table `.hyper` with assumed FKs for relationships (2021.4+ publish inference) **or** emit `.tdsx` (hyper + handcrafted `.tds`).
2. Emit calculated fields in datasource XML.
3. Emit worksheets (shelves/marks/filters).
4. Emit dashboard zones (tiled layout algorithm).
5. Package `.twbx`; validate XSD; publish via TSC; set permissions.

---

# Part 11 — Validation Framework

| Check | Method | Production threshold (suggested) |
|-------|--------|----------------------------------|
| Row counts | Execute cube/report vs Hyper/worksheet CSV | Exact on grain keys; ±0 |
| Metric values | Pairwise KPI under same filters | ≤0.1% relative or ±ε absolute |
| Aggregations | Multi-grain matrix | 100% critical KPIs; ≥98% secondary |
| Filters | Enumeration of filter members | Exact set match |
| Parameters/prompts | Answer matrix | All default paths green |
| Drill | Path smoke tests | ≥95% paths |
| Formatting | Screenshot SSIM / style JSON diff | Informational; not gate |
| Layout | Zone IOU vs expected template | ≥0.7 or review |
| Navigation | Link/action crawl | 100% critical |
| Performance | Extract refresh + view load | Within 1.5× agreed SLO |

**Gate policy:** auto-publish only if `numericScore ≥ 0.98` and `blockerIssues == 0`; else review queue.

---

# Part 12 — Scalability

Assumptions: ~150–400 REST calls per dossier including dependencies (shared objects cached).

| Scale | API calls | Storage | Workers | Wall time | Bottleneck |
|-------|-----------|---------|---------|-----------|------------|
| 100 | 15–40K | 10–50 GB | 4–8 | 4–12 h | I-Server |
| 1,000 | 150–400K | 0.1–1 TB | 16–32 | 1–3 d | I-Server + validation queries |
| 10,000 | 1.5–4M | 1–10 TB | 64–128 | 1–2 wk | Queue + warehouse extract IO |
| 100,000 | 15–40M | 10–100 TB | 200+ | 2–3 mo | Must use packages, deltas, sampling |

### Optimizations

- Content-addressed cache of object definitions by `versionId`
- Migration packages for bulk extract
- Shared semantic layer compiled once per project
- Validate on stratified sample + critical KPI set, not every viz daily
- Back-pressure against Intelligence Server concurrency limits

---

# Part 13 — Proof of Concept Design

## Scope

One realistic dossier: **“Regional Sales Performance”** with:

- 2 attributes (Region, Category), 1 time attribute
- 3 metrics (Revenue, Cost, Profit Margin derived)
- 1 chapter filter, 1 value prompt
- 4 visualizations (KPI, bar, line, crosstab)
- 1 security filter on Region

## Steps

1. Login + project select  
2. Walk dossier definition → collect dataset object IDs  
3. Pull attribute/metric definitions (`showExpressionAs=tree`)  
4. Build dependency graph (NetworkX)  
5. Emit BI-IR JSON  
6. Compile measures → Tableau calcs; dims → Hyper columns  
7. Extract data via Cube/Report JSON API → Hyper  
8. Generate TWB; XSD validate; publish  
9. Compare Revenue/Cost/Margin under Region=X  

## Sample IR (abridged)

```json
{
  "irVersion": "1.3.0",
  "model": {
    "dimensions": [
      { "id": "dim:region", "fields": ["Region"] },
      { "id": "dim:category", "fields": ["Category"] }
    ],
    "measures": [
      {
        "id": "meas:revenue",
        "expression": { "ast": { "op": "agg", "fn": "sum", "field": "Revenue" } },
        "confidence": 0.99
      },
      {
        "id": "meas:margin",
        "expression": {
          "ast": {
            "op": "div",
            "args": [
              { "op": "agg", "fn": "sum", "field": "Profit" },
              { "op": "agg", "fn": "sum", "field": "Revenue" }
            ]
          }
        },
        "confidence": 0.95
      }
    ]
  }
}
```

## Pseudocode

```python
token = mstr.login(url, user, password)
dossier = mstr.get_dossier_definition(token, project, dossier_id)
objs = discover_dependencies(token, dossier)
ir = compile_to_ir(objs)
ir = ai_fill_gaps(ir)          # only confidence < 0.85
hyper = build_hyper(ir, mstr.extract_data(...))
twb = emit_twb(ir, hyper)
validate_xsd(twb)
score = compare_metrics(mstr, tableau, scenarios)
if score.ok: tsc.publish(twbx)
else: queue_for_review(ir, score)
```

### PoC success gates

- TWB opens on Server without repair  
- Revenue/Cost match within 0.1% for 10 filter scenarios  
- Margin calc present as calculated field  
- Security filter blocks out-of-region rows for test user  

---

# Part 14 — Production Architecture

```
                    ┌─────────────┐
  Users/API  ──────▶│ API Gateway │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         Auth/OIDC    Control Plane   Web UI
                           │
                           ▼
                     Job Queue (Redis/NATS)
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
  Extract Workers   Compile Workers    Validate Workers
        │                  │                  │
        └────────────┬─────┴─────┬────────────┘
                     ▼           ▼
              PostgreSQL    Object Storage (S3)
              (catalog)     (defs, IR, twbx, logs)
                     │
                     ▼
              Neo4j (lineage)   LLM Service (gated)
                     │
                     ▼
              Observability (OTel, Prometheus, Loki)
```

**Deploy:** Kubernetes (HPA on queue depth), CI/CD (build → scan → staging soak against demo MSTR → prod).  
**Security:** customer credentials in KMS/vault; network isolation to MSTR/Tableau; per-tenant encryption; audit log of every object touched; no training on customer formulas without contract.

---

# Part 15 — Risks & Feasibility Matrix (summary)

| Feature | Class | Reason |
|---------|-------|--------|
| Schema facts/attrs/relationships | Fully automatable | Modeling APIs |
| Base metrics with tree/tokens | Mostly automatable | Compiler + tests |
| Level/transformation metrics | AI-assisted | Dimty semantics ≠ LOD |
| Custom groups/consolidations | Manual review | Conceptual mismatch |
| Cubes→Hyper | Mostly automatable | Data APIs + Hyper |
| Security filters | Mostly automatable | Predicate mapping gaps |
| Prompts | AI-assisted | Interaction model differs |
| Dossier structure | Mostly automatable | Definition API |
| Pixel layout/themes | Manual review | Metadata incomplete |
| RSD Documents | Not feasible (public APIs) | Documented parity gap |
| Training/extreme/relationship metrics | Not feasible | Official API exclusion |
| Schedules/subscriptions | Mostly automatable | Feature subset |
| TWB/Hyper/publish codegen | Fully automatable | Hyper+REST+XSD |

---

## Final Feasibility Assessment

### Can you build a fully automated, high-fidelity, minimal-touch enterprise migrator?

| Interpretation | Answer |
|----------------|--------|
| Zero human intervention, pixel-perfect UX, 100% object types | **No** |
| High automation of semantics + data + structure, numeric SLAs, review for exceptions | **Yes** |
| Commercially defensible product in 18–24 months | **Yes, with disciplined scope** |

### Confidence

- **Technical platform (hybrid IR architecture):** 80%  
- **Meeting “enterprise-grade” reliability for automatable subset:** 75%  
- **Meeting naive customer expectation of full UX clone:** 20%  

### Phased roadmap

1. **MVP (0–6 months):** Semantic extract, Hyper, simple calcs, simple dossiers, validation harness, review UI.  
2. **Pilot (6–14 months):** Dimty/LOD patterns, prompts, RLS, multi-table Hyper, confidence scoring, 3–5 pilots.  
3. **Enterprise (14–24 months):** Scale-out, subscriptions, layout assist, multi-source IR, compliance, 10K+ throughput.

---

## Knowledge Gaps & Required Experiments

| Gap | Experiment |
|-----|------------|
| Exact dossier layout fields per version | Diff definition JSON vs Workstation XML/package for 20 dossiers |
| Dimty→LOD correctness | 100-metric golden set across grains |
| MDX cube live vs extract | Parallel publish; compare 50 queries |
| RSD document extract | Attempt Web SDK XML + package; measure coverage |
| TWB semantic open failures despite XSD | Fuzz generator; catalog failure modes |
| Security filter functions unsupported in Tableau | Enumerate predicates from 3 real projects |

---

## Sources (primary)

1. Strategy REST API docs — https://microstrategy.github.io/rest-api-docs/  
2. Modeling Service configuration — Strategy System Admin help  
3. Manage metrics/attributes/reports/cubes — REST common workflows  
4. Dossier definition / filters / selectors — REST analytics workflows  
5. REST API white paper (dossiers vs documents parity note)  
6. Tableau Hyper API — https://tableau.github.io/hyper-db/  
7. Tableau REST publishing — help.tableau.com REST publishing methods  
8. Tableau Document API (As-Is) — tableau/document-api-python  
9. Official TWB XSDs — github.com/tableau/tableau-document-schemas (2026)  
10. Industry migration analyses — Entrans, Preset, SI vendor blogs (limitations consensus)

---

## Appendix A — Decision Record

**ADR-001:** Use BI-IR, not direct converters.  
**ADR-002:** Hybrid metadata + execution validation.  
**ADR-003:** LLM never bypasses IR schema or golden tests.  
**ADR-004:** Do not read metadata DB directly.  
**ADR-005:** Desktop optional for QA only.  
**ADR-006:** Sell confidence-scored automation, not silent 100% fidelity.

---

## Part 16 — Complete Agent System

All **13 expert R&D agents** and **12 runtime pipeline agents** are fully specified in:

**`MSTR-Tableau-Agents-Complete.md`** (also on Desktop).

### Runtime pipeline

```
Orchestrator
 → DiscoveryAgent → GraphAgent → SemanticAgent → IRCompilerAgent
 → AITranslationAgent (gated) → VisualizationAgent
 → TemplateTableauAgent (copy empty .twb) + HyperAgent
 → ValidationAgent → PublishAgent | ReviewQueueAgent
```

### Expert sign-off

Combined decision from all 13 experts: **BUILD** (PoC experiments still required by Reverse Engineering Specialist).

---

*End of report.*
