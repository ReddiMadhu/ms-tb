"""
One-shot probe: does MicroStrategy's Model API expose the DERIVED attribute
'High Fraud Flag' (GUID harvested from the High Fraud Claims metric AST)?

Reads credentials from backend/.env. Never prints secrets.
Usage:  venv\\Scripts\\python.exe scripts\\probe_hff_metadata.py [ATTR_GUID]
"""
import json
import os
import sys

import httpx

GUID = sys.argv[1] if len(sys.argv) > 1 else "CA915844CF4E214775EE71960F823A8D"


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

    with httpx.Client(timeout=60, follow_redirects=True) as c:
        # 1. Login
        r = c.post(f"{base}/api/auth/login",
                   json={"username": env["MSTR_USERNAME"],
                         "password": env["MSTR_PASSWORD"]})
        r.raise_for_status()
        token = r.headers.get("X-MSTR-AuthToken")
        headers = {"X-MSTR-AuthToken": token,
                   "X-MSTR-ProjectID": env.get("MSTR_PROJECT_ID", ""),
                   "Accept": "application/json"}
        print(f"auth OK (project {env.get('MSTR_PROJECT_ID', '')})")

        # 1b. Resolve project id when .env left it empty
        if not env.get("MSTR_PROJECT_ID"):
            pr = c.get(f"{base}/api/projects",
                       headers={"X-MSTR-AuthToken": token, "Accept": "application/json"})
            projects = pr.json() if pr.status_code == 200 else []
            if not projects:
                raise SystemExit(f"no accessible projects (HTTP {pr.status_code})")
            proj = projects[0]
            headers["X-MSTR-ProjectID"] = proj["id"]
            print(f"resolved project: {proj['name']} ({proj['id']})")

        # 2. Ask the Model API for the derived attribute itself
        r = c.get(f"{base}/api/model/attributes/{GUID}", headers=headers)
        print(f"\nGET /api/model/attributes/{GUID}  ->  HTTP {r.status_code}")
        try:
            data = r.json()
        except Exception:
            print(r.text[:400])
            return

        def find_expressions(node, path="root"):
            """Recursively surface anything formula-like in the payload."""
            found = []
            if isinstance(node, dict):
                for k, v in node.items():
                    p = f"{path}.{k}"
                    if isinstance(v, str) and any(
                        w in v for w in ("IF(", "IF (", ">=", "Score")
                    ):
                        found.append((p, v))
                    else:
                        found += find_expressions(v, p)
            elif isinstance(node, list):
                for i, v in enumerate(node[:50]):
                    found += find_expressions(v, f"{path}[{i}]")
            return found

        print("-- keys:", list(data.keys()) if isinstance(data, dict) else type(data))
        if isinstance(data, dict) and data.get("name"):
            print("-- name:", data.get("name"))
        exprs = find_expressions(data)
        if exprs:
            print("\n== FORMULA-LIKE CONTENT FOUND ==")
            for p, v in exprs[:10]:
                print(f"  {p}\n    {v}")
        else:
            print("\n== no formula-like text anywhere in the response ==")
            print(json.dumps(data, indent=2)[:1200])

        # 3. Also try the cube/dossier-side endpoint variant used elsewhere
        r2 = c.get(f"{base}/api/model/attributes/{GUID}?showExpressionAs=tree",
                   headers=headers)
        print(f"\nGET …?showExpressionAs=tree  ->  HTTP {r2.status_code}")
        try:
            d2 = r2.json()
            e2 = find_expressions(d2)
            print("formula-like:", *e2[:6], sep="\n  ") if e2 else print(
                json.dumps(d2, indent=2)[:600])
        except Exception as ex:
            print("parse error:", ex)

        # 4. Does the search index know the object at all?
        r3 = c.get(f"{base}/api/searches/results",
                   headers=headers,
                   params={"name": "High Fraud Flag", "limit": 10})
        print(f"\nGET /api/searches/results?name='High Fraud Flag' -> HTTP {r3.status_code}")
        for o in (r3.json().get("result") or []):
            print("   ", json.dumps({k: o.get(k) for k in
                  ("name", "id", "type", "subType", "versionId")}))

        # 5. Does the METRIC's model tree embed the referenced attribute's definition?
        r4 = c.get(f"{base}/api/model/metrics/1EFA3F094B46BD2A24F88ABFDD13ACBE",
                   headers=headers, params={"showExpressionAs": "tree"})
        print(f"\nGET /api/model/metrics/1EFA…(High Fraud Claims)?showExpressionAs=tree "
              f"-> HTTP {r4.status_code}")
        d4 = r4.json()
        print(json.dumps(d4, indent=2)[:1500])


if __name__ == "__main__":
    main()
