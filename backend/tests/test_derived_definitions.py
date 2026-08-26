"""
Ground-truth derived-definition harvest → resolve → compile precedence.

Locks in the pipeline fix for dataset-derived objects (subType 3077) whose
formulas MicroStrategy exposes ONLY inside the dossier instance payload
(datasets{dsId}.att[] / .mx[] `f` fields) — never via the Model API.

Regression anchor: before this fix the Tier-1 LLM cache supplied these rules
and got Net Loss wrong (Incurred − Recovery − Salvage instead of MSTR's
(Paid + Reserve) − Recovery) at confidence 1.0.
"""

from types import SimpleNamespace

import pytest

from app.agents.expression_resolver import resolve_expression
from app.agents.ir_compiler import BIIR, IRMeasure
from app.services.pipeline.orchestrator import (
    apply_definition_expansions,
    collect_object_definitions,
)

# ──────────────────────────────────────────────────────────────────
#  Fixture: verbatim shape of the live dossier instance payload
#  (names/GUIDs from backend/artifacts/instance_full.json)
# ──────────────────────────────────────────────────────────────────

FRAUD_SCORE_DID = "B82168CCC24FD779357A6FAE0AD774E6"
LITIGATION_DID = "B29D7E26D34DF17A0D62E7978EA450EE"

ATT_HIGH_FRAUD_FLAG = {
    "t": 12, "st": 3077, "n": "High Fraud Flag",
    "did": "CA915844CF4E214775EE71960F823A8D",
    "f": "IF(([Fraud Score]@ID >= 70),1,0)",
}
ATT_LITIGATION_FLAG = {
    "t": 12, "st": 3077, "n": "Litigation_Flag",
    "did": "C6DF85F0504C3F948AA687839B16B19A",
    "f": 'IF((Litigation@ID = "Yes"),1,0)',
}
ATT_NET_LOSS = {
    "t": 12, "st": 3077, "n": "Net Loss",
    "did": "D5C0B8A52E1B4C6E9F03A7B21D84E660",
    "dsc": "Paid plus reserve minus recovery",
    "f": "([Paid Amount USD] + [Reserve Amount USD]) - [Recovery Amount USD]",
}
ATT_LOSS_YEAR = {
    "t": 12, "st": 3077, "n": "Loss_Year", "did": "LY0000000000000000000000000000001",
    "f": "Year([Loss Date]@ID)",
}
ATT_MONTH_LOSS = {
    "t": 12, "st": 3077, "n": "Month_Loss", "did": "ML0000000000000000000000000000002",
    "f": "Month([Loss Date]@ID)",
}
ATT_LOSS_YR_MTH = {
    "t": 12, "st": 3077, "n": "LOSS_YR_MTH", "did": "LM0000000000000000000000000000003",
    "f": 'Concat(Loss_Year@ID,"-",Month_Loss@ID)',
}
ATT_FRAUD_SCORE_BASE = {
    "t": 12, "st": 3072, "n": "Fraud Score", "did": FRAUD_SCORE_DID,
}  # base attribute — NO formula

MX_HIGH_FRAUD_CLAIMS = {
    "t": 4, "st": 1024, "n": "High Fraud Claims",
    "did": "1EFA3F094B46BD2A24F88ABFDD13ACBE", "um": True,
    "f": "Sum<UseLookupForAttributes=False >([High Fraud Flag]){~+}",
}
MX_NET_LOSSES = {
    "t": 4, "st": 1024, "n": "Net Losses",
    "did": "B10EE5CE32408E9CE60E71B2C5AB857C", "um": True,
    "f": "Sum<UseLookupForAttributes=False >([Net Loss]@ID){~+}",
}

DATASET = {
    "att": [
        ATT_FRAUD_SCORE_BASE,
        ATT_HIGH_FRAUD_FLAG, ATT_LITIGATION_FLAG, ATT_NET_LOSS,
        ATT_LOSS_YEAR, ATT_MONTH_LOSS, ATT_LOSS_YR_MTH,
    ],
    "mx": [MX_HIGH_FRAUD_CLAIMS, MX_NET_LOSSES],
}


def _bare_compiler():
    from app.agents.ir_compiler import IRCompilerAgent
    agent = IRCompilerAgent.__new__(IRCompilerAgent)
    agent.db = None
    agent.job = None
    agent._caption_counter = 0
    agent._id_to_name = {}
    return agent


def _defs_maps(ds=None):
    return collect_object_definitions({"DS1": ds or DATASET})


# ──────────────────────────────────────────────────────────────────
#  [1] Harvest
# ──────────────────────────────────────────────────────────────────

def test_collect_object_definitions_captures_derived_attrs_and_metrics():
    by_did, by_name = _defs_maps()
    # 6 derived att entries WITH f + 2 mx metrics WITH f; base attr excluded
    assert len(by_did) == 8
    hff = by_name["high fraud flag"]
    assert hff["formula"] == "IF(([Fraud Score]@ID >= 70),1,0)"
    assert hff["st"] == 3077
    nl = by_name["net loss"]
    assert nl["formula"] == "([Paid Amount USD] + [Reserve Amount USD]) - [Recovery Amount USD]"
    assert nl["dsc"] == "Paid plus reserve minus recovery"
    assert FRAUD_SCORE_DID not in by_did, "base attributes must not enter the definition map"
    assert "high fraud claims" in by_name, "mx metrics join the same definition space"


def test_collect_keeps_first_on_conflicting_duplicate_did():
    dup = dict(ATT_NET_LOSS, f="Something Else")
    ds_map = {"DS1": {"att": [ATT_NET_LOSS], "mx": []},
              "DS2": {"att": [dup], "mx": []}}
    by_did, _ = collect_object_definitions(ds_map)
    assert len(by_did) == 1
    assert by_did[ATT_NET_LOSS["did"]]["formula"] == ATT_NET_LOSS["f"]


def test_collect_reads_current_form_nested_payload_shape():
    """Current Library payloads moved the formula INSIDE the ID form
    (`fs[].f`) and mark derived attributes with `da:true`. The old att-level
    `f` shape must keep working too."""
    current_shape = {
        "t": 12, "st": 3077, "n": "High Fraud Flag",
        "did": ATT_HIGH_FRAUD_FLAG["did"], "da": True,
        "fs": [{"fnm": "ID", "fid": "45C11FA478E745FEA08D781CEA190FE5",
                # form-level formula — no att-level `f` in this generation
                "f": "IF(([Fraud Score]@ID >= 70),1,0)"}],
    }
    by_did, by_name = collect_object_definitions(
        {"DS": {"att": [current_shape], "mx": []}})
    rec = by_did[ATT_HIGH_FRAUD_FLAG["did"]]
    assert rec["formula"] == "IF(([Fraud Score]@ID >= 70),1,0)"
    assert rec["source_field"].startswith("fs:")
    assert rec["derived_attr"] is True
    assert by_name["high fraud flag"]["derived_attr"] is True


# ──────────────────────────────────────────────────────────────────
#  [2] Resolver
# ──────────────────────────────────────────────────────────────────

def test_resolver_inlines_high_fraud_flag_chain():
    _, by_name = _defs_maps()
    res = resolve_expression(MX_HIGH_FRAUD_CLAIMS["f"], {}, by_name)
    assert res.chain and res.chain[0]["name"] == "High Fraud Flag"
    assert "[High Fraud Flag]" not in res.text
    assert "[Fraud Score]" in res.text          # physical ref preserved for compiler


def test_resolver_inlines_net_loss_arithmetic_body():
    _, by_name = _defs_maps()
    res = resolve_expression(MX_NET_LOSSES["f"], {}, by_name)
    assert "Paid Amount USD" in res.text and "Recovery Amount USD" in res.text
    assert "Total Incurred" not in res.text and "Salvage" not in res.text


def test_resolver_recurses_through_nested_definitions():
    _, by_name = _defs_maps()
    res = resolve_expression("[LOSS_YR_MTH]", {}, by_name)
    assert "Concat" in res.text and "Loss_Year" not in res.text.replace("LOSS_YR_MTH", "")
    names = [c["name"] for c in res.chain]
    assert set(names) == {"LOSS_YR_MTH", "Loss_Year", "Month_Loss"}


def test_resolver_cycle_safe_a_b():
    defs = {
        "a": {"name": "A", "formula": "[B] + 1"},
        "b": {"name": "B", "formula": "[A] + 1"},
    }
    res = resolve_expression("[A]", {}, defs)
    assert res.unresolved, "mutual recursion must be reported, not spun on"


def test_resolver_never_touches_unknown_refs():
    res = resolve_expression("Sum([Totally Unknown Thing]){~+}", {}, {})
    assert res.text == "Sum([Totally Unknown Thing]){~+}"
    assert res.chain == []


# ──────────────────────────────────────────────────────────────────
#  [3] Wiring precedence — ground truth beats everything after it
# ──────────────────────────────────────────────────────────────────

def _measure_with(name, mstr_id, text):
    return IRMeasure(
        id=f"id-{mstr_id}", mstr_id=mstr_id, name=name,
        local_name=name.replace(" ", "_"), remote_name=name.replace(" ", "_"),
        caption=name, tableau_calc="", confidence=0.5, expression_text=text,
    )


def test_apply_definition_expansions_pins_ground_truth_calcs():
    ir = BIIR(job_id="t")
    ir.object_definitions = dict(zip(("by_did", "by_name_lower"), _defs_maps()))
    ir.measures = [
        _measure_with("High Fraud Claims", MX_HIGH_FRAUD_CLAIMS["did"], MX_HIGH_FRAUD_CLAIMS["f"]),
        _measure_with("Net Losses", MX_NET_LOSSES["did"], MX_NET_LOSSES["f"]),
        _measure_with("Subrogation", "58601298AE4B0401E6CE07BDE298AE4B",
                      "Sum<UseLookupForAttributes=False >(Subrogation){~+}"),
    ]
    n = apply_definition_expansions(ir, _bare_compiler())

    assert n == 2, "only the two measures referencing harvested defs expand"

    hfc = ir.measures[0]
    assert hfc.precomputed_calc == hfc.tableau_calc
    assert "70" in hfc.tableau_calc and "IF" in hfc.tableau_calc.upper()
    assert hfc.definition_chain[0]["name"] == "High Fraud Flag"
    assert hfc.expression_text == MX_HIGH_FRAUD_CLAIMS["f"], (
        "raw source formula must stay untouched for the UI lineage panel"
    )

    nl = ir.measures[1]
    assert "[Paid Amount USD]" in nl.tableau_calc and "[Reserve Amount USD]" in nl.tableau_calc
    assert "Total Incurred" not in nl.tableau_calc, "LLM-cache Net Loss must be gone"
    assert "Salvage" not in nl.tableau_calc

    untouched = ir.measures[2]
    assert untouched.precomputed_calc is None and untouched.definition_chain is None


# ──────────────────────────────────────────────────────────────────
#  [3b] mexp fast-path must never win over resolved text (job 1622b1cc)
# ──────────────────────────────────────────────────────────────────

def test_expansion_overrides_mexp_fastpath_and_restores_ast():
    """Regression: with a non-null mexp AST present, the compiler's AST
    fast-path fired before our resolved text and emitted literal SELF-references
    (SUM([High Fraud Claims])) that got pinned via precomputed_calc and then
    rejected by the emitter as illegal aggregation nesting."""
    ir = BIIR(job_id="t")
    by_did, by_name = collect_object_definitions({"DS": DATASET})
    ir.object_definitions = {"by_did": by_did, "by_name_lower": by_name}

    ast = {"ft": 12, "args": [{"did": ATT_HIGH_FRAUD_FLAG["did"], "t": 12}], "prms": []}
    m = _measure_with("High Fraud Claims", MX_HIGH_FRAUD_CLAIMS["did"],
                      MX_HIGH_FRAUD_CLAIMS["f"])
    m.expression_ast = dict(ast)
    ir.measures = [m]

    assert apply_definition_expansions(ir, _bare_compiler()) == 1
    assert "[High Fraud Claims]" not in m.tableau_calc, (
        "self-reference pinned — emitter will skip this field"
    )
    assert "70" in m.tableau_calc
    assert m.expression_ast == ast, "provenance AST must survive the pass untouched"


def test_total_claims_collapses_double_aggregation():
    """Sum(Count(x)) at report grain is ONE aggregate in Tableau; emitting
    SUM over the aggregate calc [Count (Claim ID)] is illegal nesting.
    Estate convention: undecorated MSTR Count stays COUNT (only an explicit
    Distinct=True decoration promotes to COUNTD), so the collapsed alias is
    COUNT([Claim ID]) — identical to its sibling metric's translation."""
    count_def = {
        "t": 4, "st": 1024, "n": "Count (Claim ID)",
        "did": "93B2A1A14045562420AD10BBBB42FD43", "um": True,
        "f": "Count<UseLookupForAttributes=False >([Claim ID]){~+}",
    }
    total_claims = {
        "t": 4, "st": 1024, "n": "Total_Claims",
        "did": "CA1F6172CA4F5E0FA1C7DB8A2D6A5F31", "um": True,
        "f": "Sum<UseLookupForAttributes=False >([Count (Claim ID)]){~+}",
    }
    ds = {"DS": {"att": DATASET["att"], "mx": DATASET["mx"] + [count_def, total_claims]}}
    by_did, by_name = collect_object_definitions(ds)

    ir = BIIR(job_id="t")
    ir.object_definitions = {"by_did": by_did, "by_name_lower": by_name}
    tc = _measure_with("Total_Claims", total_claims["did"], total_claims["f"])
    tc.expression_ast = {"ft": 12, "args": [{"did": count_def["did"], "t": 4}], "prms": []}
    ir.measures = [tc]

    assert apply_definition_expansions(ir, _bare_compiler()) == 1
    assert tc.tableau_calc == "COUNT([Claim ID])", tc.tableau_calc


def test_distinct_count_decoration_survives_text_path():
    """Regression: Count<Distinct=True>(…) wired through the TEXT path lost
    its distinctness and emitted plain COUNT — only expansion-pass measures
    were normalized. The compiler must normalize decorations at any depth."""
    agent = _bare_compiler()
    m = IRMeasure(
        id="s", mstr_id="M-States", name="States", local_name="States",
        remote_name="States", caption="States", tableau_calc="", confidence=0.5,
        expression_text="Count<Distinct=True , UseLookupForAttributes=False >(State){~+}",
        expression_ast=None,
    )
    calc = agent._compile_expression(m, "propagate", "null")
    assert calc.upper().startswith("COUNTD("), calc


# ──────────────────────────────────────────────────────────────────
#  [3c] nested aggregates from inlined metric bodies (job 655daf13)
# ──────────────────────────────────────────────────────────────────

_RATE_DEFS = {
    "lit_claims": {
        "t": 4, "st": 1024, "n": "Litigation Claims",
        "did": "D1D1D1D1D1D1D1D1D1D1D1D1D1D1D1D1", "um": True,
        "f": "Sum<UseLookupForAttributes=False >(Litigation_Flag){~+}",
    },
    "total": {
        "t": 4, "st": 1024, "n": "Total_Claims",
        "did": "T0T0T0T0T0T0T0T0T0T0T0T0T0T0T0T0", "um": True,
        "f": "Sum<UseLookupForAttributes=False >([Count (Claim ID)]){~+}",
    },
    "count": {
        "t": 4, "st": 1024, "n": "Count (Claim ID)",
        "did": "93B2A1A14045562420AD10BBBB42FD43", "um": True,
        "f": "Count<UseLookupForAttributes=False >([Claim ID]){~+}",
    },
    "tot_incur": {
        "t": 4, "st": 1024, "n": "Total Incurred",
        "did": "E2E2E2E2E2E2E2E2E2E2E2E2E2E2E2E2", "um": True,
        "f": "Sum<UseLookupForAttributes=False >([Total Incurred USD]){~+}",
    },
}


def _rate_ir(extra_raw):
    ds = {"DS": {"att": DATASET["att"],
                 "mx": DATASET["mx"] + list(_RATE_DEFS.values())}}
    by_did, by_name = collect_object_definitions(ds)
    ir = BIIR(job_id="t")
    ir.object_definitions = {"by_did": by_did, "by_name_lower": by_name}
    m = _measure_with("Probe", "PROBE-0000-0000-0000-000000000001", extra_raw)
    m.expression_ast = None
    ir.measures = [m]
    return ir, m


def test_rate_expansion_has_no_nested_aggregates():
    """Job 655daf13: rate denominators compiled to SUM(COUNT([Claim ID])) —
    Tableau rejects nested aggregates; the pass must flatten them."""
    raw = "[Litigation Claims] / Total_Claims"
    ir, m = _rate_ir(raw)
    assert apply_definition_expansions(ir, _bare_compiler()) == 1
    c = m.tableau_calc
    assert "SUM(COUNT(" not in c.upper().replace(" ", ""), c
    assert c == ("IIF(COUNT([Claim ID]) = 0, NULL, "
                 'SUM(IF ([Litigation] = "Yes") THEN 1 ELSE 0 END)'
                 " / COUNT([Claim ID]))"), c


def test_incurred_loss_inner_aggregate_dissolved():
    """Job 655daf13: Sum(IF(c,[Total Incurred],0)) expanded to
    THEN SUM([Total Incurred USD]) — a nested agg under the outer SUM."""
    raw = ('Sum<UseLookupForAttributes=False >'
           '(IF((Litigation@ID = "1"),[Total Incurred],0)){~+}')
    ir, m = _rate_ir(raw)
    assert apply_definition_expansions(ir, _bare_compiler()) == 1
    assert m.tableau_calc == (
        'SUM(IF ([Litigation] = "1") THEN [Total Incurred USD] ELSE 0 END)'
    ), m.tableau_calc


def test_expansion_never_pins_a_self_reference():
    """Even if compilation goes sideways, a calc referencing the measure itself
    must not be pinned (the emitter skips self-nested fields downstream)."""
    by_did, by_name = collect_object_definitions({"DS": DATASET})
    weird = {"t": 12, "st": 3077, "n": "Loop", "did": "LOOP0000000000000000000000000001",
             "formula": "[Net Losses]", "name": "Loop"}
    by_name["loop"] = weird
    by_did["LOOP0000000000000000000000000001"] = weird

    ir = BIIR(job_id="t")
    ir.object_definitions = {"by_did": by_did, "by_name_lower": by_name}
    m = IRMeasure(
        id="x", mstr_id="M-LOOP", name="Net Losses", local_name="Net_Losses",
        remote_name="Net_Losses", caption="Net Losses", tableau_calc="",
        confidence=0.5,
        expression_text="Sum<UseLookupForAttributes=False >([Loop]){~+}",
        expression_ast={"ft": 12, "args": [{"did": "LOOP0000000000000000000000000001", "t": 12}],
                        "prms": []},
    )
    ir.measures = [m]
    apply_definition_expansions(ir, _bare_compiler())
    if m.precomputed_calc:
        bad = {"SUM([Net_Losses])", "SUM([Net Losses])"}
        assert m.precomputed_calc.strip() not in bad


# ──────────────────────────────────────────────────────────────────
#  [4] AI stage must refuse to override pinned ground truth
# ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ai_translation_skips_precomputed_ground_truth(db_session, tmp_path):
    """precomputed_calc (set by definition expansion) removes the measure from
    AI candidates even when the Tier-1 cache holds an answer."""
    import uuid as _uuid

    from app.agents.ai_translation import AITranslationAgent
    from app.models.job import Job as JobModel

    job = JobModel(
        id=f"dd-{_uuid.uuid4().hex[:8]}", name="DD", status="PENDING",
        mstr_base_url="https://env-test.cloud.strategy.com/MicroStrategyLibrary",
        mstr_project_id="TESTPROJECT",
        artifacts_dir=str(tmp_path),
    )
    db_session.add(job)
    db_session.commit()

    agent = AITranslationAgent(db=db_session, job=job, artifacts_dir=str(tmp_path))
    called = False

    async def _spy(_measure):
        nonlocal called
        called = True
        return None

    agent._translate = _spy  # type: ignore[method-assign]

    m = IRMeasure(
        id="x", mstr_id="M-X", name="Net Losses", local_name="Net_Losses",
        remote_name="Net_Losses", caption="Net Losses", tableau_calc="",
        confidence=0.5, expression_text="Sum([Net Loss]@ID)",
        precomputed_calc="SUM(([Paid Amount USD] + [Reserve Amount USD]) - [Recovery Amount USD])",
    )
    await agent.run(BIIR(job_id="t", measures=[m]))
    assert called is False, "ground-truth-pinned measure reached the AI stage"


# ──────────────────────────────────────────────────────────────────
#  [5] Honest method labeling
# ──────────────────────────────────────────────────────────────────

def test_honest_method_reports_harvested_expansion():
    from app.agents.ai_translation import _honest_method

    m = SimpleNamespace(definition_chain=[{"name": "Net Loss", "formula": "(…)"}])
    assert _honest_method(m) == "Harvested Definition Expansion"
