"""Final verification: distinct-value domain hypothesis + misc."""
from tableauhyperapi import HyperProcess, Telemetry, Connection

HYPER = r"C:\Users\madhu\Desktop\ms-tb\backend\artifacts\87b07292-cd96-47a3-b1f9-2fc6b6088f61\hyper\extract.hyper"
T = '"Extract"."Extract"'

QUERIES = [
    ("DISTINCT DOMAIN CHECKS", f"""
        SELECT COUNT(DISTINCT "Fraud Score") AS distinct_scores,
               COUNT(DISTINCT CASE WHEN "Fraud Score" >= 70 THEN "Fraud Score" END) AS distinct_scores_ge70
        FROM {T}
    """),
    ("DISTINCT LITIGATION VALUES", f"""
        SELECT COUNT(DISTINCT "Litigation") AS n_dist,
               COUNT(DISTINCT CASE WHEN "Litigation" = 'Yes' THEN "Litigation" END) AS distinct_eq_yes
        FROM {T}
    """),
    ("MAX CLAIM INCURRED (overall)", f"""
        SELECT MAX("Total Incurred USD") FROM {T}
    """),
    ("MAX CLAIM IN RANK-1 STATE (FL)", f"""
        SELECT MAX("Total Incurred USD") FROM {T} WHERE "State" = 'FL'
    """),
    ("LITIGATION BY STATE TOTAL (row-level)", f"""
        SELECT SUM(CASE WHEN "Litigation" = 'Yes' THEN 1 ELSE 0 END) FROM {T}
    """),
    ("HIGH FRAUD FLAG ROW-LEVEL SUM", f"""
        SELECT SUM(CASE WHEN "Fraud Score" >= 70 THEN 1 ELSE 0 END) FROM {T}
    """),
]

with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hp:
    with Connection(endpoint=hp.endpoint, database=HYPER) as con:
        for title, q in QUERIES:
            print(f"\n== {title} ==")
            with con.execute_query(q) as res:
                for row in res:
                    print("   ", [str(v) for v in row])
