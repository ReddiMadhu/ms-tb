"""
Unit & integration tests for Calculated Field static validation and re-emission.
"""

import json
import os
import shutil
import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.job import Job
from app.models.objects import MigrationObject, ReviewTask
from app.services.pipeline.cf_reemit_service import (
    validate_static_formula,
    reemit_calculated_field,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_validate_static_formula_valid_cases():
    # 1. User specific target formula: High Fraud Count / Flag
    calc1 = "SUM(IF ([Fraud Score] >= 70) THEN 1 ELSE 0 END)"
    is_valid, checks, msg = validate_static_formula(calc1)
    assert is_valid is True
    assert all(c["status"] == "passed" for c in checks)

    # 2. LOD Fixed expression
    calc2 = "{FIXED [Region], [Category] : SUM([Profit]) / SUM([Sales])}"
    is_valid, checks, msg = validate_static_formula(calc2)
    assert is_valid is True

    # 3. Simple aggregation
    calc3 = "AVG([Fraud Score])"
    is_valid, checks, msg = validate_static_formula(calc3)
    assert is_valid is True


def test_validate_static_formula_invalid_cases():
    # 1. Unmatched bracket
    calc_unmatched = "SUM(IF [Fraud Score >= 70 THEN 1 ELSE 0 END)"
    is_valid, checks, msg = validate_static_formula(calc_unmatched)
    assert is_valid is False
    assert "Unmatched brackets" in msg

    # 2. Unmatched parenthesis
    calc_paren = "SUM(IF ([Fraud Score] >= 70 THEN 1 ELSE 0 END)"
    is_valid, checks, msg = validate_static_formula(calc_paren)
    assert is_valid is False

    # 3. Missing END in IF statement
    calc_if = "IF [Fraud Score] >= 70 THEN 1 ELSE 0"
    is_valid, checks, msg = validate_static_formula(calc_if)
    assert is_valid is False
    assert "missing" in msg.lower()

    # 4. Illegal nested aggregation
    calc_nested = "SUM(SUM([Revenue]))"
    is_valid, checks, msg = validate_static_formula(calc_nested)
    assert is_valid is False
    assert "nested aggregation" in msg.lower()


@pytest.mark.anyio
async def test_reemit_calculated_field_workflow(db_session):
    job_id = f"test-{uuid.uuid4().hex[:8]}"
    # Explicit workspace-local temp dir (tempfile.mkdtemp's restricted ACLs
    # trip sandboxed filesystems; makedirs is equivalent and portable).
    base_tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".cf-test-tmp")
    os.makedirs(base_tmp, exist_ok=True)
    tmp_dir = os.path.join(base_tmp, uuid.uuid4().hex)
    os.makedirs(tmp_dir)
    try:
        # Create Job
        job = Job(
            id=job_id,
            name="Fraud Analysis Migration",
            status="STAGING",
            mstr_base_url="https://mock.mstr/MicroStrategyLibrary",
            mstr_project_id="P123",
            artifacts_dir=tmp_dir,
        )
        db_session.add(job)

        # Create MigrationObject for High Fraud Claims
        obj = MigrationObject(
            id="obj-hf-01",
            job_id=job_id,
            mstr_id="MSTR-HF-001",
            mstr_type=4,
            type_name="metric",
            name="High Fraud Claims",
            expression_text="Sum<UseLookupForAttributes=False >([High Fraud Flag]){~+}",
            tableau_calc="SUM(IF INT([Fraud Score]) >= 70 THEN 1 ELSE 0 END)",
            confidence=0.80,
            status="pending_review",
        )
        db_session.add(obj)

        # Create ReviewTask
        task = ReviewTask(
            id="task-hf-01",
            job_id=job_id,
            object_id="MSTR-HF-001",
            severity="warning",
            reason="LOD / derived attribute expansion requires verification",
            mstr_expression="Sum<UseLookupForAttributes=False >([High Fraud Flag]){~+}",
            generated_calc="SUM(IF INT([Fraud Score]) >= 70 THEN 1 ELSE 0 END)",
            confidence=0.80,
            status="pending",
        )
        db_session.add(task)
        db_session.commit()

        # Create dummy ir.json in artifacts dir
        ir_payload = {
            "job_id": job_id,
            "tables": [],
            "relationships": [],
            "dimensions": [{"name": "Fraud Score", "data_type": "integer"}],
            "measures": [{
                "id": "m-hf-01",
                "mstr_id": "MSTR-HF-001",
                "name": "High Fraud Claims",
                "caption": "High Fraud Claims",
                "tableau_calc": "SUM(IF INT([Fraud Score]) >= 70 THEN 1 ELSE 0 END)",
                "confidence": 0.80,
            }],
            "filters": [],
            "visuals": [],
            "issues": [],
        }
        with open(os.path.join(tmp_dir, "ir.json"), "w", encoding="utf-8") as f:
            json.dump(ir_payload, f)

        # Re-emit with edited formula
        new_calc = "SUM(IF ([Fraud Score] >= 70) THEN 1 ELSE 0 END)"
        result = await reemit_calculated_field(
            db=db_session,
            job_id=job_id,
            calc_id="MSTR-HF-001",
            new_calc=new_calc,
            notes="Edited threshold formula verified against MSTR ground truth",
        )

        assert result["success"] is True
        assert result["validation_passed"] is True
        assert result["updated_calc"] == new_calc
        assert len(result["steps"]) == 4
        assert all(s["status"] == "completed" for s in result["steps"])

        # Verify DB object updated
        db_session.refresh(obj)
        assert obj.tableau_calc == new_calc
        assert obj.confidence == 0.99
        assert obj.status == "valid"

        # Verify task approved
        db_session.refresh(task)
        assert task.status == "approved"
        assert task.generated_calc == new_calc

        # Verify ir.json updated
        with open(os.path.join(tmp_dir, "ir.json"), "r", encoding="utf-8") as f:
            updated_ir = json.load(f)
        assert updated_ir["measures"][0]["tableau_calc"] == new_calc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
