# Technical Audit v4 — mstr-tableau-migrator (State Machine Rollback, Watermark Contract, Entitlement Security, Impersonation Validation)

**Auditor role:** Principal BI Migration Architect & Reverse Engineering Auditor  
**Scope:** Full fourth-pass audit treating v1–v3 remediations as baseline.  
**Date:** 17 August 2026

---

## Executive Verdict

The specification has successfully hardened extraction grain, caption registry, and basic staging concepts. However, four critical production-breaking flaws survived:
1. **State Machine Violates Rollback Invariant:** Publishing the shared datasource to production prior to workbook validation overwrites live datasources before numeric checks even run.
2. **Golden-Set Live Data Drift:** Golden capture ($T_0$) and warehouse extraction ($T_1$) are uncoordinated, guaranteeing false numeric gate failures on live data warehouses.
3. **Per-Wave Deduplication & Double Compilation:** Running deduplication per-wave prevents cross-wave metric sharing and repeatedly overwrites published field bindings.
4. **Entitlement Substring Collision & Mutable Identity:** `CONTAINS` substring matching grants illegal access (e.g. `"East"` matches `"Northeast"`), and `FULLNAME()` keys security to non-unique, mutable display names.
5. **Unmeasurable Security Validation & Exposure:** `SECURITY_VALIDATE` lacked a concrete runtime verification mechanism, and placing entitlements in the shared datasource creates an information-disclosure risk.

---

## 1. Critical Flaws & Resolutions

### Flaw 1 — Production Datasource Publish Timing (ADR-029 Rollback Contradiction)
- **Flaw:** Emitting and publishing the production datasource before `NUMERIC_VALIDATE` meant that if a wave failed validation, the production datasource had already overwritten the existing live version, breaking pre-existing dashboards.
- **Resolution:** Production is strictly write-locked during all extraction, compilation, staging, and validation stages. `DATASOURCE_PUBLISH_PRODUCTION` is moved strictly inside the `PROMOTE` step, executed atomically only after `auto_publish_ok == True`.

### Flaw 2 — Golden-Set Time Paradox / Live Data Drift
- **Flaw:** MSTR API golden data ($T_0$) vs. live warehouse extraction ($T_1$) diverge due to standard ETL and transaction inserts, triggering false-positive numeric gate failures.
- **Resolution:** Added **ADR-030 (Validation Snapshot Watermark Contract)** pinning extraction queries and golden MSTR executions to a shared high-water mark timestamp (`load_ts <= :watermark`). Divergences due to timestamp boundaries are triaged as `data_drift`.

### Flaw 3 — Two-Phase Orchestration
- **Flaw:** Deduplication and datasource publishing inside per-wave loops broke cross-wave metric visibility and re-published shared datasources repeatedly.
- **Resolution:** Pipeline structured into **Phase 1 (Wave-by-Wave Extraction & Compilation)** and **Phase 2 (Global Deduplication, Datasource Emission, Staging Publish, Multi-Gate Validation, and Atomic Promotion)**. Removed duplicate `IR_COMPILE` calls.

### Flaw 4 — Entitlement Substring Safety & Identity Keying
- **Flaw:** `CONTAINS([ALLOWED_VALUES], [Region])` allows substring collisions where a user entitled to `"Northeast"` matches `"East"`. `FULLNAME()` keys security to non-unique display names.
- **Resolution:** Added **ADR-031** wrapping delimiters on both sides: `CONTAINS("|" + [ALLOWED_VALUES] + "|", "|" + [Region] + "|")`, added **Validation Rule 16**, and keyed security to immutable `USERNAME()` logins with an approved identity mapping table.

### Flaw 5 — Impersonation-Based Security Validation & Isolation
- **Flaw:** Security validation was purely static and could not verify vizql engine evaluation; entitlement tables in shared datasources exposed user permission mappings.
- **Resolution:** `ValidationAgent` executes `Export Crosstab` impersonation tests across 3 distinct test identities (`Regional Manager East`, `Regional Manager West`, `Global Admin`). Entitlement tables are isolated in a permission-locked datasource.

---

## 2. Semantic Traps & XML Gotchas

- **Trap A (`Count(Attribute)`):** Compiles to `COUNTD([ID_FORM])` under raw-grain extraction based on operand type.
- **Trap B (Derived Elements):** Detected on report templates and flagged with `Issue(blocker, derived_elements_present)`.
- **Trap C (Prompt in Condition):** Flagged with `Issue(blocker, prompt_in_condition)`.
- **Trap D (Multi-Dataset Blend):** Supported via `blendSpec` in `WorksheetSpec` or flagged with `Issue(blocker, dossier_multi_dataset_blend)`.
- **Trap E (Semi-Additive Measures):** Validated via `semi_additive_rollup` check comparing rolled time grains against MSTR.
- **Gotcha 1 (Template Version Ceiling):** Enforced via `template_version <= server_version` at job creation (**Validation Rule 17**).
- **Gotcha 2 (Large Extract Upload):** Mandates `TSC.FileUpload` chunked upload for extracts > 64MB.
- **Gotcha 3 (Failed Sheet Hiding):** Implemented via unreferenced dashboard zones and `<window>` omission.
- **Gotcha 4 (Context-Filter Scope):** Specified at datasource/dashboard scope with `<filter class='categorical' context='true'>`.
- **Gotcha 5 (Identifier Escaping):** Unified identifier normalization between Hyper DDL and TDS XML.

---

*End of fourth-pass audit.*
