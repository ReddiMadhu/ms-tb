# Verified Root-Cause Analysis — Tableau (`hklm_prod`) vs MicroStrategy

> [!IMPORTANT]
> Every claim below was **verified against three independent sources**:
> 1. The row-level extract `backend/artifacts/87b07292-cd96-47a3-b1f9-2fc6b6088f61/hyper/extract.hyper` (500,000 rows — embedded byte-identical inside `hklm_prod.twbx` as `Data/Extracts/default.hyper`, 35,913,728 bytes).
> 2. The harvested MicroStrategy visual payloads `…/visual_defs/W*.json` (the *actual rendered values* MSTR returned per visual, incl. raw values and view-filter summaries).
> 3. The generated workbook `…/workbooks/hklm_prod/hklm_prod.twb` (calculated-field formulas, sheet bindings, filters) and `…/object_definitions.json` (harvested MSTR metric/attribute definitions).

---

## ✅ Headline

**Both systems compute from the same 500K-row dataset and agree everywhere their definitions match.**
Of the original 11 reported discrepancies, only **3 are real defects**; the rest are misreadings or properties of the synthetic source data.

| Original # | Discrepancy | Verdict |
|---|---|---|
| 1 | Fraud & Litigation KPIs ~1000x off | 🔴 **REAL — MSTR domain-evaluation bug** (not a page filter) |
| 2 | Region ranking swapped West/South | ⚪ **PHANTOM** — both systems render identical values |
| 3 | "Top States Loss" $5.34B vs $300K | 🔴 **REAL — mistranslation** `Max(F){~+}` → `MAX({FIXED : SUM(F)})` |
| 4 | Litigation Incurred Loss shows Salvage-range data | 🟠 **REAL (double bug)** — dead `"1"` condition + MSTR binding slip |
| 5 | Top states suspiciously uniform | ⚪ Synthetic source-data property — identical in both tools |
| 6 | Loss-cause rankings/values differ | ⚪ **PHANTOM** — identical values; MSTR exec-summary chart sorts ascending |
| 7 | Coverage distribution differs | ⚪ **PHANTOM** — MSTR's own payload shows Flood Endorsement dominant at $1,173M |
| 8 | Severity distribution differs | ⚪ **PHANTOM** — all four band totals byte-identical; Low/Medium labels were transposed when reading |
| 9 | Adjuster workload uniform | ⚪ Synthetic source-data property |
| 10 | Adjuster resolution days differ | ⚪ **PHANTOM** — same metric (`Avg_Claim_Resolution_Days`) bound in both |
| 11 | Loss trend 40K vs 7K monthly | ⚪ **PHANTOM** — data spans **72 months** (Jan 2021 – Dec 2026); ≈6.9K claims/month is correct |

---

## 🔴 Discrepancy 1 — Fraud & Litigation KPIs: SOLVED with arithmetic proof

### What each system renders
| Visual (harvested MSTR id) | MSTR raw value | Tableau / row-level truth |
|---|---|---|
| High Fraud Claims (W339) | `30` | **27,979** |
| High Fraud Rate (W340) | `0.00006` (= 30/500,000) | 0.05596 |
| Litigation Claims (W342) | `1` | **30,638** |
| Litigation Rate (W343) | `0.000002` (= 1/500,000) | 0.06128 |
| Litigation by State bars (W344) | 18 states summing to **exactly 30,638** | same |

### Root cause: attribute-domain evaluation, not a filter
Definitions are logically identical on both sides:
```
MSTR : High Fraud Flag ≔ IF(([Fraud Score]@ID >= 70),1,0)   → Sum([High Fraud Flag]){~+}
TWB  : SUM(IF [Fraud Score] >= 70 THEN 1 ELSE 0 END)
```
But in MicroStrategy these flags were created as **derived attributes** (`t=12, st=3077`), not derived metrics. MSTR evaluated them over the **distinct value domain**, not over fact rows:

| Check against extract.hyper | Result |
|---|---|
| Distinct `Fraud Score` values | **99** (integers 1–99) |
| Distinct scores ≥ 70 | **30** ← matches W339 exactly |
| Distinct `Litigation` values | **2** ('No','Yes') |
| Values equal to 'Yes' | **1** ← matches W342 exactly |

Three corroborating proofs:
1. **Rates use the full-population denominator**: 30/500,000 = 6e-05 and 1/500,000 = 2e-06 — exactly what W340/W343 return. A page filter would have shrunk the denominator too.
2. **Avg Fraud Score on the same page = 39.618852** (full population, unfiltered).
3. **MSTR's own bar chart on the same page sums to 30,638** — the chart aggregates per-State (row-level join), while the standalone text KPI hits the attribute domain.

> [!CAUTION]
> This **refutes** the earlier hypothesis of a hidden page-level selector/filter on the Fraud & Litigation page. There is no filter; the numerator itself is evaluated over `{70..99}` and `{'Yes'}`.
>
> The Tableau numbers (27,979 / 30,638) are the **correct business answers** — they implement the author's evident intent.

---

## 🔴 Discrepancy 3 — "Top States Loss": a genuine translation defect

Harvested MSTR definition + rendered value:
```
Top State Loss ≔ Max<UseLookupForAttributes=False>([Total Incurred USD]){~+}
viewFilterSummary : "(Rank of {Top State Loss} = 1)"
rendered (W352)   : rv = 300000.00  ("300K")
```
Row-level truth: `MAX(Total Incurred USD)` over the whole table = **$300,000.00** (also exactly $300,000 within FL, the rank-1 state). So MSTR's KPI = *largest single claim in the top-ranked state* — despite its name.

Generated TWB translation ([hklm_prod.twb line 93–94](backend/artifacts/87b07292-cd96-47a3-b1f9-2fc6b6088f61/workbooks/hklm_prod/hklm_prod.twb)):
```tableau
[Top State Loss] = MAX({FIXED : SUM([Total Incurred USD])})
```
On the no-dimension KPI sheet, `{FIXED : SUM(...)}` collapses to the grand total, so Tableau renders **5,343,932,378.47** — matching your comparison table exactly.

**Root cause**: the emitter translated row-level `Max(F){~+}` into `MAX({FIXED : SUM(F)})`, turning "max single claim" into "max (grand) sum". Fix: `MAX([Total Incurred USD])` (+ optional `Rank` filter), and consider renaming the KPI in both systems.

---

## 🟠 Discrepancy 4 — "Litigation Incurred Loss": double bug confirmed

1. **Dead condition (source metric)**: `Sum(IF((Litigation@ID = "1"),[Total Incurred],0)){~+}` — but the data contains **only 'Yes'/'No'** (no '1'), so the true value is $0 everywhere. The TWB faithfully copied the dead condition (`SUM(IF [Litigation] = "1" …)`), so Tableau also renders $0.
2. **Binding slip (MSTR API)**: the visual *titled* "Litigation Incurred Loss" (W345) returns metric **`Sum (Salvage)`** (rv range 124,174.82–158,601.46 = per-state Salvage). This matches the known slip handled by `visualization.py`'s binding-slip detector.

Net effect: MSTR displays Salvage-per-state under the wrong title; Tableau displays $0. Neither shows what the metric name promises.

---

## ⚪ Phantom discrepancies — proof of equality (MSTR payload vs Hyper truth)

| Item | Harvested MSTR payload | Hyper/TWBX value | Conclusion |
|---|---|---|---|
| Region incurred (W373) | Midwest 1,188,073,592 · Northeast 1,185,508,843 · **South 1,788,367,853** · West 1,181,982,090 | identical | Both South-dominant; "West dominant" reading doesn't correspond to either system. Bars sorted alphabetically/descending likely misled. |
| Claim volume by region (W365) | 111,239 / 111,259 / 166,965 / 110,537 | identical | — |
| Coverage (W105) | **Flood Endorsement 1,173,214,340 dominant**, then Liability 577.7M … Comprehensive 268.8M | identical | "Evenly distributed in MSTR" was a misread; one coverage dominates in both. |
| Severity (W278) | High 1,979,538,534 · Low 552,862,651 · Medium 2,066,508,082 · Severe 745,023,111 | identical | All four totals byte-identical; the earlier reading transposed Low↔Medium labels. |
| Trend month-1 (W209) | 2021‑01: incurred 77,761,072.55, claims 7,291 | identical row exists | Monthly ≈ 6.3–7.3K claims across **72 months**; "~42K/month" assumed 12 months. |
| Top states (W94) | FL 304,866,215 (max) … CA 290,084,791 (min) | identical | Uniform because the synthetic generator made it so. |
| Loss causes (W93/W325) | min 235,484,942 · max 553,736,637 (**Vandalism**) | identical | Fire/smoke = 315,358,456 everywhere — never $400–500M. Exec-summary chart simply sorts ascending. |
| Adjusters (W230/W205) | workload min 8,286 max 20,322 · avg-days 177.83–186.41 | identical | Same metric bound in TWBX; "Tableau clusters 140–170" unsupported. |
| Claim Status donut (W104) | In Litigation = 29,996 | Claim Status column: 29,996 | Donut counts `Claim Status='In Litigation'`, a **different field** from `Litigation='Yes'` (30,638) — near-equal by coincidence of the generator, which fueled confusion with the F&L page. |

---

## Why MSTR shows "suspiciously uniform" values (#5, #9)

Source dataset: `MSTR_PC_Claims_Sample_Data_500K_With_Resolution_Time.xlsx`.
- 18 states × 27.4–28.0K claims each ($290–305M incurred)
- Top-8 senior adjusters × ~20.1–20.3K claims; mid adjusters ~13.5K
- Loss causes mostly $235–330M (Vandalism deliberately spiked to $553.7M)
- Single-claim incurred capped at exactly **$300,000**

This is the **generator's signature**, present identically in both tools — not an aggregation artifact in either.

---

## Corrected ownership summary

| # | Issue | Real root cause | Owner |
|---|---|---|---|
| 1 | Fraud/Litigation 1000x | MSTR evaluates flag **derived attributes at distinct-value domain level** (30 of 99 score values; 1 of 2 litigation values); rates prove unfiltered scope | Migration note: keep Tableau's row-level logic; optionally rebuild MSTR flags as derived metrics |
| 3 | Top States Loss $5.34B vs $300K | Emitter mistranslated `Max(F){~+}` → `MAX({FIXED : SUM(F)})`; MSTR's own metric is semantically odd (max single claim, Rank=1 filter) | Migration engine (emitter) |
| 4 | Litigation Incurred Loss | Dead `"1"` condition (data has Yes/No) + MSTR API binding slip rendering `Sum(Salvage)` | MSTR dashboard author + MSTR API |
| 2,6,7,8,10,11 | Region/causes/coverage/severity/days/trend | No difference exists between current systems; earlier readings were chart-order/scale/label misreads | Comparison methodology |
| 5,9 | Uniform distributions | Synthetic generator property of the shared source XLSX | Data engineering |

### Recommended fixes (migration engine)
1. **Emitter**: translate `Max<UseLookupForAttributes=False>(F){~+}` as `MAX([F])` (row-level), never `MAX({FIXED : SUM(F)})`.
2. **Validation agent**: numeric parity checks compared KPIs that MSTR computes at different granularity (domain-level attributes vs row-level) — treat derived-attribute-based metrics as suspect and verify against the fact table (financial_kpi_confidence was already flagged **0.0** in `validation_scorecard.json`, correctly signalling this).
3. **Documentation**: annotate `Litigation_Flag`-style fields whose MSTR definition tests an ID form (`"1"`) absent from data.
