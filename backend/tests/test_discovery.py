"""
Tests for Discovery Agent, dossier reference extraction, and MSTR session handling.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.agents.discovery import DiscoveryAgent
from app.models.job import Job
from app.models.objects import MigrationObject
from app.services.mstr_client.session import (
    MSTRProjectIdleError,
    MSTRSession,
)


@pytest.mark.asyncio
async def test_extract_dossier_references_with_list_available_objects(db_session):
    """
    Test dossier reference extraction when MSTR returns availableObjects as a list.
    Verifies the fix for AttributeError: 'list' object has no attribute 'get'.
    """
    job = Job(
        id="test-discovery-job-1",
        name="Discovery Test",
        status="DISCOVERY",
        mstr_base_url="https://env-test.cloud.strategy.com/MicroStrategyLibrary",
        mstr_project_id="B928FD6C7B744238BE7CEDE129051F13",
    )
    db_session.add(job)
    db_session.commit()

    agent = DiscoveryAgent(
        db=db_session,
        job=job,
        mstr_username="admin",
        mstr_password="password",
    )

    # Mock AsyncMSTRSession
    mock_mstr = AsyncMock()
    mock_mstr.get_dossier_definition.return_value = {
        "id": "64A11C7D4F547708FEAD43AA022C1919",
        "name": "Executive Dashboard",
        "datasets": [
            {
                "id": "DS_CUBE_001",
                "name": "Sales Cube",
                # MSTR returns availableObjects as a list of dictionaries
                "availableObjects": [
                    {
                        "id": "ATTR_REGION_01",
                        "name": "Region",
                        "type": "attribute",
                    },
                    {
                        "id": "ATTR_CATEGORY_02",
                        "name": "Category",
                        "type": 12,
                    },
                    {
                        "id": "METRIC_REVENUE_01",
                        "name": "Total Revenue",
                        "type": "metric",
                    },
                    {
                        "id": "METRIC_PROFIT_02",
                        "name": "Net Profit",
                        "type": 4,
                    },
                ],
            }
        ],
    }

    mock_mstr.get_attribute.side_effect = lambda attr_id: {
        "id": attr_id,
        "name": f"Name for {attr_id}",
        "forms": [
            {"id": "F1", "name": "ID", "dataType": {"type": "INTEGER"}},
            {"id": "F2", "name": "DESC", "dataType": {"type": "VARCHAR"}},
        ],
    }

    mock_mstr.get_metric.side_effect = lambda metric_id: {
        "id": metric_id,
        "name": f"Name for {metric_id}",
        "expression": {"text": "Sum(Sales)"},
        "references": [{"id": "ATTR_REGION_01"}],
    }

    agent._mstr = mock_mstr

    dossier_summary = {"id": "64A11C7D4F547708FEAD43AA022C1919", "name": "Executive Dashboard"}
    objects = await agent._extract_dossier_references(dossier_summary)

    # Verify that dataset cube, attributes, and metrics were extracted without errors
    assert "DS_CUBE_001" in objects
    assert "ATTR_REGION_01" in objects
    assert "ATTR_CATEGORY_02" in objects
    assert "METRIC_REVENUE_01" in objects
    assert "METRIC_PROFIT_02" in objects

    # Verify database persistence
    saved_objects = db_session.query(MigrationObject).filter(MigrationObject.job_id == job.id).all()
    assert len(saved_objects) == 5


@pytest.mark.asyncio
async def test_extract_dossier_references_with_dict_available_objects(db_session):
    """
    Test dossier reference extraction when MSTR returns availableObjects as a dictionary.
    """
    job = Job(
        id="test-discovery-job-2",
        name="Discovery Test Dict",
        status="DISCOVERY",
        mstr_base_url="https://env-test.cloud.strategy.com/MicroStrategyLibrary",
        mstr_project_id="B928FD6C7B744238BE7CEDE129051F13",
    )
    db_session.add(job)
    db_session.commit()

    agent = DiscoveryAgent(db=db_session, job=job)
    mock_mstr = AsyncMock()
    mock_mstr.get_dossier_definition.return_value = {
        "id": "DOSSIER_DICT_01",
        "name": "Dict Format Dossier",
        "datasets": [
            {
                "id": "DS_002",
                "name": "Finance Report",
                "availableObjects": {
                    "attributes": [{"id": "ATTR_YEAR", "name": "Year"}],
                    "metrics": [{"id": "METRIC_EXPENSE", "name": "Operating Expense"}],
                },
            }
        ],
    }
    mock_mstr.get_attribute.return_value = {"id": "ATTR_YEAR", "forms": []}
    mock_mstr.get_metric.return_value = {"id": "METRIC_EXPENSE", "expression": {"text": "Sum(Expense)"}}

    agent._mstr = mock_mstr
    objects = await agent._extract_dossier_references({"id": "DOSSIER_DICT_01"})

    assert "DS_002" in objects
    assert "ATTR_YEAR" in objects
    assert "METRIC_EXPENSE" in objects


@pytest.mark.asyncio
async def test_managed_objects_fallback_extraction(db_session):
    """
    Test that when Model API calls return 400 (cube ID null) or 500 (managed metric not supported),
    the discovery agent falls back to using the dataset's embedded metadata.
    """
    job = Job(
        id="test-discovery-job-managed",
        name="Managed Objects Test",
        status="DISCOVERY",
        mstr_base_url="https://env-test.cloud.strategy.com/MicroStrategyLibrary",
        mstr_project_id="B928FD6C7B744238BE7CEDE129051F13",
    )
    db_session.add(job)
    db_session.commit()

    agent = DiscoveryAgent(db=db_session, job=job)
    mock_mstr = AsyncMock()
    mock_mstr.get_dossier_definition.return_value = {
        "id": "DOSSIER_MANAGED_01",
        "name": "Managed Objects Dossier",
        "datasets": [
            {
                "id": "DS_MANAGED_CUBE_01",
                "name": "In-Memory Dataset",
                "availableObjects": [
                    {
                        "id": "ATTR_MANAGED_01",
                        "name": "Product SKU",
                        "type": "attribute",
                    },
                    {
                        "id": "METRIC_MANAGED_01",
                        "name": "Calculated Profit Ratio",
                        "type": "metric",
                        "formula": "Profit / Revenue",
                    },
                ],
            }
        ],
    }

    # Simulate MSTR Model API throwing 400 and 500
    mock_mstr.get_attribute.side_effect = Exception("MSTR API 400: The cube ID 'null' in report is either null or invalid")
    mock_mstr.get_metric.side_effect = Exception("MSTR API 500: We do not support managed metric")

    agent._mstr = mock_mstr

    objects = await agent._extract_dossier_references({"id": "DOSSIER_MANAGED_01"})

    # Assert that all 3 objects (cube, attribute, metric) are extracted and saved via fallback
    assert "DS_MANAGED_CUBE_01" in objects
    assert "ATTR_MANAGED_01" in objects
    assert "METRIC_MANAGED_01" in objects

    attr_obj = db_session.query(MigrationObject).filter(MigrationObject.mstr_id == "ATTR_MANAGED_01").first()
    assert attr_obj is not None
    assert attr_obj.name == "Product SKU"
    assert attr_obj.dependency_ids == ["DS_MANAGED_CUBE_01"]

    metric_obj = db_session.query(MigrationObject).filter(MigrationObject.mstr_id == "METRIC_MANAGED_01").first()
    assert metric_obj is not None
    assert metric_obj.name == "Calculated Profit Ratio"
    assert metric_obj.expression_text == "Profit / Revenue"
    assert metric_obj.dependency_ids == ["DS_MANAGED_CUBE_01"]


def test_mstr_session_idle_project_detection():
    """
    Test that MSTRSession detects iServerCode -2147209151 on 404 responses
    and raises MSTRProjectIdleError.
    """
    import time

    session = MSTRSession(
        base_url="https://env-test.cloud.strategy.com/MicroStrategyLibrary",
        username="admin",
        password="pwd",
        project_id="IDLE_PROJ_123",
    )
    # Simulate already-authenticated token
    session._token = "mock-auth-token"
    session._token_acquired_at = time.monotonic()

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.json.return_value = {
        "code": "ERR001",
        "iServerCode": -2147209151,
        "message": "There are no Intelligence Servers in the cluster with the project available. The projects are idle.",
    }

    with patch.object(session._client, "request", return_value=mock_resp):
        with pytest.raises(MSTRProjectIdleError) as exc_info:
            session.search_objects(object_type=55)

        assert "idle" in str(exc_info.value).lower()
        assert exc_info.value.project_id == "IDLE_PROJ_123"


def test_validate_connection_returns_projects(client):
    """
    Test that /discovery/validate-connection calls server-level list_projects
    and returns available projects to the caller.
    """
    mock_projects = [
        {"id": "PROJ_TUTORIAL_01", "name": "MicroStrategy Tutorial", "status": 0},
        {"id": "PROJ_SALES_02", "name": "Enterprise Sales", "status": 0},
    ]

    with patch.object(MSTRSession, "authenticate", return_value="fake-token"):
        with patch.object(MSTRSession, "get_server_status", return_value={"version": "11.3.1200"}):
            with patch.object(MSTRSession, "list_projects", return_value=mock_projects):
                res = client.post(
                    "/api/v1/discovery/validate-connection",
                    json={
                        "mstr_base_url": "https://env-test.cloud.strategy.com/MicroStrategyLibrary",
                        "mstr_username": "administrator",
                        "mstr_password": "password123",
                        "mstr_project_id": "PROJ_TUTORIAL_01",
                    },
                )
                assert res.status_code == 200
                body = res.json()
                assert body["valid"] is True
                assert body["project_name"] == "MicroStrategy Tutorial"
                assert body["server_version"] == "11.3.1200"
                assert len(body["projects"]) == 2
                assert body["projects"][0]["id"] == "PROJ_TUTORIAL_01"
