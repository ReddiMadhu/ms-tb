"""Sanity print: final compiled calcs from harvested definitions."""
import sys

sys.path.insert(0, "src")
sys.path.insert(0, "tests")
from test_derived_definitions import (  # noqa: E402
    DATASET, MX_HIGH_FRAUD_CLAIMS, MX_NET_LOSSES,
    _bare_compiler, _measure_with,
)
from app.agents.ir_compiler import BIIR  # noqa: E402
from app.services.pipeline.orchestrator import (  # noqa: E402
    apply_definition_expansions, collect_object_definitions,
)

ir = BIIR(job_id="t")
d, n = collect_object_definitions({"DS": DATASET})
ir.object_definitions = {"by_did": d, "by_name_lower": n}
ir.measures = [
    _measure_with("High Fraud Claims", MX_HIGH_FRAUD_CLAIMS["did"], MX_HIGH_FRAUD_CLAIMS["f"]),
    _measure_with("Net Losses", MX_NET_LOSSES["did"], MX_NET_LOSSES["f"]),
]
apply_definition_expansions(ir, _bare_compiler())
for m in ir.measures:
    chain = " → ".join(c["name"] for c in (m.definition_chain or []))
    print(f"{m.name}")
    print(f"  raw  : {m.expression_text}")
    print(f"  calc : {m.tableau_calc}")
    print(f"  chain: {chain or '-'}")
