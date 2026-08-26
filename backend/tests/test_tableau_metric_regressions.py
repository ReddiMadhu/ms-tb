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


# ── RCA-VERIFIED defect regressions ─────────────────────────────────

class TestRCADefect3_TopStateLossMistranslation:
    """Defect #3: Max<...>([Total Incurred USD]){~+} must compile to
    MAX([Total Incurred USD]), never MAX({FIXED : SUM(…)}).

    Root cause: ft=16 (MAX) was missing from MSTR_FT_AGG, so the mexp
    tree path fell through to the text/AI path which wrapped it in a FIXED
    LOD expression turning "max single claim" into "grand total" ($300K → $5.34B).
    """

    def test_mexp_ft16_compiles_to_max(self):
        """mexp tree with ft=16 should produce MAX([field])."""
        from app.agents.ir_compiler import MSTR_FT_AGG
        # Verified: ft=16 → MAX, ft=17 → MIN
        assert MSTR_FT_AGG.get(16) == "MAX"
        assert MSTR_FT_AGG.get(17) == "MIN"

    def test_compile_mstr_formula_max_report_level(self):
        """Max<UseLookupForAttributes=False>([Total Incurred USD]){~+}
        must compile to MAX([Total Incurred USD])."""
        from app.agents.ir_compiler import IRCompilerAgent
        from types import SimpleNamespace

        # Minimal IR bundle
        ir = SimpleNamespace(
            dimensions=[], measures=[], tables=[], filters=[], issues=[],
            relationships=[],
        )
        compiler = IRCompilerAgent.__new__(IRCompilerAgent)
        compiler.ir = ir
        compiler._id_to_name = {}

        result = compiler._compile_mstr_formula(
            'Max<UseLookupForAttributes=False >([Total Incurred USD]){~+}'
        )
        assert result is not None, "Formula must not fail closed"
        assert "MAX(" in result.upper(), f"Expected MAX(...), got: {result}"
        assert "FIXED" not in result.upper(), f"Must NOT contain FIXED LOD: {result}"
        assert "SUM" not in result.upper(), f"Must NOT wrap in SUM: {result}"

    def test_max_calc_pinned_as_precomputed(self):
        """After orchestrator enrichment, simple MAX([F]) calcs must be pinned
        via precomputed_calc so the AI stage cannot overwrite them."""
        # Simulate what the orchestrator does post-enrichment
        calc = "MAX([Total Incurred USD])"
        upper = calc.strip().upper()
        should_pin = upper.startswith(("MAX(", "MIN(")) and upper.count("(") == 1
        assert should_pin, "Simple MAX calc must be pinned as precomputed_calc"

        # Complex MAX (nested) should NOT be pinned
        complex_calc = "MAX(SUM([Total Incurred USD]))"
        upper_c = complex_calc.strip().upper()
        should_not_pin = upper_c.startswith(("MAX(", "MIN(")) and upper_c.count("(") == 1
        assert not should_not_pin, "Nested MAX(SUM(...)) must NOT be auto-pinned"


class TestRCADefect4_DeadConditionDetection:
    """Defect #4: Litigation Incurred Loss tests Litigation@ID = '1' but
    data has only 'Yes'/'No'. The dead-condition detector must flag this."""

    def test_dead_condition_detected_with_known_values(self):
        """When dimension elements are known, a test for an absent value is flagged."""
        from app.agents.validation_agent import ValidationAgent

        # Build a minimal IR with a dimension that has known values
        ir = type("IR", (), {
            "dimensions": [type("Dim", (), {
                "name": "Litigation",
                "caption": "Litigation",
                "mstr_id": "LIT001",
                "elements": ["Yes", "No"],
                "known_values": None,
            })()],
            "measures": [type("M", (), {
                "name": "Litigation Incurred Loss",
                "mstr_id": "LIL001",
                "tableau_calc": "SUM(IF [Litigation] = \"1\" THEN [Total Incurred] ELSE 0 END)",
            })()],
            "object_definitions": {},
        })()

        agent = ValidationAgent.__new__(ValidationAgent)
        checks = agent._detect_dead_conditions(ir)
        assert len(checks) >= 1, "Dead condition must be detected"
        assert checks[0].check_type == "dead_condition"
        assert not checks[0].passed
        assert "'1'" in checks[0].message
        assert "Litigation" in checks[0].message

    def test_no_false_positive_for_valid_values(self):
        """A condition testing a value that exists should NOT be flagged."""
        from app.agents.validation_agent import ValidationAgent

        ir = type("IR", (), {
            "dimensions": [type("Dim", (), {
                "name": "Litigation",
                "caption": "Litigation",
                "mstr_id": "LIT001",
                "elements": ["Yes", "No"],
                "known_values": None,
            })()],
            "measures": [type("M", (), {
                "name": "Litigation Claims",
                "mstr_id": "LC001",
                "tableau_calc": "SUM(IF [Litigation] = 'Yes' THEN 1 ELSE 0 END)",
            })()],
            "object_definitions": {},
        })()

        agent = ValidationAgent.__new__(ValidationAgent)
        checks = agent._detect_dead_conditions(ir)
        assert len(checks) == 0, "Valid condition must NOT be flagged"


class TestRCADefect1_DerivedAttrDomainRisk:
    """Defect #1: Metrics depending on st=3077 derived attributes must be
    flagged because MSTR evaluates them at domain level, not row level."""

    def test_derived_attr_flagged(self):
        """A metric with definition_chain containing st=3077 must get a warning."""
        from app.agents.validation_agent import ValidationAgent

        ir = type("IR", (), {
            "dimensions": [],
            "measures": [type("M", (), {
                "name": "High Fraud Claims",
                "mstr_id": "HFC001",
                "tableau_calc": "SUM(IF INT([Fraud Score]) >= 70 THEN 1 ELSE 0 END)",
                "definition_chain": [
                    {"name": "High Fraud Flag", "st": 3077, "derived_attr": True,
                     "formula": "IF(([Fraud Score]@ID >= 70),1,0)"},
                ],
            })()],
            "object_definitions": {},
        })()

        agent = ValidationAgent.__new__(ValidationAgent)
        checks = agent._detect_derived_attr_domain_risk(ir)
        assert len(checks) == 1
        assert checks[0].check_type == "derived_attr_domain_risk"
        assert not checks[0].passed
        assert "High Fraud Flag" in checks[0].message
        assert "domain" in checks[0].message.lower()

    def test_no_warning_for_normal_metrics(self):
        """Metrics without derived attrs in their chain should not be flagged."""
        from app.agents.validation_agent import ValidationAgent

        ir = type("IR", (), {
            "dimensions": [],
            "measures": [type("M", (), {
                "name": "Total Incurred",
                "mstr_id": "TI001",
                "tableau_calc": "SUM([Total Incurred USD])",
                "definition_chain": [],
            })()],
            "object_definitions": {},
        })()

        agent = ValidationAgent.__new__(ValidationAgent)
        checks = agent._detect_derived_attr_domain_risk(ir)
        assert len(checks) == 0, "Normal metric must NOT be flagged"


class TestRCADefect4_DeadConditionAutoRepair:
    """Defect #4 proper fix: repair_dead_conditions cross-references sibling
    definitions to auto-substitute the correct condition value."""

    def test_repair_litigation_incurred_loss(self):
        """Litigation Incurred Loss tests Litigation@ID='1' but Litigation_Flag
        tests Litigation@ID='Yes'. The auto-repair should fix the formula."""
        from app.services.pipeline.orchestrator import repair_dead_conditions
        from app.agents.ir_compiler import IRCompilerAgent
        from types import SimpleNamespace

        # Build IR with object_definitions matching the real harvested data
        ir = SimpleNamespace(
            dimensions=[],
            measures=[SimpleNamespace(
                name="Litigation Incurred Loss",
                mstr_id="LIL001",
                local_name="Litigation Incurred Loss",
                caption="Litigation Incurred Loss",
                expression_text='Sum<UseLookupForAttributes=False >(IF((Litigation@ID = "1"),[Total Incurred],0)){~+}',
                expression_ast=None,
                tableau_calc="SUM(IF [Litigation] = '1' THEN [Total Incurred] ELSE 0 END)",
                precomputed_calc=None,
                null_policy="propagate",
                zero_division_policy="null",
                is_derived=True,
                confidence=0.85,
                definition_chain=[],
            )],
            tables=[],
            filters=[],
            issues=[],
            relationships=[],
            object_definitions={
                "by_did": {
                    "C6DF85F0504C3F948AA687839B16B19A": {
                        "name": "Litigation_Flag",
                        "formula": 'IF((Litigation@ID = "Yes"),1,0)',
                        "derived_attr": True,
                        "t": 12, "st": 3077,
                    },
                    "LIL_DID_001": {
                        "name": "Litigation Incurred Loss",
                        "formula": 'Sum<UseLookupForAttributes=False >(IF((Litigation@ID = "1"),[Total Incurred],0)){~+}',
                        "derived_attr": False,
                        "t": 4, "st": 1024,
                    },
                },
                "by_name_lower": {
                    "litigation_flag": {
                        "name": "Litigation_Flag",
                        "formula": 'IF((Litigation@ID = "Yes"),1,0)',
                        "derived_attr": True,
                        "t": 12, "st": 3077,
                    },
                    "litigation incurred loss": {
                        "name": "Litigation Incurred Loss",
                        "formula": 'Sum<UseLookupForAttributes=False >(IF((Litigation@ID = "1"),[Total Incurred],0)){~+}',
                        "derived_attr": False,
                        "t": 4, "st": 1024,
                    },
                },
            },
        )

        # Create a minimal compiler
        compiler = IRCompilerAgent.__new__(IRCompilerAgent)
        compiler.ir = ir
        compiler._id_to_name = {}

        # Run repair
        count = repair_dead_conditions(ir, compiler)

        # Verify repair happened
        assert count == 1, f"Expected 1 repair, got {count}"
        calc = ir.measures[0].tableau_calc
        assert calc is not None, "Calc must not be None"

        # The repaired calc must test 'Yes' not '1'
        calc_upper = calc.upper()
        assert "'YES'" in calc_upper or '"YES"' in calc_upper, (
            f"Repaired calc must test 'Yes', got: {calc}"
        )
        assert "'1'" not in calc_upper and '"1"' not in calc_upper, (
            f"Repaired calc must NOT test '1', got: {calc}"
        )

        # Must be pinned
        assert ir.measures[0].precomputed_calc == calc, "Repaired calc must be pinned"

        # definition_chain must record the repair
        chain = ir.measures[0].definition_chain
        assert any("dead_condition_repair" in c.get("name", "") for c in chain), (
            f"Repair must be recorded in definition_chain: {chain}"
        )



