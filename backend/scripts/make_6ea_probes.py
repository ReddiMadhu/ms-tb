"""Surgical probes for persistent 6EA18A9E on job 2281d8a3 (hbdfgh_prod).

P1_NoAxis      : strip y-axis-name/x-axis-name from every pane.
                 Tests whether the pane-axis attributes crash layout parsing.
P2_NoMonthPill : KEEP axis attrs, but point Columns at the declared
                 [none:Loss Date:nk] instance instead of [mn:Loss Date:ok].
                 Tests whether the MONTH datepart query itself is the trigger.
"""
import re
import sys
import zipfile
from pathlib import Path

src = Path(sys.argv[1])
out_dir = src.parent / "crash_probes_6ea"
out_dir.mkdir(exist_ok=True)

zin = zipfile.ZipFile(src)
twb_name = [n for n in zin.namelist() if n.endswith(".twb")][0]
others = {n: zin.read(n) for n in zin.namelist() if n != twb_name}
xml = zin.read(twb_name).decode("utf-8")


def package(tag: str, text: str) -> None:
    dst = out_dir / f"{tag}.twbx"
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(twb_name, text)
        for n, d in others.items():
            z.writestr(n, d)
    print("wrote", dst)


# P1 — strip axis attributes
p1 = re.sub(r'\s+y-axis-name="[^"]*"', "", xml)
p1 = re.sub(r'\s+x-axis-name="[^"]*"', "", p1)
assert "axis-name" not in p1
package("P1_NoAxis", p1)

# P2 — swap the month pill reference for the plain none-instance
p2 = xml.replace(
    "[federated.default].[mn:Loss Date:ok]",
    "[federated.default].[none:Loss Date:nk]",
)
swapped = p2.count("[federated.default].[none:Loss Date:nk]")
print("P2 none-pill refs now:", swapped, "(mn refs left:", p2.count("mn:Loss Date"), ")")
package("P2_NoMonthPill", p2)

print(
    "\nOpen P1_NoAxis FIRST.\n"
    "  loads OK  -> pane axis attributes are the crasher\n"
    "  fails too -> open P2_NoMonthPill:\n"
    "      loads OK  -> the MONTH datepart query is the trigger\n"
    "      fails too -> neither; deeper layout issue (send me both results)"
)
