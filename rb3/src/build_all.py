"""Build the 3D model, one model per ELEMENT rather than per drawing package.

A package such as PW-GF-09 can contain several elements, each with its own
sheet and its own part of the schedule. Each schedule is bound to the element
whose sheet actually tags its marks, then modelled inside that element alone.
"""
import sys, json, glob, collections
sys.path.insert(0, 'src')
import assemble as A
import elements as E

bbs = json.load(open('out/bbs.json'))

# schedules that live in an (R) sheet rather than an (S) sheet
import bbs as BBS
for stem, panel in (("PW-GF-27_R2", "PW-GF-27"), ("PW-GF-30_R2", "PW-GF-30"),
                    ("PC-GF-01_R", "PC-GF-01")):
    try:
        r = BBS.extract(f"dxf/{stem}.dxf")
        if r["bars"]:
            bbs[panel] = r
    except Exception:
        pass

models, rows = {}, []
for panel in sorted(bbs):
    entry = bbs[panel]
    if not entry["bars"]:
        continue
    paths = sorted(glob.glob(f'dxf/{panel}_R*.dxf'))
    if not paths:
        rows.append((panel, None, 0, 0, None, "no (R) drawing")); continue
    els = E.candidates(panel, paths)
    if not els:
        rows.append((panel, None, 0, 0, None, "no usable views")); continue
    sched = collections.defaultdict(list)
    for m in entry["bars"]:
        sched[m["schedule"] or panel].append(m)
    amap = E.assign(sched, els)

    by_elem = collections.defaultdict(list)
    for name, marks in sched.items():
        by_elem[amap[name]["element"]] += marks

    for ei, marks in sorted(by_elem.items(), key=lambda kv: kv[0]):
        el = els[ei]
        w, h, t = el["key"]
        key = panel if len(by_elem) == 1 else f"{panel} [{w}x{h}x{t}]"
        m = A.build_panel(key, entry, paths, only_marks=marks, element=el)
        if m is None:
            continue
        m["sheet"] = el["sheet"]
        models[key] = m
        exp = sum(x["qty"] for x in marks)
        wt = sum(b["weight_kg"] for b in m["bars"])
        rows.append((key, el["sheet"], m["n_bars"], exp, wt, m["placement_stats"]))

json.dump(models, open('out/model3d.json', 'w'))
print("{:26}{:16}{:>7}{:>9}{:>11}".format('element', 'sheet', 'bars', 'expected', 'kg'))
tb = te = 0; tw = 0.0
for r in rows:
    key, sheet, n, exp, wt, st = r
    if wt is None:
        print("  {:26}{:16}{:>7}{:>9}{:>11}  {}".format(key, '-', '-', '-', '-', st)); continue
    tb += n; te += exp; tw += wt
    print("  {:26}{:16}{:7d}{:9d}{:11.2f}".format(key, sheet or '-', n, exp, wt))
print("\nTOTAL bars {} / expected {}   weight {:.2f} kg   elements {}".format(
    tb, te, tw, len(models)))
