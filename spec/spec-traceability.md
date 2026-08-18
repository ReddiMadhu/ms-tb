# Specification Traceability Matrix — mstr-tableau-migrator

**Product:** MicroStrategy → Tableau Migration Platform  
**Document:** `spec-traceability.md`  
**Classification:** Normative Traceability & Coverage Matrix  
**Version:** 1.0.0  
**Date:** 17 August 2026  

---

## 1. Traceability Architecture

This matrix guarantees that every architectural requirement, invariant, and ADR has an explicit implementing Agent, a corresponding BI-IR entity, a defined API endpoint, and a dedicated adversarial test fixture.

---

## 2. Requirement to Artifact Traceability Matrix

| Requirement / Invariant | Architecture ADR | Implementing Agent | BI-IR Entity | API Endpoint | Adversarial Test Suite |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **MSTR Session & Capability Probe** | ADR-016, ADR-032 | `DiscoveryAgent` | `Root.source` | `POST /connections/mstr/test` | `T04_expired_mstr_token.py` |
| **Compound Attribute Keys** | ADR-026 | `DiscoveryAgent`, `PhysicalModelPlanner` | `Table.columns`, `Relationship.compoundKeys` | `POST /discovery/dossiers` | `T01_composite_attribute_key.py`, `T02_duplicate_attribute_ids.py` |
| **Inaccessible Dependency Blocking** | ADR-007 | `DiscoveryAgent`, `GraphAgent` | `CatalogObject.accessibility` | `GET /jobs/{id}` | `T03_inaccessible_cube_dependency.py` |
| **Cyclic Dependency SCC Collapse** | ADR-003 | `GraphAgent` | `Lineage.nodes`, `Lineage.edges` | `GET /jobs/{id}/waves` | `T09_cyclic_metric_filter.py` |
| **Transitive Failure Propagation** | ADR-007 | `GraphAgent`, `Orchestrator` | `Issue.blocking`, `Issue.severity` | `GET /jobs/{id}/blast-radius/{id}` | `T10_failed_base_metric_cascade.py` |
| **Warehouse-Direct Raw Extraction** | ADR-022 | `PhysicalModelPlanner`, `HyperAgent` | `Table.extractionGrain` | `POST /jobs` | `T13_insufficient_lod_grain.py` |
| **Heterogeneous Fact Grain Isolation** | ADR-032 | `PhysicalModelPlanner` | `Table.cardinalityContract` | `POST /jobs` | `T11_heterogeneous_daily_monthly_facts.py` |
| **Reconstructable Snapshot Watermark** | ADR-030 | `PhysicalModelPlanner`, `ValidationAgent` | `Table.snapshotIdentity` | `POST /jobs` | `T20_mutable_warehouse_watermark.py` |
| **Transformation Shifted-Key Joins** | ADR-026 | `PhysicalModelPlanner`, `HyperAgent` | `Measure.transformation` | — | `T12_transformation_table_prior_year.py` |
| **Level Metric Dimensionality (Dimty)** | ADR-005 | `IRCompilerAgent`, `ExpressionCompiler` | `Measure.dimty`, `Measure.evaluationPlan` | `POST /review/{id}/edit-ir` | `T14_fixed_dim_filter_conflict.py` |
| **Attribute Counting Parity (COUNTD)** | ADR-005 | `ExpressionCompiler` | `Measure.expression.ast` | — | `T15_count_attribute_vs_countd.py` |
| **VLDB Null Propagation (ZN)** | ADR-005 | `ExpressionCompiler` | `Measure.nullPolicy`, `CompilationContext` | — | `T08_vldb_null_propagation.py`, `T16_null_arithmetic.py` |
| **Semantic Metric Fingerprinting** | ADR-027 | `IRCompilerAgent` | `Measure.semanticFingerprint` | — | `T17_identical_formula_diff_fingerprint.py` |
| **Caption Disambiguation Registry** | ADR-027 | `TableauEmitterAgent` | `CaptionRegistryEntry` | — | `T18_same_caption_diff_fingerprint.py` |
| **Streaming Hyper Chunking & Atomic Swap** | ADR-019 | `HyperAgent` | `Table.connectionMode` | — | `T21_hyper_partial_write_crash.py` |
| **TWB Logical Relationship Injection** | ADR-004, ADR-021 | `TableauEmitterAgent` | `Relationship.joinModel` | — | `T22_tableau_xsd_vs_server_render.py` |
| **Staging/Production Path Rewriting** | ADR-023 | `TableauEmitterAgent`, `PublishAgent` | `Datasource.targetPath` | `GET /jobs/{id}/publish-operations` | `T24_production_publish_partial_failure.py` |
| **Impersonation Security Normalization** | ADR-031 | `ValidationAgent` | `SecurityPolicy` | `GET /jobs/{id}/validation` | `T19_east_vs_northeast_security_attack.py` |
| **Canonical Validation Scorecard** | ADR-018 | `ValidationAgent` | `ValidationScorecard` | `GET /jobs/{id}/validation` | `T22_tableau_xsd_vs_server_render.py` |
| **Idempotent Promotion & Compensating Rollback** | ADR-029 | `PublishAgent`, `Orchestrator` | `PublishOperation` | `GET /jobs/{id}/publish-operations` | `T23_publish_network_timeout.py`, `T24_production_publish_partial_failure.py` |
| **Human Review AST Editing** | ADR-006 | `ReviewQueueAgent` | `Issue`, `Measure` | `POST /review/{id}/edit-ir`, `POST /review/{id}/approve` | `T25_human_ir_edit_revalidation.py` |
