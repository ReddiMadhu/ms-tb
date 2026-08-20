"""
test_semantic_managed_metrics.py — ADR-032

End-to-end + unit tests for the managed metric fix.

Pipeline flow under test:
  INPUT  : File-based MSTR cube (.xlsx import) -> discovery returns
             {id, name, type:'metric'} stubs (no expression)
  AGENT 1: SemanticAgent detects stub, skips /api/model/metrics/{id},
             derives tableau_calc = SUM([MetricName]) from subtotalType
  AGENT 2: IRCompilerAgent uses precomputed_calc fast-path
  OUTPUT : semantic_bundle.json (expression_text != null, confidence >= 0.85)
           ir.json (tableau_calc = "SUM([Name])" for each metric)
           TWBX artifact downloadable via /api/v1/jobs/{id}/download/{aid}

Checkpoints:
  [1] _is_managed_metric correctly classifies stubs vs schema metrics
  [2] SUBTOTAL_TO_TABLEAU maps each subtotalType to correct Tableau syntax
  [3] _build_managed_metric_def produces correct MeasureDef (precomputed_calc)
  [4] _extract_metric skips Model API for managed metrics (0 HTTP 500 errors)
  [5] HTTP 500 8004d72a runtime fallback also works
  [6] SemanticAgent.run() bundle has 8 measures, non-null expressions
  [7] IRCompiler fast-path returns precomputed_calc directly
  [8] Full pipeline E2E: COMPLETE status, correct artifacts, API download 200
  [9] Regression: schema metrics still call Model API (unaffected by fix)
"""

import json
import os
import uuid
import zipfile
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.ir_compiler import IRCompilerAgent
from app.agents.semantic import (
    MANAGED_METRIC_SUBTYPES,
    SUBTOTAL_TO_TABLEAU,
    MeasureDef,
    SemanticAgent,
)
from app.models.job import Job
from app.models.objects import Artifact, MigrationObject
from app.services.mstr_client.session import MSTRAPIError


# ──────────────────────────────────────────────────────────────────
#  REAL TEST DATA — from job fcba2981-aed0-44bb-9e84-532688feae98
# ──────────────────────────────────────────────────────────────────

PROJECT_ID = "B928FD6C7B744238BE7CEDE129051F13"

REAL_MANAGED_METRICS = [
    ("4EC0DE38274C531488F2C599CD15D3E1", "Total Incurred USD"),
    ("58601298AE4B0401E6CE07BDE28A7CB1", "Subrogation"),
    ("6D9DCA083D42498C088DF19445ED916F",
     "Row Count - MSTR_PC_Claims_Sample_Data_500K_With_Resolution_Time.xlsx"),
    ("85E015CDC44A3CD76E5C67BC3DD35EF7", "Recovery Amount USD"),
    ("873B00E9A64D31054FFED194945AB124", "Salvage"),
    ("9DCE7F2B0B455418DDC5D4B980B6BC03", "Claim Resolution Time Days"),
    ("CE0863496E43CA3894ABBBAA783EE2F4", "Paid Amount USD"),
    ("F90C4616E94FFE75FA102BAE4C870139", "Reserve Amount USD"),
]

REAL_MANAGED_ATTRIBUTES = [
    ("ATTR-LOSS-CAUSE-001", "Loss Cause"),
    ("ATTR-CLAIM-STATUS-002", "Claim Status"),
    ("ATTR-POLICY-TYPE-003", "Policy Type"),
    ("ATTR-STATE-004", "State"),
]


# ──────────────────────────────────────────────────────────────────
#  HELPERS
# ──────────────────────────────────────────────────────────────────

def _managed_stub(mstr_id: str, name: str) -> dict:
    """Exact dict MSTR returns in cube availableObjects for managed metrics."""
    return {"id": mstr_id, "name": name, "type": "metric"}


def _schema_metric_def(mstr_id: str, name: str, expr: str) -> dict:
    """Full schema metric as returned by /api/model/metrics/{id}."""
    return {
        "id": mstr_id, "name": name, "subType": "metric",
        "expression": {"text": expr, "tree": None},
        "subtotalType": "SUM", "dataType": {"type": "DOUBLE"},
    }


def _attr_def(mstr_id: str, name: str) -> dict:
    return {
        "id": mstr_id, "name": name,
        "forms": [
            {"name": "ID", "id": "F1", "dataType": {"type": "string"}},
            {"name": "DESC", "id": "F2", "dataType": {"type": "string"}},
        ],
        "relationships": [],
    }


def _seed_metric(db_session, job, mstr_id, name, defn):
    obj = MigrationObject(
        id=str(uuid.uuid4()), job_id=job.id,
        mstr_id=mstr_id, mstr_type=4, type_name="metric",
        name=name, status="discovered", mstr_definition=defn,
    )
    db_session.add(obj)
    db_session.commit()
    return obj


def _seed_all(db_session, job):
    for mid, name in REAL_MANAGED_METRICS:
        _seed_metric(db_session, job, mid, name, _managed_stub(mid, name))
    for mid, name in REAL_MANAGED_ATTRIBUTES:
        obj = MigrationObject(
            id=str(uuid.uuid4()), job_id=job.id,
            mstr_id=mid, mstr_type=12, type_name="attribute",
            name=name, status="discovered", mstr_definition=_attr_def(mid, name),
        )
        db_session.add(obj)
    db_session.commit()


# ──────────────────────────────────────────────────────────────────
#  FIXTURES
# ──────────────────────────────────────────────────────────────────

@pytest.fixture
def insurance_job(db_session) -> Job:
    job_id = f"test-ins-{uuid.uuid4().hex[:8]}"
    job = Job(
        id=job_id, name="PC_Claims_Insurance_Dashboard", status="PENDING",
        mstr_base_url="https://env-oerj65cpma7xdo0a.cloud.strategy.com/MicroStrategyLibrary",
        mstr_project_id=PROJECT_ID,
        artifacts_dir=f"/tmp/art/{job_id}", auto_publish=False,
    )
    db_session.add(job)
    db_session.commit()
    return job


# ──────────────────────────────────────────────────────────────────
#  [1] _is_managed_metric DETECTION
# ──────────────────────────────────────────────────────────────────

class TestManagedMetricDetection:
    """SemanticAgent._is_managed_metric() classification tests."""

    def test_all_8_real_metric_stubs_detected(self):
        """All 8 stubs from job fcba2981 must be detected as managed."""
        for mid, name in REAL_MANAGED_METRICS:
            stub = _managed_stub(mid, name)
            assert SemanticAgent._is_managed_metric(stub), (
                f"Failed for {name!r}: {stub}"
            )

    def test_schema_metric_with_expression_not_managed(self):
        schema = _schema_metric_def("M1", "Net Revenue", "Sum(Revenue)")
        assert not SemanticAgent._is_managed_metric(schema)

    def test_managed_true_flag(self):
        assert SemanticAgent._is_managed_metric({"id": "X", "name": "Y", "managed": True})

    def test_is_managed_true_flag(self):
        assert SemanticAgent._is_managed_metric({"id": "X", "name": "Y", "isManaged": True})

    def test_managed_subtype_values(self):
        for st in MANAGED_METRIC_SUBTYPES:
            assert SemanticAgent._is_managed_metric({"id": "X", "name": "Y", "subType": st})

    def test_empty_dict_false(self):
        assert not SemanticAgent._is_managed_metric({})

    def test_none_false(self):
        assert not SemanticAgent._is_managed_metric(None)  # type: ignore

    def test_metric_with_formula_not_stub(self):
        d = {"id": "X", "name": "Y", "type": "metric", "formula": "A/B"}
        assert not SemanticAgent._is_managed_metric(d)

    def test_attribute_stub_false(self):
        assert not SemanticAgent._is_managed_metric(
            {"id": "A1", "name": "Region", "type": "attribute"}
        )

    def test_filter_stub_false(self):
        assert not SemanticAgent._is_managed_metric(
            {"id": "F1", "name": "Active", "type": "filter"}
        )


# ──────────────────────────────────────────────────────────────────
#  [2] SUBTOTAL_TO_TABLEAU MAPPING
# ──────────────────────────────────────────────────────────────────

class TestSubtotalMapping:

    @pytest.mark.parametrize("st,expected", [
        ("SUM",    "SUM([Total Incurred USD])"),
        ("AVG",    "AVG([Total Incurred USD])"),
        ("COUNT",  "COUNT([Total Incurred USD])"),
        ("CNTD",   "COUNTD([Total Incurred USD])"),
        ("MIN",    "MIN([Total Incurred USD])"),
        ("MAX",    "MAX([Total Incurred USD])"),
        ("MEDIAN", "MEDIAN([Total Incurred USD])"),
        ("STDEV",  "STDEV([Total Incurred USD])"),
        ("VAR",    "VAR([Total Incurred USD])"),
        ("FIRST",  "MIN([Total Incurred USD])"),
        ("LAST",   "MAX([Total Incurred USD])"),
        ("NONE",   "[Total Incurred USD]"),
    ])
    def test_subtotal(self, st, expected):
        result = SUBTOTAL_TO_TABLEAU[st].format(name="Total Incurred USD")
        assert result == expected

    def test_unknown_falls_back_to_sum(self):
        tmpl = SUBTOTAL_TO_TABLEAU.get("UNKNOWN", "SUM([{name}])")
        assert tmpl.format(name="X") == "SUM([X])"

    def test_8_real_stubs_default_sum(self):
        for _, name in REAL_MANAGED_METRICS:
            st = str(_managed_stub("X", name).get("subtotalType", "SUM") or "SUM").upper()
            calc = SUBTOTAL_TO_TABLEAU.get(st, "SUM([{name}])").format(name=name)
            assert calc == f"SUM([{name}])"


# ──────────────────────────────────────────────────────────────────
#  [3] _build_managed_metric_def OUTPUT
# ──────────────────────────────────────────────────────────────────

class TestBuildManagedMetricDef:

    @pytest.fixture
    def agent(self, db_session, insurance_job):
        return SemanticAgent(db=db_session, job=insurance_job, mstr=AsyncMock())

    def test_returns_measure_def(self, agent, db_session, insurance_job):
        mid, name = REAL_MANAGED_METRICS[0]
        obj = _seed_metric(db_session, insurance_job, mid, name, _managed_stub(mid, name))
        result = agent._build_managed_metric_def(obj, _managed_stub(mid, name))
        assert isinstance(result, MeasureDef)
        assert result.mstr_id == mid and result.name == name and not result.blocked

    def test_confidence_085(self, agent, db_session, insurance_job):
        mid, name = REAL_MANAGED_METRICS[0]
        obj = _seed_metric(db_session, insurance_job, mid, name, _managed_stub(mid, name))
        result = agent._build_managed_metric_def(obj, _managed_stub(mid, name))
        assert result.confidence == 0.85

    def test_expression_text_not_none(self, agent, db_session, insurance_job):
        mid, name = REAL_MANAGED_METRICS[0]
        obj = _seed_metric(db_session, insurance_job, mid, name, _managed_stub(mid, name))
        result = agent._build_managed_metric_def(obj, _managed_stub(mid, name))
        assert result.expression_text is not None
        assert "SUM" in result.expression_text.upper()

    def test_precomputed_calc_all_metrics(self, agent, db_session, insurance_job):
        for mid, name in REAL_MANAGED_METRICS:
            obj = _seed_metric(db_session, insurance_job, mid, name, _managed_stub(mid, name))
            result = agent._build_managed_metric_def(obj, _managed_stub(mid, name))
            assert result.precomputed_calc == f"SUM([{name}])", (
                f"{name!r}: got {result.precomputed_calc!r}"
            )

    def test_explicit_count_subtotal(self, agent, db_session, insurance_job):
        mid, name = REAL_MANAGED_METRICS[2]
        stub = {**_managed_stub(mid, name), "subtotalType": "COUNT"}
        obj = _seed_metric(db_session, insurance_job, mid, name, stub)
        result = agent._build_managed_metric_def(obj, stub)
        assert result.subtotal_type == "COUNT"
        assert result.precomputed_calc == f"COUNT([{name}])"

    def test_expression_ast_is_none(self, agent, db_session, insurance_job):
        mid, name = REAL_MANAGED_METRICS[0]
        obj = _seed_metric(db_session, insurance_job, mid, name, _managed_stub(mid, name))
        result = agent._build_managed_metric_def(obj, _managed_stub(mid, name))
        assert result.expression_ast is None


# ──────────────────────────────────────────────────────────────────
#  [4+5] _extract_metric MANAGED PATH + 500 FALLBACK
# ──────────────────────────────────────────────────────────────────

class TestExtractMetricManagedPath:

    @pytest.mark.asyncio
    async def test_managed_skips_model_api(self, db_session, insurance_job):
        """CRITICAL: get_metric must NEVER be called for managed stubs."""
        mock = AsyncMock()
        agent = SemanticAgent(db=db_session, job=insurance_job, mstr=mock)
        mid, name = REAL_MANAGED_METRICS[0]
        obj = _seed_metric(db_session, insurance_job, mid, name, _managed_stub(mid, name))

        result = await agent._extract_metric(obj)

        mock.get_metric.assert_not_called()
        assert result.confidence == 0.85
        assert result.precomputed_calc == f"SUM([{name}])"
        assert not result.blocked

    @pytest.mark.asyncio
    async def test_all_8_zero_api_calls(self, db_session, insurance_job):
        mock = AsyncMock()
        agent = SemanticAgent(db=db_session, job=insurance_job, mstr=mock)

        for mid, name in REAL_MANAGED_METRICS:
            obj = _seed_metric(db_session, insurance_job, mid, name, _managed_stub(mid, name))
            result = await agent._extract_metric(obj)
            assert result.precomputed_calc == f"SUM([{name}])"
            assert result.confidence == 0.85

        mock.get_metric.assert_not_called()

    @pytest.mark.asyncio
    async def test_http500_8004d72a_runtime_fallback(self, db_session, insurance_job):
        """Edge case: schema-looking metric that still 500s at runtime."""
        mock = AsyncMock()
        mock.get_metric.side_effect = MSTRAPIError(
            500,
            '{"errors":[{"code":"8004d72a","message":"We do not support managed metric."}]}',
            "/api/model/metrics/EDGE-001",
        )
        partial = {"id": "EDGE-001", "name": "Edge Metric", "type": "metric",
                   "subType": "schema_metric"}
        agent = SemanticAgent(db=db_session, job=insurance_job, mstr=mock)
        obj = _seed_metric(db_session, insurance_job, "EDGE-001", "Edge Metric", partial)
        result = await agent._extract_metric(obj)

        assert result is not None
        assert not result.blocked
        assert result.precomputed_calc is not None

    @pytest.mark.asyncio
    async def test_schema_metric_calls_model_api(self, db_session, insurance_job):
        mock = AsyncMock()
        schema_def = _schema_metric_def("S001", "Net Revenue", "Sum(Revenue)")
        mock.get_metric.return_value = schema_def

        agent = SemanticAgent(db=db_session, job=insurance_job, mstr=mock)
        obj = _seed_metric(db_session, insurance_job, "S001", "Net Revenue", schema_def)
        result = await agent._extract_metric(obj)

        mock.get_metric.assert_called_once_with("S001")
        assert result.expression_text == "Sum(Revenue)"


# ──────────────────────────────────────────────────────────────────
#  [6] SemanticAgent.run() BUNDLE OUTPUT
# ──────────────────────────────────────────────────────────────────

class TestSemanticRunBundle:

    @pytest.mark.asyncio
    async def test_8_measures_non_null_expression(self, db_session, insurance_job):
        _seed_all(db_session, insurance_job)
        mock = AsyncMock()
        mock.get_metric.side_effect = MSTRAPIError(500, "8004d72a", "/test")

        agent = SemanticAgent(db=db_session, job=insurance_job, mstr=mock)
        all_ids = [mid for mid, _ in REAL_MANAGED_METRICS + REAL_MANAGED_ATTRIBUTES]
        bundle = await agent.run(all_ids)

        assert len(bundle.measures) == 8
        for m in bundle.measures:
            assert m.expression_text is not None, f"{m.name!r}: expression_text=None"
            assert m.confidence >= 0.85, f"{m.name!r}: confidence={m.confidence}"
            assert not m.blocked

        mock.get_metric.assert_not_called()

    @pytest.mark.asyncio
    async def test_4_dimensions(self, db_session, insurance_job):
        _seed_all(db_session, insurance_job)
        mock = AsyncMock()
        mock.get_metric.side_effect = MSTRAPIError(500, "managed", "/test")

        agent = SemanticAgent(db=db_session, job=insurance_job, mstr=mock)
        all_ids = [mid for mid, _ in REAL_MANAGED_METRICS + REAL_MANAGED_ATTRIBUTES]
        bundle = await agent.run(all_ids)

        assert len(bundle.dimensions) == 4


# ──────────────────────────────────────────────────────────────────
#  [7] IRCompiler FAST PATH
# ──────────────────────────────────────────────────────────────────

class TestIRCompilerFastPath:

    def _m(self, name, precomputed=None, expr_text=None, ast=None):
        return MeasureDef(
            mstr_id=f"M-{name}", name=name,
            expression_ast=ast, expression_text=expr_text,
            precomputed_calc=precomputed,
            subtotal_type="SUM", confidence=0.85, blocked=False,
        )

    def test_precomputed_used_directly(self, db_session, insurance_job):
        c = IRCompilerAgent(db=db_session, job=insurance_job)
        m = self._m("Total Incurred USD", precomputed="SUM([Total Incurred USD])")
        assert c._compile_expression(m, "propagate", "null") == "SUM([Total Incurred USD])"

    def test_precomputed_beats_expr_text(self, db_session, insurance_job):
        c = IRCompilerAgent(db=db_session, job=insurance_job)
        m = self._m("Salvage", precomputed="SUM([Salvage])", expr_text="SUM(Salvage)")
        assert c._compile_expression(m, "propagate", "null") == "SUM([Salvage])"

    def test_all_8_calcs(self, db_session, insurance_job):
        c = IRCompilerAgent(db=db_session, job=insurance_job)
        for _, name in REAL_MANAGED_METRICS:
            expected = f"SUM([{name}])"
            m = self._m(name, precomputed=expected)
            assert c._compile_expression(m, "propagate", "null") == expected

    def test_no_precomputed_uses_ast(self, db_session, insurance_job):
        c = IRCompilerAgent(db=db_session, job=insurance_job)
        m = self._m("Revenue", ast={
            "type": "function", "function": "Sum",
            "children": [{"type": "column", "name": "Revenue"}],
        })
        assert "SUM" in c._compile_expression(m, "propagate", "null").upper()

    def test_no_anything_falls_to_sum(self, db_session, insurance_job):
        c = IRCompilerAgent(db=db_session, job=insurance_job)
        m = self._m("Paid Amount USD")
        assert c._compile_expression(m, "propagate", "null") == "SUM([Paid Amount USD])"


# ──────────────────────────────────────────────────────────────────
#  [8] FULL E2E PIPELINE TEST
# ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_pipeline_managed_insurance_cube(db_session, client, tmp_path):
    """
    End-to-end pipeline test for the insurance claims cube.

    Simulates the exact scenario that caused 8x HTTP 500 errors.
    Validates all 10 checkpoints from input to API download.

    Before fix: 8x HTTP 500 (8004d72a), null expressions, broken workbook
    After fix : 0 HTTP errors, SUM([Name]) calcs, valid TWBX, 200 on download
    """
    from app.services.pipeline.orchestrator import PipelineOrchestrator

    job_id = f"test-e2e-{uuid.uuid4().hex[:8]}"
    art_dir = str(tmp_path / job_id)
    os.makedirs(art_dir, exist_ok=True)

    job = Job(
        id=job_id, name="PC_Claims_Insurance_Dashboard", status="PENDING",
        mstr_base_url="https://env-oerj65cpma7xdo0a.cloud.strategy.com/MicroStrategyLibrary",
        mstr_project_id=PROJECT_ID,
        artifacts_dir=art_dir, auto_publish=False,
    )
    db_session.add(job)

    for mid, name in REAL_MANAGED_METRICS:
        db_session.add(MigrationObject(
            id=str(uuid.uuid4()), job_id=job_id,
            mstr_id=mid, mstr_type=4, type_name="metric",
            name=name, status="discovered", mstr_definition=_managed_stub(mid, name),
        ))

    for mid, name in REAL_MANAGED_ATTRIBUTES:
        db_session.add(MigrationObject(
            id=str(uuid.uuid4()), job_id=job_id,
            mstr_id=mid, mstr_type=12, type_name="attribute",
            name=name, status="discovered", mstr_definition=_attr_def(mid, name),
        ))

    db_session.commit()

    orch = PipelineOrchestrator(
        job_id=job_id, mstr_username="demo", mstr_password="demo"
    )

    with patch("app.services.pipeline.orchestrator.SessionLocal", return_value=db_session):
        with patch("app.agents.discovery.DiscoveryAgent.run", new_callable=AsyncMock,
                   return_value={"dossiers": 1, "total_objects": 12}):
            with patch("app.services.mstr_client.session.AsyncMSTRSession.authenticate",
                       new_callable=AsyncMock, return_value="tok"):
                with patch("app.services.mstr_client.session.AsyncMSTRSession.close",
                           new_callable=AsyncMock):
                    await orch.run()

    # Checkpoint 1: COMPLETE status
    done_job = db_session.query(Job).filter(Job.id == job_id).first()
    assert done_job.status == "COMPLETE"

    # Checkpoint 2: semantic_bundle.json — 8 measures, expression_text != null
    bundle_path = os.path.join(art_dir, "semantic_bundle.json")
    assert os.path.exists(bundle_path)
    with open(bundle_path) as f:
        bdata = json.load(f)
    measures = bdata.get("measures", [])
    assert len(measures) == 8
    for m in measures:
        assert m.get("expression_text") is not None, (
            f"{m['name']!r}: expression_text=null (managed metric fix failed)"
        )
        assert m.get("confidence", 0) >= 0.85

    # Checkpoint 3: ir.json — 8 measures, SUM([Name]) calcs
    ir_path = os.path.join(art_dir, "ir.json")
    assert os.path.exists(ir_path)
    with open(ir_path) as f:
        irdata = json.load(f)
    ir_measures = irdata.get("measures", [])
    assert len(ir_measures) == 8
    for irm in ir_measures:
        expected_calc = f"SUM([{irm['name']}])"
        assert irm.get("tableau_calc") == expected_calc, (
            f"{irm['name']!r}: tableau_calc={irm.get('tableau_calc')!r}"
        )

    # Checkpoint 4: Hyper extract
    assert os.path.exists(os.path.join(art_dir, "hyper", "extract.hyper"))

    # Checkpoint 5: TWBX structure
    wb_dir = os.path.join(art_dir, "workbooks", "PC_Claims_Insurance_Dashboard")
    twbx = os.path.join(wb_dir, "PC_Claims_Insurance_Dashboard.twbx")
    assert os.path.exists(twbx)
    with zipfile.ZipFile(twbx) as zf:
        names = zf.namelist()
        assert "PC_Claims_Insurance_Dashboard.twb" in names
        assert any("Data/Extracts" in n for n in names)

    # Checkpoint 6: API download returns 200
    artifacts = db_session.query(Artifact).filter(Artifact.job_id == job_id).all()
    wb_art = next((a for a in artifacts if a.artifact_type == "workbook"), None)
    assert wb_art is not None
    res = client.get(f"/api/v1/jobs/{job_id}/download/{wb_art.id}")
    assert res.status_code == 200
    assert len(res.content) > 0


# ──────────────────────────────────────────────────────────────────
#  [9] REGRESSION — Schema metrics unaffected
# ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_schema_metrics_unaffected_by_fix(db_session, insurance_job):
    """
    Regression: schema metrics must still call /api/model/metrics/{id}.
    The fix must not accidentally skip schema metric processing.
    """
    mock = AsyncMock()
    schema = _schema_metric_def("S001", "Net Revenue", "Sum(Revenue)")
    mock.get_metric.return_value = schema

    obj = _seed_metric(db_session, insurance_job, "S001", "Net Revenue", schema)
    agent = SemanticAgent(db=db_session, job=insurance_job, mstr=mock)
    result = await agent._extract_metric(obj)

    mock.get_metric.assert_called_once_with("S001")
    assert result.expression_text == "Sum(Revenue)"
    assert result.precomputed_calc is None   # schema metrics don't use precomputed path
