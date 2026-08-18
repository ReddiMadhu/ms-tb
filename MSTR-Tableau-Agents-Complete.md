# Complete Agent Specifications — MSTR → Tableau Migration Platform

**Companion to:** MSTR-Tableau-Migration-Feasibility-Report.md  
**Date:** 28 July 2026  
**Purpose:** Finish every expert R&D agent and every runtime pipeline agent required to design and build the commercial platform.

---

# Section A — R&D Expert Agents (13)

Each agent owns a verdict slice. Together they form the investment decision.

---

## A1. Principal BI Architect

| Field | Value |
|-------|-------|
| **Mission** | Decide product architecture and migration philosophy |
| **Owns** | Hybrid IR strategy, fidelity SLAs, phased roadmap |
| **Inputs** | All specialist findings |
| **Outputs** | ADR-001..006, product posture, go/no-go |

### Findings
- Direct MSTR→Tableau 1:1 conversion is wrong; **vendor-neutral BI-IR** is mandatory.
- Sell **confidence-scored automation + review queue**, not silent 100% fidelity.
- Target numeric SLA: ≥98% on critical KPIs for automatable subset.

### Verdict contribution
**Invest** in platform with honest boundaries. Overall confidence **72%**.

---

## A2. MicroStrategy (Strategy) Expert

| Field | Value |
|-------|-------|
| **Mission** | Map what can be extracted from Strategy metadata |
| **Owns** | Object catalog, API inventory (source), version gates |
| **Inputs** | Modeling Service, JSON Data API, packages |
| **Outputs** | Extractable vs blocked object matrix |

### Findings
- **Extractable:** facts, attributes, relationships, hierarchies, base/derived metrics (tree/tokens + dimty), filters, security filters, custom groups, consolidations, prompts (most types), reports, cubes, dossier structure, schedules/subs (subset).
- **Blocked / weak:** training/extreme/reference-line/relationship metrics; level & system prompts; RSD document parity; pixel layout/themes.
- Minimum platform: **2021 Update 5+**; prefer current Strategy One.

### Agent contract (runtime later)
```
extract(projectId) → ObjectCatalog + raw JSON defs + provenance
```

---

## A3. Tableau Platform Architect

| Field | Value |
|-------|-------|
| **Mission** | Define how Tableau artifacts are authored and published |
| **Owns** | Template strategy, Hyper, TWB/TWBX, REST publish |
| **Inputs** | Hyper API, REST/TSC, TWB XSD, Document API limits |
| **Outputs** | Generation blueprint |

### Findings
- **No official API to author dashboards from scratch.**
- MVP: **copy empty golden template `.twb` → mutate XML → package `.twbx` → REST publish**.
- Hyper API official for extracts; multi-table + assumed FKs for relationships (Server 2021.4+).
- Document API As-Is: connections only; cannot create/calc/extract inject.
- Keep **one template per Tableau major version**.

### Agent contract
```
emit(ir, templateId) → twb + hyper + twbx
publish(twbx, site, project) → workbookId
```

---

## A4. Reverse Engineering Specialist

| Field | Value |
|-------|-------|
| **Mission** | Identify undocumented gaps and validation experiments |
| **Owns** | Knowledge-gap register, PoC experiments |
| **Outputs** | Gap list with experiment protocols |

### Critical gaps to close
1. Diff dossier definition JSON vs Workstation package for layout fields (n=20).
2. Dimty→LOD golden set (n=100 metrics).
3. RSD Web SDK / package coverage measurement.
4. TWB XSD-valid but won’t-open failure catalog.
5. Security-filter predicate inventory from 3 real projects.

### Status
All marked **[ASM]** until PoC runs. Do not claim production coverage without these.

---

## A5. Enterprise Software Architect

| Field | Value |
|-------|-------|
| **Mission** | Production system design |
| **Owns** | K8s, queues, multi-tenant, security, CI/CD |
| **Outputs** | Deployment architecture |

### Services
| Service | Role |
|---------|------|
| API Gateway | Auth, tenancy, rate limits |
| Control Plane | Jobs, projects, review UI API |
| Extract Workers | MSTR API crawl |
| Compile Workers | IR + Tableau emit |
| Validate Workers | Numeric/layout checks |
| Publish Workers | TSC publish |
| LLM Gateway | Gated AI only |
| Postgres | Catalog, jobs, scores |
| Redis/NATS | Queues |
| S3 | Artifacts |
| Neo4j (optional) | Lineage graph |

### Non-negotiables
- Idempotent jobs, artifact versioning, KMS for credentials, no customer formula training without contract.

---

## A6. Metadata Modeling Expert

| Field | Value |
|-------|-------|
| **Mission** | Unified object model + BI-IR schema |
| **Owns** | IR JSON Schema, versioning, validation rules |
| **Outputs** | `bi-ir/v1` schema |

### Core IR entities
`Project`, `Table`, `Relationship`, `Dimension`, `Measure`, `Parameter`, `Filter`, `SecurityPolicy`, `Query`, `Visual`, `Layout`, `Navigation`, `Issue`

### Rules
- Semver `irVersion`; major bumps break readers.
- Every visual field must resolve to model field.
- Calc graph acyclic unless explicitly flagged.
- Every node carries `confidence` + `provenance`.

---

## A7. Graph Database Engineer

| Field | Value |
|-------|-------|
| **Mission** | Dependency graph for migrate-order and blast radius |
| **Owns** | Graph schema, traversal algorithms |
| **Outputs** | Migration waves, impact analysis |

### Edge types
`USES`, `CONTAINS`, `FILTERS`, `SECURED_BY`, `PROMPTED_BY`, `MATERIALIZES`, `PUBLISHES_TO`

### Algorithms
1. Topological migrate order (schema → metrics → reports/cubes → dossiers → security → subs).
2. Shared-object dedupe (compile semantic layer once).
3. Blast radius when a metric fails validation.

### Storage
Postgres adjacency for MVP; Neo4j/AGE at enterprise scale.

---

## A8. XML & Serialization Expert

| Field | Value |
|-------|-------|
| **Mission** | Safe TWB/TDS XML generation |
| **Owns** | Template mutation, XSD validation, packaging |
| **Outputs** | TWB emitter, fail-closed open tests |

### Strategy
1. Start from Desktop-saved **empty golden template** (not hand-written root).
2. Inject datasource, columns, calcs, worksheets, dashboard zones via deterministic XML transforms.
3. Validate against official `tableau-document-schemas` XSD.
4. Smoke: publish or open in headless/CI Tableau where available.
5. Never ship LLM-written raw XML without XSD + smoke gates.

### Packaging
`.twb` + `.hyper` (+ images) → `.twbx` ZIP; optional `.tdsx` for published DS.

---

## A9. Python Backend Architect

| Field | Value |
|-------|-------|
| **Mission** | Implement connectors and workers |
| **Owns** | MSTR client, IR compiler, Hyper builder, TSC publisher |
| **Stack** | Python 3.11+, FastAPI, Celery/Arq, lxml, tableauhyperapi, tableauserverclient, pydantic, networkx |

### Module map
```
mstr_client/          # auth, modeling, dossier, cubes, data
ir/                   # schema, compile, validate
semantic/             # expression AST, dimty→LOD rules
tableau_emit/         # template copy, xml mutate, package
hyper_builder/        # schema + load from MSTR extracts
validate/             # numeric scenarios, scoring
publish/              # TSC
ai_gateway/           # only low-confidence nodes
api/                  # control plane
workers/              # queue consumers
```

---

## A10. AI / LLM Systems Architect

| Field | Value |
|-------|-------|
| **Mission** | Define where AI is allowed |
| **Owns** | Decision matrix, prompts, confidence thresholds |
| **Outputs** | AI policy |

### Use AI for
- Formula paraphrase when rule compiler fails
- Viz type suggestion
- Layout packing / template selection
- Unsupported-feature triage explanations
- Documentation generation
- Validation anomaly narratives

### Never let AI alone decide
- Object IDs / lineage
- Security filter compilation (rules first)
- Hyper schema
- Final TWB bytes
- Publish ACL
- Pass/fail numeric gates

### Gate
```
if confidence < 0.85 → AI propose IR patch → schema validate → golden tests → else review queue
```

---

## A11. ETL / Data Engineering Specialist

| Field | Value |
|-------|-------|
| **Mission** | Physical data path MSTR → Hyper / live |
| **Owns** | Cube/report extract, FFSQL capture, warehouse pushdown |
| **Outputs** | Hyper build + optional dbt recommendations |

### Strategy
- Prefer **materialize Intelligent Cube / report result** into Hyper for fidelity PoC.
- Capture **FFSQL** text into Custom SQL datasource or rewrite to dbt.
- Push complex transformations upstream when Tableau calcs would be fragile.
- Multi-table Hyper with assumed FKs for relationship inference on publish.

---

## A12. Enterprise Migration Consultant

| Field | Value |
|-------|-------|
| **Mission** | Commercial delivery model |
| **Owns** | Assessment methodology, wave planning, change management |
| **Outputs** | Engagement playbook |

### Waves
1. Inventory + unused content retirement  
2. Shared semantic layer migration  
3. Critical dossiers (high usage)  
4. Long-tail reports  
5. Security + subscriptions  
6. Decommission MSTR  

### Commercial packaging
- Assessment (2–4 weeks)
- Platform license + success metrics
- Managed review capacity for red/yellow objects

---

## A13. QA & Validation Architect

| Field | Value |
|-------|-------|
| **Mission** | Prove fidelity before publish |
| **Owns** | Golden tests, thresholds, review gates |
| **Outputs** | Validation framework |

### Gates
| Check | Threshold |
|-------|-----------|
| Critical KPI values | ≤0.1% relative or ±ε |
| Row counts at grain | Exact |
| Filter member sets | Exact |
| Blocker issues | 0 for auto-publish |
| Layout IOU | ≥0.7 or review |
| Formatting | Informational only |

### Auto-publish rule
`numericScore ≥ 0.98 AND blockerIssues == 0 AND securityParity == pass`

---

# Section B — Runtime Pipeline Agents (Platform Workers)

These are the **software agents** that execute a migration job.

```
Orchestrator
   ├─ DiscoveryAgent
   ├─ GraphAgent
   ├─ SemanticAgent
   ├─ IRCompilerAgent
   ├─ AITranslationAgent      (optional, gated)
   ├─ VisualizationAgent
   ├─ TemplateTableauAgent    (copy empty dashboard template)
   ├─ HyperAgent
   ├─ ValidationAgent
   ├─ PublishAgent
   └─ ReviewQueueAgent
```

---

## B0. Orchestrator Agent

| | |
|--|--|
| **Trigger** | `POST /jobs` with project + scope |
| **Input** | `MigrationJobSpec` |
| **Output** | Job status, artifact URIs, scores |
| **Responsibilities** | Wave planning from graph, retries, idempotency keys, DLQ |

```python
# pseudocode
def run_job(spec):
    catalog = DiscoveryAgent.run(spec)
    graph = GraphAgent.run(catalog)
    for wave in graph.waves():
        ir = IRCompilerAgent.run(SemanticAgent.run(wave))
        ir = AITranslationAgent.run(ir)  # only low confidence
        specs = VisualizationAgent.run(ir)
        hyper = HyperAgent.run(ir, wave)
        twbx = TemplateTableauAgent.run(ir, specs, hyper, template=spec.template_id)
        score = ValidationAgent.run(wave, twbx)
        if score.auto_ok:
            PublishAgent.run(twbx, spec.target)
        else:
            ReviewQueueAgent.enqueue(ir, twbx, score)
```

---

## B1. DiscoveryAgent

| | |
|--|--|
| **Input** | MSTR project id, auth |
| **Output** | `ObjectCatalog` (GUIDs, types, paths, versionIds) |
| **APIs** | Login, folders/search, object lineage, package optional |
| **Failures** | Auth, rate limit → retry with backoff |

---

## B2. GraphAgent

| | |
|--|--|
| **Input** | Catalog + dependency edges |
| **Output** | DAG, migrate waves, shared semantic core |
| **Tech** | NetworkX MVP / Neo4j enterprise |

---

## B3. SemanticAgent

| | |
|--|--|
| **Input** | Object GUIDs |
| **Output** | Typed defs + expression AST + dimty + security predicates |
| **APIs** | `/api/model/*` with `showExpressionAs=tree|tokens` |
| **Flags** | Unsupported metric/prompt types → `Issue(severity=blocker|warn)` |

---

## B4. IRCompilerAgent

| | |
|--|--|
| **Input** | Semantic bundle |
| **Output** | BI-IR JSON conforming to schema |
| **Rules** | Deterministic only; no LLM |

---

## B5. AITranslationAgent

| | |
|--|--|
| **Input** | IR nodes with `confidence < 0.85` or unknown patterns |
| **Output** | Proposed IR patches + rationale |
| **Gate** | Schema validate + must not touch security without human |

---

## B6. VisualizationAgent

| | |
|--|--|
| **Input** | IR visuals + dossier structure |
| **Output** | Worksheet/dashboard specs (mark type, shelves, filters) |
| **Fallback** | Template family selection (KPI / crosstab / mixed) |

---

## B7. TemplateTableauAgent  ★ (answers template question)

| | |
|--|--|
| **Input** | Specs + Hyper path + `templateId` |
| **Process** | 1) Copy empty golden `.twb` 2) Inject DS/calcs/sheets/zones 3) XSD validate 4) Zip `.twbx` |
| **Output** | `.twbx` artifact |
| **Templates** | `blank-2024.2.twb`, `blank-2025.1.twb`, `kpi-shell.twb`, … |

```text
templates/
  tableau/
    2024.2/empty-dashboard.twb
    2025.1/empty-dashboard.twb
    shells/kpi-filter-body.twb
```

---

## B8. HyperAgent

| | |
|--|--|
| **Input** | IR physical model + MSTR data extract |
| **Output** | `.hyper` with tables + assumed FKs |
| **APIs** | MSTR JSON Data / cube instances; Tableau Hyper API |

---

## B9. ValidationAgent

| | |
|--|--|
| **Input** | Source scenarios + published or local Tableau extract/query |
| **Output** | `Scorecard` (numeric, filter, security, layout) |
| **Side effect** | Blocks PublishAgent on failure |

---

## B10. PublishAgent

| | |
|--|--|
| **Input** | `.twbx` / `.tdsx`, target site/project, ACL map |
| **Output** | Workbook/datasource IDs |
| **API** | Tableau REST / TSC |

---

## B11. ReviewQueueAgent

| | |
|--|--|
| **Input** | Failed/low-confidence jobs |
| **Output** | Human tasks in UI (approve / edit IR / redesign) |
| **SLA** | Track time-in-queue for commercial ops |

---

# Section C — Agent Interaction Matrix

| From → To | Data |
|-----------|------|
| Discovery → Graph | Catalog |
| Graph → Semantic | Wave object IDs |
| Semantic → IRCompiler | Typed defs + AST |
| IRCompiler → AI | Low-confidence nodes |
| AI → IRCompiler | Patches (re-validate) |
| IR → Viz + Hyper | Model + visuals |
| Viz+Hyper → TemplateTableau | Specs + extract |
| TemplateTableau → Validation | twbx |
| Validation → Publish or Review | Scorecard |

---

# Section D — Implementation Priority

| Phase | Agents to build |
|-------|-----------------|
| **MVP (0–6 mo)** | Orchestrator, Discovery, Semantic (subset), IRCompiler, Hyper, TemplateTableau (empty copy), Validation (numeric), Publish, ReviewQueue (basic) |
| **Pilot** | Graph waves, AITranslation, Viz richness, security mapping, multi-template |
| **Enterprise** | Full Graph/Neo4j, subscriptions, layout AI, multi-tenant Orchestrator hardening |

---

# Section E — Expert Sign-off Summary

| Expert Agent | Sign-off |
|--------------|----------|
| Principal BI Architect | **GO** with IR + review-queue product |
| MicroStrategy Expert | **GO** for extract on 2021.5+; blockers documented |
| Tableau Platform Architect | **GO** via template-copy generation |
| Reverse Engineering | **CONDITIONAL** — PoC experiments required |
| Enterprise Software Architect | **GO** K8s reference architecture |
| Metadata Modeling | **GO** BI-IR v1 |
| Graph DB Engineer | **GO** |
| XML & Serialization | **GO** template + XSD |
| Python Backend | **GO** |
| AI/LLM Systems | **GO** gated only |
| ETL/Data Engineering | **GO** Hyper-first |
| Migration Consultant | **GO** wave playbook |
| QA & Validation | **GO** with hard publish gates |

**Combined decision: BUILD** — complete agent system as specified above.

---

*End of agent pack.*
