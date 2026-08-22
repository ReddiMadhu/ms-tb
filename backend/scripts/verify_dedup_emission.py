"""One-shot simulation: the exact 33-measure estate from the run log
through dedup -> physical classification -> emitter injection."""
import sys, tempfile, json
sys.path.insert(0, 'src')
from app.services.pipeline.orchestrator import PipelineOrchestrator, classify_physical_measures
from app.agents.ir_compiler import IRMeasure
from app.agents.tableau_emitter import TableauEmitterAgent
from lxml import etree

LOG = [
 ('States','COUNTD([State])','Count<Distinct=True , UseLookupForAttributes=False >(State){~+}'),
 ('High Fraud Claims','SUM([High Fraud Flag])','Sum<UseLookupForAttributes=False >([High Fraud Flag]){~+}'),
 ('Sum (Subrogation)','SUM([Subrogation])','Sum<UseLookupForAttributes=False >(Subrogation){~+}'),
 ('Reserve','SUM([Reserve Amount USD])','Sum<UseLookupForAttributes=False >([Reserve Amount USD]){~+}'),
 ('Claim_Count_2','COUNTD([Claim ID])','Count<Distinct=True , UseLookupForAttributes=False >([Claim ID]@ID){~+}'),
 ('Total Incurred USD','SUM([Total Incurred USD])',''),
 ('Paid Amount','SUM([Paid Amount USD])','Sum<UseLookupForAttributes=False >([Paid Amount USD]){~+}'),
 ('Subrogation','SUM([Subrogation])',''),
 ('State Loss Rank','RANK([Top State Loss])',''),
 ('Row Count - MSTR_PC_Claims_Sample_Data_500K_With_Resolution_Time.xlsx','SUM([Row Count - MSTR_PC_Claims_Sample_Data_500K_With_Resolution_Time.xlsx])',''),
 ('Avg_Claim_Resolution_Days','AVG([Claim Resolution Time Days])','Avg<UseLookupForAttributes=False >([Claim Resolution Time Days]){~+}'),
 ('Count (Region)','COUNTD([Region])','Count<Distinct=True , UseLookupForAttributes=False >(Region){~+}'),
 ('Litigation Claims','SUM([Litigation_Flag])','Sum<UseLookupForAttributes=False >(Litigation_Flag){~+}'),
 ('Litigation Rate','[Litigation Claims] / [Total_Claims]','[Litigation Claims] / Total_Claims'),
 ('Recovery Amount USD','SUM([Recovery Amount USD])',''),
 ('Salvage','SUM([Salvage])',''),
 ('Avg Severity','AVG([Total Incurred USD])','Avg<UseLookupForAttributes=False >([Total Incurred USD]){~+}'),
 ('Count (Claim ID)','COUNT([Claim ID])','Count<UseLookupForAttributes=False >([Claim ID]){~+}'),
 ('Outstanding Exposure','SUM([Reserve Amount USD])','Sum<UseLookupForAttributes=False >([Reserve Amount USD]){~+}'),
 ('Recovery','SUM([Recovery Amount USD])','Sum<UseLookupForAttributes=False >([Recovery Amount USD]){~+}'),
 ('Claim Resolution Time Days','SUM([Claim Resolution Time Days])',''),
 ('Avg (Fraud Score)','AVG([Fraud Score])','Avg<UseLookupForAttributes=False >([Fraud Score]){~+}'),
 ('Total Incurred','SUM([Total Incurred USD])','Sum<UseLookupForAttributes=False >([Total Incurred USD]){~+}'),
 ('Net Losses','SUM([Net Loss])','Sum<UseLookupForAttributes=False >([Net Loss]@ID){~+}'),
 ('Sum (Salvage)','SUM([Salvage])','Sum<UseLookupForAttributes=False >(Salvage){~+}'),
 ('Total_Claims','SUM([Count (Claim ID)])','Sum<UseLookupForAttributes=False >([Count (Claim ID)]){~+}'),
 ('Paid Amount USD','SUM([Paid Amount USD])',''),
 ('Top State Loss','MAX([Total Incurred USD])','Max<UseLookupForAttributes=False >([Total Incurred USD]){~+}'),
 ('Litigation Incurred Loss',"SUM(IF [Litigation] = '1' THEN [Total Incurred] ELSE 0 END)","Sum<UseLookupForAttributes=False >(IF((Litigation@ID = \"1\"),[Total Incurred],0)){~+}"),
 ('High Fraud Rate','[High Fraud Claims] / [Total_Claims]','[High Fraud Claims] / Total_Claims'),
 ('Count (Adjuster Name)','COUNTD([Adjuster Name])','Count<Distinct=True , UseLookupForAttributes=False >([Adjuster Name]){~+}'),
 ('Reserve Amount USD','SUM([Reserve Amount USD])',''),
 ('Avg Claim','AVG([Total Incurred USD])','Avg<UseLookupForAttributes=False >([Total Incurred USD]){~+}'),
]

tmp = tempfile.mkdtemp()

def mk(i, name, calc, text):
    return IRMeasure(id=f'M{i}', mstr_id=f'MSTR{i:02d}', name=name, local_name=name,
                     remote_name=name.replace(' ', '_'), caption=name, tableau_calc=calc,
                     expression_text=text or None)

ir = type('IR', (), {})()
ir.measures = [mk(i, n, c, t) for i, (n, c, t) in enumerate(LOG)]
ir.dimensions = []
orch = PipelineOrchestrator(job_id='sim')
orch._merge_duplicate_measures(ir, tmp)

phys = classify_physical_measures([
    {'mstr_id': m.mstr_id, 'name': m.name, 'local_name': m.local_name,
     'expression_text': m.expression_text, 'tableau_calc': m.tableau_calc}
    for m in ir.measures
])
phys_ids = {p['mstr_id'] for p in phys}

class Job:
    id = 'sim'

agent = TableauEmitterAgent(db=None, job=Job(), artifacts_dir=tmp, target_environment='staging')
with open(tmp + '/physical_measures.json', 'w') as f:
    json.dump([{'mstr_id': p} for p in phys_ids], f)
ds = etree.Element('datasource')
existing = agent._inject_datasource_columns(ds, ir)
agent._inject_calculated_fields(ds, ir, existing_cols=existing)
cols = ds.findall('column')
names = [c.get('name') for c in cols]
assert len(names) == len(set(names)), 'DUPLICATES REMAIN'

calc_fields = [c.get('name') for c in cols if c.find('calculation') is not None]
print(f'BEFORE: 33 measures emitted, 18 "field is already defined" warnings')
print(f'AFTER dedup: {len(ir.measures)} canonical measures ({33 - len(ir.measures)} aliases merged)')
print(f'Physical extract columns: {len(phys_ids)} | True calculated fields: {len(calc_fields)}')
print(f'Total datasource fields: {len(names)} - zero duplicates')
print()
print('Merged aliases (two-layer collapse):')
for rec in json.load(open(tmp + '/merge_map.json'))['merges']:
    print(f"  [{rec['dropped']}]  ->  [{rec['canonical']}]")
print()
print('Surviving calculated fields:')
for cf in calc_fields:
    print(f'  {cf}')

# ── Aggregate-context check: derived formulas over bare physical columns ──
formulas = {c.get('name'): c.find('calculation').get('formula')
            for c in cols if c.find('calculation') is not None}
lr = formulas.get('[Litigation Rate]', '')
assert 'SUM([Litigation Claims])' in lr, f'physical ref not wrapped: {lr}'
assert lr.count('SUM(') >= 1
hfr = formulas.get('[High Fraud Rate]', '')
assert 'SUM([High Fraud Claims])' in hfr, f'physical ref not wrapped: {hfr}'
# [Total_Claims] is a surviving CALC (SUM already inside) — must NOT be double-wrapped
assert '[SUM(' not in lr and '[SUM(' not in hfr, f'double-wrap detected: {lr} | {hfr}'
print()
print('Aggregate-context fixes verified:')
print(f'  [Litigation Rate]  =  {lr}')
print(f'  [High Fraud Rate]  =  {hfr}')

# ── Direct scanner unit cases ──
from app.agents.tableau_emitter import _wrap_bare_aggregate_refs as W
bare = {'X'}
assert W('[X] / SUM([Y])', bare) == 'SUM([X]) / SUM([Y])'
assert W('SUM([X]) / [Y]', bare) == 'SUM([X]) / [Y]'
assert W('SUM([X] + [Y])', bare) == 'SUM([X] + [Y])', 'token already inside agg must stay untouched'
assert W('[X] * 2', bare) == 'SUM([X]) * 2'
assert W('IF [Z] = "1" THEN [X] ELSE 0 END', {'X'}) == 'IF [Z] = "1" THEN SUM([X]) ELSE 0 END'
assert W('[X]', bare) == 'SUM([X])'
print()
print('SCANNER UNIT TESTS PASSED')
