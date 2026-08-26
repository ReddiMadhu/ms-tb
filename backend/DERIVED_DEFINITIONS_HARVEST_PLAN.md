# Plan — Harvest MSTR Dataset-Derived Object Definitions (Ground-Truth Expansion)

**Status:** READY TO IMPLEMENT
**Owner:** TBD · **Scope:** backend harvest → resolver → compiler precedence → LLM context → API/UI chain display → tests

---

## 0. Evidence (already verified against the live env)

The dossier **instance** endpoint (`GET /api/dossiers/{id}/instances/{mid}`) returns, per dataset,
TWO object arrays. We currently read only one:

| Array | Entry shape | Content |
|:---|:---|:---|
| `datasets{dsId}.att` | `{t:12, st:3072\|3077, n, did, f?}` | attributes; **`st=3077` = DERIVED attributes carrying real `f` formulas** |
| `datasets{dsId}.mx`  | `{t:4, st:1024\|1031, n, did, um, f, aggFunc, nf}` | metrics (we harvest this today, `orchestrator.py:585`) |

Ground truth captured in `backend/artifacts/instance_full.json`:

```
High Fraud Flag ≔ IF(([Fraud Score]@ID >= 70),1,0)
Litigation_Flag ≔ IF((Litigation@ID = "Yes"),1,0)
Net Loss        ≔ ([Paid Amount USD] + [Reserve Amount USD]) - [Recovery Amount USD]   (dsc: "Paid plus reserve minus recovery")
Loss_Year       ≔ Year([Loss Date]@ID)
Month_Loss      ≔ Month([Loss Date]@ID)
LOSS_YR_MTH     ≔ Concat(Loss_Year@ID,"-",Month_Loss@ID)          ← nested derivation ⇒ resolver must recurse
```

Consequences of today's behavior:
* `/api/model/*` cannot serve these objects (500 `attribute_derived unsupported`; metrics are dataset-local ⇒ 404) — the instance payload is the ONLY REST source.
* Translations currently come from the Tier‑1 LLM cache and are **wrong where it matters**:
  * `Net Losses` emitted as `Incurred − Recovery − Salvage` (conf 1.0) — truth is **`(Paid + Reserve) − Recovery`**.
  * `Litigation_Flag` calc tests `'Yes' OR '1'` — truth is only `"Yes"`.

---

## 1. Harvest layer — capture every `f`

**File:** `backend/src/app/services/pipeline/orchestrator.py` (mx-harvest block, ~lines 576–591)

Replace the mx-only loop with an both-arrays collector:

```python
object_defs: dict[str, dict] = {}          # did -> definition
for _ds_id, ds in ds_map.items():
    for key in ("att", "mx"):
        for e in (ds or {}).get(key) or []:
            did, f = e.get("did"), e.get("f")
            if did and isinstance(f, str) and f.strip():
                if did in object_defs and object_defs[did]["formula"] != f.strip():
                    logger.warning("Conflicting defs for %s (%s) across datasets — keeping first",
                                   e.get("n"), did)
                    continue
                object_defs[did] = {
                    "name": e.get("n") or "",
                    "formula": f.strip(),
                    "t": e.get("t"), "st": e.get("st"),
                    "um": bool(e.get("um")),
                    "dsc": e.get("dsc") or "",
                    "dataset_id": _ds_id,
                }
logger.info("Harvested %d dataset-object definitions (attrs+metrics)", len(object_defs))
```

* Persist as a new artifact **`object_definitions.json`** next to `ir.json`
  (`{"by_did": {...}, "by_name_lower": {...}}`).
* Attach the same map to the in-memory IR (`ir.object_definitions`) for downstream stages.

---

## 2. Resolver — inline true definitions recursively

**New file:** `backend/src/app/agents/expression_resolver.py`

```python
@dataclass
class Resolved:
    text: str                 # fully inlined, decorations stripped
    chain: list[dict]         # [{"name","formula","source":"harvested"}...] expansion order
    unresolved: list[str]     # names still dangling after resolution

def resolve_expression(text: str, defs_by_did, defs_by_name_lower,
                       *, max_depth: int = 8) -> Resolved: ...
```

Rules:
1. Tokenize refs `\[[^\]]+\](@ID|@DESC)?`.
2. Lookup order: exact-name (ci) via `by_name_lower` → did alias.
3. Substitute definition body; recurse until fixpoint or `max_depth`.
4. Strip MSTR decorations while inlining: `<…>` VLDB hints, trailing `{…}` dimty, `@ID`/`@DESC` form suffixes.
5. Cycle guard (visited-did set) — fail closed: leave text as-is, add to `unresolved`.
6. NEVER invent a definition; unknown refs stay and get reported.

Unit cases (must include): `Sum<…>([High Fraud Flag]){~+}` → `SUM(IF((Fraud Score >= 70),1,0))`-shape;
`Sum<…>([Net Loss]@ID){~+}` → Paid/Reserve/Recovery expansion; `Concat` two-hop chain; A↔B cycle safety.

---

## 3. Compiler precedence — ground truth beats LLM cache

**Problem to design around:** today's stage order is `IR_COMPILE → AI_TRANSLATE → VIZ(mx-wiring)`,
so the LLM answers first and the current mx step only rewrites what `_compile_expression` can handle.

**Change:** run definition-resolution EARLY — immediately after `IR_COMPILE` (before
`AI_TRANSLATE`) inside `run_pipeline`:

1. Create dossier instance(s) there (reuse `MSTRSession` factory pattern already used in the VIZ
   harvest; tolerate failure ⇒ fall back to today's path).
2. For each `IRMeasure` whose `expression_text` resolves against `object_defs`:
   ```python
   res = resolve_expression(m.expression_text, defs_by_did, defs_by_name_lower)
   calc = compiler._compile_expression(resolved_measure_stub, m.null_policy, m.zero_division_policy)
   if calc:
       m.tableau_calc = calc
       m.precomputed_calc = calc          # ← makes AITranslationAgent SKIP it (filter exists:
                                          #   ai_translation.py:182,192 “never re-translate
                                          #   measures with a valid precomputed_calc”)
       m.translation_method = "Harvested Definition Expansion"
       m.definition_chain = res.chain     # new optional IRMeasure field
       m.is_derived = True                # stays out of the Hyper extract
   ```
3. The existing VIZ-stage mx application stays but gains a guard
   `if getattr(m, "precomputed_calc", None): continue` so it cannot overwrite ground-truth output.

Cache poisoning becomes unreachable-by-construction for covered measures (no purge required).

---

## 4. Acceptance criteria (corrected calcs)

| Measure | Required output |
|:---|:---|
| High Fraud Claims | `SUM(IF INT([Fraud Score]) >= 70 THEN 1 ELSE 0 END)` — unchanged value, now **metadata-proven**, method=`Harvested Definition Expansion` |
| Litigation Claims | `SUM(IF [Litigation] = 'Yes' THEN 1 ELSE 0 END)` — **no `'1'` branch** |
| Litigation Incurred Loss | `SUM(IF [Litigation] = 'Yes' THEN [Total Incurred USD] ELSE 0 END)` |
| **Net Losses** | row-level `(Paid + Reserve) − Recovery` inside SUM per null-policy — **must NOT contain `Total Incurred` or `Salvage`** |

---

## 5. Pass definitions into the LLM (context grounding)

**File:** `backend/src/app/agents/ai_translation.py` → `_llm_translate()`

Append to the prompt, only the defs referenced (directly) by this measure:

```
Known MicroStrategy object definitions harvested from the live environment
(GROUND TRUTH — use verbatim; never contradict or reinvent):
  High Fraud Flag ≔ IF(([Fraud Score]@ID >= 70),1,0)
Rules additions:
- If the expression references an object NOT defined above, set requires_human_review=true
  and say which reference is unverified in the explanation.
```

Build the snippet from `ir.object_definitions` filtered by names appearing in
`measure.expression_text` (one extra hop for chained derivations).

---

## 6. Surface the chain in DB → API → UI

1. **IRMeasure**: new optional field `definition_chain: Optional[list[dict]] = None`
   (`ir_compiler.py`, persisted automatically into `ir.json`).
2. **API** `GET /jobs/{id}/objects` (`api/v1/discovery.py:249-281`): when patching from `ir.json`,
   also copy `definition_chain` into `ObjectResponse` (schema += `definition_chain: Optional[list]`,
   `schemas.py`; forward in `frontend/src/api.ts` `MigrationObject`).
3. **LogicExplorer.tsx** source panel renders beneath the raw formula:

   ```
   Sum<UseLookupForAttributes=False >([High Fraud Flag]){~+}
     └─ High Fraud Flag ≔ IF(([Fraud Score]@ID >= 70),1,0)    ● harvested
   ```
   Chain rows carry a badge: `● harvested` (method=Harvested Definition Expansion) vs
   `◆ AI-expanded` (legacy rows keep working unchanged).

---

## 7. Tests (new file `backend/tests/test_derived_definitions.py`)

1. **Harvest unit**: fixture copying the REAL payload shape (`att` st=3077 with `f`, `mx`)
   → assert 6 defs found incl. `Net Loss` formula string and `dsc` preserved.
2. **Resolver unit**: HFF inline, Net Loss inline, LOSS_YR_MTH 2-hop recursion,
   A↔B cycle leaves text intact + reports unresolved, `@ID`/`<…>`/`{…}` stripping.
3. **Precedence integration**: measure with `precomputed_calc` never reaches
   `AITranslationAgent._translate` (assert cache/LLM untouched even when Tier‑1 would hit).
4. **Regression locks** (fail today, pass after):
   * Net Losses calc contains `[Paid Amount USD]` and `[Reserve Amount USD]`,
     and NOT `Total Incurred` / `Salvage`.
   * Litigation Claims has no `'1'` alternative branch.
5. Update `backend/scripts/verify_dedup_emission.py` LOG expectations to the corrected calcs.

---

## 8. Implementation order (checklist)

- [ ] 1. `expression_resolver.py` + unit tests (pure function — build first)
- [ ] 2. Orchestrator both-array harvest → `object_definitions.json` + `ir.object_definitions` + unit test
- [ ] 3. Early wiring after IR_COMPILE: resolve → compile → `precomputed_calc`/`definition_chain`;
       VIZ-mx guard `continue` when precomputed present
- [ ] 4. Correct `verify_dedup_emission.py`; run full `pytest` (expect the 2 known live-env failures only)
- [ ] 5. LLM context section + unverified-reference review rule in `ai_translation.py`
- [ ] 6. `definition_chain` through schemas → API → `LogicExplorer.tsx` badges/chain render
- [ ] 7. Live job re-run; diff old-vs-new calcs (expect exactly: Litigation `'1'` gone,
       Net Loss rewritten); paste results into `spec/AUDIT-v5.md`

## Risks / notes

* Same did across multiple datasets with different formulas → keep-first + warning (rare; cube-scoped objects).
* Name collisions between datasets → resolution prefers did match from the SAME dataset as the metric, then global unique name.
* Formulas containing dimty on derived attrs (none observed) → resolver strips `{…}`; if a def ever needs dimty, fail closed to review.
* Old jobs' artifacts remain frozen snapshots — only new runs gain chains (consistent with prior decisions).
