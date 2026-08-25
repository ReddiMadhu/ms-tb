"""Probe: emit a dual-measure combo sheet and verify pane axis-name attrs."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, "src")
sys.path.insert(0, "tests")

from test_visualization_dossier import insurance_ir  # noqa: E402
from app.agents.visualization import VisualizationAgent  # noqa: E402
from app.agents.tableau_emitter import TableauEmitterAgent  # noqa: E402

ir = insurance_ir.__wrapped__() if hasattr(insurance_ir, "__wrapped__") else None
if ir is None:
    # fixture is a pytest fixture function; build manually by invoking its body
    from tests.test_visualization_dossier import insurance_ir as f  # type: ignore
    # Fallback: call underlying function via closure stored on fixture
    ir = f.fn if hasattr(f, "fn") else None
if ir is None:
    raise SystemExit("could not materialize fixture")

agent = VisualizationAgent(ir=ir)
plan = agent.plan()
trend = next(w for w in plan.worksheets if w.name.startswith("Loss Trend"))

class _FakeDB:
    def add(self, *a, **k): pass
    def commit(self): pass
    def rollback(self): pass

art = Path("artifacts/probe_pane")
emitter = TableauEmitterAgent(
    db=_FakeDB(),
    job=SimpleNamespace(id="probe"),
    artifacts_dir=str(art),
    target_environment="staging",
)
twbx = emitter.emit_workbook(
    ir=ir,
    viz_plan=plan,
    hyper_paths={"default": "does-not-exist.hyper"},
    workbook_name="PaneProbe",
)
twb = Path(str(twbx).replace(".twbx", ".twb"))
if not twb.exists():
    cand = list((art / "workbooks" / "PaneProbe").glob("*.twb"))
    twb = cand[0]
xml = twb.read_text(encoding="utf-8")
i = xml.find("Loss Trend")
seg = xml[i : i + 3200]
print("--- pane/rows/cols lines ---")
for line in seg.splitlines():
    s = line.strip()
    if "<pane" in s or "axis-name" in s or s.startswith("<rows>") or s.startswith("<cols>"):
        print(s[:170])
