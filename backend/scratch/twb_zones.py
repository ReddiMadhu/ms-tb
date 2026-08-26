"""Count dashboard zones, check missing sheet, extract sort orders."""
import re

TWB = r"C:\Users\madhu\Desktop\ms-tb\backend\artifacts\87b07292-cd96-47a3-b1f9-2fc6b6088f61\workbooks\hklm_prod\hklm_prod.twb"
twb = open(TWB, encoding="utf-8").read()

ws = re.findall(r'<worksheet name="([^"]+)"', twb)
print("n_worksheet_tags:", len(ws), " unique:", len(set(ws)))
print("has 'Incurred Loss' sheet:", any("ncurred Loss" in w for w in ws))

for dm in re.finditer(r'<dashboard name="([^"]+)"(.*?)</dashboard>', twb, re.S):
    dname, dbody = dm.group(1), dm.group(2)
    zones = re.findall(r'<zone [^>]*name="([^"]+)"', dbody)
    print("\nDASH", dname.replace("&amp;", "&"), "->", len(zones), "zones")
    print("   ", zones)

print("\nSORTS:")
for sm in re.finditer(r'<worksheet name="([^"]+)"(.*?)</worksheet>', twb, re.S):
    body = sm.group(2)
    s = re.search(r'<sort class="([^"]+)"[^>]*>(.{0,220}?)</sort>', body, re.S)
    if s:
        print("  ", sm.group(1), "::", s.group(1), "::", re.sub(r"\s+", " ", s.group(2))[:180])
