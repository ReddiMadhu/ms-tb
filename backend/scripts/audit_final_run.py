import re, json
from pathlib import Path

run = Path(r'artifacts\e2e-runs\e2e-live-1787633676')
twbf = next(f for f in run.rglob('*.twb'))
txt = twbf.read_text(encoding='utf-8')
vp = json.loads((run / 'viz_plan.json').read_text(encoding='utf-8'))

print('FINAL RUN SHAPE AUDIT (e2e-live-1787633676)')
print(' parenthesized multi-measure rows :',
      len(re.findall(r'<rows>\([^<]*\+[^<]*\)</rows>', txt)))
print(' bare multi-measure rows          :',
      len(re.findall(r'<rows>[^<(]*\+[^<)]*</rows>', txt)))
print(' axis-name attrs                  :', txt.count('axis-name'))
print(' worksheets emitted               :', txt.count('<worksheet '))
lt = re.search(r'Loss Trend[^>]*>.*?<rows>([^<]*)</rows>', txt, re.S)
print(' Loss Trend rows                  :', lt.group(1)[:110] if lt else 'n/a')
failed = [(w['name'], bool(w.get('failure_reason')))
          for w in vp['worksheets'] if w.get('is_failed')]
print(' planned-failed (with reason)     :', failed)
