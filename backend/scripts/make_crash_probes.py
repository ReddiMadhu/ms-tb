"""Bisect probes for Tableau error 6EA18A9E from the exact crashing TWB.

V_A_Original : byte-identical repack of the crashing workbook (control)
V_B_NoAxis   : same XML with every y-axis-name / x-axis-name stripped
V_C_NoCombo  : V_B plus the entire Loss Trend worksheet removed
"""
import re
import shutil
import sys
import zipfile
from pathlib import Path

src_twbx = Path(sys.argv[1])
out_dir = Path(sys.argv[2]) / "crash_probes"
out_dir.mkdir(parents=True, exist_ok=True)

zin = zipfile.ZipFile(src_twbx)
twb_name = [n for n in zin.namelist() if n.endswith(".twb")][0]
hyper_members = {n: zin.read(n) for n in zin.namelist() if n != twb_name}
xml = zin.read(twb_name).decode("utf-8")


def package(tag: str, xml_text: str) -> Path:
    dst = out_dir / f"{tag}.twbx"
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(twb_name, xml_text)
        for n, data in hyper_members.items():
            z.writestr(n, data)
    print("wrote", dst)
    return dst


# V_A control
package("V_A_Original", xml)

# V_B strip axis attrs
noaxis = re.sub(r'\s+y-axis-name="[^"]*"', "", xml)
noaxis = re.sub(r'\s+x-axis-name="[^"]*"', "", noaxis)
assert "y-axis-name" not in noaxis
package("V_B_NoAxis", noaxis)

# V_C additionally drop the whole Loss Trend worksheet block
m = re.search(
    r"\n\s*<worksheet name=\"Loss Trend: Monthly Claims and Incurred Amount\">.*?</worksheet>",
    noaxis,
    flags=re.S,
)
if m:
    nocombo = noaxis[: m.start()] + noaxis[m.end():]
else:
    print("WARN: Loss Trend block not found; V_C == V_B")
    nocombo = noaxis
package("V_C_NoCombo", nocombo)

print(
    "\nOpen V_B_NoAxis.twbx first.\n"
    "  - loads fine  -> pane axis attributes caused 6EA18A9E\n"
    "  - still fails -> open V_C_NoCombo.twbx to isolate the combo sheet"
)
