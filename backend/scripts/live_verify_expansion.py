"""
LIVE verification of derived-definition expansion against the real MSTR env.
Read-only: authenticates, pulls the dossier instance payload, harvests
definitions, expands three affected measures through the REAL compiler,
and prints before/after. No pipeline artifacts are written.
"""
import json
import os
import sqlite3
import sys

sys.path.insert(0, "src")

import httpx  # noqa: E402

from app.agents.expression_resolver import resolve_expression  # noqa: E402
from app.agents.ir_compiler import BIIR, IRMeasure, IRCompilerAgent  # noqa: E402
from app.services.pipeline.orchestrator import (  # noqa: E402
    apply_definition_expansions, collect_object_definitions,
)


def load_env() -> dict:
    env = {}
    for line in open(os.path.join(os.path.dirname(__file__), "..", ".env"), encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def bare_compiler():
    agent = IRCompilerAgent.__new__(IRCompilerAgent)
    agent.db = None
    agent.job = None
    agent._caption_counter = 0
    agent._id_to_name = {
        "B82168CCC24FD779357A6FAE0AD774E6": "Fraud Score",      # Fraud Score
        "CE0863496E43CA3894ABBBAA783EE2F4": "Paid Amount USD",
        "F90C4616E94FFE75FA102BAE4C870139": "Reserve Amount USD",
        "85E015CDC44A3CD76E5C67BC33DD35EF7": "Recovery Amount USD",
        "B29D7E26D34DF17A0D62E7978EA450EE": "Litigation",
    }
    return agent


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    env = load_env()
    base = env["MSTR_BASE_URL"].rstrip("/")

    conn = sqlite3.connect(r"artifacts\migrations.db")
    dossier_id = conn.execute(
        "SELECT mstr_id FROM objects WHERE type_name='dossier'").fetchone()[0]
    conn.close()

    with httpx.Client(timeout=90, follow_redirects=True) as c:
        r = c.post(f"{base}/api/auth/login",
                   json={"username": env["MSTR_USERNAME"],
                         "password": env["MSTR_PASSWORD"]})
        r.raise_for_status()
        h = {"X-MSTR-AuthToken": r.headers["X-MSTR-AuthToken"], "Accept": "application/json"}
        projects = c.get(f"{base}/api/projects", headers=h).json()
        h["X-MSTR-ProjectID"] = env.get("MSTR_PROJECT_ID") or projects[0]["id"]

        inst = c.post(f"{base}/api/dossiers/{dossier_id}/instances", headers=h, json={}).json()
        mid = inst.get("mid") or inst.get("instanceId")
        full = c.get(f"{base}/api/dossiers/{dossier_id}/instances/{mid}", headers=h).json()
        try:
            with open(os.path.join(os.path.dirname(__file__), "..", "artifacts",
                                   "live_instance_now.json"), "w", encoding="utf-8") as fh:
                json.dump(full, fh, indent=2)
            print("payload saved → artifacts/live_instance_now.json")
        except Exception as de:
            print("payload dump skipped:", de)

    ds_map = full.get("datasets") or {}
    # ── payload shape diagnostics ──
    for ds_id, ds in ds_map.items():
        if not isinstance(ds, dict):
            continue
        att = ds.get("att") or []
        with_f = [a for a in att if isinstance(a, dict) and a.get("f")]
        sts = sorted({a.get("st") for a in att if isinstance(a, dict)})
        print(f"dataset {ds_id}: keys={list(ds.keys())}")
        print(f"  att={len(att)} (with f: {len(with_f)}) st-values={sts}")
        if with_f:
            s = json.dumps(with_f[0])
            print(f"  sample f-entry: {s[:160]}")
        elif att:
            s = json.dumps(att[0])
            print(f"  sample att-entry: {s[:200]}")

    by_did, by_name = collect_object_definitions(ds_map)
    print(f"harvested {len(by_did)} object definitions from LIVE instance")
    for n in sorted(by_name):
        rec = by_name[n]
        tag = "DERIVED" if rec["st"] == 3077 else "metric  "
        print(f"  [{tag}] {rec['name']:<20} := {rec['formula'][:80]}")

    ir = BIIR(job_id="live")
    ir.object_definitions = {"by_did": by_did, "by_name_lower": by_name}

    targets = ["High Fraud Claims", "Net Losses", "Litigation Claims"]
    for entry_ds in ds_map.values():
        for e in entry_ds.get("mx") or []:
            if e.get("n") in targets and e.get("f"):
                ir.measures.append(IRMeasure(
                    id=f"live-{e['did']}", mstr_id=e["did"], name=e["n"],
                    local_name=e["n"].replace(" ", "_"),
                    remote_name=e["n"].replace(" ", "_"), caption=e["n"],
                    tableau_calc="", confidence=0.5, expression_text=e["f"],
                ))

    expanded = apply_definition_expansions(ir, bare_compiler())
    print(f"\nexpanded {expanded}/{len(ir.measures)} measures — FINAL CALCS:")
    for m in ir.measures:
        chain = " → ".join(c["name"] for c in (m.definition_chain or [])) or "-"
        print(f"\n{m.name}\n  raw : {m.expression_text}\n  calc: {m.tableau_calc}\n  via : {chain}")


if __name__ == "__main__":
    main()
