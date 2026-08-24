"""
Regression tests — translation fidelity for jobs
087560ee-cfba-462a-b726-4c2dbd04bb56 and 482de454-2eb5-49f9-87d5-d76e64d4ffe3.

Philosophy under test:
  • Every wrapper/cast in an emitted formula must trace to the MSTR
    definition (expression_text, mexp `ft`, dimty, form data_type) — the
    emitter NEVER invents ATTR()/SUM()/INT() wrappers.
  • References to other metrics/calcs pass through verbatim.
  • Illegal aggregation nesting (ATTR(SUM(..)), RANK(SUM([agg-calc]))) is a
    translation defect: fail closed — skip emission and record a blocker
    Issue for human review instead of mutating the formula.
  • Column declarations follow the MSTR form data type end-to-end.
"""

import xml.etree.ElementTree as ET

import pytest

from app.models.job import Job
from app.models.objects import Issue
from app.agents.tableau_emitter import (
    TableauEmitterAgent,
    _find_illegal_aggregation_nesting,
)


class Dim:
    def __init__(self, mstr_id, caption, local_name, data_type="string",
                 role="dimension", remote_name=None, hidden=False):
        self.mstr_id = mstr_id
        self.caption = caption
        self.local_name = local_name
        self.name = caption
        self.data_type = data_type
        self.role = role
        self.remote_name = remote_name
        self.hidden = hidden


class Measure:
    def __init__(self, mstr_id, name, local_name=None, tableau_calc="",
                 dependencies=None, is_derived=True):
        self.mstr_id = mstr_id
        self.caption = name
        self.name = name
        self.local_name = local_name or name
        self.tableau_calc = tableau_calc
        self.dependencies = dependencies or []
        self.is_derived = is_derived


class IR:
    def __init__(self, dimensions=(), measures=(), tables=("Extract",)):
        self.dimensions = list(dimensions)
        self.measures = list(measures)
        self.tables = [type("T", (), {"name": t, "physical_name": t})() for t in tables]
        self.relationships = []


@pytest.fixture
def emitter(db_session, tmp_path):
    job = Job(
        id="regression-job",
        name="T_prod",
        status="PENDING",
        mstr_base_url="https://mstr.example.com/MicroStrategyLibrary",
        mstr_project_id="PROJ12345",
        artifacts_dir=str(tmp_path),
    )
    db_session.add(job)
    db_session.commit()
    return TableauEmitterAgent(db=db_session, job=job, artifacts_dir=str(tmp_path))


def _emit_datasource(emitter, ir):
    tds_path = emitter.emit_datasource(
        ir=ir, hyper_paths={"Extract": "unused.hyper"}, ds_name="Reg_DS"
    )
    root = ET.parse(tds_path).getroot()
    formulas = {
        c.get("name"): c.find("calculation").get("formula")
        for c in root.findall("column") if c.find("calculation") is not None
    }
    cols = {c.get("name"): c for c in root.findall("column")}
    raw = tds_path.read_text(encoding="utf-8")
    return formulas, cols, raw


# ── XML escaping ────────────────────────────────────────────────────

def test_comparison_operators_not_double_escaped(emitter):
    formula = "SUM(IF INT([Fraud Score]) >= 70 THEN 1 ELSE 0 END)"
    ir = IR(measures=[Measure("m1", "High Fraud Claims", tableau_calc=formula)])
    formulas, _, raw = _emit_datasource(emitter, ir)

    assert formulas["[High Fraud Claims]"] == formula   # round-trips exactly
    assert "&gt;=" in raw                               # single escape only
    assert "&amp;" not in raw                           # never double


# ── Type fidelity: MSTR form type drives declaration ────────────────

def test_mstr_integer_form_promoted_to_quantitative(emitter):
    """MSTR declares Fraud Score ID form integer → extract built numeric →
    TDS declares real/quantitative and plain AVG() is legal. No INT() cast."""
    fraud = Dim("d1", "Fraud Score", "Fraud Score", data_type="integer",
                remote_name="Fraud_Score_ID")
    ir = IR(dimensions=[fraud], measures=[
        Measure("m1", "Avg (Fraud Score)", tableau_calc="AVG([Fraud Score])"),
    ])
    formulas, cols, _ = _emit_datasource(emitter, ir)

    col = cols["[Fraud Score]"]
    assert col.get("datatype") == "real"
    assert col.get("role") == "measure"
    assert col.get("type") == "quantitative"
    # Formula passes through VERBATIM — no synthesised INT() cast
    assert formulas["[Avg (Fraud Score)]"] == "AVG([Fraud Score])"


def test_string_dimension_stays_dimension(emitter):
    ir = IR(dimensions=[Dim("d1", "Region", "Region", data_type="string")])
    _, cols, _ = _emit_datasource(emitter, ir)
    col = cols["[Region]"]
    assert col.get("datatype") == "string"
    assert col.get("role") == "dimension"


# ── Aggregate operands pass through verbatim ────────────────────────

def test_metric_ratio_references_pass_through_bare(emitter):
    """MSTR '[High Fraud Claims] / Total_Claims' divides two report-grain
    metrics ({~+}). Both operands are already aggregates — emitted exactly
    as translated, no ATTR()/SUM() invented around references."""
    total = Measure("m-total", "Total_Claims",
                    tableau_calc="SUM({FIXED : COUNTD([Claim ID])})")
    claims = Measure("m-hfc", "High Fraud Claims",
                     tableau_calc="SUM(IF INT([Fraud Score]) >= 70 THEN 1 ELSE 0 END)")
    rate = Measure("m-rate", "High Fraud Rate",
                   tableau_calc="IIF([Total_Claims] = 0, NULL, "
                                "[High Fraud Claims] / [Total_Claims])",
                   dependencies=["m-total", "m-hfc"])
    ir = IR(measures=[total, claims, rate])
    formulas, _, _ = _emit_datasource(emitter, ir)

    assert formulas["[High Fraud Rate]"] == (
        "IIF([Total_Claims] = 0, NULL, [High Fraud Claims] / [Total_Claims])"
    )
    assert formulas["[Total_Claims]"] == "SUM({FIXED : COUNTD([Claim ID])})"


def test_rank_references_aggregate_calc_verbatim(emitter):
    top = Measure("m-top", "Top State Loss",
                  tableau_calc="MAX({FIXED : SUM([Total Incurred USD])})")
    rank = Measure("m-rank", "State Loss Rank",
                   tableau_calc="RANK([Top State Loss])",   # as MSTR Rank(...)
                   dependencies=["m-top"])
    ir = IR(measures=[top, rank])
    formulas, _, _ = _emit_datasource(emitter, ir)
    assert formulas["[State Loss Rank]"] == "RANK([Top State Loss])"


# ── Fail-closed gate on illegal nesting ─────────────────────────────

def test_illegal_attr_over_aggregate_not_emitted(emitter):
    """The regression from job 482de454: a cached calc carrying
    ATTR([Total_Claims]) must be BLOCKED at emission, not shipped."""
    total = Measure("m-total", "Total_Claims",
                    tableau_calc="SUM({FIXED : COUNTD([Claim ID])})")
    claims = Measure("m-hfc", "High Fraud Claims",
                     tableau_calc="SUM(IF INT([Fraud Score]) >= 70 THEN 1 ELSE 0 END)")
    bad_rate = Measure(
        "m-rate", "High Fraud Rate",
        tableau_calc="IIF(ATTR([Total_Claims]) = 0, NULL, "
                     "[High Fraud Claims] / ATTR([Total_Claims]))",
        dependencies=["m-total", "m-hfc"],
    )
    ir = IR(measures=[total, claims, bad_rate])
    formulas, _, _ = _emit_datasource(emitter, ir)

    assert "[High Fraud Rate]" not in formulas           # failed closed
    issues = (
        emitter.db.query(Issue)
        .filter(Issue.job_id == "regression-job", Issue.severity == "blocker")
        .all()
    )
    assert any("High Fraud Rate" in i.message for i in issues)


def test_poisoned_rank_sum_cache_blocked_for_human_review(emitter):
    """RANK(SUM([Top State Loss])) — SUM over an aggregate calc field — is a
    translation defect vs MSTR 'Rank([Top State Loss])'. Blocked, surfaced."""
    top = Measure("m-top", "Top State Loss",
                  tableau_calc="MAX({FIXED : SUM([Total Incurred USD])})")
    rank = Measure("m-rank", "State Loss Rank",
                   tableau_calc="RANK(SUM([[Top State Loss]]))",
                   dependencies=["m-top"])
    ir = IR(measures=[top, rank])
    formulas, _, _ = _emit_datasource(emitter, ir)

    assert "[State Loss Rank]" not in formulas
    issues = (
        emitter.db.query(Issue)
        .filter(Issue.job_id == "regression-job", Issue.severity == "blocker")
        .all()
    )
    assert any("State Loss Rank" in i.message for i in issues)


def test_physical_column_refs_still_sum_guarded():
    """Extract columns are row-level by definition (classify_physical_measures
    record); a derived formula referencing one without an aggregation gets the
    SUM named by its MSTR parent function restored."""
    from app.agents.tableau_emitter import _wrap_bare_aggregate_refs
    out = _wrap_bare_aggregate_refs(
        "[Net Revenue] - SUM([Tax])",
        {"Net Revenue"},
        skip_names=set(),
    )
    assert out == "SUM([Net Revenue]) - SUM([Tax])"


# ── Detector unit tests ─────────────────────────────────────────────

def test_detector_flags_and_clears_correctly():
    agg_fields = {"Top State Loss", "Total_Claims"}
    assert _find_illegal_aggregation_nesting(
        "IIF(ATTR([Total_Claims]) = 0, NULL, [X] / ATTR([Total_Claims]))",
        agg_fields,
    )
    assert _find_illegal_aggregation_nesting(
        "RANK(SUM([Top State Loss]))", agg_fields,
    )
    # Legal shapes must NOT flag
    assert _find_illegal_aggregation_nesting(
        "RANK([Top State Loss])", agg_fields,
    ) is None
    assert _find_illegal_aggregation_nesting(
        "SUM({FIXED : COUNTD([Claim ID])})", agg_fields,
    ) is None
    assert _find_illegal_aggregation_nesting(
        "ZN(SUM([Paid Amount USD]))", set(),
    ) is None
    assert _find_illegal_aggregation_nesting(
        "AVG(ZN([Total Incurred USD]))", {"Total Incurred USD"},
    ) is None
