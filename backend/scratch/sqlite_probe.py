"""Try reading extract.hyper via plain sqlite3 (read-only)."""
import sqlite3

P = r"C:\Users\madhu\Desktop\ms-tb\backend\artifacts\87b07292-cd96-47a3-b1f9-2fc6b6088f61\hyper\extract.hyper"
con = sqlite3.connect(f"file:{P}?mode=ro", uri=True)
cur = con.cursor()
rows = cur.execute("SELECT type, name FROM sqlite_master WHERE type IN ('table','view')").fetchall()
print(rows)
