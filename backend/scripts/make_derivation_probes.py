"""
Empirical derivation probes for Tableau's <column-instance derivation> XSD.

Background (evidence so far):
  - "MY"        : loads in Desktop 2026.1 (no D2E8DA72) but renders blank
  - "my"        : REJECTED — value 'my' not in enumeration
  - "MonthYear" : REJECTED — value 'MonthYear' not in enumeration

This script builds one minimal, self-contained .twbx per candidate token,
reusing a real extract.hyper from the latest migration job, so Tableau
Desktop itself tells us which tokens are (a) schema-valid AND (b) rendered
as a date axis. Each probe has exactly ONE worksheet using ONE candidate
token, so a failure unambiguously indicts that token.

Usage:
  python scripts/make_derivation_probes.py <job_artifacts_dir>
Output: <job_artifacts_dir>/derivation_probes/PROBE_<token>.twbx
"""

import shutil
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

CANDIDATES = ["mn", "MN", "Month", "YR", "Year"]

TWB_TEMPLATE = """<?xml version='1.0' encoding='utf-8' ?>

<!-- PROBE workbook: derivation='{token}' -->
<workbook original-version='18.1' source-build='2026.1.0 (20261.25.0214.0917)' source-platform='win' version='18.1'>
  <document-format-change-manifest>
    <SheetIdentifierTracking />
    <SortTagUnified />
  </document-format-change-manifest>
  <datasources>
    <datasource caption='Probe Data' inline='true' name='federated.1p55probe' version='18.1'>
      <connection class='hyper' cleanup='false' filename='Data/Extracts/default.hyper' interpretationMode='0' server='oem'>
        <relation connection='hyper' name='Extract' table='[Extract].[Extract]' type='table' />
        <cols>
          <map key='[Loss Date]' value='[Loss Date]' />
          <map key='[Total Incurred USD]' value='[Total Incurred USD]' />
        </cols>
      </connection>
      <column datatype='date' name='[Loss Date]' role='dimension' type='ordinal' />
      <column-instance column='[Loss Date]' derivation='{token}' name='[{prefix}:{col}:ok]' pivot='key' type='ordinal' />
      <column datatype='real' name='[Total Incurred USD]' role='measure' type='quantitative' />
      <column-instance column='[Total Incurred USD]' derivation='Sum' name='[sum:Total Incurred USD:qk]' pivot='key' type='quantitative' />
      <layout dim-ordering='alphabetic' dim-percentage='0.5' measure-ordering='alphabetic' measure-percentage='0.5' show-structure='true' />
      <datasource-parameters />
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name='ProbeTrend'>
      <table>
        <view>
          <datasources>
            <datasource caption='Probe Data' name='federated.1p55probe' />
          </datasources>
          <datasource-dependencies datasource='federated.1p55probe'>
            <column datatype='date' name='[Loss Date]' role='dimension' type='ordinal' />
            <column-instance column='[Loss Date]' derivation='{token}' name='[{prefix}:{col}:ok]' pivot='key' type='ordinal' />
            <column datatype='real' name='[Total Incurred USD]' role='measure' type='quantitative' />
            <column-instance column='[Total Incurred USD]' derivation='Sum' name='[sum:Total Incurred USD:qk]' pivot='key' type='quantitative' />
          </datasource-dependencies>
          <aggregation value='true' />
        </view>
        <style />
        <panes>
          <pane id='0'>
            <view>
              <breakdown value='auto' />
            </view>
            <mark class='Bar' />
          </pane>
        </panes>
        <rows>[federated.1p55probe].[sum:Total Incurred USD:qk]</rows>
        <cols>[federated.1p55probe].[{prefix}:{col}:ok]</cols>
      </table>
    </worksheet>
  </worksheets>
  <dashboards />
  <windows source-height='30'>
    <window class='worksheet' name='ProbeTrend'>
      <viewpoint>
        <zoom type='entire-view' />
      </viewpoint>
    </window>
  </windows>
</workbook>
"""


def main(job_dir: str) -> None:
    job = Path(job_dir)
    hyper_src = job / "hyper" / "extract.hyper"
    if not hyper_src.exists():
        # fall back to any extract under the job
        hits = list(job.rglob("*.hyper"))
        if not hits:
            raise SystemExit(f"no extract.hyper found under {job}")
        hyper_src = hits[0]

    out_dir = job / "derivation_probes"
    out_dir.mkdir(parents=True, exist_ok=True)

    for token in CANDIDATES:
        prefix = {
            "None": "none",
        }.get(token, token.lower())
        col = "Loss Date"
        twb_text = TWB_TEMPLATE.format(token=token, prefix=prefix, col=col)
        # Windows FS is case-insensitive: disambiguate mn vs MN explicitly.
        case_tag = "lower" if token.islower() else ("upper" if token.isupper() else "mixed")
        safe = f"{token}_{case_tag}"
        twb_name = f"PROBE_{safe}.twb"
        twbx_path = out_dir / f"PROBE_{safe}.twbx"

        tmp = out_dir / f"_tmp_{safe}"
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir()
        (tmp / twb_name).write_text(twb_text, encoding="utf-8")
        data_dir = tmp / "Data" / "Extracts"
        data_dir.mkdir(parents=True)
        shutil.copy2(hyper_src, data_dir / "default.hyper")

        with zipfile.ZipFile(twbx_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(tmp / twb_name, twb_name)
            z.write(data_dir / "default.hyper", "Data/Extracts/default.hyper")

        shutil.rmtree(tmp)
        print(f"wrote {twbx_path}")

    print(
        "\nOpen each PROBE_*.twbx in Tableau Desktop and note:\n"
        "  1) Does it load without D2E8DA72?\n"
        "  2) Does the columns axis show DATE values (months/years), 'Abc', or nothing?\n"
        "The tokens that pass BOTH tests are the valid, rendering derivations."
    )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
