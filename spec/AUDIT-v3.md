# Technical Audit v3 — mstr-tableau-migrator (Warehouse Planner, Semantic Fingerprint, Publish/Recovery)

**Auditor role:** Principal BI Migration Architect & Reverse Engineering Auditor  
**Scope:** Full third-pass audit reviewing revision of `architecture.md`, `agents.md`, `api.md`, `database.md`, and `expression-compiler.md`  
**Verdict:** Implementation blocked pending resolution of 5 critical architectural gaps.  
**Date:** 17 August 2026

---

## Executive Verdict

The revision is materially better. The previous extraction grain flaw was resolved by recognizing the warehouse-direct vs. MSTR API split. However, implementation remains blocked by 5 critical bottlenecks:
1. **Missing Semantic SQL Planner:** Warehouse-direct extraction requires transforming MSTR semantic model (logical tables, attribute forms, fact expressions, VLDB settings, relationship paths) into warehouse SQL ASTs.
2. **Unsafe Metric Deduplication:** Deduplicating measures by normalized `compiledTableau` string is invalid; identity must be a multi-dimensional `SemanticFingerprint`.
3. **Staging Datasource Topology Ambiguity:** Staging workbooks referencing staging datasources requires explicit dual-datasource publication (Option A).
4. **Validation Order Inversion:** Deterministic static validation (XML/XSD checks) must precede server staging publish.
5. **State Machine / Database / Agent Contract Inconsistencies:** State enums, ORM models, and API contracts must be fully synchronized.

---

## 1. What Was Genuinely Fixed in v2
- Extraction grain contract (`ExtractionGrain` with `physicalGrain`, `semanticGrain`, `keys`, `aggregationState`, `snapshotIdentity`).
- Canonical staging -> render validation -> production promotion workflow.
- Category-weighted confidence model (`security=1.0`, `financial=0.98`, `structural=0.99`, `visual=0.80`).

---

## 2. Critical Flaws & Resolutions

### Critical #1: Missing Warehouse Semantic SQL Compiler
- **Flaw:** The spec defined metadata sources but not the engine that reconstructs MSTR attribute forms (ID, DESC, expressions), fact expressions (e.g. `CASE WHEN status='POSTED' THEN net_amount END`), VLDB join types, and filters into warehouse SQL.
- **Resolution:** Added **Agent 3.5: PhysicalModelPlanner** and **ADR-026**, generating `PhysicalModelPlan` with SQL ASTs for warehouse extraction.

### Critical #2: String-Based Metric Deduplication
- **Flaw:** Merging metrics based on `expression.compiledTableau` string normalization collapses distinct semantic metrics into one.
- **Resolution:** Added **ADR-027** introducing `SemanticFingerprint` incorporating source dependencies, datasource domain, physical/semantic grain, aggregation, filtering mode, condition phase, transformation, null policy, and security scope.

### Critical #3: Staging Datasource Topology
- **Flaw:** Staging workbooks referencing `_migration_staging/Datasources/...` require that the datasource exists in staging.
- **Resolution:** Explicitly locked **Option A (Dual Datasource Publication)** via `datasource_path_rewrites` with `staging_ds_id` and `production_ds_id`.

### Critical #4: Validation Order Inversion
- **Flaw:** Server staging publish ran before static XML/XSD validation.
- **Resolution:** Pipeline reordered so `STATIC_VALIDATE` strictly precedes `STAGING_PUBLISH`.

### Critical #5: State Machine & Contract Divergence
- **Flaw:** Divergence between `architecture.md` state machine, `agents.md` pseudocode, `database.md` status enums, and ORM models.
- **Resolution:** Synchronized all enums and ORM models, added `artifacts`, `publish_operations`, `reconciliation_events`, `physical_model_plans`, and `semantic_fingerprints` tables.

---

## 3. Semantic Engine & Compiler Hardening
- **EvaluationPlan IR:** Added `EvaluationPlan` intermediate representation between MSTR AST and target formula.
- **EXCLUDE LOD Safety:** Changed `EXCLUDE` LOD to a structural blocker requiring `requires_view_dependency_analysis` with mandatory human review.
- **Context-Aware Division:** Operand null semantics analyzed across the expression tree rather than naive universal wrapping.
- **Datasource Topology Planning:** Moved datasource mode decision (`embedded` vs `published`) prior to emission planning (**ADR-028**).
- **Publish Idempotency & Rollback:** Added operation tracking, idempotency keys, and rollback contracts (**ADR-029**).

---

*End of third-pass audit.*
