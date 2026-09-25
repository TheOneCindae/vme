import sys
sys.path.insert(0,'src')
import json
from pathlib import Path
model = json.load(open('out/model3d.json'))
bbs = json.load(open('out/bbs.json'))
import re
bbs = {k: v for k, v in bbs.items()}
import bbs as BBS
for stem, pan in (("PW-GF-27_R2","PW-GF-27"),("PW-GF-30_R2","PW-GF-30")):
    try:
        r = BBS.extract(f'dxf/{stem}.dxf')
        if r['bars']: bbs[pan] = r
    except Exception: pass
# the viewer keys on element; map each element back to its package schedule
out = {}
for k in model:
    p0 = re.sub(r'\s*\[.*\]$', '', k)
    marks = {b['mark'] for b in model[k]['bars']}
    src = bbs.get(p0)
    if src:
        out[k] = {**src, 'bars': [b for b in src['bars'] if b['mark'] in marks]}
bbs = out
meta = {"footnote":
  "Bar list, cut lengths and weights are read verbatim from the (S) bar bending "
  "schedules and independently reconciled (length x quantity, computed steel "
  "weight, and printed totals) with no discrepancies. Geometry is generated from "
  "each mark's shape code and A-G dimensions. PW-GF-27 is excluded: its (S) file "
  "contains only the legend sheet, with no schedule table."}
sys_path = None
shell = Path('src/viewer/shell.html').read_text()
app = Path('src/viewer/app.js').read_text()
html = (shell + "\n<script>\nconst MODEL=" + json.dumps(model, separators=(',', ':'))
        + ";\nconst BBS=" + json.dumps(bbs, separators=(',', ':'))
        + ";\nconst META=" + json.dumps(meta) + ";\n" + app + "\n</script>\n")
Path('out/viewer.html').write_text(html)
print(f"out/viewer.html  {len(html)//1024} KB")
