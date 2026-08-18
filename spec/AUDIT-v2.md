# Technical Audit v2 — mstr-tableau-migrator (Post-AUDIT.md Synthesis)

**Auditor role:** Principal BI Migration Architect & Reverse Engineering Auditor  
**Scope:** Full second-pass audit after reading all spec files + existing `AUDIT.md`  
**Posture:** adversarial. Findings are net-new relative to `AUDIT.md`.  
**Date:** 17 August 2026

---

## Executive Verdict

The specification is not implementation-ready. The previous AUDIT.md correctly identified several defects, but the current spec has a deeper architectural contradiction: it simultaneously tries to preserve MSTR's server-evaluated semantics by extracting what the MSTR cube/report returns, while building a reusable Tableau semantic model that must support different visualization grains, filters, LODs, transformations, and workbook-local calculations. Those two goals are incompatible unless the extraction grain is explicitly modeled.

---

## Part 1: Top 5 Critical Flaws the AUDIT.md Missed

### Flaw A: Caption Registry Is a Silent Data-Corruption Vector

The audit-revised `TableauEmitterAgent` introduces a caption registry (`{ir_field_id → disambiguated_caption}`) built once before all worksheets are emitted. Three problems:

1. **`remote-name` vs. caption mismatch.** The shared datasource is published *before* TWBs. When the registry disambiguates `Revenue` to `Revenue (2)` in workbook B, the `remote-name` must still be the canonical server name (`Revenue`). If the emitter uses the disambiguated caption as both `local-name` and `remote-name`, Tableau Server returns "field does not exist" for every disambiguated field.

2. **Registry is per-workbook, not per-pipeline.** Two dossiers emitted in the same wave can independently assign `Revenue (2)` to different metrics against the same shared datasource.

3. **`(2)` suffix is Tableau-hostile.** Tableau uses parenthetical suffixes for auto-generated aggregation labels (`Revenue (sum)`). A manually emitted `Revenue (2)` caption creates confusion.

**Fix:** Registry must be global per published datasource, not per workbook. Initialize during `HyperAgent` schema building, locked before any TWB emission. Separate `local-name`/`remote-name` (canonical published name) from `caption` (display disambiguation).

### Flaw B: GraphAgent Wave Structure Makes Shared Datasource Impossible to Stage-Validate

Staging and production are different Tableau Server projects with different datasource IDs. A workbook staged in `_migration_staging` referencing a datasource staged in `_migration_staging/datasources` must have different `<connection class='sqlproxy' dbname='...'>` XML than the same workbook published to production. **No mechanism for path rewriting exists.**

**Fix:** `PublishAgent` must maintain `staging_ds_path` and `production_ds_path`. `TableauEmitterAgent` must accept `target_environment: "staging" | "production"` and emit the appropriate datasource path. This requires a two-emit sequence per workbook.

### Flaw C: `asyncio.to_thread()` + SQLite WAL Creates New Concurrency Defect

`asyncio.to_thread()` runs in OS threads. Multiple HyperAgent threads doing checkpoint writes + event loop thread handling API writes + batched audit logger = 5-6 concurrent SQLite writers. WAL mode allows one writer. With `busy_timeout=5000`, Hyper insertion can stall 5s per checkpoint.

**Fix:** All SQLite writes from background threads must go through a single dedicated async write queue (`asyncio.Queue`). Hyper extraction threads enqueue write operations and continue immediately.

### Flaw D: `scope: "shared" | "local"` Is Unresolvable at Compile Time

A metric like `YTD Revenue` might appear in 3 dossiers. In 2 it's identical, in the third there's a variant. The wave-by-wave compilation model processes dossiers independently and cannot determine scope without a cross-object deduplication pass.

**Fix:** Add `MetricDeduplication` step after all waves are extracted but before any TWB emission. Group metrics by normalized `expression.compiledTableau`; identical metrics in 2+ objects get `scope: "shared"`.

### Flaw E: MSTR JSON Data API Returns Pre-Aggregated Data — Hyper Schema Is Wrong

The MSTR JSON Data API returns metric-evaluated, pre-aggregated data. Column headers are metric names, not physical columns. There are no FK columns for star schema joins. LOD calcs against pre-aggregated data produce double-counts when users change the view grain.

**Fix:** Split extraction into two paths: (a) **Hyper path** — connect to warehouse using MSTR schema metadata to build proper star-schema extract; (b) **MSTR API path** — use JSON Data API only for golden test datasets.

---

## Part 2: Semantic Engine — Remaining Traps

### Trap 6: `{EXCLUDE}` LOD + Computed Date Dimensions
`{EXCLUDE [Year]}` where `[Year]` is `DATETRUNC('year', [Order Date])` — Tableau cannot reference computed dimensions in EXCLUDE. Silently computes at wrong grain.

### Trap 7: Metric Subtotals Math Mismatch
MSTR subtotals re-evaluate metric conditions at subtotal grain via SQL rollup. Tableau Grand Totals re-aggregate underlying data. For conditional/LOD metrics, subtotal values will differ silently.

### Trap 8: `ApplySimple()` Cross-Database Reference
`RAWSQL_*()` translation fails at runtime if live TDS connects to a different database than the MSTR cube's underlying warehouse. Not detectable by syntax analysis.

### Trap 9: VLDB `NULL_PROPAGATION` Not Consumed by Compiler
Extracted to `vldb_settings_json` but never used during compilation. If project has `NULL_PROPAGATION = ignore`, MSTR treats NULL as 0 in arithmetic. Tableau propagates NULL. All division/arithmetic calcs produce wrong results.

---

## Part 3: Tableau Generation & XML Gotchas

### Gotcha 5: `<column>` Ordering in Datasource XML
Calculated fields referencing other calculated fields must appear after their dependencies in the `<datasource>` block. Tableau Server's parser is stricter than Desktop.

### Gotcha 6: Hyper Multi-Table Logical Relationship XML Structure
`<datasource>` for logical-table Hyper requires `hasconnection='false'` at datasource level and Hyper connection nested inside `<connection class='federated'>`. Missing this causes Server publish failures.

### Gotcha 7: TWBX 64MB Chunk Size Limit
Tableau Server REST API has version-dependent chunk size limits. TWBX > 64MB fails on older servers with generic 500 error. Split Hyper to standalone published datasource for large files.

---

## Part 4: Edge Cases Matrix (Net-New)

| Edge Case | Severity | Fix |
|---|---|---|
| Pre-aggregated MSTR API data used as Hyper rows | **Critical** | Warehouse-direct extraction; MSTR API for golden tests only |
| Caption registry per-workbook collision | **Critical** | Global registry per datasource |
| Staging/production datasource path mismatch | **Critical** | Two-emit sequence with path rewriting |
| SQLite write contention from multiple threads | **High** | Dedicated async write queue |
| `EXCLUDE` LOD on computed date dimension | **High** | Detect computed dims; flag as warning |
| VLDB NULL_PROPAGATION = ignore | **High** | Wrap arithmetic operands in `ZN()` |
| Metric subtotal math divergence | **High** | `subtotalWarning` flag on Worksheet |
| TWBX > 64MB publish failure | **Medium** | Size gate; split Hyper to standalone DS |
| `<column>` ordering in datasource XML | **High** | Topo-sort by dependency |
| ApplySimple cross-database RAWSQL | **Medium** | Parse SQL for cross-schema refs |
| FULLNAME() vs USERNAME() for SAML auth | **Medium** | Detect Tableau auth type |
| Metric scope unresolvable per-wave | **Critical** | Cross-wave MetricDeduplication pass |

---

## Part 5: Concrete Spec Errata

### `architecture.md`
- ADR-019 extension: SQLite writes from background threads through dedicated async write queue
- ADR-022: Extraction Grain Contract — warehouse-direct for Hyper, MSTR API for golden tests
- ADR-023: Staging/Production Path Rewriting — two-emit per workbook, target_environment flag
- ADR-012 must be a buildtime config option with two code paths, not a deferred decision

### `agents.md`
- IRCompilerAgent: Add MetricDeduplication step (cross-wave, before emission)
- TableauEmitterAgent: Topo-sort `<column>` elements by dependency; datasource XML fixture library
- PublishAgent: TWBX size gate (>50MB → split Hyper to standalone published DS)
- HyperAgent: Two extraction paths (warehouse-direct vs MSTR API)

### `expression-compiler.md`
- §3.4: EXCLUDE + computed date dimension → confidence 0.30, Issue(warning)
- §3.7: VLDB null_propagation consumed by CompilationContext; wrap operands in ZN() if "ignore"
- §3.2: Division guard — `ZN(SUM([A])) / NULLIF(SUM([B]), 0)`

### `ir-schema.md`
- Datasource: add `stagingFieldNameMapping`
- Measure: add `nullPropagation: "propagate" | "ignore" | null`
- Worksheet: add `subtotals: bool`, `subtotalWarning: bool`
- Validation Rule 12: subtotal math divergence warning

### `database.md`
- `caption_registry`: add `datasource_id TEXT` FK + unique constraint on `(job_id, datasource_id, caption)`
- New table: `datasource_path_rewrites`
- `jobs`: add `null_propagation TEXT` separate from vldb_settings_json

### `testing.md`
- Multi-workbook shared datasource collision tests
- Staging/production path rewrite tests
- Pre-aggregated data detection tests

### Three Decisions Required Before Line 1 of Code
1. **Hyper data source:** warehouse direct (for Hyper) vs. MSTR API (for golden tests only)
2. **Shared datasource scope:** buildtime config option (per-project vs per-domain)
3. **Logical relationship model:** gate on Tableau Server version ≥ 2020.2

---

*End of second-pass audit.*
