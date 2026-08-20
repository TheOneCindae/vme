"""Render the raw legend outline for each shape code, for visual verification."""
import sys, glob, re, json, math, collections
sys.path.insert(0, 'src')
import ezdxf, shapelib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

def norm(c):
    return re.sub(r"\s*\(.*\)$", "", c).strip()

WANT = json.load(open('out/shapes_raw.json'))
cells = {}
for f in sorted(glob.glob('dxf/*_S.dxf')):
    doc = ezdxf.readfile(f); lbs = shapelib.find_labels(doc)
    for lb in lbs:
        code = norm(lb['code'])
        if code not in WANT or code in cells:
            continue
        if WANT[code].get('src') != Path(f).stem:
            continue
        cells[code] = shapelib.cell_geometry(doc, lb, lbs)

n = len(cells)
fig, axes = plt.subplots(2, (n+1)//2, figsize=(4*((n+1)//2), 8))
for ax, (code, (lines, arcs, dims)) in zip(axes.ravel(), sorted(cells.items())):
    for p, q in lines:
        ax.plot([p[0], q[0]], [p[1], q[1]], '-', lw=1.1, color='#1b6ac9')
    for a in arcs:
        t = [math.radians(x) for x in
             ([a['a0'] + i*((a['a1']-a['a0']) % 360)/24 for i in range(25)])]
        ax.plot([a['c'][0]+a['r']*math.cos(x) for x in t],
                [a['c'][1]+a['r']*math.sin(x) for x in t], '-', lw=1.1, color='#1b6ac9')
    for d in dims:
        ax.plot(*d['p'], 'r.', ms=6)
        ax.annotate(d['text'] or '?', d['p'], color='crimson', fontsize=11, weight='bold')
    ax.set_title(f"{code}\nwant {WANT[code].get('want')}", fontsize=9)
    ax.set_aspect('equal'); ax.axis('off')
for ax in axes.ravel()[len(cells):]:
    ax.axis('off')
plt.tight_layout(); plt.savefig('out/legend_shapes.png', dpi=115)
print("wrote out/legend_shapes.png for", sorted(cells))
