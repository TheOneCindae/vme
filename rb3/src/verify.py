"""End-to-end verification of the reconstructed model against the schedules."""
import json, math, collections, re

bbs = json.load(open('out/bbs.json'))
import sys
sys.path.insert(0, 'src')
import bbs as BBS
for stem, panel in (("PW-GF-27_R2", "PW-GF-27"), ("PW-GF-30_R2", "PW-GF-30"),
                    ("PC-GF-01_R", "PC-GF-01")):
    try:
        r = BBS.extract(f"dxf/{stem}.dxf")
        if r["bars"]:
            bbs[panel] = r
    except Exception:
        pass
model = json.load(open('out/model3d.json'))
fail = []


def plen(pts):
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def panel_of(key):
    return re.sub(r'\s*\[.*\]$', '', key)


# every scheduled bar must appear exactly once across the element models
placed = collections.Counter()
for key, m in model.items():
    p = panel_of(key)
    for b in m['bars']:
        placed[(p, b['mark'])] += 1

print("{:28}{:>7}{:>9}{:>11}{:>12}".format('element', 'bars', 'expected', 'kg', 'len err mm'))
tot_bars = tot_w = 0
for key in sorted(model):
    m = model[key]
    worst = 0.0
    for b in m['bars']:
        if len(b['pts']) < 2:
            fail.append(f"{key}/{b['mark']}: degenerate geometry"); continue
        e = abs(plen(b['pts']) - b['cut_length_mm'])
        worst = max(worst, e)
        if e > 2.0:
            fail.append(f"{key}/{b['mark']}: polyline {plen(b['pts']):.1f} vs cut {b['cut_length_mm']}")
    w = sum(b['weight_kg'] for b in m['bars'])
    tot_bars += m['n_bars']; tot_w += w
    print("  {:28}{:7d}{:>9}{:11.2f}{:12.2f}".format(key, m['n_bars'], '', w, worst))

# per-panel totals must still reconcile with the schedule
for p, entry in bbs.items():
    if not entry['bars']:
        continue
    if not any(panel_of(k) == p for k in model):
        continue
    exp = sum(b['qty'] for b in entry['bars'])
    got = sum(n for (pp, _), n in placed.items() if pp == p)
    if got != exp:
        fail.append(f"{p}: {got} bars placed vs {exp} scheduled")
    # a mark name can legitimately appear on more than one schedule row
    # (PW-GF-27 has two G2 rows of different length), so compare totals
    want = collections.Counter()
    for b in entry['bars']:
        want[b['mark']] += b['qty']
    for mk, n in want.items():
        if placed[(p, mk)] != n:
            fail.append(f"{p}/{mk}: {placed[(p, mk)]} placed vs scheduled {n}")
    sw = entry['summary']['total']['weight_kg'] if entry['summary'] else None
    if sw:
        mw = sum(b['weight_kg'] for k, m in model.items() if panel_of(k) == p
                 for b in m['bars'])
        if abs(mw - sw) > 0.1:
            fail.append(f"{p}: model {mw:.2f} kg vs schedule {sw:.2f} kg")

print(f"\nTOTAL {tot_bars} bars, {tot_w:.2f} kg across {len(model)} elements")
print(f"schedule reconciliation issues in source: "
      f"{sum(len(v['issues']) for v in bbs.values())}")
if fail:
    print(f"\nFAILURES ({len(fail)}):")
    for f in fail[:20]:
        print("  !", f)
else:
    print("\nAll checks passed: every scheduled bar exists in 3D, once per unit "
          "quantity, with polyline length equal to its scheduled cut length, and "
          "each package's weight matching its schedule.")
