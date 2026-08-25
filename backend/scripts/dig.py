import json, sys
from pathlib import Path
job = Path(sys.argv[1])

# 1) list visual_defs titles + types
print("== visual_defs (W*.json) names/types:")
for f in sorted((job / "visual_defs").glob("W*.json")):
    d = json.load(open(f, encoding="utf-8"))
    print(f"  {f.name} name={d.get('name')!r} type={d.get('visualizationType')!r}")

# 2) find any visual whose name or content mentions Litigation / Salvage
print("\n== matches for 'litig' or 'salv':")
for f in sorted((job / "visual_defs").glob("W*.json")):
    txt = open(f, encoding="utf-8").read()
    if "litig" in txt.lower() or "salv" in txt.lower():
        d = json.load(open(f, encoding="utf-8"))
        print(f"  {f.name}: name={d.get('name')!r}")
        # dump its binding columns
        for k in ("columns", "rows", "metrics", "dataFields", "measures"):
            if d.get(k) is not None:
                print(f"    {k}: {d.get(k)}")

# 3) semantic bundle: find Litigation / Salvage measure defs
print("\n== semantic bundle measure defs mentioning litig/salv:")
sb = job / "semantic_bundle.json"
if sb.exists():
    bundle = json.load(open(sb, encoding="utf-8"))
    measures = bundle.get("measures") or bundle.get("managed_metrics") or []
    if isinstance(measures, dict):
        measures = list(measures.values())
    for m in measures:
        nm = m.get("name") or m.get("id") or ""
        if "litig" in nm.lower() or "salv" in nm.lower():
            print(f"  {nm}: expression_text={m.get('expression_text')!r} precomputed_calc={m.get('precomputed_calc')!r} provenance={m.get('provenance')!r}")
