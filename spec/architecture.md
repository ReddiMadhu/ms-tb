# Architecture Specification — mstr-tableau-migrator

**Product:** MicroStrategy → Tableau Migration Platform  
**Codename:** `mstr-tableau-migrator`  
**Classification:** Proprietary / Internal Use  
**Date:** 17 August 2026  
**Author:** Auto-generated from interview + feasibility report  

---

## 0. Normative Specification Rules

This document defines authoritative architectural invariants for the platform.

### Priority of Authority:
1. **Safety & Security Invariants** (RLS isolation, credential protection, production write-locks)
2. **Data, Grain & Mathematical Parity Invariants** (Extraction grain proofs, watermark consistency, $\le 0.1\%$ KPI tolerance)
3. **State-Machine Invariants** (Two-phase staging promotion, idempotent recovery, failure propagation)
4. **API Contracts** (`api.md`, JSON schemas)
5. **Agent Behaviors** (`agents.md`, pseudocode)
6. **Implementation Details** (Language frameworks, libraries)

> **Conflict Resolution Mandate:** If any specification document conflicts with the invariants defined herein or in [validation-contract.md](file:///c:/Users/madhu/Desktop/ms-tb/spec/validation-contract.md), the conflict must be resolved before implementation. No implementation component may infer behavior from an ambiguous specification.

---

## 1. Product Vision & Positioning

### 1.1 What This Is

An AI-augmented migration platform that automatically extracts MicroStrategy (Strategy One) semantic metadata, compiles it into an intermediate representation, and emits validated Tableau Server artifacts — with confidence scoring, partial publishing, and a web-based review UI for exceptions.

### 1.2 What This Is NOT

- Not a pixel-perfect UI cloner (accept Tableau-native auto layout)
- Not a multi-tenant SaaS product (single-customer deployment)
- Not a real-time sync tool (batch migration, full re-runs, no incremental deltas)
- Not a "100% fidelity" promise — confidence-scored automation + review queue

### 1.3 Key Metrics

| Metric | Target |
|--------|--------|
| Numeric KPI match (automatable content) | ≥ 98% |
| Auto-conversion rate (average estate) | 60–80% |
| Critical KPI precision | ≤ 0.1% relative tolerance |
| Objects requiring manual review | < 30% |

### 1.4 Migration Execution Modes

The platform supports two operational execution modes:

1. **Selective Dossier Migration (Interactive Wizard Mode — Recommended):**
   - Operators use the `/jobs/new` visual wizard to run a fast pre-job discovery scan (`POST /discovery/dossiers`).
   - Operators browse, search, and check the specific dossiers to migrate.
   - The orchestrator extracts only the chosen dossiers and resolves their exact dependency subgraph (cubes, facts, attributes, shared/local metrics), avoiding unnecessary migration overhead.
2. **Full Project Estate Migration:**
   - Evaluates all folders and objects across the entire MicroStrategy project, pruning orphan/unused objects automatically.

---

## 2. Environment Context

| Concern | Decision |
|---------|----------|
| **Source platform** | MicroStrategy Strategy One (cloud) |
| **Source auth** | Username/password (standard REST `POST /api/auth/login`) |
| **Source estate size** | < 50 dossiers, < 200 reports/cubes |
| **Source warehouse** | TBD (to be discovered during extraction) |
| **Target platform** | Tableau Server (on-prem) |
| **Data strategy** | Mixed: live connections (same warehouse) + Hyper extracts |
| **Locale** | English only (MVP) |
| **Developer count** | Solo developer |
| **Timeline** | No fixed deadline — iterate until solid |

---

## 3. System Architecture

### 3.1 High-Level Overview

```
┌──────────────────────────────────────────────────────────┐
│                  mstr-tableau-migrator                    │
│                                                          │
│  ┌─────────────┐    ┌──────────────┐    ┌─────────────┐ │
│  │   FastAPI    │    │  Background  │    │  Next.js    │ │
│  │   Backend    │◄──►│   Workers    │    │  Review UI  │ │
│  │  (REST API)  │    │ (in-process) │    │ (frontend/) │ │
│  └──────┬──────┘    └──────┬───────┘    └──────┬──────┘ │
│         │                  │                    │        │
│         ▼                  ▼                    │        │
│  ┌─────────────────────────────────┐           │        │
│  │          SQLite (catalog)       │◄──────────┘        │
│  │  jobs, objects, scores, audit   │                    │
│  └─────────────────────────────────┘                    │
│         │                                               │
│         ▼                                               │
│  ┌─────────────────────────────────┐                    │
│  │   Local Filesystem (artifacts)  │                    │
│  │  IR JSON, .twb, .hyper, .twbx   │                    │
│  │  logs, reports, audit trail     │                    │
│  └─────────────────────────────────┘                    │
│                                                          │
└──────────────────────────────────────────────────────────┘
        │                           │
        ▼                           ▼
┌───────────────┐          ┌────────────────┐
│  MicroStrategy │          │ Tableau Server │
│  Strategy One  │          │   (on-prem)    │
│  (cloud REST)  │          │   (REST/TSC)   │
└───────────────┘          └────────────────┘
        │
        ▼
┌───────────────┐          ┌────────────────┐
│   Data         │          │   LLM Service  │
│   Warehouse    │          │  (OpenAI/Azure)│
│   (TBD)        │          │   + LLM Cache  │
└───────────────┘          └────────────────┘
```

### 3.2 Repository Structure

```
mstr-tableau-migrator/              ← monorepo
├── backend/                        ← Python FastAPI
│   ├── src/
│   │   └── app/
│   │       ├── main.py             ← FastAPI entrypoint
│   │       ├── core/               ← config, llm, cache, logging
│   │       ├── models/             ← SQLAlchemy ORM models
│   │       ├── db/                 ← session, migrations
│   │       ├── api/                ← route handlers
│   │       │   └── v1/
│   │       ├── agents/             ← pipeline agents
│   │       │   ├── discovery.py
│   │       │   ├── semantic.py
│   │       │   ├── ir_compiler.py
│   │       │   ├── ai_translation.py
│   │       │   ├── visualization.py
│   │       │   ├── hyper_builder.py
│   │       │   ├── tableau_emitter.py
│   │       │   ├── validation.py
│   │       │   ├── publisher.py
│   │       │   └── review_queue.py
│   │       ├── services/
│   │       │   ├── mstr_client/    ← MSTR REST API client
│   │       │   ├── expression/     ← AST compiler, pattern catalog, LLM fallback
│   │       │   ├── ir/             ← BI-IR schema, builder, validator
│   │       │   ├── tableau/        ← TWB XML emitter, Hyper builder, packager
│   │       │   └── pipeline/       ← orchestrator, job management
│   │       └── workers/            ← in-process background task runner
│   ├── templates/                  ← golden Tableau .twb templates
│   │   └── tableau/
│   │       └── blank-{version}.twb
│   ├── tests/
│   ├── golden_tests/               ← curated metric translation test data
│   ├── artifacts/                  ← runtime output directory
│   ├── requirements.txt
│   ├── pyproject.toml
│   └── .env.example
├── frontend/                       ← Next.js (TypeScript)
│   ├── src/
│   │   ├── app/
│   │   ├── components/
│   │   └── lib/
│   ├── package.json
│   └── tsconfig.json
├── spec/                           ← this specification
└── README.md
```

### 3.3 Technology Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| **Backend framework** | Python 3.11+ / FastAPI | Async, type-safe, consistent with db-tb |
| **ORM** | SQLAlchemy (2.0) | Consistent with db-tb, works with SQLite |
| **Database** | SQLite | Zero ops, single-customer, single-file |
| **Background tasks** | FastAPI `BackgroundTasks` / in-process | Solo dev, single-process MVP |
| **Artifact storage** | Local filesystem | No S3/MinIO needed for single deployment |
| **LLM** | OpenAI / Azure OpenAI (reuse db-tb config) | GPT-4o-mini / GPT-4o |
| **LLM caching** | SHA-256 hash → JSON file (db-tb pattern) | Avoid repeated API calls |
| **Expression validation** | `sqlglot` (Tableau dialect where applicable) | Syntax check before emit |
| **Tableau extract** | `tableauhyperapi` | Official Hyper creation |
| **Tableau publish** | `tableauserverclient` (TSC) | Official REST publish |
| **TWB generation** | `lxml` + XSD validation | XML manipulation + structural check |
| **Dependency graph** | `networkx` (in-memory) | Sufficient for <200 objects |
| **Settings** | `pydantic_settings` | Consistent with db-tb |
| **Frontend** | Next.js (TypeScript) | Rich review UI |
| **Frontend ↔ Backend** | REST API (JSON) | Polling-based status |
| **Audit log** | Append-only SQLite table | Full trail per requirement |

### 3.4 Deployment Model

**Single-process deployment:**

```bash
# Backend
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000

# Frontend
cd frontend && npm run dev  # or npm run build && npm start
```

Background tasks run in-process via FastAPI's `BackgroundTasks` or `asyncio` tasks. No Celery, no Redis, no separate worker processes.

> **CRITICAL (Audit Fix #4):** All blocking calls — `HyperProcess` (subprocess spawn), `Inserter.add_rows()`, `tableauserverclient` publish (synchronous HTTP) — **must** be wrapped in `asyncio.to_thread()` to prevent event loop deadlock. Without this, the FastAPI event loop blocks during Hyper builds (5–15 min for large extracts), causing all poll requests from the Next.js frontend to queue and timeout.
>
> ```python
> # WRONG — blocks event loop
> await hyper_agent.run()
>
> # CORRECT — runs in thread pool, event loop stays responsive
> await asyncio.to_thread(hyper_agent.run_sync)
> ```

---

## 4. Design Decisions (ADRs)

### ADR-001: MSTR-first IR with Extension Points
Design the BI-IR strictly for MSTR→Tableau now. Include namespaced `vendorExtensions` blocks for future source/target adapters. Avoid premature generalization.

### ADR-002: SQLite over PostgreSQL/dqlite
Single-customer, single-developer, <200 objects. SQLite provides zero-ops overhead. If scale demands change, migrate to PostgreSQL later — SQLAlchemy abstraction makes this straightforward.

### ADR-003: Collapse Strongly-Connected Components for Cycles & Persisted Waves
When dependency cycles exist (metric ↔ filter ↔ prompt), collapse strongly-connected components into a single immutable `MigrationUnit`.
- **MigrationUnit Structure:** Contains `scc_id`, `member_object_ids`, `internal_edges`, `external_dependencies`, `external_dependents`, `wave_index`, `compile_status`, and `failure_reason`.
- **Topological Invariant:** For every dependency edge $u \to v$ (where $u \text{ USES } v$), $\text{wave}(u) \ge \text{wave}(v)$ must strictly hold unless $u$ and $v$ belong to the same SCC.
- **Wave State Persistence:** All wave assignments and execution statuses are persisted to SQLite `wave_executions` table (`job_id`, `wave_id`, `scc_id`, `object_id`, `dependency_hash`, `status`, `attempt`, `started_at`, `completed_at`, `failure_reason`) to guarantee crash resilience.

### ADR-004: Single Blank Template per Tableau Version
One empty golden `.twb` per target Tableau Server version. The XML emitter handles all layout injection. No variant shells.

> **Audit constraint:** Blank templates **must** be saved with *logical table connections* (Tableau's relationship model, not physical joins) and with an empty published datasource reference (not an embedded connection). The emitter injects into the logical-table XML structure. Requires Tableau Server **2020.2+**.

### ADR-005: Rule-Based Compiler + 3-Tier LLM Fallback
Expression compilation: deterministic AST pattern catalog first. Fallback sequence: hash lookup → pattern match → semantic search → LLM (only if all three miss). Every LLM-proposed calc must pass golden tests.

### ADR-006: Partial Publishing
Worksheets/dashboards that pass validation get published. Failed ones are hidden via `<worksheet-visibility>` XML attributes in the dashboard zone — **not removed from the TWB**. This preserves the dashboard layout structure for future re-attempts after review. Users see working content while exceptions sit in the review queue.

### ADR-007: Failure Isolation and Dependency Propagation
An extraction or compilation failure must never invalidate unrelated objects. However, any object that transitively depends on a failed object becomes `BLOCKED` and cannot be emitted as validated content.

**Failure Classes:**
- `FAILED_EXTRACT`
- `FAILED_COMPILE`
- `FAILED_VALIDATION`
- `BLOCKED_DEPENDENCY`
- `SKIPPED_UNUSED`
- `SKIPPED_INACCESSIBLE`
- `SKIPPED_UNSUPPORTED`

**Propagation Invariant:**
$$\text{FAILED}(v) \implies \forall u \text{ where } u \text{ transitively depends on } v: \text{status}(u) \in \{\text{BLOCKED}, \text{REVIEW\_REQUIRED}\}$$
- Direct and transitive dependents become `BLOCKED`. A `BLOCKED` object can **never** receive `STATUS_SUCCESS`.
- A failed security dependency strictly blocks the affected workbook/dossier.
- Every skipped, failed, or blocked object must appear with explicit reason codes in the audit inventory.

### ADR-008: Tableau-Native Auto Layout
Accept Tableau's automatic tiled layout. Don't attempt to reconstruct MSTR pixel positioning. This is a feature — users learn Tableau's paradigm.

### ADR-009: No Incremental Migration
Each run is a full, clean migration from scratch. No delta tracking for MVP.

### ADR-010: Full Audit Trail
Log every API call to MSTR, every object touched, every AI invocation with prompt/response, every validation score, every publish action. Append-only SQLite table.

### ADR-011: Entitlement Table for Security Filters
Map MSTR users/groups to Tableau user filters via entitlement tables in Hyper extracts with `USERNAME()` match column (immutable login IDs). Not Tableau RLS calculated fields.

### ADR-012: Shared Published Datasource
One shared published Tableau datasource per MSTR project. All workbooks reference this shared datasource. Local calculations specific to dossiers are emitted as workbook-local calcs with federation XML (`<datasource caption='[shared_ds_name]'>`).

### ADR-013: No Prompt Migration (MVP)
Document existing MSTR prompts in the migration report. Don't attempt automated prompt → parameter conversion. Tableau developers re-implement interactivity manually.

### ADR-014: Skip Unused Content with Explicit Inventory
Unused/orphan objects are not migrated. Every skipped object appears in the audit report categorized as: (a) unused per usage stats, (b) unused per dependency analysis, (c) inaccessible (permission denied), or (d) unsupported type.

### ADR-015: Backend-First Build Order
Build the entire Python pipeline end-to-end. Verify it works. Then build the Next.js review UI as the last major component.

### ADR-016: Dynamic MSTRSession Lifecycle Management
The implementation must not depend on fixed MSTR token or cube-instance TTL assumptions (e.g. fixed 30m/10m). The session manager shall:
1. Track token creation time and proactively renew using a configurable safety margin (`proactive_renewal_margin_seconds: 60`).
2. Treat HTTP 401/authorization expiry as authoritative.
3. Re-create cube instances on HTTP 404 (where instance expiry is suspected) with `page_offset` state preserved.
4. Persist `last_successful_page_offset` to SQLite `extraction_checkpoints` table so a crashed extraction resumes from the last committed page.
5. Record observed server behavior dynamically in the audit log.

### ADR-017: Staging Publish Validation
XSD validation is necessary but insufficient — Tableau Server performs semantic validation that XSD cannot catch. Before final publish, the PublishAgent uploads TWBX to a `_migration_staging` Tableau Server project, calls the workbook-views REST API (`GET .../workbooks/{id}/views`) to trigger server-side rendering/validation. If 200 → semantically valid → proceed to promotion.

### ADR-018: Min-Confidence Auto-Publish Gate
The auto-publish gate uses `min(confidence)` across all measures in the wave's scope — not the average. A dossier with 9 metrics at 0.99 and one at 0.50 has effective confidence 0.50.

### ADR-019: Execution Isolation
Run Hyper builds and MSTR extraction in background threads via `asyncio.to_thread()`. All SQLite writes from background threads must go through a dedicated async write queue (`asyncio.Queue`) drained by a single writer coroutine. Direct SQLAlchemy session use inside worker threads is prohibited.

### ADR-020: SQLite WAL Mode + Batched Audit Writes
SQLite is opened in WAL mode (`PRAGMA journal_mode=WAL`). Audit log writes are accumulated in-memory for up to 100 events or 5 seconds, then flushed in a single transaction.

### ADR-021: Live vs. Hyper Connection Reconciliation
- `Table.connectionMode: "extract" | "live"` on IR Table entity.
- Relationships cannot span extract→live boundaries; dimensions must be materialized into extracts.

### ADR-022: Extraction Grain Contract (Mandatory Invariant)
The MSTR JSON Data API returns pre-aggregated data, which breaks Tableau LOD calculations. Warehouse-direct SQL extraction is mandatory for Hyper data (raw fact rows, proper FKs). MSTR API results are reserved strictly for golden-test ground truth validation.
- **Mandatory Invariant:** No Hyper table may be generated without a validated `ExtractionGrain`. No Tableau LOD may reference a dataset whose physical grain is insufficient to evaluate that LOD (`insufficient_extraction_grain` = BLOCKER).

### ADR-023: Staging/Production Path Rewriting
Two-emit sequence per workbook:
1. Emit TWB with **staging** datasource path (`_migration_staging/Datasources/...`) → publish to staging → validate.
2. Re-emit TWB with **production** datasource path (`{target_project}/Datasources/...`) during `PROMOTE`.
3. Clean up staging workbook.

### ADR-026: Physical Semantic SQL Planner (Agent 3.5)
Dedicated compiler transforming MSTR schema, attribute forms, fact expressions, and VLDB settings into direct warehouse SQL ASTs with exact grain derivation.

### ADR-027: Canonical Semantic Metric Fingerprinting & CaptionRegistry
Deduplication of metrics across waves evaluates a 12-field `SemanticFingerprint` with a canonical `fingerprint_hash`.
- **`CaptionRegistry`:** Scoped globally per published datasource. Disambiguates identical captions referencing distinct fingerprints, preventing accidental overwrites by generating deterministic unique Tableau field names.

### ADR-028: Datasource Topology Fixed Before Emit
Datasource architecture decisions (`embedded` vs `published`) are frozen in `DatasourcePlan` before generating any TWB XML. No in-flight topology mutations.

### ADR-029: Idempotent Promotion and Compensating Rollback
Tableau Server does not participate in the engine's SQLite transaction; production promotion is not a distributed 2PC transaction.
- **Production Write-Lock Invariant:** Target production project on Tableau Server is strictly write-locked during all extraction, compilation, staging emission, and validation steps. No production entity is created or modified until the `PROMOTE` step.
- **Idempotency & Reconcile:** Every operation carries an `idempotency_key = sha256(job_id + artifact_id + environment + version)`. If network timeout occurs, the remote entity state is queried and reconciled.
- **Compensating Rollback:** If staging validation fails or promotion is rejected, staging artifacts are deleted and production remains 100% untouched.

### ADR-030: Reconstructable Snapshot Watermark Contract
A timestamp predicate is valid only when the source warehouse guarantees a reconstructable historical state.
- For append-only warehouses: `WHERE load_timestamp <= :validation_watermark`.
- For mutable/in-place updated warehouses: Native time-travel (Snowflake `AT(TIMESTAMP => ...)`), system-versioned temporal tables, CDC batch IDs, or immutable snapshot tables are required. If historical state cannot be reconstructed: `Issue(BLOCKER, non_reconstructable_snapshot)`.

### ADR-031: Entitlement Predicate Safety & Isolation
- **Strict Normalization:** Security tokens undergo trimming, uppercase folding, Unicode NFKC normalization, pipe-escaping, and empty-token rejection.
- **Delimiter Wrapping:** Predicates enforce:
  ```tableau
  CONTAINS([ALLOWED_VALUES_NORMALIZED], "|" + UPPER(TRIM([Region])) + "|")
  ```
- Keyed strictly to immutable `USERNAME()`. Entitlements are published to a separate, permission-locked datasource (`_migration_staging/Datasources/Entitlements_Locked`).

### ADR-032: Heterogeneous Fact Grain Isolation
Facts with incompatible physical grains (e.g. Daily Sales at `(date, product)` vs. Monthly Budget at `(month, product)`) must **never** be physically joined on partial keys alone.
- Allowed solutions: (a) separate logical fact tables in Tableau relationship model, (b) explicit conformed-grain transformation, or (c) pre-aggregation with documented cardinality proof.
- Unproven joins emit: `Issue(BLOCKER, heterogeneous_fact_grain_join)`.

### ADR-033: Single-Expression Re-Validation Gate Post-IR-Edit
When an operator applies an IR patch to a calculation in the review queue:
- The expression compiler re-validates syntax, re-evaluates semantic fingerprint, checks for collision, and cascades re-validation to transitive dependent metrics.
- The `ValidationScorecard` is re-aggregated in real-time. If all blocker issues are cleared and `auto_publish_ok` evaluates to `True`, the job is marked `AUTO_PUBLISHABLE`.

### ADR-034: Human Review Approval Workflow & Confidence Calibration
Human operator modifications in the review queue:
- Provide an additive confidence boost (+10% base, +5% for detailed justification notes, +5% for BI Architect certification), capped strictly at 0.99.
- Approval re-acquires the production write-lock, applies all registered IR edits, re-emits production artifacts, promotes atomically, and audits production rendering error rates post-promotion.

---

## 5. Orchestrator State Machine (Normative Two-Phase Flow)

```
[PHASE 1: EXTRACTION & COMPILATION WAVES]
DISCOVERY 
  → GRAPH (SCC condensation & persisted waves)
  → [FOR EACH WAVE:
       SEMANTIC_EXTRACT 
       → PHYSICAL_MODEL_PLAN (Heterogeneous grain check)
       → IR_COMPILE 
       → HYPER_BUILD]

[PHASE 2: GLOBAL DEDUPLICATION, STAGING, VALIDATION & CONTROLLED PROMOTION]
  → METRIC_DEDUPLICATION (Canonical SemanticFingerprint hash & CaptionRegistry)
  → AI_TRANSLATE (Low-confidence / unmapped patterns only)
  → VIZ_PLAN
  → DATASOURCE_PLAN & DATASOURCE_EMIT(staging)
  → DATASOURCE_PUBLISH_STAGING
  → WORKBOOK_EMIT(staging)
  → STATIC_VALIDATE (Deterministic XML/XSD parsing)
  → STAGING_PUBLISH
  → SERVER_RENDER_VALIDATE (Crosstab view rendering check)
  → SECURITY_VALIDATE (Impersonation-based Connected App member-set diff)
  → NUMERIC_VALIDATE (Watermark/snapshot-pinned KPI comparison)
  → PROMOTE_PRECHECK (auto_publish_ok evaluation per validation-contract.md)
  → [IF auto_publish_ok:
       PROMOTE:
         ├─ DATASOURCE_PUBLISH_PRODUCTION (Write-lock released)
         ├─ RECONCILE_DATASOURCE
         ├─ WORKBOOK_EMIT(production)
         ├─ WORKBOOK_PUBLISH_PRODUCTION
         ├─ APPLY_PERMISSIONS
         └─ RECONCILE_PRODUCTION
       → CLEANUP_STAGING
       → REPORT
       → COMPLETE]
  → [ELSE:
       ENQUEUE_REVIEW
       → ROLLBACK_STAGING (Production remains untouched)]
```

> **Normative State Invariants:**
> 1. `STATIC_VALIDATE` strictly precedes `STAGING_PUBLISH`.
> 2. No production write occurs outside the `PROMOTE` composite state. Production is strictly write-locked prior to promotion.
> 3. `METRIC_DEDUPLICATION` runs globally across all waves before datasource emission.
> 4. All warehouse queries and golden data executions pin the `validation_watermark` snapshot.
> 5. Entitlement predicates are delimiter-wrapped, normalized, and keyed to `USERNAME()`.
