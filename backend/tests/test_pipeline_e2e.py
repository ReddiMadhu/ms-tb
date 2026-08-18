import os
import json
import zipfile
from unittest.mock import AsyncMock, patch
import pytest
from app.models.job import Job
from app.models.objects import MigrationObject, Artifact
from app.services.pipeline.orchestrator import PipelineOrchestrator


@pytest.mark.asyncio
async def test_full_pipeline_produces_twbx_and_hyper(db_session, client, tmp_path):
    """
    Test the complete wired pipeline end-to-end:
    - Prepopulates discovered MSTR objects with mstr_definition in database
    - Executes PipelineOrchestrator through all 20 stages
    - Verifies Semantic extraction -> IR Compile -> Viz Planning -> Hyper Build -> TDS -> TWBX -> Validation -> Report
    - Verifies downloadable .twbx file structure and DB artifact records
    """
    job_id = "test-e2e-pipeline-job-1234"
    artifacts_dir = str(tmp_path / job_id)
    os.makedirs(artifacts_dir, exist_ok=True)

    job = Job(
        id=job_id,
        name="Sales_Performance_Dashboard",
        status="PENDING",
        mstr_base_url="https://env-test.cloud.strategy.com/MicroStrategyLibrary",
        mstr_project_id="B928FD6C7B744238BE7CEDE129051F13",
        artifacts_dir=artifacts_dir,
        auto_publish=False,
    )
    db_session.add(job)

    # 1. Attribute: Region
    attr_region = MigrationObject(
        job_id=job_id,
        mstr_id="ATTR-REGION-001",
        mstr_type=12,
        type_name="attribute",
        name="Region",
        status="discovered",
        mstr_definition={
            "id": "ATTR-REGION-001",
            "name": "Region",
            "forms": [
                {"name": "ID", "id": "FORM-ID-1", "dataType": {"type": "string"}},
                {"name": "DESC", "id": "FORM-DESC-1", "dataType": {"type": "string"}},
            ],
            "relationships": [],
        },
    )

    # 2. Attribute: Category
    attr_category = MigrationObject(
        job_id=job_id,
        mstr_id="ATTR-CAT-002",
        mstr_type=12,
        type_name="attribute",
        name="Category",
        status="discovered",
        mstr_definition={
            "id": "ATTR-CAT-002",
            "name": "Category",
            "forms": [
                {"name": "ID", "id": "FORM-ID-2", "dataType": {"type": "string"}},
                {"name": "DESC", "id": "FORM-DESC-2", "dataType": {"type": "string"}},
            ],
            "relationships": [],
        },
    )

    # 3. Metric: Total Revenue
    metric_revenue = MigrationObject(
        job_id=job_id,
        mstr_id="METRIC-REV-001",
        mstr_type=4,
        type_name="metric",
        name="Total Revenue",
        status="discovered",
        mstr_definition={
            "id": "METRIC-REV-001",
            "name": "Total Revenue",
            "expression": {
                "text": "Sum(Revenue)",
                "tree": {
                    "type": "function",
                    "function": "Sum",
                    "children": [{"type": "column", "name": "Revenue"}],
                },
            },
            "subtotalType": "SUM",
        },
    )

    # 4. Metric: Profit Margin
    metric_margin = MigrationObject(
        job_id=job_id,
        mstr_id="METRIC-MRG-002",
        mstr_type=4,
        type_name="metric",
        name="Profit Margin",
        status="discovered",
        mstr_definition={
            "id": "METRIC-MRG-002",
            "name": "Profit Margin",
            "expression": {
                "text": "Profit / Revenue",
                "tree": {
                    "type": "operator",
                    "operator": "/",
                    "children": [
                        {"type": "column", "name": "Profit"},
                        {"type": "column", "name": "Revenue"},
                    ],
                },
            },
            "subtotalType": "AVG",
        },
    )

    db_session.add_all([attr_region, attr_category, metric_revenue, metric_margin])
    db_session.commit()

    orchestrator = PipelineOrchestrator(
        job_id=job_id,
        mstr_username="demo_user",
        mstr_password="demo_password",
    )

    with patch("app.services.pipeline.orchestrator.SessionLocal", return_value=db_session):
        with patch("app.agents.discovery.DiscoveryAgent.run", new_callable=AsyncMock) as mock_discovery_run:
            mock_discovery_run.return_value = {"dossiers": 1, "total_objects": 4}

            with patch("app.services.mstr_client.session.AsyncMSTRSession.authenticate", new_callable=AsyncMock) as mock_auth:
                mock_auth.return_value = "mock_token"
                with patch("app.services.mstr_client.session.AsyncMSTRSession.close", new_callable=AsyncMock):
                    await orchestrator.run()

    # ── Assertions ──────────────────────────────────────────────────────────

    # Check job completion
    completed_job = db_session.query(Job).filter(Job.id == job_id).first()
    assert completed_job is not None
    assert completed_job.status == "COMPLETE"
    assert completed_job.structural_confidence > 0.0

    # 1. Semantic Bundle JSON was created
    bundle_file = os.path.join(artifacts_dir, "semantic_bundle.json")
    assert os.path.exists(bundle_file)
    with open(bundle_file) as f:
        bundle_data = json.load(f)
    assert len(bundle_data["dimensions"]) == 2
    assert len(bundle_data["measures"]) == 2

    # 2. IR JSON was created
    ir_file = os.path.join(artifacts_dir, "ir.json")
    assert os.path.exists(ir_file)
    with open(ir_file) as f:
        ir_data = json.load(f)
    assert len(ir_data["dimensions"]) >= 2
    assert len(ir_data["measures"]) == 2

    # 3. Viz Plan JSON was created
    viz_file = os.path.join(artifacts_dir, "viz_plan.json")
    assert os.path.exists(viz_file)

    # 4. Hyper extract file was built
    hyper_file = os.path.join(artifacts_dir, "hyper", "extract.hyper")
    assert os.path.exists(hyper_file)

    # 5. Datasource TDS was emitted
    tds_file = os.path.join(artifacts_dir, "datasources", "Migrated_DS.tds")
    assert os.path.exists(tds_file)

    # 6. Workbook TWB and TWBX were generated
    wb_dir = os.path.join(artifacts_dir, "workbooks", "Sales_Performance_Dashboard")
    twb_file = os.path.join(wb_dir, "Sales_Performance_Dashboard.twb")
    twbx_file = os.path.join(wb_dir, "Sales_Performance_Dashboard.twbx")
    assert os.path.exists(twb_file)
    assert os.path.exists(twbx_file)

    # Verify TWBX is a valid zip containing .twb and .hyper
    with zipfile.ZipFile(twbx_file, "r") as zf:
        namelist = zf.namelist()
        assert "Sales_Performance_Dashboard.twb" in namelist
        assert any("Data/Extracts" in name for name in namelist)

    # 7. Validation scorecard & report was written
    report_file = os.path.join(artifacts_dir, "migration_report.json")
    assert os.path.exists(report_file)

    # 8. Verify DB Artifact records were created
    artifacts = db_session.query(Artifact).filter(Artifact.job_id == job_id).all()
    assert len(artifacts) >= 2
    wb_artifact = next((a for a in artifacts if a.artifact_type == "workbook"), None)
    assert wb_artifact is not None
    assert wb_artifact.file_name == "Sales_Performance_Dashboard.twbx"

    # 9. Verify API download endpoint
    res = client.get(f"/api/v1/jobs/{job_id}/download/{wb_artifact.id}")
    assert res.status_code == 200
    assert len(res.content) > 0
