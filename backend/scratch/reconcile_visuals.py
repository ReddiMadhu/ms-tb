"""Exact reconciliation: harvested MSTR visuals vs generated TWB sheets."""
import json
import glob
import os
import re

VD = r"C:\Users\madhu\Desktop\ms-tb\backend\artifacts\87b07292-cd96-47a3-b1f9-2fc6b6088f61\visual_defs"
TWB = r"C:\Users\madhu\Desktop\ms-tb\backend\artifacts\87b07292-cd96-47a3-b1f9-2fc6b6088f61\workbooks\hklm_prod\hklm_prod.twb"

twb = open(TWB, encoding="utf-8").read()
sheets = set(re.findall(r'<worksheet name="([^"]+)"', twb))

def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())

sheets_n = {norm(s): s for s in sheets}

files = sorted(glob.glob(os.path.join(VD, "*.json")))
print("total visual_defs files:", len(files))
matched, unmatched = [], []
for f in files:
    j = json.load(open(f, encoding="utf-8"))
    vname = (j.get("name") or j.get("n") or "").strip()
    hit = sheets_n.get(norm(vname))
    (matched if hit else unmatched).append((os.path.basename(f), vname))
print(f"\nmapped to TWB sheet: {len(matched)}")
for k, n in matched:
    print("   OK ", k, "->", n)
print(f"\nNO matching sheet: {len(unmatched)}")
for k, n in unmatched:
    print("   MISS", k, "->", repr(n))
