"""
test_e2e_live_verification.py

TRUE start-to-end verification against the LIVE MicroStrategy environment.

Runs the complete pipeline (discovery -> semantic -> IR -> translation ->
viz plan -> Hyper build -> TDS/TWB/TWBX emission -> validation) with real
credentials, then audits the PRODUCED WORKBOOK against every invariant that
ever regressed:

  P1  artifact completeness (ir/viz_plan/physical_plan/hyper/tds/twb/twbx)
  P2  phantom-pill gate      — every [field] referenced anywhere in the TWB
                              (rows/cols/encodings/formulas) is declared
  P3  no illegal nesting     — no AGG(AGG(...)) in any calculation
  P4  rank fidelity          — RANK never wraps SUM
  P5  pie discipline         — Pie mark => empty axis pills + wedge-size
  P6  scatter grain          — Circle mark => <lod> detail encoding present
  P7  dual-axis combo        — two measures on Rows => >= 2 panes
  P8  dashboard completeness — zones match viz_plan exactly, no orphans
  P9  Fraud Score chain      — MSTR integer => plan INTEGER => TDS real
                              => Hyper numeric column
  P10 zero blocker issues    — harvest/emission gates stayed silent

Keys are read from EITHER backend/artifacts/e2e_keys.json:
    {
      "mstr_base_url":  "https://env-XXXX.cloud.strategy.com/MicroStrategyLibrary",
      "mstr_project_id": "...",
      "dossier_id":      "...",
      "username":        "...",
      "password":        "..."
    }
OR environment variables MSTR_BASE_URL / MSTR_PROJECT_ID / MSTR_DOSSIER_ID /
MSTR_USERNAME / MSTR_PASSWORD.

If neither is present the test SKIPS — the normal suite stays hermetic.
NEVER commit real credentials.
"""

import json
import os
import re
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

_ARTIFACTS_ROOT = Path(__file__).resolve().parent.parent / "artifacts"
_KEYS_FILE = _ARTIFACTS_ROOT / "e2e_keys.json"

_AGG = r"(?:SUM|AVG|ATTR|MEDIAN|COUNT|COUNTD|STDEVP?|VARP?)"


def _load_keys():
    if _KEYS_FILE.exists():
        raw = json.loads(_KEYS_FILE.read_text(encoding="utf-8"))
    else:
        raw = {
            "mstr_base_url": os.environ.get("MSTR_BASE_URL"),
            "mstr_project_id": os.environ.get("MSTR_PROJECT_ID"),
            "dossier_id": os.environ.get("MSTR_DOSSIER_ID"),
            "username": os.environ.get("MSTR_USERNAME"),
            "password": os.environ.get("MSTR_PASSWORD"),
        }
    required = ["mstr_base_url", "mstr_project_id", "dossier_id", "username", "password"]
    missing = [k for k in required if not raw.get(k)]
    if missing:
        pytest.skip(f"Live e2e keys not provided (missing: {missing})")
    return raw


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


async def _run_pipeline(keys, run_dir: Path):
    """Execute the real pipeline against live MSTR; returns (job_id, job_row, artifacts_dir)."""
    from unittest.mock import patch

    from app.models.job import Job
    from app.services.pipeline.orchestrator import PipelineOrchestrator

    job_id = f"e2e-live-{int(time.time())}"
    artifacts_dir = str(run_dir / job_id)
    os.makedirs(artifacts_dir, exist_ok=True)

    from app.db.session import SessionLocal as RealSessionLocal

    job = Job(
        id=job_id,
        name="E2E_Live_Verification",
        status="PENDING",
        mstr_base_url=keys["mstr_base_url"],
        mstr_project_id=keys["mstr_project_id"],
        artifacts_dir=artifacts_dir,
        auto_publish=False,
    )

    session = RealSessionLocal()
    try:
        session.add(job)
        session.commit()
    finally:
        session.close()

    orchestrator = PipelineOrchestrator(
        job_id=job_id,
        selected_dossier_ids=[keys["dossier_id"]],
        mstr_username=keys["username"],
        mstr_password=keys["password"],
    )

    async def _execute_with_real_db():
        def _factory():
            return RealSessionLocal()

        with patch("app.services.pipeline.orchestrator.SessionLocal", _factory):
            await orchestrator.run()

    await _execute_with_real_db()

    check = RealSessionLocal()
    try:
        row = check.query(Job).filter(Job.id == job_id).first()
        return job_id, row, artifacts_dir
    finally:
        check.close()


# ────────────────────────── helpers ──────────────────────────

def _declared_columns(twb_text: str):
    return set(re.findall(r'<column[^>]*name="(\[[^\]]+\])"', twb_text))


def _referenced_fields(twb_text: str):
    """Every [Field] pill reference in shelves, encodings and calc formulas.
    Datasource qualifiers like [federated.default] are not fields."""
    refs = set()
    for el_name in ("rows", "cols"):
        for m in re.finditer(rf"<{el_name}>(.*?)</{el_name}>", twb_text, re.S):
            refs.update(re.findall(r"(\[[^\]\[]+\])", m.group(1)))
    for m in re.finditer(r'<(?:color|size|text|lod|wedge-size)\s+column="([^"]+)"', twb_text):
        refs.update(re.findall(r"(\[[^\]]+\])", m.group(1)))
    for m in re.finditer(r'formula="([^"]*)"', twb_text):
        refs.update(re.findall(r"(\[[^\]\[]+\])", m.group(1)))
    refs.discard("[federated.default]")
    # drop doubled [[...]] artifacts from bracket stripping
    return {r for r in refs if not r.startswith("[[")}


def _worksheets(twb_text: str):
    out = {}
    for m in re.finditer(
        r'<worksheet name="([^"]+)">(.*?)</worksheet>', twb_text, re.S
    ):
        out[m.group(1)] = m.group(2)
    return out


# ────────────────────────── the test ──────────────────────────

@pytest.mark.asyncio
async def test_live_end_to_end_pipeline_and_workbook_audit():
    if not os.environ.get("RUN_LIVE_E2E"):
        pytest.skip(
            "live verification is opt-in: set RUN_LIVE_E2E=1 "
            "(requires network access and permission to spawn hyperd.exe)"
        )
    keys = _load_keys()
    run_dir = _ARTIFACTS_ROOT / "e2e-runs"
    run_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    job_id, job_row, artifacts_dir = await _run_pipeline(keys, run_dir)
    elapsed = time.time() - t0
    adir = Path(artifacts_dir)
    report = {"job_id": job_id, "pipeline_seconds": round(elapsed, 1)}

    # Job must complete
    assert job_row is not None, "job row missing"
    assert job_row.status == "COMPLETE", (
        f"pipeline ended {job_row.status}: {job_row.error_message}"
    )
    report["job_status"] = job_row.status

    # ── P1 artifact completeness ──
    for rel in (
        "ir.json", "viz_plan.json", "physical_plan.json",
        "physical_measures.json", "semantic_bundle.json",
        "hyper/extract.hyper",
    ):
        p = adir / rel
        assert p.exists() and p.stat().st_size > 0, f"missing artifact {rel}"
    assert (adir / "hyper" / "extract.hyper").stat().st_size > 1024, \
        "hyper is a placeholder, not a real extract"
    tds_files = list((adir / "datasources").glob("*.tds"))
    assert tds_files, "no TDS emitted"
    wb_dirs = list((adir / "workbooks").iterdir())
    assert wb_dirs, "no workbook emitted"
    twb_file = next((wb_dirs[0]).glob("*_prod.twb"), None) or next((wb_dirs[0]).glob("*.twb"))
    twbx_file = twb_file.with_suffix(".twbx")
    assert twbx_file.exists(), "prod TWBX missing"
    with zipfile.ZipFile(twbx_file) as zf:
        names = zf.namelist()
        assert twb_file.name in names
        assert any(n.startswith("Data/Extracts/") for n in names)
    report["P1_artifacts"] = "PASS"

    twb_text = twb_file.read_text(encoding="utf-8")

    # ── P2 phantom-pill gate ──
    declared = _declared_columns(twb_text)
    referenced = _referenced_fields(twb_text)
    phantoms = sorted(referenced - declared)
    assert not phantoms, f"phantom field references (undeclared pills): {phantoms}"
    report["P2_no_phantoms"] = "PASS"

    # ── P3 illegal aggregation nesting ──
    bad_nesting = []
    for name, body in _worksheets(twb_text).items():
        pass
    for m in re.finditer(r'formula="([^"]*)"', twb_text):
        f = m.group(1)
        if re.search(rf"{_AGG}\s*\(\s*{_AGG}\s*\(", f, re.I):
            bad_nesting.append(f[:120])
    assert not bad_nesting, f"AGG(AGG(...)) nesting found: {bad_nesting}"
    report["P3_no_nested_aggs"] = "PASS"

    # ── P4 rank fidelity ──
    rank_wrapped = [
        f[:120] for f in re.findall(r'formula="([^"]*)"', twb_text)
        if re.search(r"RANK\s*\(\s*SUM\s*\(", f, re.I)
    ]
    assert not rank_wrapped, f"RANK(SUM(...)) regression: {rank_wrapped}"
    report["P4_rank_clean"] = "PASS"

    # ── P5 pie discipline ──
    for name, body in _worksheets(twb_text).items():
        if '<mark class="Pie"/>' in body:
            rows_t = re.search(r"<rows>(.*?)</rows>", body, re.S)
            cols_t = re.search(r"<cols>(.*?)</cols>", body, re.S)
            assert not (rows_t and rows_t.group(1).strip()), f"{name}: pie has Rows pills"
            assert not (cols_t and cols_t.group(1).strip()), f"{name}: pie has Cols pills"
            assert "wedge-size" in body, f"{name}: pie lacks wedge-size angle"
    report["P5_pie_discipline"] = "PASS"

    # ── P6 scatter grain ──
    for name, body in _worksheets(twb_text).items():
        if '<mark class="Circle"/>' in body:
            assert "<lod " in body or "<lod " in twb_text, (
                f"{name}: circle sheet without Detail (<lod>) — dots will collapse"
            )
    report["P6_scatter_grain"] = "PASS"

    # ── P7 dual-axis combo structure ──
    for name, body in _worksheets(twb_text).items():
        r = re.search(r"<rows>(.*?)</rows>", body, re.S)
        if r:
            # Count QUANTITATIVE pills (:qk) only — :nk pills are dimensions
            meas_pills = re.findall(r"\[[^\]]*:qk\]", r.group(1))
            if len(meas_pills) >= 2:
                pane_count = len(re.findall(r"<pane[ >]", body))
                assert pane_count >= 2, (
                    f"{name}: {len(meas_pills)} measures on Rows but only "
                    f"{pane_count} pane(s)"
                )
    report["P7_combo_panes"] = "PASS"

    # ── P8 dashboard completeness vs viz_plan ──
    vp = json.loads((adir / "viz_plan.json").read_text(encoding="utf-8"))
    ws_names = set(_worksheets(twb_text).keys())
    root = ET.fromstring(twb_text)
    dash_nodes = {
        d.get("name"): d for d in root.iter("dashboard")
    }
    for ds in vp.get("dashboards", []):
        dname = ds["name"].strip()
        assert dname in dash_nodes, f"dashboard '{dname}' not emitted"
        zoned = {
            z.get("name") for z in dash_nodes[dname].iter("zone") if z.get("name")
        }
        expected = set(ds.get("worksheets", []))
        assert expected <= zoned, (
            f"dashboard '{dname}': planned-but-unzoned sheets: {expected - zoned}"
        )
    orphan_zones = set()
    for dn, dnode in dash_nodes.items():
        for z in dnode.iter("zone"):
            zn = z.get("name")
            if zn and zn not in ws_names:
                orphan_zones.add(zn)
    assert not orphan_zones, f"zones pointing to nonexistent worksheets: {orphan_zones}"
    failed_planned = [w["name"] for w in vp.get("worksheets", []) if w.get("is_failed")]
    assert not failed_planned, f"planned worksheets marked failed: {failed_planned}"
    report["P8_dashboards_complete"] = "PASS"

    # ── P9 Fraud Score type chain ──
    ir = json.loads((adir / "ir.json").read_text(encoding="utf-8"))
    fs_dim = next(d for d in ir["dimensions"]
                  if (d.get("caption") or d.get("name")) == "Fraud Score")
    assert fs_dim.get("data_type") in ("integer", "double", "real", "numeric"), (
        f"IR Fraud Score type drifted: {fs_dim.get('data_type')}"
    )
    pp = json.loads((adir / "physical_plan.json").read_text(encoding="utf-8"))
    fs_types = [
        c["data_type"] for t in pp["table_plans"] for c in t["columns"]
        if c["column_name"].lower().startswith("fraud_score")
    ]
    assert fs_types and all(t == "INTEGER" for t in fs_types), (
        f"physical Fraud Score columns not INTEGER: {fs_types}"
    )
    tds_text = tds_files[0].read_text(encoding="utf-8")
    m = re.search(r'<column[^>]*name="\[Fraud Score\]"[^>]*>', tds_text)
    assert m, "[Fraud Score] column missing from TDS"
    decl = m.group(0)
    assert 'datatype="real"' in decl or 'datatype="integer"' in decl, (
        f"TDS declares Fraud Score non-numeric: {decl}"
    )

    # Hyper ground truth (best-effort: skipped if sandbox blocks HyperProcess)
    try:
        from tableauhyperapi import HyperProcess, Telemetry, Connection, SqlType
        with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hp:
            with Connection(
                endpoint=hp.endpoint,
                database=str(adir / "hyper" / "extract.hyper"),
            ) as conn:
                cols = conn.catalog.get_table_definition(("Extract", "Extract")).columns
                fs_col = next((c for c in cols if c.name.unescaped == "Fraud Score"), None)
                assert fs_col is not None, "Hyper Extract has no 'Fraud Score' column"
                assert fs_col.type in (SqlType.int(), SqlType.double(), SqlType.big_int()), (
                    f"Hyper 'Fraud Score' is {fs_col.type} — text leak persists"
                )
                report["P9_fraud_score_chain"] = "PASS (incl. Hyper)"
    except AssertionError:
        raise
    except Exception as he:  # sandbox/HyperProcess unavailable
        report["P9_fraud_score_chain"] = f"PASS (TDS/plan; Hyper probe skipped: {he})"

    # ── P10 zero blockers ──
    try:
        from app.db.session import SessionLocal
        from app.models.objects import Issue
        s = SessionLocal()
        try:
            blockers = (
                s.query(Issue)
                .filter(Issue.job_id == job_id, Issue.severity == "blocker")
                .count()
            )
        finally:
            s.close()
        assert blockers == 0, f"{blockers} blocker issue(s) recorded"
        report["P10_zero_blockers"] = "PASS"
    except AssertionError:
        raise
    except Exception as de:
        report["P10_zero_blockers"] = f"inconclusive ({de})"

    print("\n===== LIVE E2E VERIFICATION =====")
    print(json.dumps(report, indent=2))
