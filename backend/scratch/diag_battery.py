"""Full diagnostic battery on extract.hyper - reproduce every disputed KPI."""
from tableauhyperapi import HyperProcess, Telemetry, Connection

HYPER = r"C:\Users\madhu\Desktop\ms-tb\backend\artifacts\87b07292-cd96-47a3-b1f9-2fc6b6088f61\hyper\extract.hyper"
T = '"Extract"."Extract"'

QUERIES = [
    ("TOP-LEVEL TOTALS", """
        SELECT COUNT(*) AS claims,
               SUM("Total Incurred USD") AS incurred,
               SUM("Paid Amount USD") AS paid,
               SUM("Reserve Amount USD") AS reserve,
               SUM("Recovery Amount USD") AS recovery,
               SUM("Subrogation") AS subro,
               SUM("Salvage") AS salvage,
               AVG("Fraud Score") AS avg_fraud,
               AVG("Claim Resolution Time Days") AS avg_res_days
        FROM {T}
    """),
    ("FRAUD SCORE DISTRIBUTION", """
        SELECT CASE WHEN "Fraud Score" >= 90 THEN '90+'
                    WHEN "Fraud Score" >= 80 THEN '80-89'
                    WHEN "Fraud Score" >= 70 THEN '70-79'
                    WHEN "Fraud Score" >= 60 THEN '60-69'
                    WHEN "Fraud Score" >= 50 THEN '50-59'
                    WHEN "Fraud Score" >= 40 THEN '40-49'
                    ELSE '<40' END AS band,
               COUNT(*) AS n
        FROM {T} GROUP BY 1 ORDER BY 1
    """),
    ("HIGH FRAUD >=70 / >=80 / >=90", """
        SELECT SUM(CASE WHEN "Fraud Score" >= 70 THEN 1 ELSE 0 END) AS ge70,
               SUM(CASE WHEN "Fraud Score" >= 80 THEN 1 ELSE 0 END) AS ge80,
               SUM(CASE WHEN "Fraud Score" >= 90 THEN 1 ELSE 0 END) AS ge90,
               MIN("Fraud Score") AS mn, MAX("Fraud Score") AS mx
        FROM {T}
    """),
    ("LITIGATION COLUMN VALUES", """
        SELECT COALESCE("Litigation", '<null>') AS lit, COUNT(*) AS n
        FROM {T} GROUP BY 1 ORDER BY 2 DESC
    """),
    ("CLAIM STATUS VALUES", """
        SELECT "Claim Status", COUNT(*) AS n
        FROM {T} GROUP BY 1 ORDER BY 2 DESC
    """),
    ("CLAIM STATUS CATEGORY VALUES", """
        SELECT "Claim Status Category", COUNT(*) AS n
        FROM {T} GROUP BY 1 ORDER BY 2 DESC
    """),
    ("BY REGION (count, incurred)", """
        SELECT "Region", COUNT(*) AS n, SUM("Total Incurred USD") AS incurred
        FROM {T} GROUP BY 1 ORDER BY 3 DESC
    """),
    ("BY REGION_STATE col", """
        SELECT "Region State", COUNT(*) AS n
        FROM {T} GROUP BY 1 ORDER BY 2 DESC LIMIT 30
    """),
    ("STATE x REGION mapping", """
        SELECT "State", MIN("Region") AS region, COUNT(*) AS n, SUM("Total Incurred USD") AS inc
        FROM {T} GROUP BY 1 ORDER BY 4 DESC LIMIT 20
    """),
    ("TOP STATES BY INCURRED", """
        SELECT "State", SUM("Total Incurred USD") AS inc, COUNT(*) AS n
        FROM {T} GROUP BY 1 ORDER BY 2 DESC LIMIT 10
    """),
    ("LOSS CAUSE TOP 12", """
        SELECT "Loss Cause", SUM("Total Incurred USD") AS inc
        FROM {T} GROUP BY 1 ORDER BY 2 DESC LIMIT 12
    """),
    ("COVERAGE BY INCURRED", """
        SELECT "Coverage", SUM("Total Incurred USD") AS inc, COUNT(*) AS n
        FROM {T} GROUP BY 1 ORDER BY 2 DESC
    """),
    ("SEVERITY BAND", """
        SELECT "Severity Band", SUM("Total Incurred USD") AS inc, COUNT(*) AS n,
               AVG("Total Incurred USD") AS avg_sev
        FROM {T} GROUP BY 1 ORDER BY 2 DESC
    """),
    ("MONTHLY CLAIMS + INCURRED (Loss Date)", """
        SELECT YEAR("Loss Date") AS y, MONTH("Loss Date") AS m, COUNT(*) AS n,
               SUM("Total Incurred USD") AS inc
        FROM {T} GROUP BY 1,2 ORDER BY 1,2
    """),
    ("ADJUSTER WORKLOAD", """
        SELECT "Adjuster Name", COUNT(*) AS n, AVG("Claim Resolution Time Days") AS avg_days
        FROM {T} GROUP BY 1 ORDER BY 2 DESC LIMIT 15
    """),
    ("LINE OF BUSINESS", """
        SELECT "Line of Business", COUNT(*) AS n, SUM("Total Incurred USD") AS inc
        FROM {T} GROUP BY 1 ORDER BY 3 DESC
    """),
]

with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hp:
    with Connection(endpoint=hp.endpoint, database=HYPER) as con:
        for title, q in QUERIES:
            print(f"\n===== {title} =====")
            with con.execute_query(q.replace("{T}", T)) as res:
                names = [c.name.unescaped for c in res.schema.columns]
                print(" | ".join(names))
                for row in res:
                    print(" | ".join(str(v) for v in row))
