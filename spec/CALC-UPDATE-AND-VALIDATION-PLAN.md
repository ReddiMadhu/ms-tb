# Implementation Plan — Calculated-Field Update Flow & Formula Validation Proof

**Project:** mstr-tableau-migrator
**Companion to:** `expression-compiler.md`, `validation-contract.md`, `api.md §4`, `AGENTS.md` (ADR-029/030/031/033/034)
**Status:** Proposed — pending approval
**Date:** 2026

---

## 1. Goals

| # | Goal | Success looks like |
|---|------|--------------------|
| G1 | **Prove formula correctness** — close the "UNVERIFIED" gap in the Financial KPI / Security gates | Every emitted calc carries machine evidence: golden-test result and/or server read-back parity ≤ 0.1%. Gates compute real confidence when evidence exists; stay fail-closed when it does not |
| G2 | **Allow calculated-field updates end-to-end** — human edits a calc in review → validated → regenerated TWB/TWBX → republished/promoted | A review edit reaches the regenerated `.twb` `<calculation formula>` without a full pipeline restart, with blast-radius re-validation (ADR-033) |

### Non-goals
- In-place `.twb` XML patching (regeneration is the chosen strategy — see D2).
- Editing MSTR-side expressions (source of truth stays MSTR metadata).
- Auto-approving security predicates without human sign-off (AI policy invariant).

---

## 2. Current State Map (verified against code)

| Capability | File | State |
|---|---|---|
| Edit capture | `backend/src/app/api/v1/review.py` `PUT /review/{task_id}` | Stores `edited_calc` on task. **Re-validation is a TODO (line 91–95)** |
| Edit write-back | `backend/src/app/agents/review_queue.py` `apply_patch()` | Updates `MigrationObject.tableau_calc` + confidence boost (ADR-034). **Never touches `ir.json`** |
| Approve→promote | `review.py` `POST /review/{task_id}/approve` | Sets status + confidence only. **Promotion TODO (line 155–159)** |
| Blast radius | `review.py` GET endpoint | Returns stored count; `affected_worksheets` hardcoded `[]` (line 118) |
| Workbook emission | `orchestrator.py` `_run_wb_emit_staging` (L1459) / `_run_wb_emit_prod` | **Loads IR from `artifacts/{job}/ir.json`, NOT from DB** ← critical integration gap |
| Stage resume | `orchestrator.py` `_run_stage` (L274) | Skips stages `<= job.checkpoint_stage`; no public "resume from stage X" entrypoint |
| KPI gate | `agents/validation_agent.py` `_validate_kpi` | HONESTY GUARD: all measures marked UNVERIFIED → fail-closed |
| Security gate | same, `_validate_security` | Fail-closed UNVERIFIED when security filters exist |
| Syntax validation | `agents/ai_translation.py` L472–477 | `sqlglot.parse()` advisory-only (try/except, debug log); does not understand LOD `{...}` |
| Emission guards | `agents/tableau_emitter.py` L686–780 | Placeholder skip (`//` formulas), illegal-aggregation-nesting fail-closed gate |
| Tests | — | **No project test suite exists** (only `venv` site-packages) |

---

## 3. Target Architecture

```
                    ┌──────────────────────────────────────────────────────┐
                    │  EDIT LOOP                                           │
   Human reviewer   │                                                      │
        │           │                                                      │
        ▼           │                                                      │
PUT /review/{id} ───┤  1. CalcValidator.validate()          [NEW A1]       │
        │           │        │ pass                                         │
        │           │        ▼                                              │
        │           │  2. IrEditService.apply_edit()        [NEW B2]       │
        │           │       ├─ DB: MigrationObject.tableau_calc             │
        │           │       ├─ artifact: ir.json measure.tableau_calc       │
        │           │       ├─ audit row: ir_edits                          │
        │           │       └─ new-column scan → needs_hyper_rebuild?       │
        │           │        ▼                                              │
        │           │  3. RevalidationCascade.run()         [NEW B4]       │
        │           │       ├─ fingerprint recompute                        │
        │           │       ├─ dependents re-checked (blast radius)         │
        │           │       └─ numeric evidence for edited calc → STALE     │
        ▼           │        ▼                                              │
POST /jobs/{id}/    │  4. resume_pipeline(from_stage)       [NEW B5]       │
reemit              │       ├─ WORKBOOK_EMIT_STAGING (or HYPER_BUILD first) │
                    │       ├─ STAGING_PUBLISH                              │
                    │       └─ STATIC_VALIDATE (+ read-back if wired)       │
                    │        ▼                                              │
POST /review/{id}/  │  5. approve → prod re-emit → PROMOTE  [B6, ADR-029]  │
approve             └──────────────────────────────────────────────────────┘

                    ┌──────────────────────────────────────────────────────┐
                    │  VALIDATION PROOF LOOP                               │
   SEMANTIC stage ──┤  mstr_golden.json (pinned watermark values)   [A4]   │
                    │        ▼                                             │
   Golden harness ──┤  calc → SQL subset → execute in Hyper vs fixtures[A3]│
                    │        ▼                                             │
   Server readback ─┤  Export Crosstab on staging → diff vs MSTR     [A4]  │
                    │        ▼                                             │
   NUMERIC_VALIDATE ┤  Gate consumes evidence; else UNVERIFIED      [A5]  │
                    └──────────────────────────────────────────────────────┘
```

---

## 4. Design Decisions

### D1 — DB + ir.json are written together by one service (single source of truth pair)
Emission stages load `ir.json`; review code writes the DB. Today an edit updates one and never reaches the TWB. Rather than adding overlay logic inside every consumer, one `IrEditService.apply_edit()` atomically patches both `MigrationObject.tableau_calc` and the corresponding `measure.tableau_calc` entry in `artifacts/{job}/ir.json`, and appends an `ir_edits` audit row. All stages stay dumb; consistency is enforced in exactly one place.

### D2 — Regenerate the TWB; never patch it
The TWB/TWBX is fully machine-generated from IR. After an edit, re-running `WORKBOOK_EMIT_STAGING` regenerates deterministic XML including the corrected formula. In-place XML patching would drift from IR and break on hand-edited workbooks. (If sub-second single-field turnaround is ever needed, a patcher can be added later as a cache of this flow — out of scope.)

### D3 — Edits invalidate numeric evidence
Numeric parity evidence is keyed to `(mstr_id, sha256(calc), watermark)`. Any edit resets that measure's KPI checks to UNVERIFIED until re-read-back. This preserves the honesty-guard property after the loop exists.

### D4 — Validator is shared and enforced everywhere calcs enter the system
One `CalcValidator` module used by (a) `PUT /review` (hard 400 gate), (b) AI translation output (replaces advisory sqlglot), (c) emitter pre-flight (defense-in-depth). Rules: balanced delimiters incl. `{}` LOD braces, comment-only rejection, `RAWSQL` ban, function whitelist, `[field]` resolution against known datasource names, illegal aggregation-nesting rule (moved from `tableau_emitter._find_illegal_aggregation_nesting` into the shared module and re-imported by the emitter).

### D5 — New physical column reference ⇒ HYPER_BUILD re-run
`PhysicalModelPlanner` synthesizes fact columns from formula refs at build time. If an edited calc references a token that resolves to neither an existing extract column nor another measure caption, re-emission alone would emit a broken field binding. The edit service detects this and the re-emit request upgrades `from_stage` from `WORKBOOK_EMIT_STAGING` to `HYPER_BUILD`.

### D6 — Resume = reset checkpoint, reuse everything else
`run_pipeline(job_id, from_stage=...)`: effective checkpoint becomes the stage preceding `from_stage`; existing skip logic then naturally re-runs `from_stage` onward. Hyper paths, viz plan, IR are reused from artifacts. Tableau/MSTR credentials are accepted again on the re-emit call (never persisted — matches current create-job behavior).

---

## 5. Workstream A — Formula Validation Proof

### A1. Shared `CalcValidator` module
**Files:** `backend/src/app/services/calc_validator.py` (NEW); refactor `tableau_emitter.py` to import nesting rule.

```python
@dataclass
class CalcValidationResult:
    valid: bool
    errors: list[str]
    warnings: list[str]
    referenced_fields: list[str]     # resolved names, case-insensitive match
    unresolved_fields: list[str]

def validate_tableau_calc(calc: str, context_fields: set[str],
                          allow_aggregates: bool = True) -> CalcValidationResult
```
Checks (ordered): non-empty → not comment-only (`//`) → balanced `( ) [ ] { }` with string-literal awareness → no `RAWSQL`/`SCRIPT` → function whitelist (aggregate set + scalar set + LOD keywords `FIXED/INCLUDE/EXCLUDE` followed by `:` … `}`) → bracket-token extraction → field resolution case-insensitive vs `context_fields` → aggregation-nesting gate → self-reference detection.

**Acceptance:** unit tests covering each reject class + a pass set of ≥ 15 representative calcs (incl. `{ FIXED [Year] : SUM([F]) }`, `ZN(SUM([A]) / NULLIF(SUM([B]),0))`, `CASE ... END`).

### A2. Enforce validator at ingestion points
**Files:** `ai_translation.py` (replace try/except sqlglot block L472–477 with `validate_tableau_calc`; on failure, retry prompt once with error text injected, else mark `// NEEDS_REVIEW`), `tableau_emitter.py` (pre-flight before `<calculation>` injection; failure ⇒ existing Issue path).

**Acceptance:** an LLM returning `SUM(SUM([x]))` can no longer reach emission; review-editing the same string returns HTTP 400 with error list.

### A3. Golden-test harness (Hyper numeric execution)
**Files:** `backend/src/app/services/calc_to_sql.py` (NEW — Tableau-calc → Hyper-SQL subset translator), `backend/tests/golden/fixtures/*.json` (NEW), `backend/src/app/services/golden_test_runner.py` (NEW), fixture linter.

Supported subset for translation: aggregates `SUM/AVG/MIN/MAX/COUNT/COUNTD`, arithmetic, `CASE/IF`, `ZN/IIF/NULLIF/ISNULL/IFNULL`, string/date basics (`UPPER/LOWER/TRIM/LEN/MID/FIND/YEAR/MONTH/DATEDIFF/DATEADD`). Single-level `FIXED` via GROUP-BY subquery join. Anything outside subset ⇒ `SKIP(reason)` — never a fake pass.

Runner loads fixture `{input_rows[], expected_results[]}`, creates temp `.hyper`, executes translated SQL, compares with tolerance 1e-3 relative / 1e-5 absolute-zero per `validation-contract.md §2.1`. **Fixture linter (CI):** reject fixtures whose expected values are identical across grain rows (spec F2 identity-bug rule). Wire runner into CI and into `STATIC_VALIDATE` as `check_type="golden_test"`.

**Acceptance:** ≥ 10 fixtures green; mutated-calc fault injection (drop grain, drop offset) turns fixtures red.

### A4. MSTR golden dataset + server read-back parity
**Files:** `backend/src/app/services/tableau_readback.py` (NEW), SEMANTIC-stage export hook, `NUMERIC_VALIDATE` wiring.

1. During extraction, persist `artifacts/{job}/mstr_golden.json`: per KPI `{mstr_id, filters_hash, watermark, value}` sampled from cube/report instances at pinned filter contexts (reuse existing instance harvesting in `orchestrator._run_semantic`).
2. Read-back client: TSC auth → for each validated worksheet, `Export Crosstab` (CSV) → parse measure cells → compare vs golden within tolerance 0.001 relative. *Synergy:* the emitter's default plan already emits **one text worksheet per measure**, which makes crosstab parsing trivial and stable.
3. Results persisted as `ValidationCheck(check_type="kpi_value", expected, actual, tolerance=0.001, category="financial_kpi")` with `evidence_hash = sha256(calc+watermark+filters)`.

**Acceptance:** staging-published workbook yields real parity numbers for ≥ 90% of simple-aggregate measures; missing server config ⇒ checks remain UNVERIFIED fail-closed (behavior unchanged, message cites reason code `NO_TABLEAU_CONNECTION`).

### A5. Gate consumption of evidence
**File:** `validation_agent.py` — `_validate_kpi` computes confidence from evidence rows when present for a measure's current `evidence_hash`; otherwise keeps the existing honesty guard. Same pattern later for security impersonation (out of scope here; gate untouched).

**Acceptance:** job with full evidence + zero blockers ⇒ `auto_publish_ok == True` reachable end-to-end; deleting evidence rows flips it back to blocked.

---

## 6. Workstream B — Calculated-Field Update Loop

### B1. Harden edit acceptance
**File:** `review.py` `PUT /review/{task_id}`
Flow: load task → `CalcValidator` (context fields = union of IR table columns + measure captions/local-names from `ir.json`) → on failure return `400 {errors, warnings}` keeping task `pending` → on success delegate to `IrEditService` → respond `200 {task, validation, needs_hyper_rebuild, cascade_summary}`. Add `edited_by`, `edited_at` echo. New schema fields on `ReviewEditRequest`: `edited_by: str`, optional `reason`.

### B2. `IrEditService.apply_edit()` (D1)
**Files:** `backend/src/app/services/ir_edit_service.py` (NEW)
Atomic steps: snapshot previous calc → update DB object → rewrite matching measure in `ir.json` (match by `mstr_id`; error if absent) → insert `ir_edits` audit row → new-column scan (D5) → return `EditOutcome(needs_hyper_rebuild, affected_object_ids)`.

### B3. New-column detection (D5)
Inside `IrEditService`: regex-extract `[tokens]` from edited calc; resolve against physical local-names (read from Hyper catalog if extract exists, else IR table columns) ∪ measure captions ∪ dimension names. Unknown tokens that look like columns ⇒ `needs_hyper_rebuild=True`. Record decision in audit row.

### B4. ADR-033 re-validation cascade
**Files:** extend `ir_edit_service.py` or new `backend/src/app/services/revalidation_cascade.py`
- Dependents: reverse index over `MigrationObject.dependency_ids` (+ `SemanticFingerprint.source_dependencies`), transitive closure; seed from `ReviewTask.blast_radius`.
- For each dependent: syntax-recheck its calc (name references unchanged ⇒ textual impact normally none; still rechecked), mark dependent numeric evidence stale too (calc-hash chaining), recompute its structural checks.
- Recompute scorecard subset → update `Job` confidences → persist refreshed `validation_scorecard.json`.
- Implement real `GET /review/{task_id}/blast-radius` body per `api.md §4.5` (resolve worksheets via `viz_plan.json` field references) replacing the `TODO []` stub.

**Acceptance:** editing a shared (`scope="shared"`) measure marks ≥ its dependents stale and reports them in the API response.

### B5. Resume-from-stage + `POST /jobs/{job_id}/reemit`
**Files:** `orchestrator.py` (add `from_stage` param to `run_pipeline`; effective-checkpoint logic per D6), `jobs.py` (new endpoint, BackgroundTasks launch like create-job).

Request body: `{reason, from_stage?: "HYPER_BUILD"|"WORKBOOK_EMIT_STAGING" (default auto), mstr_username?, mstr_password?, tableau_token_name?, tableau_token_value?}`.
Behavior: reject if job currently RUNNING (409) → set status `REEMIT_PENDING` → run stages from `from_stage` through `STATIC_VALIDATE` (+ `STAGING_PUBLISH` when credentials provided). Guard rails: refuse `from_stage=WORKBOOK_EMIT_STAGING…` downgrade when `needs_hyper_rebuild` is outstanding (422). Emit progress via existing job-status polling.

### B6. Approve → production re-emit → promote
**File:** `review.py` `POST /review/{task_id}/approve`
Replace TODO block: acquire production write-lock (ADR-029 idempotency key on `publish_operations`), verify no pending blocker tasks for the job, then background-launch production tail: `_run_wb_emit_prod` → `_run_promote` → `_run_reconcile` (existing handlers, reused verbatim). Response includes `promotion_operation_id`; job status surfaces through normal polling. Concurrent approves serialize on the write-lock; second caller gets 409.

### B7. Frontend review UI
**Files:** `frontend/src/**` (review drawer/page)
Tasks: (1) editor textarea posts to hardened `PUT` and renders inline `errors[]` on 400; (2) show `needs_hyper_rebuild` banner ("edit requires extract rebuild"); (3) blast-radius panel listing affected metrics/worksheets before confirm; (4) Re-emit button → `POST /jobs/{id}/reemit` + progress poll; (5) Approve confirm dialog wired to new promote behavior. Keep components within existing design system; no new dependencies.

---

## 7. Data Model Changes (SQLite, lightweight migration)

| Change | Type | Notes |
|---|---|---|
| `ir_edits` table | NEW | `id, job_id, task_id, object_id, previous_calc, new_calc, edited_by, edited_at, validation_json, needs_hyper_rebuild, applied_ir_json` |
| `review_tasks.edited_by`, `edited_at` | ADD columns | Pair with existing `edited_calc` |
| `validation_checks.evidence_hash` | ADD column | Stale-evidence detection (D3) |
| `jobs.last_reemit_stage`, `last_reemit_at` | ADD columns | Observability of the loop |
| Existing tables reused as-is | — | `ReviewTask.blast_radius`, `SemanticFingerprint`, `PublishOperation.idempotency_key` |

Migration: startup `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE … ADD COLUMN` guarded by pragma introspection (matches current session bootstrap style in `db/session.py`).

## 8. API Contract Changes

| Endpoint | Change |
|---|---|
| `PUT /review/{task_id}` | 200 now returns `{task, validation, needs_hyper_rebuild, cascade:{affected_object_ids}}`; 400 on invalid calc |
| `GET /review/{task_id}/blast-radius` | Real payload per `api.md §4.5` (worksheets resolved) |
| `POST /review/{task_id}/approve` | Triggers background promote; returns `promotion_operation_id`; 409 on lock contention |
| `POST /jobs/{job_id}/reemit` | NEW — resume pipeline from stage (body per B5) |
| `GET /jobs/{id}/validation` | Unchanged shape; numbers now reflect evidence when present |

## 9. Test Plan (new `backend/tests/`)

1. **Unit:** CalcValidator (reject/pass matrices), calc_to_sql translator, IrEditService atomicity (inject mid-failure), new-column detector.
2. **Integration (stubbed servers):** PUT→edit→ir.json diff assertion; reemit resumes correct stage set (assert stage ledger); cascade staleness propagation; approve→promote happy path + 409 contention.
3. **Golden:** fixture suite + linter + fault-injection mutants.
4. **Regression:** emitter snapshot test before/after refactor of nesting-rule move (bytes-identical TWB for unchanged input).
5. **E2E smoke (optional env-gated):** real staging publish + Export Crosstab read-back on a 3-measure sample dossier.

## 10. Rollout Phases & Estimates

| Phase | Scope | Est. |
|---|---|---|
| P1 Foundation | A1 validator + A2 enforcement, `ir_edits` migration, B1 hardening, B2/B3 edit service | 2 d |
| P2 Update loop | B5 resume-from-stage + reemit endpoint, B4 cascade + blast radius, B6 approve→promote | 2–3 d |
| P3 Validation proof | A3 golden harness + fixtures + linter, A4 golden dataset + read-back, A5 gate wiring | 3–5 d |
| P4 UI + e2e | B7 frontend, integration/e2e suites, spec-traceability update | 1–2 d |
| **Total** | | **8–12 working days** |

P1+P2 deliver the user-visible update capability independently; P3 is additive and can ship after.

## 11. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Export Crosstab layout instability | Emitter-controlled one-measure-per-text-sheet default keeps crosstabs canonical; fallback: parse per-worksheet CSV with header pinning |
| calc_to_sql semantic divergence (NULL/COUNTD edge cases) | Golden harness is advisory; server read-back remains authoritative; mismatches logged, never force-passed |
| ir.json/DB divergence pre-existing from earlier runs | One-time reconciliation script diffs both sources on first edit; mismatch blocks edit with explicit report |
| Long HYPER_BUILD re-runs after column-adding edits | Checkpointed extraction already exists (`extraction_checkpoints`); reemit reuses completed pages |
| Concurrent review edits to interdependent measures | Per-job edit mutex (row-lock on job); second edit waits/rejects with 409 |
| Credentials handling on reemit | Tokens accepted per-request only, never persisted (mirrors create-job contract) |

## 12. Definition of Done

- [ ] Invalid calc rejected at PUT with actionable errors; valid edit reflected in regenerated `.twbx` formula bytes (integration assertion)
- [ ] Column-adding edit forces HYPER_BUILD re-run automatically; others do not rebuild extracts
- [ ] Cascade marks dependents stale and blast-radius endpoint returns real worksheets
- [ ] Approve produces a promoted production workbook with recorded `publish_operations` + reconciliation event
- [ ] KPI gate shows real parity numbers when evidence exists; UNVERIFIED fail-closed otherwise; edit resets evidence (staleness proven by test)
- [ ] Golden fixture suite + linter green in CI; ≥ 1 fault-injection mutant detected
- [ ] No project spec violated: AI-policy invariants, ADR-029 write-lock, ADR-033/034 models intact
