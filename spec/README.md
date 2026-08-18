# mstr-tableau-migrator — Technical Specification

**Product:** MicroStrategy → Tableau AI-Powered Migration Platform  
**Classification:** Proprietary / Internal Use  
**Date:** 17 August 2026  
**Source Documents:** `MSTR-Tableau-Migration-Feasibility-Report.md`, `MSTR-Tableau-Agents-Complete.md`  
**Derived From:** 15 rounds of structured design interview  

---

## Specification Documents

| # | Document | Description |
|---|----------|-------------|
| 1 | [architecture.md](file:///c:/Users/madhu/Desktop/ms-tb/spec/architecture.md) | Product vision, system architecture, repo structure, deployment model, **32 ADRs** + two-phase orchestrator state machine |
| 2 | [agents.md](file:///c:/Users/madhu/Desktop/ms-tb/spec/agents.md) | All 13 pipeline agents with expanded `CatalogObject`, dependency poisoning, caption registry, and compensating rollback |
| 3 | [api.md](file:///c:/Users/madhu/Desktop/ms-tb/spec/api.md) | Complete REST API specification — 28+ endpoints; pre-flight capability probe, dossier discovery scan, publish operations |
| 4 | [ir-schema.md](file:///c:/Users/madhu/Desktop/ms-tb/spec/ir-schema.md) | BI-IR JSON Schema v1.0.0 — `ExtractionGrain`, `SemanticFingerprint` canonical hash, `CaptionRegistry`, `CompilationContext`; **21 validation rules** |
| 5 | [validation-contract.md](file:///c:/Users/madhu/Desktop/ms-tb/spec/validation-contract.md) | **Normative Quality Gate Contract** — Row count parity, $\le 0.1\%$ KPI tolerance, zero-value guard, RLS impersonation, unified `ValidationScorecard` |
| 6 | [spec-traceability.md](file:///c:/Users/madhu/Desktop/ms-tb/spec/spec-traceability.md) | **Requirement Traceability Matrix** — Maps every ADR and invariant to its implementing Agent, IR entity, API endpoint, and test suite |
| 7 | [expression-compiler.md](file:///c:/Users/madhu/Desktop/ms-tb/spec/expression-compiler.md) | Expression compiler with EvaluationPlan IR, operand-type aware Count, context-aware division analysis, EXCLUDE blocker, VLDB null_propagation consumption |
| 8 | [database.md](file:///c:/Users/madhu/Desktop/ms-tb/spec/database.md) | SQLite schema (17 tables incl. semantic_fingerprints, physical_model_plans, artifacts, publish_operations), SQLAlchemy ORM parity |
| 9 | [frontend.md](file:///c:/Users/madhu/Desktop/ms-tb/spec/frontend.md) | Next.js review UI — `/jobs/new` Scan & Select Wizard, Object Catalog, side-by-side AST editor, API integration |
| 10 | [testing.md](file:///c:/Users/madhu/Desktop/ms-tb/spec/testing.md) | Testing strategy — unit, integration, golden suite, E2E smoke + **25 Adversarial Golden Scenarios (`T01` to `T25`)** |
| 🔍 | [AUDIT.md](file:///c:/Users/madhu/Desktop/ms-tb/spec/AUDIT.md) | Technical audit v1 — 5 critical flaws, 5 semantic traps, 4 XML gotchas, 16 edge cases, errata |
| 🔍 | [AUDIT-v2.md](file:///c:/Users/madhu/Desktop/ms-tb/spec/AUDIT-v2.md) | Technical audit v2 — 5 net-new critical flaws (extraction grain, caption registry, staging paths, SQLite contention, metric dedup) |
| 🔍 | [AUDIT-v3.md](file:///c:/Users/madhu/Desktop/ms-tb/spec/AUDIT-v3.md) | Technical audit v3 — Warehouse Semantic SQL Planner, Semantic Metric Fingerprint, Staging Datasource Topology |
| 🔍 | [AUDIT-v4.md](file:///c:/Users/madhu/Desktop/ms-tb/spec/AUDIT-v4.md) | Technical audit v4 — Rollback Invariant Parity, Validation Snapshot Watermark Contract, Two-Phase Orchestration |

---

## Implementation Companion Guides (10-Step Architecture Review)

| Document | Purpose | Contents |
|----------|---------|----------|
| [IMPLEMENTATION-GUIDE.md](file:///c:/Users/madhu/Desktop/ms-tb/spec/IMPLEMENTATION-GUIDE.md) | Concrete code patterns & ready-to-implement solutions | **Part 1:** MSTRSession proactive renewal (ADR-016) with checkpoint recovery; **Part 2:** Warehouse-direct SQL generation for Snowflake/BigQuery/PostgreSQL; **Part 3:** Production lock + watermark tracking (ADR-029/030); **Part 4:** IR patch engine for Step 10 review workflow |
| [GAP-ANALYSIS.md](file:///c:/Users/madhu/Desktop/ms-tb/spec/GAP-ANALYSIS.md) | Identifies 18 specification blindspots from 10-step review | **Part 1:** SCC wave persistence + blast radius (Step 2); **Part 2:** CaptionRegistry collision handling (Step 5); **Part 3:** Hyper schema validation (Step 6); Plus missing database tables & algorithms |
| [SQL-TEMPLATES.md](file:///c:/Users/madhu/Desktop/ms-tb/spec/SQL-TEMPLATES.md) | Battle-tested SQL extraction patterns for ADR-022/026 | **Part 1–3:** Snowflake, BigQuery, PostgreSQL warehouse patterns; **Part 4:** Append-only data lakes; **Part 5:** Complex multi-fact joins with grain isolation; **Part 6:** SCD Type 2 dimensions; **Part 7:** Query optimization (predicate pushdown, partition pruning) |
| [IMPLEMENTATION-ROADMAP.md](file:///c:/Users/madhu/Desktop/ms-tb/spec/IMPLEMENTATION-ROADMAP.md) | 3-phase delivery plan (16 weeks total) with dependency tracking | **Phase 1 (6 weeks):** Foundation & extraction (STEPS 1–3); **Phase 2 (6 weeks):** Compilation & Hyper (STEPS 4–6); **Phase 3 (4 weeks):** Publishing & production safety (STEPS 7–10); Plus testing strategy, risk mitigation, deployment checklist |

---

## Key Design Decisions Summary

| # | Decision | Rationale |
|---|----------|-----------|
| ADR-001 | MSTR-first IR with extension points | Avoid premature generalization |
| ADR-002 | SQLite over PostgreSQL/dqlite | Zero ops for solo dev, single customer |
| ADR-003 | Collapse SCCs for dependency cycles | Atomic compilation of entangled objects & persisted wave state |
| ADR-004 | Single blank TWB template per version | Emitter handles all injection |
| ADR-005 | Rule compiler + 3-tier LLM fallback | Hash → pattern → semantic → LLM |
| ADR-006 | Partial publishing | Green content goes live; failures stay draft |
| ADR-007 | Failure Isolation & Dependency Propagation | FAILED(v) transitively poisons all dependents to BLOCKED |
| ADR-008 | Tableau-native auto layout | Don't clone MSTR pixels |
| ADR-009 | No incremental migration (MVP) | Full re-run each time |
| ADR-010 | Full append-only audit trail | Every API call, every AI invocation logged |
| ADR-011 | Entitlement tables for security | Immutable `USERNAME()` match, delimiter wrapped (ADR-031) |
| ADR-012 | One shared published datasource/project | Maximize Tableau reuse |
| ADR-013 | No prompt migration (MVP) | Document only, manual re-implementation |
| ADR-014 | Skip unused/orphan objects | Clean house during migration with explicit inventory logging |
| ADR-015 | Backend-first build order | Pipeline works before UI is built |
| ADR-016 | **Dynamic MSTRSession lifecycle** | **Proactive token re-auth with margin, 404 instance recreation, no fixed TTL assumptions** |
| ADR-017 | **Staging publish validation** | **XSD insufficient; publish to `_migration_staging`, call views API, delete** |
| ADR-018 | **Min-confidence auto-publish gate** | **`min(confidence)` across wave scope, not average** |
| ADR-019 | **Execution isolation + write queue** | **`asyncio.to_thread` + dedicated SQLite write queue; direct session use in threads prohibited** |
| ADR-020 | **SQLite WAL mode + batched audit** | **`PRAGMA journal_mode=WAL` & 100-event batched writes prevent lock convoys** |
| ADR-021 | **Live vs. Hyper connection rules** | **Explicit `connectionMode` per Table; no relationships spanning extract-live boundary** |
| ADR-022 | **⛔ Extraction Grain Contract** | **Warehouse-direct for Hyper (raw fact rows); MSTR API for golden tests only. Mandatory blocker if grain insufficient** |
| ADR-023 | **Staging/Production path rewriting** | **Two-emit sequence per workbook; `target_environment` flag rewrites datasource path in TWB XML** |
| ADR-024 | **Tableau Server version gate** | **Reject Tableau Server < 2020.2; logical relationship models unsupported on older versions** |
| ADR-025 | **Category-weighted confidence** | **Separate security/financial/structural/visual confidence; hard gates per category** |
| ADR-026 | **⛔ Physical Semantic SQL Planner** | **Dedicated compiler (Agent 3.5) converting MSTR schema & VLDB into warehouse SQL ASTs for raw Hyper extraction** |
| ADR-027 | **⛔ Semantic Metric Fingerprint** | **Deduplication by canonical 12-field fingerprint hash + CaptionRegistry, NOT formula strings** |
| ADR-028 | **Datasource Topology Fixed Before Emit** | **Datasource mode (`embedded` vs `published`) frozen in `DatasourcePlan`; dual staging/production datasource publishing** |
| ADR-029 | **Idempotent Promotion & Compensating Rollback** | **Target production write-locked until PROMOTE; remote idempotency reconciliation; compensating rollback on failure** |
| ADR-030 | **⛔ Reconstructable Snapshot Contract** | **Pin warehouse extraction and golden executions to reconstructable snapshot (Time-Travel / Temporal / CDC)** |
| ADR-031 | **⛔ Entitlement Normalization & Delimiters** | **Strict token normalization, delimiter-wrapped matching (`CONTAINS('\|' + [ALLOWED] + '\|', '\|' + [Val] + '\|')`), locked datasource** |
| ADR-032 | **⛔ Heterogeneous Fact Grain Isolation** | **Prohibits physical joins between facts with differing grains on partial keys alone; requires logical relationships** |
| ADR-033 | **Single-Expression Re-Validation Gate** | **IR patch in review queue re-validates syntax, re-evaluates semantic fingerprint, and cascades to dependent metrics** |
| ADR-034 | **Human Review Approval & Confidence** | **Human modifications provide additive confidence boost (+10% base, max 0.99); atomic re-emit and post-promotion error rate audit** |

---

## Interview Decisions Register

| Topic | Decision |
|-------|----------|
| **Source environment** | MicroStrategy Strategy One (cloud) |
| **Target environment** | Tableau Server (on-prem) |
| **Estate size** | < 50 dossiers, < 200 reports/cubes |
| **Deployment** | Single-process FastAPI, no containers for MVP |
| **Multi-tenancy** | None — single customer / internal use |
| **Storage** | SQLite + local filesystem |
| **Graph DB** | NetworkX in-memory (no Neo4j) |
| **LLM provider** | OpenAI/Azure OpenAI (reuse db-tb project config) |
| **LLM integration** | Direct API calls, no LangChain |
| **Frontend** | Next.js (TypeScript), separate from Python backend |
| **Auth (MSTR)** | Long-lived service account, username/password |
| **Data extraction** | Always via MSTR JSON Data API (not warehouse direct) |
| **Live connections** | Yes — generate TDS for warehouse where applicable |
| **Datasource architecture** | One shared published DS per MSTR project |
| **Validation** | Golden dataset approach (curated expected results) |
| **Job monitoring** | Polling-based status page |
| **Review UI** | Essential for MVP, built last per ADR-015 |
| **Report format** | Excel/PDF per project |
| **Lineage** | Cross-reference DB (MSTR GUID → Tableau ID) |
| **Viz type mapping** | LLM-assisted + static fallback table |
| **Formatting** | Basic (font sizes, colors, number formats). Skip theming. |
| **MSTR rate limiting** | Sequential with retry (no special throttling for MVP) |
| **Discovery strategy** | Search API with type filters, folder walk for structure |
| **RSD Documents** | Best-effort: treat grids/graphs as independent reports |
| **Folder mapping** | Flat: MSTR path → Tableau project hierarchy |
| **Unused content** | Silently skip |
| **Prompts** | Excluded from MVP |
| **FFSQL** | Parse SQL, materialize in Hyper, build clean datasource |
| **Localization** | English only |
| **Timeline** | No fixed deadline — iterate |
| **Team** | Solo developer |
| **License** | Proprietary |
| **ORM** | SQLAlchemy 2.0 |
| **Repo structure** | Monorepo (backend/ + frontend/) |
| **Error handling** | Skip object, log blocker, continue pipeline |
| **Dependency cycles** | Collapse SCCs, compile atomically |

---

## MVP Scope — In-Scope Object Types

| Object Type | Status |
|-------------|--------|
| ✅ Dossiers/Dashboards | In scope |
| ✅ Reports (template-based) | In scope |
| ✅ Metrics (base, derived, conditional, level/dimty) | In scope |
| ✅ Attributes & Facts | In scope |
| ✅ Intelligent Cubes (DDA) | In scope |
| ❌ FFSQL Reports/Cubes | Materialize to Hyper, best-effort |
| ❌ Security Filters | Deferred to post-MVP |
| ❌ Schedules/Subscriptions | Out of scope |
| ❌ RSD Documents | Best-effort conversion only |
| ❌ Prompts | Document only, no migration |

---

## Build Order (Solo Developer)

```
Phase 1: MSTR Extraction Pipeline
    ├─ MSTR REST API client (auth, session management)
    ├─ DiscoveryAgent (catalog building)
    └─ SemanticAgent (metric/attribute/filter extraction)

Phase 2: Expression Compiler
    ├─ MSTR expression tree parser
    ├─ Rule-based compiler + pattern catalog
    ├─ Golden test suite (20+ initial tests)
    └─ LLM fallback integration

Phase 3: BI-IR Schema & Compilation
    ├─ IR JSON schema definition
    ├─ IRCompilerAgent (semantic → IR)
    ├─ IR validator
    └─ AITranslationAgent (3-tier fallback)

Phase 4: Hyper Extract Generation
    ├─ MSTR data extraction (JSON Data API)
    ├─ HyperAgent (tableauhyperapi)
    └─ Multi-table Hyper with assumed FKs

Phase 5: Tableau Emission & Packaging
    ├─ TWB XML emitter (lxml + template copy)
    ├─ XSD validation
    ├─ TWBX packaging
    └─ Live connection TDS generation

Phase 6: Validation Framework
    ├─ Golden dataset comparison
    ├─ Row count / KPI value checks
    ├─ Scorecard generation
    └─ Auto-publish gate logic

Phase 7: Publishing
    ├─ Tableau Server REST publish (TSC)
    ├─ Project hierarchy creation
    ├─ Shared datasource publishing
    └─ Cross-reference recording

Phase 8: Review Dashboard (Next.js)
    ├─ Job list + detail pages
    ├─ Object catalog with filters
    ├─ Review queue with side-by-side comparison
    ├─ Inline IR editing + re-compilation
    ├─ Validation scorecard visualization
    └─ Migration report download

Phase 9: Polish
    ├─ Audit trail completeness
    ├─ Migration report generation (Excel/PDF)
    ├─ Error handling hardening
    └─ Documentation
```
