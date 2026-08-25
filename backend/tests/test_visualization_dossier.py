"""
test_visualization_dossier.py

Tests for the enhanced VisualizationAgent and TableauEmitterAgent visual generation:
- Dossier chapter/page hierarchy -> matching Tableau Dashboards
- Mark type mapping for all standard MSTR chart types
- Intelligent shelf assignments (rows, columns, color, size, label)
- Balanced dashboard zone layouts (KPI row + chart grid)
"""

import xml.etree.ElementTree as ET
import pytest
from app.agents.ir_compiler import BIIR, IRDimension, IRMeasure, IRVisual
from app.agents.visualization import VisualizationAgent, VizPlan, VIZ_TYPE_MAP
from app.agents.tableau_emitter import TableauEmitterAgent
from app.models.job import Job


@pytest.fixture
def insurance_ir():
    dims = [
        IRDimension(id="d1", mstr_id="MSTR_D1", name="Loss Cause", local_name="Loss Cause", remote_name="Loss_Cause", caption="Loss Cause", data_type="string"),
        IRDimension(id="d2", mstr_id="MSTR_D2", name="Claim Status", local_name="Claim Status", remote_name="Claim_Status", caption="Claim Status", data_type="string"),
        IRDimension(id="d3", mstr_id="MSTR_D3", name="State Name", local_name="State Name", remote_name="State_Name", caption="State Name", data_type="string"),
        IRDimension(id="d4", mstr_id="MSTR_D4", name="Reported Date", local_name="Reported Date", remote_name="Reported_Date", caption="Reported Date", data_type="string"),
        IRDimension(id="d5", mstr_id="MSTR_D5", name="Coverage", local_name="Coverage", remote_name="Coverage", caption="Coverage", data_type="string"),
        IRDimension(id="d6", mstr_id="MSTR_D6", name="Policy Type", local_name="Policy Type", remote_name="Policy_Type", caption="Policy Type", data_type="string"),
    ]
    measures = [
        IRMeasure(id="m1", mstr_id="MSTR_M1", name="Total Incurred USD", local_name="Total Incurred USD", remote_name="Total_Incurred_USD", caption="Total Incurred USD", tableau_calc="SUM([Total Incurred USD])"),
        IRMeasure(id="m2", mstr_id="MSTR_M2", name="Paid Amount USD", local_name="Paid Amount USD", remote_name="Paid_Amount_USD", caption="Paid Amount USD", tableau_calc="SUM([Paid Amount USD])"),
        IRMeasure(id="m3", mstr_id="MSTR_M3", name="Reserve Amount USD", local_name="Reserve Amount USD", remote_name="Reserve_Amount_USD", caption="Reserve Amount USD", tableau_calc="SUM([Reserve Amount USD])"),
        IRMeasure(id="m4", mstr_id="MSTR_M4", name="Claim Resolution Time Days", local_name="Claim Resolution Time Days", remote_name="Claim_Resolution_Time_Days", caption="Claim Resolution Time Days", tableau_calc="AVG([Claim Resolution Time Days])"),
        IRMeasure(id="m5", mstr_id="MSTR_M5", name="Row Count", local_name="Row Count", remote_name="Row_Count", caption="Row Count", tableau_calc="SUM([Row Count])"),
    ]
    visuals = [
        # Every visual carries the MSTR-provided bindings (canonical names
        # resolved from GUIDs during harvest) — exactly what the pipeline
        # emits for real dossiers. Shelf planning must use THESE, never the
        # English title.
        # Page 1: Executive Summary
        IRVisual(id="v1", name="Avg Resolution Days", mark_type="kpi", rows=[], columns=[],
                 page_name="Executive Summary", mstr_metrics=["Claim Resolution Time Days"], metric_ids=["MSTR_M4"]),
        IRVisual(id="v2", name="Claims Volume", mark_type="kpi", rows=[], columns=[],
                 page_name="Executive Summary", mstr_metrics=["Row Count"], metric_ids=["MSTR_M5"]),
        IRVisual(id="v3", name="Total Claims by Loss Cause", mark_type="bar_chart", rows=[], columns=[],
                 page_name="Executive Summary", mstr_metrics=["Row Count"], metric_ids=["MSTR_M5"],
                 mstr_attributes=["Loss Cause"], attribute_ids=["MSTR_D1"]),
        IRVisual(id="v4", name="Top States By Incurred", mark_type="bar_chart", rows=[], columns=[],
                 page_name="Executive Summary", mstr_metrics=["Total Incurred USD"], metric_ids=["MSTR_M1"],
                 mstr_attributes=["State Name"], attribute_ids=["MSTR_D3"]),
        IRVisual(id="v5", name="Claim Status Mix", mark_type="donut_chart", rows=[], columns=[],
                 page_name="Executive Summary", mstr_metrics=["Row Count"], metric_ids=["MSTR_M5"],
                 mstr_attributes=["Claim Status"], attribute_ids=["MSTR_D2"]),
        IRVisual(id="v6", name="Loss Trend: Monthly Claims and Incurred Amount", mark_type="combo_chart", rows=[], columns=[],
                 page_name="Executive Summary", mstr_metrics=["Row Count", "Total Incurred USD"],
                 metric_ids=["MSTR_M5", "MSTR_M1"],
                 mstr_attributes=["Reported Date"], attribute_ids=["MSTR_D4"]),

        # Page 2: Financial & Severity View
        IRVisual(id="v7", name="Paid", mark_type="kpi", rows=[], columns=[],
                 page_name="Financial & Severity View", mstr_metrics=["Paid Amount USD"], metric_ids=["MSTR_M2"]),
        IRVisual(id="v8", name="Reserve", mark_type="kpi", rows=[], columns=[],
                 page_name="Financial & Severity View", mstr_metrics=["Reserve Amount USD"], metric_ids=["MSTR_M3"]),
        IRVisual(id="v9", name="Coverage Loss Drivers", mark_type="bar_chart", rows=[], columns=[],
                 page_name="Financial & Severity View", mstr_metrics=["Total Incurred USD"], metric_ids=["MSTR_M1"],
                 mstr_attributes=["Coverage"], attribute_ids=["MSTR_D5"]),
        IRVisual(id="v10", name="Incurred loss by state", mark_type="bar_chart", rows=[], columns=[],
                 page_name="Financial & Severity View", mstr_metrics=["Total Incurred USD"], metric_ids=["MSTR_M1"],
                 mstr_attributes=["State Name"], attribute_ids=["MSTR_D3"]),
    ]
    return BIIR(job_id="test_job", dimensions=dims, measures=measures, visuals=visuals)


def test_visualization_agent_creates_page_dashboards(insurance_ir):
    agent = VisualizationAgent(ir=insurance_ir)
    viz_plan = agent.plan()

    assert len(viz_plan.worksheets) == 10
    assert len(viz_plan.dashboards) == 2

    dash_names = [d.name for d in viz_plan.dashboards]
    assert "Executive Summary" in dash_names
    assert "Financial & Severity View" in dash_names

    exec_summary = next(d for d in viz_plan.dashboards if d.name == "Executive Summary")
    assert len(exec_summary.worksheets) == 6
    assert "Avg Resolution Days" in exec_summary.worksheets
    assert "Total Claims by Loss Cause" in exec_summary.worksheets


def test_smart_shelf_assignments(insurance_ir):
    agent = VisualizationAgent(ir=insurance_ir)
    viz_plan = agent.plan()
    ws_by_name = {ws.name: ws for ws in viz_plan.worksheets}

    # 1. KPI Card: Avg Resolution Days -> text mark, measure label
    kpi_res = ws_by_name["Avg Resolution Days"]
    assert kpi_res.mark_type == "text"
    assert kpi_res.mstr_visual_type == "kpi"
    assert kpi_res.label is not None
    assert kpi_res.label.name == "Claim Resolution Time Days"

    # 2. Bar Chart: Total Claims by Loss Cause -> bar mark, Loss Cause on rows, Row Count / Incurred on columns
    bar_cause = ws_by_name["Total Claims by Loss Cause"]
    assert bar_cause.mark_type == "bar"
    assert bar_cause.mstr_visual_type == "bar_chart"
    assert len(bar_cause.rows) == 1
    assert bar_cause.rows[0].name == "Loss Cause"
    assert len(bar_cause.columns) == 1

    # 3. Bar Chart: Top States By Incurred -> State Name on rows, Total Incurred on columns
    bar_states = ws_by_name["Top States By Incurred"]
    assert bar_states.mark_type == "bar"
    assert bar_states.mstr_visual_type == "bar_chart"
    assert bar_states.rows[0].name == "State Name"
    assert bar_states.columns[0].name == "Total Incurred USD"

    # 4. Donut Chart: Claim Status Mix -> pie mark, Claim Status on color,
    #    metric on Angle/Size — and NO axis pills (a metric on Columns
    #    renders a pie as detached bubbles on an axis — job 087560ee audit).
    donut = ws_by_name["Claim Status Mix"]
    assert donut.mark_type == "pie"
    assert donut.mstr_visual_type == "donut_chart"
    assert donut.color is not None
    assert donut.color.name == "Claim Status"
    assert donut.size is not None
    assert donut.columns == []
    assert donut.rows == []

    # 5. Trend: Loss Trend -> line or bar mark, Reported Date on columns
    trend = ws_by_name["Loss Trend: Monthly Claims and Incurred Amount"]
    assert trend.mark_type in ("line", "bar")
    assert trend.mstr_visual_type == "combo_chart"
    assert any("Date" in (c.name or "") for c in trend.columns) or any("Date" in (r.name or "") for r in trend.rows)


@pytest.mark.asyncio
async def test_tableau_emitter_multi_dashboard_twb(db_session, tmp_path, insurance_ir):
    job_id = "test-viz-emitter-job"
    artifacts_dir = str(tmp_path / job_id)

    job = Job(
        id=job_id,
        name="Insurance_Dashboard",
        status="PENDING",
        mstr_base_url="https://env-test.cloud.strategy.com/MicroStrategyLibrary",
        mstr_project_id="PROJ123",
        artifacts_dir=artifacts_dir,
    )
    db_session.add(job)
    db_session.commit()

    agent = VisualizationAgent(ir=insurance_ir)
    viz_plan = agent.plan()

    emitter = TableauEmitterAgent(db=db_session, job=job, artifacts_dir=artifacts_dir)
    twbx_path = emitter.emit_workbook(
        ir=insurance_ir,
        viz_plan=viz_plan,
        hyper_paths={"default": str(tmp_path / "extract.hyper")},
        workbook_name="Insurance_Dashboard",
    )

    twb_path = tmp_path / job_id / "workbooks" / "Insurance_Dashboard" / "Insurance_Dashboard.twb"
    assert twb_path.exists()

    tree = ET.parse(twb_path)
    root = tree.getroot()

    dashboards = root.findall(".//dashboard")
    assert len(dashboards) == 2

    # Check dashboard zones
    exec_dash = next(d for d in dashboards if d.attrib.get("name") == "Executive Summary")
    zones = exec_dash.findall(".//zone[@name]")
    # Should have zones for all 6 worksheets
    assert len(zones) == 6

    # Verify windows exist for both worksheets and dashboards
    windows = root.findall(".//window")
    assert len(windows) >= 12
