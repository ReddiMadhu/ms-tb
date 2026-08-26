"""
Compare LLM-cache translations (llm_cache.json / test.json) against the NEW
ground-truth expansion engine, metric by metric, and classify every difference.

Cache keys are SHA-256 of the FULL Tier-3 prompt; we reconstruct each prompt
from the recorded (metric, expression) estate to recover the mapping.
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, "src")
sys.path.insert(0, "tests")

from app.agents.expression_resolver import resolve_expression  # noqa: E402
from app.agents.ir_compiler import BIIR, IRMeasure, IRCompilerAgent  # noqa: E402
from app.services.pipeline.orchestrator import (  # noqa: E402
    apply_definition_expansions, collect_object_definitions,
)

# Recorded estate (verify_dedup_emission.py LOG): (name, expected_calc, raw_expr)
LOG = [
    ("States", "Count<Distinct=True , UseLookupForAttributes=False >(State){~+}"),
    ("High Fraud Claims", "Sum<UseLookupForAttributes=False >([High Fraud Flag]){~+}"),
    ("Sum (Subrogation)", "Sum<UseLookupForAttributes=False >(Subrogation){~+}"),
    ("Reserve", "Sum<UseLookupForAttributes=False >([Reserve Amount USD]){~+}"),
    ("Claim_Count_2", "Count<Distinct=True , UseLookupForAttributes=False >([Claim ID]@ID){~+}"),
    ("Paid Amount", "Sum<UseLookupForAttributes=False >([Paid Amount USD]){~+}"),
    ("Avg_Claim_Resolution_Days", "Avg<UseLookupForAttributes=False >([Claim Resolution Time Days]){~+}"),
    ("Count (Region)", "Count<Distinct=True , UseLookupForAttributes=False >(Region){~+}"),
    ("Litigation Claims", "Sum<UseLookupForAttributes=False >(Litigation_Flag){~+}"),
    ("Litigation Rate", "[Litigation Claims] / Total_Claims"),
    ("Avg Severity", "Avg<UseLookupForAttributes=False >([Total Incurred USD]){~+}"),
    ("Count (Claim ID)", "Count<UseLookupForAttributes=False >([Claim ID]){~+}"),
    ("Outstanding Exposure", "Sum<UseLookupForAttributes=False >([Reserve Amount USD]){~+}"),
    ("Recovery", "Sum<UseLookupForAttributes=False >([Recovery Amount USD]){~+}"),
    ("Avg (Fraud Score)", "Avg<UseLookupForAttributes=False >([Fraud Score]){~+}"),
    ("Total Incurred", "Sum<UseLookupForAttributes=False >([Total Incurred USD]){~+}"),
    ("Net Losses", "Sum<UseLookupForAttributes=False >([Net Loss]@ID){~+}"),
    ("Sum (Salvage)", "Sum<UseLookupForAttributes=False >(Salvage){~+}"),
    ("Total_Claims", "Sum<UseLookupForAttributes=False >([Count (Claim ID)]){~+}"),
    ("Top State Loss", "Max<UseLookupForAttributes=False >([Total Incurred USD]){~+}"),
    ("Litigation Incurred Loss",
     'Sum<UseLookupForAttributes=False >(IF((Litigation@ID = "1"),[Total Incurred],0)){~+}'),
    ("High Fraud Rate", "[High Fraud Claims] / Total_Claims"),
    ("Count (Adjuster Name)", "Count<Distinct=True , UseLookupForAttributes=False >([Adjuster Name]){~+}"),
    ("Avg Claim", "Avg<UseLookupForAttributes=False >([Total Incurred USD]){~+}"),
]

PROMPT_TMPL = (
    "Translate this MicroStrategy metric expression to a Tableau calculated field.\n\n"
    "MicroStrategy Metric: {name}\n"
    "Expression: {expr}\n"
    "Dimensionality: null\n"
    "Conditionality: null\n\n"
    "Rules:\n"
    "- Use Tableau Desktop syntax (SUM, AVG, COUNT, COUNTD, MIN, MAX, etc.)\n"
    "- Use FIXED/INCLUDE/EXCLUDE LOD expressions where dimensionality indicates\n"
    "- Handle null with ZN() if needed\n"
    "- Handle zero division with IIF(denominator = 0, NULL, ...)\n"
    "- Do NOT use RAWSQL or custom SQL"
)

KNOWN_REASONS = [
    ("Net Losses", "CACHE INVENTED business rule: said Incurred−Recovery−Salvage; "
                   "MSTR truth is (Paid+Reserve)−Recovery"),
    ("Litigation Claims", "CACHE INVENTED an extra \"'1'\" branch; MSTR flag is only \"Yes\""),
    ("Total_Claims", "CACHE emitted SUM over aggregate calc [Count (Claim ID)] — "
                     "illegal nesting the emitter now rejects"),
    ("Top State Loss", "CACHE wrapped in {FIXED : SUM(…)} — filter-unsafe LOD; "
                       "MSTR means plain MAX at view grain"),
    ("States", None),
]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cache = json.load(open(os.path.join(root, "artifacts", "llm_cache",
                                        "llm_cache.json"), encoding="utf-8"))

    # struct_key -> (metric, cached_calc)
    key_to_metric = {}
    for name, expr in LOG:
        h = "struct_" + hashlib.sha256(
            PROMPT_TMPL.format(name=name, expr=expr).encode("utf-8")).hexdigest()
        if h in cache:
            key_to_metric[h] = (name, str(cache[h].get("tableau_calc", "?")))
    unmatched = [k for k in cache if k.startswith("struct_") and k not in key_to_metric]

    # Ground-truth engine on the LIVE captured payload
    live = json.load(open(os.path.join(root, "artifacts", "live_instance_now.json"),
                          encoding="utf-8"))
    ds_map = live.get("datasets") or {}
    by_did, by_name = collect_object_definitions(ds_map)

    agent = IRCompilerAgent.__new__(IRCompilerAgent)
    agent.db = None
    agent.job = None
    agent._caption_counter = 0
    agent._id_to_name = {}

    ir = BIIR(job_id="cmp")
    ir.object_definitions = {"by_did": by_did, "by_name_lower": by_name}
    for e_name, e_expr in LOG:
        ir.measures.append(IRMeasure(
            id=f"c-{e_name}", mstr_id=f"M-{e_name}", name=e_name,
            local_name=e_name.replace(" ", "_"), remote_name=e_name.replace(" ", "_"),
            caption=e_name, tableau_calc="", confidence=0.5, expression_text=e_expr,
        ))

    # Stage-order parity: mx-wiring compiles EVERY measure from its raw text
    # first (the pipeline's ground-truth baseline); the expansion pass then
    # overrides only measures touching harvested definitions.
    # Production policy parity: cache calcs carry ZN(...) everywhere and
    # IIF(…=0, NULL, …) guards, i.e. jobs ran with null_propagation="zero_fill".
    for m in ir.measures:
        m.null_policy = "zero_fill"
        m.zero_division_policy = "null"
        try:
            m.tableau_calc = agent._compile_expression(
                m, m.null_policy, m.zero_division_policy)
        except Exception:
            m.tableau_calc = ""
    apply_definition_expansions(ir, agent)
    gt = {m.name: m.tableau_calc for m in ir.measures}

    import re as _re

    def canon(c):
        """Cosmetic-noise remover: quotes, ZN(), INT(), braces, spacing, [ ]."""
        c = " ".join((c or "").split()).upper().replace("'", '"')
        c = _re.sub(r"\bZN\(([^()]*)\)", r"\1", c)
        c = _re.sub(r"\bINT\(([^()]*)\)", r"\1", c)
        c = c.replace("{FIXED :", "").replace("}", "")
        return c.replace("[", "").replace("]", "")

    print(f"cache entries matched to estate metrics: {len(key_to_metric)} / {len(cache)}")
    if unmatched:
        print("unmatched cache keys (prompt never reconstructed from this estate):")
        for k in unmatched:
            print("   ", k[:20], "→", str(cache[k].get("tableau_calc"))[:70])
    print()

    def norm(c):
        return canon(c)

    print(f"{'METRIC':<28} | VERDICT    | LLM CACHE vs GROUND TRUTH")
    print("-" * 118)
    same = diff = missing = 0
    for name, expr in LOG:
        cache_hit = next(((k, v) for k, v in key_to_metric.items() if v[0] == name), None)
        g = gt.get(name, "")
        if not cache_hit:
            print(f"{name:<28} | NO-CACHE   | gt: {g[:78]}")
            missing += 1
            continue
        c = cache_hit[1][1]
        if canon(c) == canon(g):
            note = "(cosmetic only: ZN/INT/braces)" if norm(c) != norm(g) else ""
            print(f"{name:<28} | SAME{note[:4]:<5}   | {c[:70]}")
            same += 1
        else:
            reason = dict(KNOWN_REASONS).get(name)
            tag = f"DIFF-{reason.split(':')[0]}" if reason else "DIFF"
            print(f"{name:<28} | {tag:<10}| cache : {c[:58]}")
            print(f"{'':<28} |            | truth : {g[:58]}")
            if reason:
                print(f"{'':<28} |            | why   : {reason}")
            diff += 1

    print()
    print(f"summary: same={same}  different={diff}  no-cache-entry={missing}")


if __name__ == "__main__":
    main()
