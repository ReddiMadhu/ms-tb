"""Diagnostic queries against the migrated Hyper extract."""
from tableauhyperapi import HyperProcess, Telemetry, Connection

HYPER = r"C:\Users\madhu\Desktop\ms-tb\backend\artifacts\87b07292-cd96-47a3-b1f9-2fc6b6088f61\hyper\extract.hyper"

with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hp:
    with Connection(endpoint=hp.endpoint, database=HYPER) as con:
        print("== SCHEMAS/TABLES ==")
        for schema in con.catalog.get_schema_names():
            for t in con.catalog.get_table_names(schema):
                cnt = con.execute_scalar_query(f"SELECT COUNT(*) FROM {t}")
                print(f"{t}: {cnt} rows")
                td = con.catalog.get_table_definition(t)
                for c in td.columns:
                    print(f"   {c.name.unescaped}  {c.type}")
