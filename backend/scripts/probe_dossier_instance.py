"""
Final probe: pull the FULL dossier instance payload and inspect EVERY
datasets{dsId}.mx[] entry — looking for 'High Fraud Flag' (or its GUID)
with an expression, i.e. can we extract the derived attribute at all?
"""
import json
import os
import sqlite3
import sys

import httpx

GUID = "CA915844CF4E214775EE71960F823A8D"


def load_env() -> dict:
    env = {}
    path = os.path.join(os.path.dirname(__file__), "..", ".env")
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def main() -> None:
    env = load_env()
    base = env["MSTR_BASE_URL"].rstrip("/")

    # dossier id from local DB
    conn = sqlite3.connect(r"artifacts\migrations.db")
    dossier_id, dossier_name = conn.execute(
        "SELECT mstr_id, name FROM objects WHERE type_name='dossier'"
    ).fetchone()
    conn.close()
    print(f"dossier: {dossier_name} ({dossier_id})")

    with httpx.Client(timeout=90, follow_redirects=True) as c:
        r = c.post(f"{base}/api/auth/login",
                   json={"username": env["MSTR_USERNAME"],
                         "password": env["MSTR_PASSWORD"]})
        r.raise_for_status()
        token = r.headers["X-MSTR-AuthToken"]
        h = {"X-MSTR-AuthToken": token, "Accept": "application/json"}
        pr = c.get(f"{base}/api/projects", headers=h).json()
        pid = env.get("MSTR_PROJECT_ID") or pr[0]["id"]
        h["X-MSTR-ProjectID"] = pid

        inst = c.post(f"{base}/api/dossiers/{dossier_id}/instances",
                      headers=h, json={}).json()
        iid = inst.get("instanceId")
        mid = inst.get("middleName") or iid
        print("instance:", iid)

        # canonical mid used by our orchestrator harvest
        full = c.get(f"{base}/api/dossiers/{dossier_id}/instances/{mid}",
                     headers=h).json()

        total_mx, hits = 0, []
        for ds_id, ds in (full.get("datasets") or {}).items():
            print(f"\ndataset {ds_id}: top-keys={list(ds.keys())}")
            for e in ds.get("mx") or []:
                total_mx += 1
                nm = str(e.get("name", ""))
                if "Fraud" in nm or e.get("did") == GUID:
                    hits.append(e)
            # also scan every other list-valued key for formula-bearing entries
            for key, val in ds.items():
                if key == "mx" or not isinstance(val, list):
                    continue
                for e in val:
                    if isinstance(e, dict) and (
                        "High Fraud Flag" in json.dumps(e) or e.get("did") == GUID
                    ):
                        print(f"  !! HFF reference under dataset key '{key}':")
                        print("  ", json.dumps(e)[:500])

        print(f"\ntotal mx entries: {total_mx}")
        if hits:
            print("== mx entries mentioning Fraud ==")
            for e in hits:
                print(json.dumps(e, indent=2))
        else:
            print("== NO mx entry for High Fraud Flag — attributes do not appear in mx ==")

        # brute-force: any string occurrence anywhere in the raw payload?
        raw = json.dumps(full)
        print("\n'High Fraud Flag' occurrences in full instance payload:",
              raw.count("High Fraud Flag"))
        print("GUID occurrences:", raw.count(GUID))


if __name__ == "__main__":
    main()
