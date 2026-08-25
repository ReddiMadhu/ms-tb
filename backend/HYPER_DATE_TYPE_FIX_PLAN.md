# Implementation Plan — Fix 6EA18A9E (TEXT-typed date column vs Month derivation)

**Status:** IMPLEMENTED AND VERIFIED
**Job evidence:** `4ac44663-9622-4a40-a901-d81501ba18a2` / artifact `633b7633…` (`Testghj_prod.twbx`)
**Companion RCA:** `artifacts/bce574a1-ed35-4bd8-8bc2-cbe8dd99ba4f/root_cause_analysis.md`

---

## 1. Verification results

| # | Claim | Checked | Result |
|---|---|---|---|
| V1 | `_dim_sql_type` defaults `date`→`SqlType.text()` | `orchestrator.py:1212-1218` | ✅ Confirmed. Only int/double mapped; everything else falls through to `text()`. The comment directly above (lines 1208-1211) documents the *same bug class* fixed earlier for numeric attributes ("red-`!` pills") — dates were simply never added to that fix. |
| V2 | Row ingestion writes raw date **strings** | `orchestrator.py:1325-1340` | ✅ Confirmed. Dim loop coerces numerics but `else: clean_row.append(str(val))` catches `date`; values like `'2025-04-28'` land as TEXT. |
| V3 | IR declares `Loss Date` as date | `ir.json` (this job) | ✅ `{name:'Loss Date', remote_name:'Loss_Date_ID', data_type:'date'}` |
| V4 | TWB declares `datatype="date"` + `derivation="Month"` | `Testghj_prod.twb` | ✅ `<column caption="Loss Date" datatype="date" name="[Loss Date]" role="dimension" type="ordinal"/>` + `[mn:Loss Date:ok]` instance |
| V5 | Extract column is TEXT; `EXTRACT(MONTH …)` throws | user-run Hyper API probe | ✅ Accepted as provided (`hyperexception: 'month' requires a date, interval, or timestamp argument`). Local re-execution impossible: sandbox denies `hyperd.exe` spawn. |
| V6 | Same hole exists elsewhere | grep `SqlType.text()` | ⚠️ Additional sites found: `hyper_builder.py:256` (default text), `:265` (`add_column(..., SqlType.text())`), `:581/:600` (`TYPE_MAP` → VARCHAR fallback). Any path served by `HyperAgent` needs the identical fix. |
| V7 | Contract verifier would catch a mistyped rebuild | `orchestrator.py:1028-1050` | ❌ It only asserts `[Extract].[Extract]` **exists** — column types unchecked, so a stale cached TEXT extract passes verification today. |

### Why it surfaced only now (timeline coherence)

| Build | Derivation emitted | Result |
|---|---|---|
| `MY` era | invalid-but-tolerated, pill dropped | workbook opened, Loss Trend blank — no datepart SQL ever issued |
| `my` / `MonthYear` | XSD rejection `D2E8DA72` | file refused before any query |
| **`Month` (current)** | first **valid** derivation | Desktop pushes `EXTRACT(MONTH FROM "Loss Date")` for the first time → hits TEXT column → Hyper engine exception → generic `6EA18A9E` |

The `Month/mn:` fix did not cause the bug; it **unmasked** the latent type bug by making Tableau issue the datepart query.

### Relationship to the pane-axis hypothesis (V_B/V_C probes)

The blank-canvas-on-open symptom (`Test_prod`, job `5ad0e73a`) and this internal-error symptom (`Testghj_prod`) are **two different defects**:

- Blank canvas with populated Marks card → pane↔axis binding gap → addressed by the `y-axis-name`/`x-axis-name` emission fix (already in `tableau_emitter.py`).
- Hard internal error on open → this TEXT-date defect → this plan.

Prediction for record: `V_B_NoAxis.twbx` should **also** fail with `6EA18A9E` (stripping axis attrs doesn't stop the month-datepart query). If it does, the bisect cleanly separates the two defects.

---

## 2. Implementation steps

### Step 1 — One shared SQL-type mapper (single source of truth)

New module-level helper in `orchestrator.py` (or `app/utils/sql_types.py` if `hyper_builder` import direction forbids reuse):

```python
def sql_type_for(dtype: str) -> "SqlType":
    d = str(dtype or "").lower()
    if d in ("integer", "bigint", "int"):        return SqlType.int()
    if d in ("double", "real", "float", "numeric", "decimal"): return SqlType.double()
    if d == "date":                              return SqlType.date()
    if d in ("datetime", "timestamp"):           return SqlType.timestamp()
    if d == "time":                              return SqlType.time()
    if d in ("bool", "boolean"):                 return SqlType.bool()   # guard: getattr fallback
    return SqlType.text()
```

- Replace the closure `_dim_sql_type` body with a delegation to this helper (keep the local name so the existing comment/history stays anchored).
- Refactor `hyper_builder.py:247-266` and its `TYPE_MAP` (`:581`, `:600`) to route through the same helper (import it; if circular-import risk, duplicate the mapping with a cross-referencing comment and a unit test asserting the two maps stay equal).

### Step 2 — Parse date values at ingestion

In the dim loop (`orchestrator.py:1325-1340`) insert explicit branches **before** the `else`:

```python
elif dt == "date":
    try:
        s = str(val).strip()
        s = s.split(" ")[0] if " " in s and "T" not in s else s
        clean_row.append(datetime.date.fromisoformat(s.rstrip("Z")))
    except Exception:
        clean_row.append(None); _bad_dates[d.get("name")] += 1
elif dt in ("datetime", "timestamp"):
    try:
        clean_row.append(datetime.datetime.fromisoformat(str(val).strip().rstrip("Z")))
    except Exception:
        clean_row.append(None); _bad_dates[d.get("name")] += 1
```

Notes:
- Python 3.11+ `fromisoformat` accepts `'T'` separators and trailing `Z`; the venv is 3.14.
- Unparseable → `None` (**never** raw string — a DATE column rejects it), with a per-field counter; after ingestion emit ONE warning Issue (`category="data"`, severity `"warning"`) summarizing `field → N unparseable values` rather than per-row spam.
- Factor this coercion into a tiny pure function `coerce_dim_value(dt, val) -> object` so `hyper_builder`'s insert path reuses it verbatim.

### Step 3 — Teach `_verify_hyper_contract` about column types

Signature becomes `_verify_hyper_contract(path, expected_types: dict[str, str] | None)`:

```python
tdef = conn.catalog.get_table_definition(TableName("Extract", "Extract"))
actual = {c.name.unescaped: c.type for c in tdef.columns}
for col_name, want in (expected_types or {}).items():
    got = actual.get(col_name)
    if want.startswith("date") and str(got) != "date":  # map precisely per SqlType
        return False, f"column '{col_name}' is {got}, expected {want}"
```

- Call sites `1098 / 1123 / 1387 / 1397` pass the dtype map built from the same `dims`/`dim_types` used at flatten time (cache/source-file branches reconstruct it from `ir.json`).
- Keep the existing "verification unavailable → pass" escape hatch, but log loudly — a silent pass is how this class ships.
- Split the reason-string formatting into a pure function so unit tests cover it without spawning `hyperd`.

### Step 4 — `hyper_builder` parity

Apply Steps 1-2 to `hyper_builder.py`'s schema construction (`~250-266`) and row-insert loop, plus `TYPE_MAP` (`581-600`). Acceptance: no code path can create an `Extract.Extract` whose declared-date columns are TEXT while the IR says `date`.

### Step 5 — Tests (no `hyperd` required)

1. `test_sql_type_mapping` — matrix over all dtypes incl. unknown → text.
2. `test_coerce_dim_value_dates` — `'2025-04-28'`, `'2025-04-28 00:00:00'`, ISO-T, trailing-Z, garbage → `None`.
3. `test_contract_reason_formatting` — pure-function check of the mismatch message.
4. Grep existing tests for assumptions that date dims land as text (the old `_dim_sql_type` had no direct test; `test_pipeline_e2e` is environmental and unaffected logically).
5. Live E2E (`RUN_LIVE_E2E=1`) P-series gains one assertion: extracted schema reports `Loss Date` as `DATE`.

### Step 6 — Rollout

1. Land Steps 1-5; full suite green (93 baseline + new units).
2. Re-run a fresh pipeline job (stale cached extracts are either rebuilt or rejected by the extended verifier — do **not** hand-delete caches; let the gate prove itself once).
3. Download TWBX → Desktop: expect Loss Trend to render month bars + incurred line (pane-axis fix handles shelf binding; this fix stops the engine crash).
4. Post-run checks: `issues` table has no `hyper` blocker; viz_plan still flags exactly `Litigation Incurred Loss`.

---

## 3. Explicitly out of scope / rejected alternatives

- **Keep TEXT column, change TWB pill to string** — rejected: breaks month semantics and contradicts MSTR's own attribute type.
- **Per-row error surfacing** — rejected: 500K-row noise; one aggregated Issue instead.
- **Altering the `Month/mn:` emitter choice** — unnecessary; it is canon-correct and merely exposed the defect.
