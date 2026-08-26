"""
Reset the High Fraud Claims object for job ffbd942f-34ea-45c2-b77a-be9f7f01ea0d
back to the Requires-Review showcase initial state (DB row + ir.json measure),
so the Logic Explorer demo flow can be replayed.

Run from backend/ with: .\\venv\\Scripts\\python.exe scratch\\reset_high_fraud_review.py
"""

import json
import sys
from pathlib import Path

JOB_ID = "ffbd942f-34ea-45c2-b77a-be9f7f01ea0d"
OBJ_ID = "94f35884-78af-4922-a9e3-f59a0ef9ad3f"
MSTR_ID = "1EFA3F094B46BD2A24F88ABFDD13ACBE"
BROKEN = "IF(([Fraud Score]@ID >= 70), 1, 0)"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.job import Job
from app.models.objects import MigrationObject, ReviewTask

engine = create_engine(settings.database_url)
Session = sessionmaker(bind=engine)
db = Session()

job = db.query(Job).filter(Job.id == JOB_ID).first()
assert job, f"job {JOB_ID} not found"
print("job:", job.id, "| artifacts_dir:", job.artifacts_dir)

obj = db.query(MigrationObject).filter(MigrationObject.id == OBJ_ID).first()
assert obj, f"object {OBJ_ID} not found"
print("object before:", obj.status, obj.confidence, repr(obj.tableau_calc))

obj.tableau_calc = BROKEN
obj.status = "requires_review"
obj.confidence = 0.40
obj.translation_method = "Uncompiled MicroStrategy Dialect"

tasks = (
    db.query(ReviewTask)
    .filter(
        ReviewTask.job_id == JOB_ID,
        (ReviewTask.object_id == obj.id) | (ReviewTask.object_id == MSTR_ID),
    )
    .all()
)
for t in tasks:
    print("resetting review task:", t.id, t.status, "-> pending")
    t.status = "pending"
    t.generated_calc = BROKEN
    t.confidence = 0.40
    t.resolution_notes = None
    t.resolved_at = None

db.commit()
print("object after:", obj.status, obj.confidence, repr(obj.tableau_calc))

ir_path = Path(job.artifacts_dir) / "ir.json"
ir = json.loads(ir_path.read_text(encoding="utf-8"))
changed = 0
for m in ir.get("measures", []):
    if m.get("mstr_id") == MSTR_ID or m.get("name") == "High Fraud Claims":
        m["tableau_calc"] = BROKEN
        m["confidence"] = 0.4
        changed += 1
ir_path.write_text(json.dumps(ir, indent=2), encoding="utf-8")
print("ir.json measures updated:", changed)
