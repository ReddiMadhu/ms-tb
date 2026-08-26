"""Parse the generated TWB: dashboards, worksheets, filters, and key viz encodings."""
import re

TWB = r"C:\Users\madhu\Desktop\ms-tb\backend\artifacts\87b07292-cd96-47a3-b1f9-2fc6b6088f61\workbooks\hklm_prod\hklm_prod.twb"
twb = open(TWB, encoding="utf-8").read()

print("DASHBOARDS:", re.findall(r'<dashboard name="([^"]+)"', twb))
print()
ws = re.findall(r'<worksheet name="([^"]+)"', twb)
print("WORKSHEETS:", ws)
print()

for m in re.finditer(r'<datasource name="([^"]+)"(.*?)</datasource>', twb, re.S):
    name, body = m.group(1), m.group(2)
    flt = re.findall(r'<filter class="([^"]+)"[^>]*>(.*?)</filter>', body, re.S)
    if flt:
        print("DS:", name)
        for c, b in flt:
            print("   filter class=", c, "::", re.sub(r"\s+", " ", b)[:200])

# per-worksheet encodings: rows/cols/filter
print("\n===== WORKSHEET ENCODINGS =====")
for m in re.finditer(r'<worksheet name="([^"]+)"(.*?)</worksheet>', twb, re.S):
    wname, body = m.group(1), m.group(2)
    rows = re.search(r"<rows>([^<]*)</rows>", body)
    cols = re.search(r"<cols>([^<]*)</cols>", body)
    flt = re.findall(r'<filter class="([^"]+)"[^>]*>(.{0,160}?)</filter>', body, re.S)
    sort = re.findall(r"<sort class=\"([^\"]+)\"", body)
    print(f"- {wname}")
    print(f"    cols={cols.group(1) if cols else '-'}")
    print(f"    rows={rows.group(1) if rows else '-'}")
    if sort:
        print(f"    sort={sort}")
    for c, b in flt:
        print(f"    filter[{c}]:: {re.sub(chr(92)+'s+',' ',b)[:180]}")
