"""
test_dossier_44819273.py

Real Dossier Integration Tests using the exact MicroStrategy P&C Claims Dossier
from Job 44819273-477c-4896-90af-d1cee5770dfc:
- 20 Dimensions
- 33 Measures (Dynamic Formulas & Aggregations)
- 45 Visualizations (KPI Cards, Bar Charts, Donut Charts, Combo Charts, Dual-Axis, Geo Maps)
- 5 Dashboards (Executive Summary, Financial & Severity, Fraud & Litigation, Geography, Adjuster Performance)
"""

import json
import os
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from app.agents.ir_compiler import BIIR, IRDimension, IRMeasure, IRVisual, IRTable, IRRelationship
from app.agents.visualization import VisualizationAgent, VizPlan
from app.agents.tableau_emitter import TableauEmitterAgent
from app.models.job import Job


@pytest.fixture
def real_dossier_ir():
    """Load the exact BIIR from the real dossier migration job artifacts."""
    artifacts_root = Path(__file__).parent.parent / "artifacts"
    candidates = list(artifacts_root.glob("**/ir.json"))
    
    if candidates:
        with open(candidates[0], "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        pytest.skip("Artifact ir.json for real dossier not found on disk")

    tables = [IRTable(**t) for t in data.get("tables", [])]
    relationships = [IRRelationship(**r) for r in data.get("relationships", [])]
    dimensions = [IRDimension(**d) for d in data.get("dimensions", [])]
    measures = [IRMeasure(**m) for m in data.get("measures", [])]
    visuals = [IRVisual(**v) for v in data.get("visuals", [])]

    return BIIR(
        job_id=data.get("job_id", "44819273-477c-4896-90af-d1cee5770dfc"),
        tables=tables,
        relationships=relationships,
        dimensions=dimensions,
        measures=measures,
        visuals=visuals,
    )


def test_real_dossier_structure(real_dossier_ir):
    """Verify that the real dossier has 20 dimensions, 33 measures, and 45 visuals across 5 pages."""
    assert len(real_dossier_ir.dimensions) == 20
    assert len(real_dossier_ir.measures) == 33
    assert len(real_dossier_ir.visuals) == 45

    pages = set(v.page_name for v in real_dossier_ir.visuals if v.page_name)
    assert len(pages) == 5
    assert "Executive Summary" in pages
    assert "Financial & Severity View" in pages
    assert "Adjuster Performance View" in pages


def test_real_dossier_viz_plan_generation(real_dossier_ir):
    """Verify VisualizationAgent plans all 45 worksheets and 5 dashboards for the real dossier."""
    agent = VisualizationAgent(ir=real_dossier_ir)
    viz_plan = agent.plan()

    assert len(viz_plan.worksheets) == 45
    assert len(viz_plan.dashboards) == 5

    # Check that each dashboard has the correct number of worksheets
    dash_map = {d.name.strip(): d for d in viz_plan.dashboards}
    assert "Executive Summary" in dash_map
    assert len(dash_map["Executive Summary"].worksheets) == 16

    # Verify no worksheet has an invalid mark type
    for ws in viz_plan.worksheets:
        assert ws.mark_type in ("text", "bar", "pie", "line", "circle", "square", "automatic", "map")


def test_real_dossier_shelf_assignment_validity(real_dossier_ir):
    """Verify smart shelf assignment handles KPI cards, combo charts, and bar charts cleanly."""
    agent = VisualizationAgent(ir=real_dossier_ir)
    viz_plan = agent.plan()
    ws_map = {ws.name: ws for ws in viz_plan.worksheets}

    # 1. KPI Card: 'Avg (Fraud Score)' -> text mark, label has measure
    if "Avg (Fraud Score)" in ws_map:
        kpi = ws_map["Avg (Fraud Score)"]
        assert kpi.mark_type == "text"
        assert kpi.label is not None
        assert kpi.label.field_type == "measure"

    # 2. Multi-measure / Dual-axis chart: 'Top Adjusters by Workload with Avg Resolution Days'
    adj_ws = next((ws for ws in viz_plan.worksheets if "Top Adjusters by Workload" in ws.name or "Adjusters" in ws.name), None)
    assert adj_ws is not None

    # 3. Bar Chart: 'Total Claims by Loss Cause' -> Loss Cause on rows/cols
    if "Total Claims by Loss Cause" in ws_map:
        cause_ws = ws_map["Total Claims by Loss Cause"]
        assert cause_ws.mark_type == "bar"


@pytest.mark.asyncio
async def test_real_dossier_tableau_emitter_twb_xml(db_session, tmp_path, real_dossier_ir):
    """Verify TableauEmitterAgent emits 100% valid Tableau XML for the entire 45-visual real dossier."""
    job_id = "test-real-dossier-job"
    artifacts_dir = str(tmp_path / job_id)

    job = Job(
        id=job_id,
        name="Real_Dossier_Prod",
        status="PENDING",
        mstr_base_url="https://env-test.cloud.strategy.com/MicroStrategyLibrary",
        mstr_project_id="PROJ_REAL",
        artifacts_dir=artifacts_dir,
    )
    db_session.add(job)
    db_session.commit()

    agent = VisualizationAgent(ir=real_dossier_ir)
    viz_plan = agent.plan()

    # Create dummy hyper file
    hyper_dir = Path(artifacts_dir) / "hyper"
    hyper_dir.mkdir(parents=True, exist_ok=True)
    dummy_hyper = hyper_dir / "extract.hyper"
    dummy_hyper.write_bytes(b"dummy hyper data")
    hyper_paths = {"default": str(dummy_hyper)}

    emitter = TableauEmitterAgent(
        db=db_session,
        job=job,
        artifacts_dir=artifacts_dir,
    )

    twbx_path = emitter.emit_workbook(
        ir=real_dossier_ir,
        viz_plan=viz_plan,
        hyper_paths=hyper_paths,
        workbook_name="Real_Dossier_Prod",
    )

    assert twbx_path.exists()

    # Inspect generated TWB XML
    twb_path = Path(artifacts_dir) / "workbooks" / "Real_Dossier_Prod" / "Real_Dossier_Prod.twb"
    assert twb_path.exists()

    tree = ET.parse(str(twb_path))
    root = tree.getroot()

    # 1. Check Datasource columns and calculations
    ds_node = root.find(".//datasources/datasource")
    assert ds_node is not None

    calc_cols = ds_node.findall("./column[calculation]")
    assert len(calc_cols) > 0

    # Ensure no calculated field has a malformed formula or conflicting prefix
    for col in calc_cols:
        col_name = col.get("name")
        assert not col_name.startswith("[Calc_Calc_")
        calc_elem = col.find("calculation")
        assert calc_elem is not None
        formula = calc_elem.get("formula")
        assert formula is not None and len(formula.strip()) > 0

    # 2. Check all 45 Worksheets
    worksheets = root.findall(".//worksheets/worksheet")
    assert len(worksheets) == 45

    for ws in worksheets:
        ws_name = ws.get("name")
        rows_el = ws.find(".//table/rows")
        cols_el = ws.find(".//table/cols")

        # CRITICAL TEST: Rows and cols must NOT have space-joined adjacent pills
        if rows_el is not None and rows_el.text:
            text = rows_el.text.strip()
            # If multiple pills exist, they must be joined with '+'
            if "][" in text:
                assert False, f"Worksheet '{ws_name}' has adjacent brackets without operator: {text}"
            if "] [" in text:
                assert False, f"Worksheet '{ws_name}' has space-separated pills without operator: {text}"

        if cols_el is not None and cols_el.text:
            text = cols_el.text.strip()
            if "][" in text:
                assert False, f"Worksheet '{ws_name}' has adjacent brackets without operator: {text}"
            if "] [" in text:
                assert False, f"Worksheet '{ws_name}' has space-separated pills without operator: {text}"

    # 3. Check all 5 Dashboards
    dashboards = root.findall(".//dashboards/dashboard")
    assert len(dashboards) == 5
