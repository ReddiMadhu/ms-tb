import xml.etree.ElementTree as ET
import pytest
from app.models.job import Job
from app.agents.tableau_emitter import TableauEmitterAgent
from app.agents.visualization import VizPlan, WorksheetSpec, DashboardSpec, FieldRef


@pytest.fixture
def mock_ir():
    class DummyDim:
        def __init__(self, mstr_id, caption, local_name, data_type="string", role="dimension", remote_name=None, hidden=False):
            self.mstr_id = mstr_id
            self.caption = caption
            self.local_name = local_name
            self.data_type = data_type
            self.role = role
            self.remote_name = remote_name
            self.hidden = hidden

    class DummyMeasure:
        def __init__(self, mstr_id, caption, local_name, tableau_calc, dependencies=None, remote_name=None):
            self.mstr_id = mstr_id
            self.caption = caption
            self.local_name = local_name
            self.tableau_calc = tableau_calc
            self.dependencies = dependencies or []
            self.remote_name = remote_name

    class DummyTable:
        def __init__(self, physical_name):
            self.name = physical_name
            self.physical_name = physical_name

    class DummyIR:
        def __init__(self):
            self.dimensions = [
                DummyDim("dim1", "Region", "Region", remote_name="region_col"),
                DummyDim("dim2", "Category", "Category"),
            ]
            self.measures = [
                DummyMeasure("m1", "Total Sales", "Total_Sales", "SUM([Sales])", remote_name="sales_col"),
            ]
            self.tables = [DummyTable("fact_sales")]
            self.relationships = []

    return DummyIR()


@pytest.mark.asyncio
async def test_tableau_emitter_xml_structure(db_session, tmp_path, mock_ir):
    job_id = "test-emitter-xml-job"
    artifacts_dir = str(tmp_path / job_id)

    job = Job(
        id=job_id,
        name="T_prod",
        status="PENDING",
        mstr_base_url="https://mstr.example.com/MicroStrategyLibrary",
        mstr_project_id="PROJ12345",
        artifacts_dir=artifacts_dir,
    )
    db_session.add(job)
    db_session.commit()

    emitter = TableauEmitterAgent(db=db_session, job=job, artifacts_dir=artifacts_dir)

    viz_plan = VizPlan(
        worksheets=[
            WorksheetSpec(
                id="ws-1",
                name="Sales Sheet",
                datasource_ref="federated.default",
                mark_type="bar",
                rows=[FieldRef(name="Region", field_type="dimension")],
                columns=[FieldRef(name="Total_Sales", field_type="measure")],
            )
        ],
        dashboards=[
            DashboardSpec(
                id="dash-1",
                name="Executive Dashboard",
                worksheets=["Sales Sheet"],
            )
        ],
    )

    hyper_paths = {"fact_sales": str(tmp_path / "sales.hyper")}

    twbx_path = emitter.emit_workbook(
        ir=mock_ir,
        viz_plan=viz_plan,
        hyper_paths=hyper_paths,
        workbook_name="T_prod",
    )

    twb_path = tmp_path / job_id / "workbooks" / "T_prod" / "T_prod.twb"
    assert twb_path.exists()

    # Parse generated TWB XML
    tree = ET.parse(twb_path)
    root = tree.getroot()

    # 1. Assert root tag and child order (<preferences> present)
    assert root.tag == "workbook"
    child_tags = [child.tag for child in root]
    assert "preferences" in child_tags
    assert "datasources" in child_tags
    assert "worksheets" in child_tags
    assert "dashboards" in child_tags
    assert "windows" in child_tags

    # 2. Assert <column> elements do NOT contain invalid 'remote-name' attribute
    for col in root.findall(".//column"):
        assert "remote-name" not in col.attrib, f"Found remote-name on column {col.attrib}"

    # 3. Assert <table> content model sequence inside <worksheet>
    worksheet = root.find(".//worksheet")
    assert worksheet is not None
    table = worksheet.find("table")
    assert table is not None

    table_children = [c.tag for c in table]
    # Required order: view, style, panes, rows, cols
    assert table_children[:5] == ["view", "style", "panes", "rows", "cols"]

    # 4. Assert <mark> is inside <pane>, NOT <view>
    view = table.find("view")
    assert view.find("mark") is None, "<mark> element found illegally inside <view>"
    pane = table.find("./panes/pane")
    assert pane is not None
    mark = pane.find("mark")
    assert mark is not None
    assert mark.attrib.get("class") == "Bar"

    # 5. Assert <window> elements contain valid children (<cards> or <viewpoints>)
    windows = root.findall(".//window")
    assert len(windows) >= 2
    for win in windows:
        if win.attrib.get("class") == "worksheet":
            assert win.find("cards") is not None, "Worksheet window missing required <cards> child"
        elif win.attrib.get("class") == "dashboard":
            assert win.find("viewpoints") is not None, "Dashboard window missing required <viewpoints> child"
