# Known MicroStrategy Behaviors — Migration Impact

This document records verified MicroStrategy platform behaviors that produce
different results than Tableau when operating on the same underlying data.
These are **not migration bugs** — they are properties of how MSTR evaluates
certain object types.

---

## 1. Derived-Attribute Domain-Level Evaluation

**Verified:** 26 August 2026 (RCA-VERIFIED.md, Defect #1)
**Affected metrics:** Any metric that aggregates a derived attribute flag (st=3077)

### Behavior

When a MicroStrategy **derived attribute** (subType 3077, `t=12`) is used as
a flag inside a `Sum()` metric, MSTR evaluates the flag expression over the
**distinct value domain** of the referenced attribute, not over fact rows.

### Arithmetic Proof

Source: 500,000-row claims dataset with:
- `Fraud Score`: 99 distinct integer values (1–99)
- `Litigation`: 2 distinct values ('Yes', 'No')

| Metric | MSTR evaluates | Tableau evaluates | MSTR result | Tableau result |
|---|---|---|---|---|
| `High Fraud Claims` = `Sum([High Fraud Flag])` | Over 99 distinct Fraud Scores → 30 values ≥ 70 | Over 500K rows → 27,979 rows with score ≥ 70 | **30** | **27,979** |
| `Litigation Claims` = `Sum([Litigation_Flag])` | Over 2 distinct Litigation values → 1 = 'Yes' | Over 500K rows → 30,638 rows with Litigation='Yes' | **1** | **30,638** |

**Corroboration:** MSTR's own rates use the full population denominator:
- `High Fraud Rate` = 30/500,000 = 6e-05 (W340 raw value)
- `Litigation Rate` = 1/500,000 = 2e-06 (W343 raw value)

If a page filter were suppressing rows, the denominators would shrink too.

### Definitions (from `object_definitions.json`)

```
High Fraud Flag ≔ IF(([Fraud Score]@ID >= 70), 1, 0)     ← st=3077, derived attr
Litigation_Flag ≔ IF((Litigation@ID = "Yes"), 1, 0)       ← st=3077, derived attr

High Fraud Claims ≔ Sum<UseLookupForAttributes=False>([High Fraud Flag]){~+}
Litigation Claims ≔ Sum<UseLookupForAttributes=False>(Litigation_Flag){~+}
```

### Migration Guidance

- **Keep Tableau's row-level evaluation** — it produces the correct business KPIs.
- The validation agent now flags these metrics with `derived_attr_domain_risk` warnings.
- If numeric parity with MSTR is required, rebuild the MSTR flags as **derived metrics**
  (`t=4`) instead of derived attributes (`t=12, st=3077`).

---

## 2. Attribute ID-Form vs DESC-Form Mismatch

**Verified:** 26 August 2026 (RCA-VERIFIED.md, Defect #4)

### Behavior

A single MSTR attribute can have multiple "forms" — typically an `ID` form
(often numeric: 0/1) and a `DESC` form (often string: 'Yes'/'No'). Different
metrics in the same dossier may test different forms:

```
Litigation_Flag          ≔ IF((Litigation@ID = "Yes"), 1, 0)      ← tests DESC-like form
Litigation Incurred Loss ≔ Sum(IF((Litigation@ID = "1"), [Total Incurred], 0)){~+}  ← tests numeric ID form
```

If the data contains only one form's values (e.g. 'Yes'/'No' but not '1'/'0'),
the metric testing the absent form produces $0 everywhere — a **dead condition**.

### Migration Guidance

- The validation agent now detects dead conditions via the `dead_condition` check.
- When flagged, verify which ID form values exist in the extract data.
- The correct fix is on the MSTR dashboard author's side — the metric definition
  should test the form that actually exists in the data.

---

## 3. MSTR API Binding Slips

**Verified:** 26 August 2026 (RCA-VERIFIED.md, Defect #4, Bug B)

### Behavior

The MSTR visual definition API (`GET /api/dossiers/{id}/instances/{iid}/chapters/{ch}/visualizations/{vk}`)
occasionally returns the **wrong metric binding** for a visual. The documented case:

- Visual titled "Litigation Incurred Loss" (W345)
- API returns metric `Sum (Salvage)` instead of `Litigation Incurred Loss`
- The visual displays Salvage data (range $124K–$159K) under the wrong title

### Migration Guidance

- The `visualization.py` binding-slip detector (lines 321-361) catches known signatures.
- Any visual where the title exactly matches a bundle measure name but the bound
  measure is different gets flagged as `Review Needed` with the source binding preserved.
- This is an MSTR REST API defect — no workaround exists other than detection.
