"""
Tests for Job API endpoints and Job execution model.
"""

from unittest.mock import patch
import pytest

from app.models.job import Job


def test_create_job_with_optional_tableau(client, db_session):
    """
    Test creating a job when tableau_server_url and tableau_token are omitted (download-only mode).
    Verifies that the nullable schema fix prevents SQL IntegrityError.
    """
    payload = {
        "name": "Test Migration Job - Download Only",
        "mstr_base_url": "https://env-test.cloud.strategy.com/MicroStrategyLibrary",
        "mstr_username": "administrator",
        "mstr_password": "testpassword123",
        "mstr_project_id": "B928FD6C7B744238BE7CEDE129051F13",
        "tableau_server_url": None,
        "tableau_site_id": "default",
        "tableau_target_project": "Migrated Dashboards",
        "template_version": "2024.2",
        "skip_unused": True,
        "extract_data": True,
        "auto_publish": False,
        "publish_mode": "partial",
        "numeric_threshold": 0.98,
    }

    with patch("app.api.v1.jobs.run_pipeline") as mock_run_pipeline:
        response = client.post("/api/v1/jobs", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == payload["name"]
        assert data["status"] == "PENDING"
        assert data["id"] is not None

        # Verify job was persisted in database with null tableau_server_url
        job = db_session.query(Job).filter(Job.id == data["id"]).first()
        assert job is not None
        assert job.name == payload["name"]
        assert job.tableau_server_url is None or job.tableau_server_url == ""

        # Verify background task was queued with credentials
        mock_run_pipeline.assert_called_once()
        call_kwargs = mock_run_pipeline.call_args.kwargs
        assert call_kwargs.get("mstr_username") == "administrator"
        assert call_kwargs.get("mstr_password") == "testpassword123"


def test_get_and_list_jobs(client, db_session):
    """Test retrieving job status and listing jobs."""
    # Create sample job directly in DB
    job = Job(
        id="test-job-uuid-1234",
        name="Sales Analytics Migration",
        status="RUNNING",
        mstr_base_url="https://env-test.cloud.strategy.com/MicroStrategyLibrary",
        mstr_project_id="B928FD6C7B744238BE7CEDE129051F13",
        tableau_server_url="",
        tableau_site_id="default",
    )
    db_session.add(job)
    db_session.commit()

    # Get single job
    res = client.get("/api/v1/jobs/test-job-uuid-1234")
    assert res.status_code == 200
    assert res.json()["name"] == "Sales Analytics Migration"
    assert res.json()["status"] == "RUNNING"

    # List jobs
    list_res = client.get("/api/v1/jobs")
    assert list_res.status_code == 200
    assert list_res.json()["total"] >= 1
    assert any(j["id"] == "test-job-uuid-1234" for j in list_res.json()["jobs"])


def test_cancel_job(client, db_session):
    """Test cancelling an in-progress job."""
    job = Job(
        id="test-cancel-uuid-5678",
        name="Cancellable Job",
        status="RUNNING",
        mstr_base_url="https://env-test.cloud.strategy.com/MicroStrategyLibrary",
        mstr_project_id="B928FD6C7B744238BE7CEDE129051F13",
    )
    db_session.add(job)
    db_session.commit()

    res = client.post("/api/v1/jobs/test-cancel-uuid-5678/cancel")
    assert res.status_code == 200
    assert res.json()["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_pipeline_orchestrator_execution(db_session):
    """
    Test running the PipelineOrchestrator through all stages with mocked discovery.
    Verifies state transitions from PENDING -> DISCOVERY -> COMPLETE.
    """
    from unittest.mock import AsyncMock, patch
    from app.services.pipeline.orchestrator import PipelineOrchestrator

    job = Job(
        id="test-pipeline-orchestrator-uuid",
        name="End-to-End Test Job",
        status="PENDING",
        mstr_base_url="https://env-test.cloud.strategy.com/MicroStrategyLibrary",
        mstr_project_id="B928FD6C7B744238BE7CEDE129051F13",
        auto_publish=True,
    )
    db_session.add(job)
    db_session.commit()

    orchestrator = PipelineOrchestrator(
        job_id="test-pipeline-orchestrator-uuid",
        mstr_username="test_user",
        mstr_password="test_password",
    )

    with patch("app.services.pipeline.orchestrator.SessionLocal", return_value=db_session):
        with patch("app.agents.discovery.DiscoveryAgent.run", new_callable=AsyncMock) as mock_discovery_run:
            mock_discovery_run.return_value = {"dossiers": 1, "total_objects": 4}

            await orchestrator.run()

            # Verify job completed successfully
            completed_job = db_session.query(Job).filter(Job.id == "test-pipeline-orchestrator-uuid").first()
            assert completed_job is not None
            assert completed_job.status == "COMPLETE"
            assert completed_job.started_at is not None
            assert completed_job.completed_at is not None
            assert completed_job.checkpoint_stage == "REPORT"
