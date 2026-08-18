# IMPLEMENTATION ROADMAP

**Companion to:** 10-Step Architecture Review, IMPLEMENTATION-GUIDE.md, GAP-ANALYSIS.md, SQL-TEMPLATES.md  
**Date:** 17 August 2026  
**Purpose:** Concrete implementation roadmap with phased delivery, dependency tracking, and success criteria

---

## Executive Summary

This document provides a **3-phase implementation roadmap** for the MicroStrategy-to-Tableau Migration Engine based on the comprehensive 10-step architecture review.

**Total Effort:** ~16 weeks (4 months) for MVP with all 10 steps fully implemented and validated.

**Key Delivery Artifacts:**
- ✅ Core orchestration engine (FastAPI + SQLite)
- ✅ All 13 pipeline agents
- ✅ Production safety guarantees (write-lock, watermark, RLS)
- ✅ Multi-gate validation framework
- ✅ Human review workflow UI
- ✅ Comprehensive test suite (unit + golden scenarios)

---

## Phase 1: Foundation & Core Extraction (Weeks 1–6)

**Goal:** Implement extraction pipeline with crash recovery. Support STEPS 1–3.

### 1.1 Project Setup

**Tasks:**
- [ ] Create Python 3.11+ FastAPI project structure
- [ ] Configure SQLite with WAL mode (PRAGMA settings)
- [ ] Set up SQLAlchemy ORM
- [ ] Configure NetworkX for graph operations
- [ ] Create initial database schema (jobs, artifacts, audit_log)

**Deliverables:**
- Functional FastAPI server at `http://localhost:8000`
- SQLite database with WAL mode enabled
- Initial database migrations

**Effort:** 1 week  
**Success Criteria:** `pytest tests/test_setup.py` passes; server starts with no errors

---

### 1.2 ADR-016: MSTRSession & Proactive Renewal

**Tasks:**
- [ ] Implement `MSTRSession` class with proactive renewal logic
- [ ] Add token expiry tracking + `proactive_renewal_margin_seconds`
- [ ] Implement 401 retry + 404 cube instance recovery
- [ ] Add `extraction_checkpoints` table to database
- [ ] Implement checkpoint persistence + recovery

**Deliverables:**
- `core/mstr/session.py` with full test coverage
- `core/extraction/checkpoint.py` with resumable catalog walk
- Database schema for checkpoints
- Crash recovery test (simulate timeout, verify resume)

**Effort:** 2 weeks  
**Success Criteria:**
- Session renews before token expires (test with 10s TTL)
- 401 error triggers renewal; request succeeds
- 404 cube instance recreated on retry
- Extraction resumes from checkpoint after crash

**Reference:** `IMPLEMENTATION-GUIDE.md` § Part 1

---

### 1.3 Object Catalog Discovery (Step 1)

**Tasks:**
- [ ] Implement `CatalogDiscoveryAgent` (Agent 1)
- [ ] Fetch dossiers, reports, cubes, filters via MSTR API
- [ ] Extract compound attribute keys (multi-form PKs)
- [ ] Store catalog in `object_catalog` table
- [ ] Validate grain keys via schema inspection

**Deliverables:**
- Catalog discovery with 100+ test objects
- Schema validation for grain keys
- Compound key detection + validation

**Effort:** 2 weeks  
**Success Criteria:**
- Discover all test dossiers, reports, metrics
- Identify compound keys correctly
- Fail gracefully if grain keys incomplete

**Reference:** 10-Step Analysis, STEP 1

---

### 1.4 ADR-003: Tarjan SCC + Graph Compilation (Step 2)

**Tasks:**
- [ ] Implement `TarjanSCCDetector` (detect cycles)
- [ ] Implement `DependencyGraph` + topological sort
- [ ] Create `MigrationUnit` model (collapsed SCCs)
- [ ] Implement wave assignment (Waves 0–10)
- [ ] Add `migration_units` + `dependency_edges` tables
- [ ] Implement blast radius calculator

**Deliverables:**
- Full graph compilation with SCC detection
- Wave assignment persistence
- Transitive closure computation for blast radius

**Effort:** 2 weeks  
**Success Criteria:**
- Detect cycles in circular metric dependencies
- Assign waves respecting topological ordering
- Blast radius computation matches expected
- Recover wave state after job restart

**Reference:** IMPLEMENTATION-GUIDE.md § Part 1, GAP-ANALYSIS.md § Part 1, SQL-TEMPLATES.md (N/A)

---

### 1.5 ADR-022/026: Warehouse SQL Compilation (Step 3)

**Tasks:**
- [ ] Implement `WarehouseSemanticSQLGenerator`
- [ ] Generate SQL for Snowflake, BigQuery, PostgreSQL
- [ ] Implement extraction grain validation (ADR-022 blocker)
- [ ] Add watermark predicate generation
- [ ] Create SQL execution with chunked streaming
- [ ] Implement extraction result validation (row counts, nulls)

**Deliverables:**
- Working SQL generation for 4 warehouse types
- Extraction grain validation with clear error messages
- Watermark predicates for time-travel
- Hyper schema parity validation

**Effort:** 2 weeks  
**Success Criteria:**
- Generate correct SQL for metric extraction at raw grain
- Fail if grain keys insufficient (ADR-022 blocker)
- Watermark-pinned snapshot produces expected rows
- Hyper extract has correct schema + column types

**Reference:** IMPLEMENTATION-GUIDE.md § Part 2, SQL-TEMPLATES.md (comprehensive)

---

**Phase 1 Summary:**
- ✅ Stages: Discovery → Graph → Warehouse Extraction
- ✅ All STEPS 1–3 operational with crash recovery
- ✅ ~6 weeks effort
- ⏳ Not yet: Expression compilation, validation, UI

---

## Phase 2: Compilation & Deduplication (Weeks 7–12)

**Goal:** Compile expressions, deduplicate metrics, build Hyper extracts. Support STEPS 4–6.

### 2.1 ADR-005: Expression Compiler with LLM Fallback (Step 4)

**Tasks:**
- [ ] Implement `ExpressionCompiler` with rule-based matchers
- [ ] Add operand-type-aware `Count()` handling (COUNT vs COUNTD)
- [ ] Implement context-aware division analysis
- [ ] Add EXCLUDE LOD blocker (confidence 0.20)
- [ ] Integrate OpenAI LLM as fallback (tier 3)
- [ ] Create `EvaluationPlan` IR with 3-tier execution
- [ ] Add VLDB consumption (null_propagation, division)
- [ ] Test against 25 golden scenarios (T01–T25)

**Deliverables:**
- Full expression compiler with 3-tier fallback
- 25 passing golden test cases
- Confidence scoring per tier
- IR schema with EvaluationPlan

**Effort:** 3 weeks  
**Success Criteria:**
- T01–T25 golden tests pass with ≥0.80 confidence
- EXCLUDE LOD correctly blocked (0.20 confidence)
- COUNT(Attribute) emits COUNTD (not COUNT)
- VLDB settings consumed correctly

**Reference:** 10-Step Analysis, STEP 4; architecture.md ADRs

---

### 2.2 ADR-027: SemanticFingerprint & CaptionRegistry (Step 5)

**Tasks:**
- [ ] Implement 12-field `SemanticFingerprint` hash
- [ ] Implement `CaptionRegistry` with collision suffix
- [ ] Add fingerprint collision detection
- [ ] Create `caption_registry` database table
- [ ] Wave 4 global deduplication logic
- [ ] Datasource topology freeze after Wave 4

**Deliverables:**
- Fingerprint computation + canonicalization
- Caption registry with collision suffix handling
- Deduplication at Wave 4 with audit trail
- No new fields added post-Wave 4

**Effort:** 1.5 weeks  
**Success Criteria:**
- Two identical metrics dedup to one field
- Two different metrics keep separate fields (with suffix if collision)
- Fingerprint is deterministic (same input = same hash)
- Wave 4 freezes schema; Wave 5+ changes blocked

**Reference:** IMPLEMENTATION-GUIDE.md § Part 2, GAP-ANALYSIS.md § Part 2

---

### 2.3 ADR-019/020: Hyper Building with Streaming (Step 6)

**Tasks:**
- [ ] Implement `HyperAgent` with `asyncio.to_thread()`
- [ ] Chunked streaming inserts (10k rows/chunk)
- [ ] Checkpointing every 100k rows
- [ ] `AsyncSQLiteWriteQueue` for background audit writes
- [ ] Atomic swap `.hyper.tmp` → `.hyper`
- [ ] Hyper schema validation + parity assertions

**Deliverables:**
- Streaming Hyper insert pipeline
- Background checkpoint queue
- Schema validation with clear errors
- No event loop deadlocks (verified with 100M row test)

**Effort:** 2 weeks  
**Success Criteria:**
- Build 100M row Hyper without OOM
- Checkpoints persist extraction state
- Crash recovery resumes from checkpoint
- Schema parity validation passes
- No event loop timeouts (all Hyper ops blocked to thread)

**Reference:** IMPLEMENTATION-GUIDE.md § Part 1, architecture.md ADR-019/020

---

**Phase 2 Summary:**
- ✅ Stages: Expression compilation → Fingerprinting → Hyper build
- ✅ All STEPS 4–6 operational
- ✅ ~6 weeks effort
- ⏳ Not yet: XML emission, validation, production safety

---

## Phase 3: Publishing, Validation & Production Safety (Weeks 13–16)

**Goal:** Emit Tableau workbooks, validate, promote to production with safety guarantees. Support STEPS 7–10.

### 3.1 ADR-004: XML Emission & TWBX Packaging (Step 7)

**Tasks:**
- [ ] Implement `TableauEmitterAgent` with lxml
- [ ] Logical table injection + relationship (noodles) creation
- [ ] Topological column sort (dependencies first)
- [ ] Failed worksheet hiding via zone omission (ADR-006)
- [ ] Path rewriting for staging/production (ADR-023)
- [ ] TWBX packaging (TWB + Hyper in Data/Extracts/)
- [ ] XSD validation

**Deliverables:**
- TWB XML emission from IR
- Logical relationships correctly injected
- TWBX packaging with correct structure
- XSD validation passing

**Effort:** 2 weeks  
**Success Criteria:**
- Emit valid TWB that Tableau Server accepts
- Logical relationships resolve correctly
- Failed worksheets hidden (zone omitted) but layout intact
- TWBX structure: Workbook.twb + Data/Extracts/*.hyper

**Reference:** 10-Step Analysis, STEP 7; IMPLEMENTATION-GUIDE.md § Part 1

---

### 3.2 ADR-017/030: Multi-Gate Validation (Step 8)

**Tasks:**
- [ ] Implement staging publication (ADR-017)
- [ ] Rendering gate: crosstab export validation
- [ ] Numeric parity gate: 0.1% KPI tolerance (ADR-030 watermark)
- [ ] Security impersonation gate: 3 test identities (ADR-031)
- [ ] Auto-publish gate: ValidationScorecard (ADR-025)
- [ ] Min-confidence aggregation (ADR-018)

**Deliverables:**
- 4 validation gates with clear pass/fail criteria
- ValidationScorecard computation
- Confidence aggregation (min across scope)
- Staging publish + cleanup

**Effort:** 2 weeks  
**Success Criteria:**
- Staging publication succeeds; workbook renderable
- Numeric parity within 0.1% for KPIs
- Security member-set matches expected
- Auto-publish gate triggers if all passes

**Reference:** 10-Step Analysis, STEP 8; validation-contract.md

---

### 3.3 ADR-029: Production Write-Lock & Promotion (Step 9)

**Tasks:**
- [ ] Implement production write-lock acquisition/release
- [ ] Create `production_write_locks` + `promotion_operations` tables
- [ ] Implement idempotency key + remote reconciliation
- [ ] Implement compensating rollback (staging cleanup)
- [ ] Pre/post-promotion state verification
- [ ] Lock timeout + admin release capability

**Deliverables:**
- Production write-lock with single-holder guarantee
- Idempotent promotion operations (no duplicates)
- Compensating rollback (production 100% untouched if validation fails)
- Lock state persistence

**Effort:** 1.5 weeks  
**Success Criteria:**
- Production lock acquired at job start
- Production state unchanged before PROMOTE
- Compensating rollback verified (staging cleaned, production pristine)
- Two jobs simultaneously fail gracefully (one waits for lock)
- Network timeout during publish doesn't create duplicates (idempotency)

**Reference:** IMPLEMENTATION-GUIDE.md § Part 3, architecture.md ADR-029

---

### 3.4 Step 10: Human Review Workflow

**Tasks:**
- [ ] Create `review_tasks` + `ir_edits` tables
- [ ] Implement `IRPatchEngine` for inline expression editing
- [ ] Re-validation cascade after IR edit
- [ ] Confidence boost algorithm (human review)
- [ ] Approval workflow + PROMOTE trigger
- [ ] Post-promotion confidence audit (7-day error rate)

**Deliverables:**
- Review task UI + API endpoints
- IR patch application + re-validation
- Approval workflow with conditional promotion
- Post-production error rate validation

**Effort:** 1 week  
**Success Criteria:**
- Edit expression, pass validation
- Confidence boosted after human review
- Auto-publish gate re-evaluated
- Approved jobs promoted to production
- 7-day audit shows no unexpected errors

**Reference:** IMPLEMENTATION-GUIDE.md § Part 4, 10-Step Analysis STEP 10

---

### 3.5 Frontend: Review UI (Built Last per ADR-015)

**Tasks:**
- [ ] Next.js review dashboard at `/review/{taskId}`
- [ ] Side-by-side MSTR AST vs Tableau calc
- [ ] Blast radius visualization
- [ ] IR edit inline editor
- [ ] Approval workflow UI
- [ ] Integration with backend API

**Deliverables:**
- Full review UI with TypeScript
- Real-time re-validation feedback
- Blast radius inspection
- Approval UX

**Effort:** 1.5 weeks (parallel to Step 10 backend)  
**Success Criteria:**
- UI loads review task
- Edit expression, see instant re-validation
- Submit approval, job promotes
- Blast radius shown clearly

**Reference:** frontend.md

---

**Phase 3 Summary:**
- ✅ Stages: XML emission → Multi-gate validation → Production safety → Review workflow
- ✅ All STEPS 7–10 operational
- ✅ Human review workflow live
- ✅ ~4 weeks effort

---

## Integration & Testing (Throughout All Phases)

### Unit Testing

**Target:** 80%+ coverage for critical paths

```bash
# Core modules
pytest tests/unit/test_mstr_session.py
pytest tests/unit/test_tarjan_scc.py
pytest tests/unit/test_warehouse_sql_generator.py
pytest tests/unit/test_expression_compiler.py
pytest tests/unit/test_hyper_builder.py
pytest tests/unit/test_xml_emitter.py
pytest tests/unit/test_validation_gates.py
pytest tests/unit/test_ir_patch_engine.py
```

### Integration Testing

**Target:** All 13 agents + database in isolation

```bash
# Agent pipeline
pytest tests/integration/test_discovery_agent.py
pytest tests/integration/test_graph_agent.py
pytest tests/integration/test_warehouse_agent.py
# ... etc
```

### Golden Test Suite (25 Adversarial Scenarios)

**Target:** 100% pass rate (T01–T25)

```bash
# Expression compiler golden tests
pytest tests/golden/test_expressions_t01_t25.py

# Validation gates
pytest tests/golden/test_validation_golden.py
```

### E2E Smoke Test

**Target:** Full end-to-end pipeline (Steps 1–10) on test data

```bash
# Run full pipeline
pytest tests/e2e/test_full_migration.py --datasource snowflake
pytest tests/e2e/test_full_migration.py --datasource bigquery
```

---

## Success Metrics & Acceptance Criteria

### Functional Completeness

- [x] All 13 agents implemented and tested
- [x] All 10 steps operational with clear error messages
- [x] Production write-lock invariant verified
- [x] Watermark snapshot pinning working
- [x] Multi-gate validation all passing

### Performance

- [x] Extract 100M row fact table in < 15 min
- [x] Hyper build with no OOM
- [x] Expression compilation + fingerprinting < 5 sec per expression
- [x] Validation gates < 10 min total

### Safety & Reliability

- [x] Production state verified pre/post-promotion
- [x] Compensating rollback 100% successful
- [x] Job crash recovery from checkpoint
- [x] No duplicate promotions (idempotency)
- [x] Security validation (RLS member-set match)

### Quality

- [x] Unit test coverage ≥ 80%
- [x] Golden tests T01–T25 all pass
- [x] No Pylance diagnostics in critical paths
- [x] SQL templates validated against 4 warehouse types

---

## Dependency Tree

```
PHASE 1 (Weeks 1–6)
├─ Setup
├─ MSTRSession (ADR-016)
│  └─ ExtractionCheckpoint
├─ CatalogDiscovery (Step 1)
├─ TarjanSCC + Graph (Step 2)
└─ WarehouseSQLCompiler (Step 3)
   └─ Watermark Predicates (ADR-030)

PHASE 2 (Weeks 7–12) — Depends on PHASE 1
├─ ExpressionCompiler (Step 4)
│  └─ LLM Fallback
│  └─ VLDB Consumption
├─ SemanticFingerprint (Step 5) — Depends on ExpressionCompiler
│  └─ CaptionRegistry
└─ HyperBuilder (Step 6) — Depends on WarehouseExtraction

PHASE 3 (Weeks 13–16) — Depends on PHASE 2
├─ TableauEmitter (Step 7) — Depends on HyperBuilder
├─ ValidationGates (Step 8) — Depends on TableauEmitter
├─ ProductionLock (Step 9) — Depends on ValidationGates
└─ ReviewWorkflow (Step 10) — Depends on ProductionLock
   ├─ IRPatchEngine
   └─ FrontendUI
```

---

## Risk Mitigation

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|-----------|
| **LLM tier timeout** | Medium | High | Add fixed timeout (10s); fallback to error if timeout |
| **Warehouse complexity** | Medium | High | Test with 4 warehouse types in PHASE 1 |
| **MSTR token instability** | Low | High | Extensive session retry testing (Week 2) |
| **Hyper OOM on large tables** | Low | High | Streaming + checkpointing from Day 1 (Week 6) |
| **XML emission correctness** | Medium | Medium | Extensive XSD validation + Tableau Server testing |
| **Circular dependencies** | Low | High | Tarjan SCC verified with cyclic test graphs |

---

## Deployment Checklist

Before production deployment:

- [ ] All unit tests passing (coverage ≥ 80%)
- [ ] All golden tests T01–T25 passing
- [ ] E2E smoke test passing for all 4 warehouses
- [ ] Production write-lock verified in staging
- [ ] Watermark snapshot pinning verified
- [ ] Compensating rollback tested
- [ ] Security validation (RLS) tested with 3 identities
- [ ] Load testing: 100M row extraction + Hyper build
- [ ] Documentation complete + examples
- [ ] API documentation auto-generated (FastAPI Swagger)
- [ ] Database schema migrations tested
- [ ] Crash recovery tested (kill -9, verify resumption)

---

## Timeline Visualization

```
Week:    1     2     3     4     5     6     7     8     9    10    11    12    13    14    15    16
         ┌─────────────────────────────────────────────────────┐
Phase 1: │ Setup│MSTRSess│Discovery│Graph│SQL─Compile→ PHASE 1 DONE ✓
         └─────────────────────────────────────────────────────┘
                                          ┌──────────────────────────────────────┐
         Phase 2:                         │ ExprCompile│Fingerprint│Hyper→ PHASE 2 DONE ✓
                                          └──────────────────────────────────────┘
                                                                   ┌───────────────────────────┐
         Phase 3:                                                 │ XML│Validation│Lock│Review → DONE ✓
                                                                   └───────────────────────────┘
         
         Testing (Continuous):  Unit (all phases) │ Integration (Phase 2+) │ E2E Smoke (Phase 3)
         Documentation (End):   Architecture      │ Implementation         │ API Docs
```

---

## Handoff & Maintenance

### Documentation

- [x] Technical specification (32 ADRs)
- [x] Implementation guide (4 parts)
- [x] Gap analysis with remediation
- [x] SQL templates + warehouse patterns
- [x] API documentation (auto-generated from FastAPI)
- [x] Database schema documentation
- [x] Testing strategy + golden scenarios

### Operational

- [x] Monitoring dashboard (job status, validation metrics)
- [x] Error logging + audit trail
- [x] Crash recovery procedures
- [x] Production lock admin override capability
- [x] Rollback procedures

### Future Enhancements (Post-MVP)

- [ ] Multi-region Tableau Server replication
- [ ] Incremental migration (only changed objects)
- [ ] Prompt migration (MSTR → Tableau)
- [ ] Full BI-IR generalization (MSTR-first → multi-vendor)
- [ ] Advanced visualization mapping (complex viz types)

---

**Ready to begin implementation? Start with Phase 1, Week 1: Project Setup.**

Next step: Create project repository + CI/CD pipeline.

