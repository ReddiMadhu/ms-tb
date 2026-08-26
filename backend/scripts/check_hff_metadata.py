"""Search EVERY mstr_definition blob in the local DB for derived-attribute evidence."""
import json
import sqlite3

GUID = "CA915844CF4E214775EE71960F823A8D"
conn = sqlite3.connect(r"artifacts\migrations.db")
cur = conn.cursor()
rows = cur.execute(
    "SELECT name, type_name, mstr_id, LENGTH(mstr_definition), mstr_definition FROM objects"
).fetchall()

print(f"{len(rows)} objects total")
for name, tname, mid, ln, defn in rows:
    blob = defn or ""
    hit = ("High Fraud Flag" in blob) or (GUID in blob)
    mark = "  <<< MENTIONS HIGH FRAUD FLAG" if hit else ""
    print(f"  [{tname:<10}] {name:<40} id={mid[:12]}… def={ln or 0}B{mark}")

# deep-dive every blob that mentions it
for name, tname, mid, ln, defn in rows:
    if not defn:
        continue
    if "High Fraud Flag" in defn or GUID in defn:
        d = json.loads(defn)

        def walk(node, path="root"):
            if isinstance(node, dict):
                if "expression" in node and node.get("expression"):
                    print(f"\n### {name} :: {path}.expression")
                    print(json.dumps(node["expression"], indent=2)[:600])
                for k, v in node.items():
                    walk(v, f"{path}.{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node[:200]):
                    walk(v, f"{path}[{i}]")

        walk(d)
conn.close()
