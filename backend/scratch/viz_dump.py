"""Dump harvested MSTR visual definitions: names, types, and fetched grid values."""
import json
import glob
import os

D = r"C:\Users\madhu\Desktop\ms-tb\backend\artifacts\87b07292-cd96-47a3-b1f9-2fc6b6088f61\visual_defs"


def summarize_data(data, depth=0):
    """Recursively print a compact view of MSTR visual data payloads."""
    if isinstance(data, dict):
        for k, v in data.items():
            if k in ("metricValues",):
                raw = v.get("raw") if isinstance(v, dict) else None
                print("  " * depth + f"{k}: {len(raw) if isinstance(raw, list) else '?'} row-matrix")
                if isinstance(raw, list):
                    for r in raw[:8]:
                        print("  " * (depth + 1) + json.dumps(r)[:220])
            elif k in ("headers",):
                rows = v.get("rows") if isinstance(v, dict) else None
                print("  " * depth + "headers.rows:")
                if isinstance(rows, list):
                    for r in rows[:10]:
                        print("  " * (depth + 1) + json.dumps(r)[:220])
            elif k in ("rows", "tabularData", "grid"):
                print("  " * depth + f"{k}: {len(v) if isinstance(v, list) else type(v)}")
                if isinstance(v, list):
                    for r in v[:8]:
                        print("  " * (depth + 1) + json.dumps(r)[:220])
            elif isinstance(v, (dict, list)) and k not in ("thresholds",):
                print("  " * depth + f"{k}:")
                summarize_data(v, depth + 1)
    elif isinstance(data, list):
        print("  " * depth + f"[list len={len(data)}]")
        for item in data[:6]:
            summarize_data(item, depth + 1)


for f in sorted(glob.glob(os.path.join(D, "*.json"))):
    j = json.load(open(f, encoding="utf-8"))
    name = j.get("name") or j.get("n") or "?"
    vt = j.get("visualizationType", "")
    print("=" * 100)
    print(f"FILE {os.path.basename(f)}  NAME={name!r}  TYPE={vt}")
    if "data" in j:
        summarize_data(j["data"])
    elif "result" in j:
        r = j["result"]
        s = json.dumps(r)
        print("  result:", s[:900])
