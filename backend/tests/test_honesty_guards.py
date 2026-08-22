"""
Honesty-guard regression tests.

These lock in the fail-closed behavior of the repaired pipeline:
  1. Validation gates NEVER pass on self-reported confidence — KPI/security/visual
     checks without a real execution/read-back path must FAIL (block auto-publish).
  2. The Hyper physical-measure classifier is driven by the MSTR expression AST,
     not by name-keyword heuristics.
  3. Publishing fails closed when Tableau Server/PAT is not configured — no
     fabricated remote IDs.
  4. Filter-unsafe LOD translations (FIXED under filters, LOOKUP prior-period)
     require human review instead of silently emitting broken math.
"""

import os
import uuid
from types import SimpleNamespace

import pytest

from app.agents.ai_translation import AITranslationAgent
from app.agents.ir_compiler import BIIR, IRFilter, IRMeasure, IRVisual
from app.agents.validation_agent import ValidationAgent
from app.models.job import Job
from app.models.objects import PublishOperation
from app.services.pipeline.orchestrator import classify_physical_measures


# ──────────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────────

def _make_job(db_session) -> Job:
    job = Job(
        id=f"honesty-{uuid.uuid4().hex[:8]}",
        name="HonestyGuard",
        status="PENDING",
        mstr_base_url="https://env-test.cloud.strategy.com/MicroStrategyLibrary",
        mstr_project_id="B928FD6C7B744238BE7CEDE129051F13",
        artifacts_dir="./artifacts/honesty-test",
    )
    db_session.add(job)
    db_session.commit()
    return job


def _measure(mstr_id="M1", name="Revenue", confidence=0.97):
    return IRMeasure(
        id=mstr_id,
        mstr_id=mstr_id,
        name=name,
        local_name=name.replace(" ", "_"),
        remote_name=name.replace(" ", "_"),
        caption=name,
        tableau_calc=f"SUM([{name}])",
        confidence=confidence,
    )


def _minimal_ir(measures=None, filters=None, visuals=None):
    return BIIR(
        job_id="honesty",
        tables=[],
        relationships=[],
        dimensions=[],
        measures=measures or [],
        filters=filters or [],
        visuals=visuals or [],
        issues=[],
    )


# ──────────────────────────────────────────────────────────────────
#  [1] Validation gates fail closed
# ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_kpi_gate_fails_closed_without_real_verification(db_session):
    """High self-reported confidence must NOT produce a passing KPI gate."""
    job = _make_job(db_session)
    agent = ValidationAgent(db=db_session, job=job)

    ir = _minimal_ir(measures=[_measure(confidence=0.99)])
    scorecard = await agent.validate(ir, hyper_paths={})

    assert scorecard.financial_kpi_confidence < 1.0, (
        "KPI gate passed purely on self-reported confidence — fabrication regression"
    )
    assert scorecard.auto_publish_ok is False


@pytest.mark.asyncio
async def test_security_and_visual_gates_fail_closed_when_unverified(db_session):
    """Pending impersonation/render must be recorded as FAILED, never passed."""
    job = _make_job(db_session)
    agent = ValidationAgent(db=db_session, job=job)

    sec_filter = IRFilter(
        id="F1", mstr_id="SEC-1", name="Region Security",
        predicate="FULLNAME() = [EntitlementUser]", is_security=True,
    )
    visual = IRVisual(id="V1", name="KPI Tile", mark_type="text", rows=[], columns=[])

    ir = _minimal_ir(filters=[sec_filter], visuals=[visual])
    scorecard = await agent.validate(ir, hyper_paths={})

    assert scorecard.security_parity is False, "Unverified security filter passed"
    assert scorecard.visual_confidence < 1.0, "Unverified visual render passed"
    assert scorecard.auto_publish_ok is False


@pytest.mark.asyncio
async def test_no_security_filters_gate_passes(db_session):
    """With zero security filters the security gate legitimately passes."""
    job = _make_job(db_session)
    agent = ValidationAgent(db=db_session, job=job)

    ir = _minimal_ir()
    scorecard = await agent.validate(ir, hyper_paths={})

    security_checks = [c for c in scorecard.checks if c.category == "security"]
    assert len(security_checks) == 1 and security_checks[0].passed is True


# ──────────────────────────────────────────────────────────────────
#  [2] Physical measure classification is MSTR-AST-driven
# ──────────────────────────────────────────────────────────────────

def test_classifier_keeps_simple_single_column_aggregate():
    m = {
        "mstr_id": "M-REV", "name": "Total Revenue", "local_name": "Total_Revenue",
        "tableau_calc": "SUM([Total Revenue])",
        "expression_ast": {
            "type": "function", "function": "Sum",
            "children": [{"type": "column", "name": "Revenue"}],
        },
    }
    assert classify_physical_measures([m]) == [m]


def test_classifier_rejects_ratio_and_nested_aggregates():
    ratio = {
        "mstr_id": "M-MRG", "name": "Profit Margin", "local_name": "Profit_Margin",
        "tableau_calc": "IIF(...)",
        "expression_ast": {
            "type": "operator", "operator": "/",
            "children": [
                {"type": "column", "name": "Profit"},
                {"type": "column", "name": "Revenue"},
            ],
        },
    }
    nested = {
        "mstr_id": "M-NEST", "name": "Avg Of Sum", "local_name": "Avg_Of_Sum",
        "tableau_calc": "AVG([X])",
        "expression_ast": {
            "type": "function", "function": "Avg",
            "children": [{
                "type": "function", "function": "Sum",
                "children": [{"type": "column", "name": "X"}],
            }],
        },
    }
    assert classify_physical_measures([ratio, nested]) == []


def test_classifier_fallback_is_exact_match_only():
    plain = {
        "mstr_id": "M-P", "name": "Amount", "local_name": "Amount",
        "tableau_calc": "SUM([Amount])",  # no AST available
    }
    keyword_trap = {
        "mstr_id": "M-K", "name": "Paid Amount USD", "local_name": "Paid_Amount_USD",
        # Old heuristic would keep this (contains 'amount'); exact-match rejects it.
        "tableau_calc": "AVG([Paid Amount USD]) / 2",
    }
    out = classify_physical_measures([plain, keyword_trap])
    assert out == [plain]


def test_classifier_prefers_bundle_ast_by_mstr_id():
    m = {
        "mstr_id": "M-B", "name": "Metric B", "local_name": "Metric_B",
        "tableau_calc": "SUM([Metric B])",  # would pass fallback…
        "expression_ast": None,
    }
    bundle_asts = {"M-B": {"type": "operator", "operator": "+", "children": [
        {"type": "column", "name": "A"}, {"type": "column", "name": "B"},
    ]}}
    assert classify_physical_measures([m], bundle_asts) == [], (
        "Bundle AST must override the calc-string fallback"
    )


# ──────────────────────────────────────────────────────────────────
#  [3] Publish fails closed without Tableau config
# ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_publish_staging_fail_closed_without_config(db_session):
    """Missing server/PAT must record a FAILED operation, never a fake success."""
    job = _make_job(db_session)
    from app.agents.publisher import PublishAgent

    agent = PublishAgent(db=db_session, job=job)
    artifacts = [{"name": "wb.twbx", "type": "workbook", "path": "./nope.twbx"}]

    result = await agent.publish_staging(artifacts, tableau_config={})

    assert result == {}, "Publish returned content ids without any Tableau config"
    ops = db_session.query(PublishOperation).filter(
        PublishOperation.job_id == job.id,
    ).all()
    assert ops and all(o.status == "failed" for o in ops), (
        "Fail-closed publish must persist failed operations"
    )


@pytest.mark.asyncio
async def test_promotion_blocked_records_blocked_operation(db_session):
    job = _make_job(db_session)
    from app.agents.publisher import PublishAgent
    from app.agents.validation_agent import ValidationScorecard

    sc = ValidationScorecard(job_id=job.id)
    sc.financial_kpi_confidence = 0.0  # failed gate
    sc.auto_publish_ok  # property; False because kpi < 0.98

    agent = PublishAgent(db=db_session, job=job)
    result = await agent.promote_to_production(
        staging_ids={"wb.twbx": "stg-1"}, scorecard=sc, tableau_config={},
    )

    assert result == {}
    blocked = db_session.query(PublishOperation).filter(
        PublishOperation.job_id == job.id,
        PublishOperation.status == "blocked",
    ).all()
    assert blocked, "Blocked promotion must be persisted"


# ──────────────────────────────────────────────────────────────────
#  [4] Filter-unsafe LOD translations require human review
# ──────────────────────────────────────────────────────────────────

def test_fixed_level_metric_requires_human_review():
    from types import SimpleNamespace

    agent = AITranslationAgent(db=None, job=SimpleNamespace(id="t"), artifacts_dir="./artifacts/llm_cache")
    measure = SimpleNamespace(
        name="Prior Year Revenue",
        expression_text="Sum(Revenue){Year}",
        dimty={"type": "fixed", "attributes": ["Year"], "aggregation": "SUM"},
        mstr_id="M-FIXED",
    )

    result = agent._pattern_match(measure)

    assert result is not None, "Fixed-level metric must produce an explicit review result"
    assert result.requires_human_review is True
    assert not result.tableau_calc.lstrip().upper().startswith("{FIXED"), (
        "Filter-unsafe FIXED LOD must never be auto-emitted"
    )
    assert "LOOKUP" not in result.tableau_calc.upper()


def test_prior_period_templates_are_disabled():
    from app.agents.ai_translation import DIMTY_LOD_TEMPLATES

    assert DIMTY_LOD_TEMPLATES["year_over_year"] is None
    assert DIMTY_LOD_TEMPLATES["percent_change"] is None
    assert DIMTY_LOD_TEMPLATES["level_metric_fixed"] is None


# ──────────────────────────────────────────────────────────────────
#  [5] No placeholder strings leak into IR / workbook XML
# ──────────────────────────────────────────────────────────────────

def test_uncompilable_filter_returns_none_not_todo():
    """A filter without a compilable MSTR predicate must return None (fail-closed),
    never a '// TODO' placeholder that flows into artifacts."""
    from types import SimpleNamespace

    from app.agents.ir_compiler import IRCompilerAgent

    agent = IRCompilerAgent.__new__(IRCompilerAgent)  # bypass db/job wiring
    flt = SimpleNamespace(
        mstr_id="F-X", name="Uncompilable Filter",
        predicate_ast=None, qualification_type=None, is_security_filter=False,
    )

    assert agent._compile_filter(flt) is None


def test_emitter_skips_placeholder_calculations(db_session, tmp_path):
    """'// TODO' calcs must not be emitted as <calculation> formulas."""
    from lxml import etree as lxml_etree

    from app.agents.tableau_emitter import TableauEmitterAgent
    from app.models.objects import Issue as IssueModel

    job = _make_job(db_session)
    emitter = TableauEmitterAgent(
        db=db_session, job=job,
        artifacts_dir=str(tmp_path), target_environment="staging",
    )

    todo_measure = IRMeasure(
        id="MT", mstr_id="M-TODO", name="Broken Calc",
        local_name="Broken_Calc", remote_name="Broken_Calc", caption="Broken Calc",
        tableau_calc="// TODO: AI translation needed for Broken Calc",
        confidence=0.30,
    )
    ir = _minimal_ir(measures=[todo_measure])

    ds_node = lxml_etree.Element("datasource")
    emitter._inject_calculated_fields(ds_node, ir)

    calc_cols = ds_node.findall("./column[calculation]")
    assert len(calc_cols) == 0, "Placeholder formula leaked into workbook XML"

    all_cols = ds_node.findall("./column")
    assert len(all_cols) == 0, "Placeholder measure column should not be emitted at all"

    issues = (
        db_session.query(IssueModel)
        .filter(IssueModel.job_id == job.id, IssueModel.object_id == "M-TODO")
        .all()
    )
    assert issues, "Skipped placeholder calc must surface an Issue"


# ──────────────────────────────────────────────────────────────────
#  [6] Real MSTR instance formulas (datasets.mx f / mexp) compile honestly
#  Formulas below are copied verbatim from captured API responses.
# ──────────────────────────────────────────────────────────────────

def _bare_compiler(id_to_name=None):
    from app.agents.ir_compiler import IRCompilerAgent
    agent = IRCompilerAgent.__new__(IRCompilerAgent)  # bypass db/job
    agent.db = None
    agent.job = None
    agent._caption_counter = 0
    agent._id_to_name = id_to_name or {}
    return agent


def _mx_measure(name, ast=None, text=None):
    return SimpleNamespace(
        name=name, precomputed_calc=None,
        expression_ast=ast, expression_text=text,
    )


def test_real_mexp_single_aggregation_compiles():
    """Avg Claim: mexp {ft:14, args:[{did of Total Incurred USD}]} → AVG([Total Incurred USD])"""
    agent = _bare_compiler({"4EC0DE38274C531488F2C599CD15D3E1": "Total Incurred USD"})
    m = _mx_measure(
        "Avg Claim",
        ast={"ft": 14, "args": [{"did": "4EC0DE38274C531488F2C599CD15D3E1", "t": 4}], "prms": []},
        text="Avg<UseLookupForAttributes=False >([Total Incurred USD]){~+}",
    )
    assert agent._compile_expression(m, "propagate", "null") == "AVG([Total Incurred USD])"


def test_real_ratio_formula_gets_zero_division_guard():
    """High Fraud Rate: '[High Fraud Claims] / Total_Claims' → guarded division."""
    agent = _bare_compiler()
    m = _mx_measure("High Fraud Rate", text="[High Fraud Claims] / Total_Claims")
    out = agent._compile_expression(m, "propagate", "null")
    assert out == "IIF([Total_Claims] = 0, NULL, [High Fraud Claims] / [Total_Claims])"


def test_real_if_formula_translates_to_tableau_if():
    """Litigation Incurred Loss: Sum(IF((Litigation@ID = \"1\"),[Total Incurred],0)){~+}"""
    agent = _bare_compiler()
    m = _mx_measure(
        "Litigation Incurred Loss",
        text='Sum<UseLookupForAttributes=False >(IF((Litigation@ID = "1"),[Total Incurred],0)){~+}',
    )
    out = agent._compile_expression(m, "propagate", "null")
    assert out.upper().startswith("SUM(IF"), out
    assert "@ID" not in out and "<" not in out
    assert 'THEN [Total Incurred] ELSE 0 END' in out


def test_nondefault_dimty_fails_closed():
    """A level-dimty formula must NOT auto-translate (filter-unsafe)."""
    agent = _bare_compiler()
    m = _mx_measure("Level Metric", text="Sum([Revenue]){Year}")
    assert agent._compile_mstr_formula(m.expression_text) is None


def test_classifier_excludes_derived_and_keeps_base_columns():
    """Base cube metrics (no f/mexp) are physical; derived (is_derived) are calcs."""
    base = {
        "mstr_id": "CE0863496E43CA3894ABBBAA783EE2F4", "name": "Paid Amount USD",
        "local_name": "Paid_Amount_USD", "tableau_calc": "SUM([Paid Amount USD])",
    }  # real base entry: no f, no mexp
    derived_avg_claim = {
        "mstr_id": "FD034950934CCEEAF6E4D9A0CAD12235", "name": "Avg Claim",
        "local_name": "Avg_Claim", "tableau_calc": "AVG([Total_Incurred_USD])",
        "expression_ast": {"ft": 14, "args": [{"did": "4EC0DE38274C531488F2C599CD15D3E1", "t": 4}]},
        "is_derived": True,
    }
    out = classify_physical_measures([base, derived_avg_claim])
    assert out == [base], (
        "Derived metric materialized into the extract — would freeze AVG semantics"
    )
