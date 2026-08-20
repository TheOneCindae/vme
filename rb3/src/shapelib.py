"""Derive bar centreline topology for each shape code from the (S) legend.

The legend draws every shape as a closed OUTLINE of a bar with finite width:
two parallel edges per straight leg, two concentric arcs per bend, and short
end caps. The centreline is the medial axis, recovered by pairing those
edges. Each leg is then labelled A..G by the DIMENSION whose text override
names the BBS column and whose measurement matches the leg length.
"""
import math, json, re, collections
import ezdxf

LEGEND_LAYERS = {"A-DETL-THIN", "A-DETL-MBND"}


def _seg(e):
    s, t = e.dxf.start, e.dxf.end
    return (s.x, s.y), (t.x, t.y)


def _len(p, q):
    return math.hypot(q[0] - p[0], q[1] - p[1])


def _ang(p, q):
    return math.atan2(q[1] - p[1], q[0] - p[0])


def find_labels(doc):
    """Shape-code labels in the legend column.

    A code may be split across several MTEXTs ("REBAR" / "SHAPE 9"), so
    texts stacked within a few units in the same column are merged.
    """
    lay = doc.layout("Layout1")
    hdr = None
    texts = []
    for e in lay:
        if e.dxftype() not in ("MTEXT", "TEXT"):
            continue
        txt = (e.text if e.dxftype() == "MTEXT" else e.dxf.text)
        txt = " ".join(txt.replace("\\P", " ").split())
        if txt == "Rebar Shape":
            hdr = e.dxf.insert
        texts.append((e.dxf.insert.x, e.dxf.insert.y, txt, e.dxf.layer))
    if hdr is None:
        return []
    col = [(x, y, t) for x, y, t, lyr in texts
           if abs(x - hdr.x) < 14 and y < hdr.y - 2 and t
           and not t.startswith("\\") and lyr != "G-ANNO-SCHD"]
    col.sort(key=lambda r: -r[1])
    groups = []
    for x, y, t in col:
        if groups and abs(groups[-1]["y"] - y) < 5.0:
            groups[-1]["parts"].append(t)
            groups[-1]["y"] = (groups[-1]["y"] + y) / 2
        else:
            groups.append({"x": x, "y": y, "parts": [t]})
    out = []
    for g in groups:
        code = " ".join(g["parts"]).strip()
        code = re.sub(r"\s+", " ", code)
        if re.fullmatch(r"REBAR SHAPE (\d+)", code, re.I):
            code = "Rebar Shape " + re.findall(r"(\d+)$", code)[0]
        out.append({"code": code, "x": g["x"], "y": g["y"]})
    return out


def cell_geometry(doc, label, labels):
    """Geometry belonging to one legend row (bounded by neighbouring labels)."""
    lay = doc.layout("Layout1")
    ys = sorted(l["y"] for l in labels)
    i = ys.index(label["y"])
    lo = (ys[i - 1] + label["y"]) / 2 if i > 0 else label["y"] - 14
    hi = (ys[i + 1] + label["y"]) / 2 if i < len(ys) - 1 else label["y"] + 14
    x0 = label["x"] + 14
    lines, arcs, dims = [], [], []
    for e in lay:
        t = e.dxftype()
        if t == "LINE" and e.dxf.layer in LEGEND_LAYERS:
            p, q = _seg(e)
            if min(p[0], q[0]) > x0 and lo < p[1] < hi and lo < q[1] < hi:
                lines.append((p, q))
        elif t == "ARC" and e.dxf.layer in LEGEND_LAYERS:
            c = e.dxf.center
            if c.x > x0 and lo < c.y < hi:
                arcs.append({"c": (c.x, c.y), "r": e.dxf.radius,
                             "a0": e.dxf.start_angle, "a1": e.dxf.end_angle})
        elif t == "DIMENSION":
            dp = e.dxf.defpoint
            if dp.x > x0 and lo < dp.y < hi:
                dims.append({"text": e.dxf.text,
                             "m": e.dxf.get("actual_measurement", None),
                             "p": (dp.x, dp.y)})
    return lines, arcs, dims


def bar_width(lines, arcs):
    """The drawn bar width = the common offset between paired edges."""
    cands = []
    for a in arcs:
        for b in arcs:
            if a is b:
                continue
            if _len(a["c"], b["c"]) < 0.15 and 0.2 < abs(a["r"] - b["r"]) < 5:
                cands.append(abs(a["r"] - b["r"]))
    for p, q in lines:
        L = _len(p, q)
        if L < 3:
            cands.append(L)          # end caps span exactly the bar width
    if not cands:
        return None
    cands.sort()
    return cands[len(cands) // 2]


def midlines(lines, w, tol=0.30):
    """Pair parallel edges offset by ~w and return their mid-segments."""
    long = [(p, q) for p, q in lines if _len(p, q) > w * 1.6]
    used, mids = set(), []
    for i, (p1, q1) in enumerate(long):
        if i in used:
            continue
        a1 = _ang(p1, q1)
        best, bd = None, 1e9
        for j, (p2, q2) in enumerate(long):
            if j <= i or j in used:
                continue
            a2 = _ang(p2, q2)
            da = abs((a1 - a2 + math.pi) % (2 * math.pi) - math.pi)
            if min(da, math.pi - da) > 0.08:
                continue
            # perpendicular distance between the two infinite lines
            nx, ny = -math.sin(a1), math.cos(a1)
            d = abs((p2[0] - p1[0]) * nx + (p2[1] - p1[1]) * ny)
            # must overlap along their shared direction
            ux, uy = math.cos(a1), math.sin(a1)
            s1 = sorted([(p1[0]*ux+p1[1]*uy), (q1[0]*ux+q1[1]*uy)])
            s2 = sorted([(p2[0]*ux+p2[1]*uy), (q2[0]*ux+q2[1]*uy)])
            if min(s1[1], s2[1]) - max(s1[0], s2[0]) < w:
                continue
            err = abs(d - w)
            if err < tol and err < bd:
                best, bd = j, err
        if best is None:
            continue
        p2, q2 = long[best]
        if _len(p1, p2) > _len(p1, q2):
            p2, q2 = q2, p2
        mids.append((((p1[0]+p2[0])/2, (p1[1]+p2[1])/2),
                     ((q1[0]+q2[0])/2, (q1[1]+q2[1])/2)))
        used.add(i); used.add(best)
    return mids


def midarcs(arcs, w, tol=0.30):
    """Pair concentric arcs whose radii differ by ~w."""
    used, out = set(), []
    for i, a in enumerate(arcs):
        if i in used:
            continue
        for j, b in enumerate(arcs):
            if j <= i or j in used:
                continue
            if _len(a["c"], b["c"]) < 0.20 and abs(abs(a["r"]-b["r"]) - w) < tol:
                out.append({"c": ((a["c"][0]+b["c"][0])/2, (a["c"][1]+b["c"][1])/2),
                            "r": (a["r"]+b["r"])/2,
                            "a0": a["a0"], "a1": a["a1"]})
                used.add(i); used.add(j)
                break
    return out


def arc_ends(a):
    r, (cx, cy) = a["r"], a["c"]
    p0 = (cx + r*math.cos(math.radians(a["a0"])), cy + r*math.sin(math.radians(a["a0"])))
    p1 = (cx + r*math.cos(math.radians(a["a1"])), cy + r*math.sin(math.radians(a["a1"])))
    return p0, p1


def chain(mids, marcs, tol=0.45):
    """Order straight legs and bends into one connected centreline path."""
    items = [{"kind": "leg", "p": p, "q": q, "len": _len(p, q)} for p, q in mids]
    for a in marcs:
        p0, p1 = arc_ends(a)
        sweep = (a["a1"] - a["a0"]) % 360
        items.append({"kind": "bend", "p": p0, "q": p1, "arc": a,
                      "sweep": sweep, "len": math.radians(sweep) * a["r"]})
    if not items:
        return []
    # endpoint adjacency
    def near(u, v):
        return _len(u, v) < tol
    # find a free end (an endpoint used only once) to start from
    ends = []
    for i, it in enumerate(items):
        for e in (it["p"], it["q"]):
            ends.append((i, e))
    def degree(e):
        return sum(1 for j, f in ends if near(e, f))
    start = None
    for i, it in enumerate(items):
        for key in ("p", "q"):
            if degree(it[key]) == 1:
                start = (i, key)
                break
        if start:
            break
    if start is None:
        start = (0, "p")           # closed loop (e.g. a full stirrup)
    order, usedi = [], set()
    i, key = start
    cur = items[i]
    at = cur["q"] if key == "p" else cur["p"]
    order.append({**cur, "rev": key == "q"}); usedi.add(i)
    while True:
        nxt = None
        for j, it in enumerate(items):
            if j in usedi:
                continue
            if near(it["p"], at):
                nxt = (j, False, it["q"]); break
            if near(it["q"], at):
                nxt = (j, True, it["p"]); break
        if nxt is None:
            break
        j, rev, at = nxt
        order.append({**items[j], "rev": rev}); usedi.add(j)
    return order


def label_legs(order, dims, tol=0.6):
    """Attach the BBS column letter to each straight leg via the DIMENSIONs."""
    legs = [(k, it) for k, it in enumerate(order) if it["kind"] == "leg"]
    out = {}
    used = set()
    for d in sorted(dims, key=lambda d: (d["text"] or "")):
        letter = (d["text"] or "").strip()
        if not letter or len(letter) > 2 or d["m"] is None:
            continue
        best, bd = None, 1e9
        for k, it in legs:
            if k in used:
                continue
            mid = ((it["p"][0]+it["q"][0])/2, (it["p"][1]+it["q"][1])/2)
            err = abs(it["len"] - d["m"]) + 0.02 * _len(mid, d["p"])
            if err < bd:
                best, bd = k, err
        if best is not None and bd < tol + 2.0:
            out[best] = letter
            used.add(best)
    return out


def turn_of(bend, prev_dir):
    """Signed turn angle (deg) the bend imposes: + = left, - = right."""
    a = bend["arc"]
    sweep = bend["sweep"]
    if sweep > 180:
        sweep = 360 - sweep
    # direction of travel before/after determines sign
    p, q = (bend["q"], bend["p"]) if bend.get("rev") else (bend["p"], bend["q"])
    cx, cy = a["c"]
    # cross product of (p-c) x (q-c) gives orientation of travel
    v1 = (p[0]-cx, p[1]-cy); v2 = (q[0]-cx, q[1]-cy)
    cross = v1[0]*v2[1] - v1[1]*v2[0]
    return sweep if cross > 0 else -sweep


def build_shape(doc, label, labels):
    lines, arcs, dims = cell_geometry(doc, label, labels)
    if not lines and not arcs:
        return None
    w = bar_width(lines, arcs)
    if not w:
        return None
    mids = midlines(lines, w)
    marcs = midarcs(arcs, w)
    order = chain(mids, marcs)
    if not order:
        return None
    names = label_legs(order, dims)
    steps = []
    for k, it in enumerate(order):
        if it["kind"] == "leg":
            p, q = (it["q"], it["p"]) if it["rev"] else (it["p"], it["q"])
            steps.append({"type": "leg", "letter": names.get(k),
                          "drawn": round(it["len"], 3),
                          "dir": round(math.degrees(_ang(p, q)), 1)})
        else:
            steps.append({"type": "bend", "turn": round(turn_of(it, None), 1),
                          "drawn_r": round(it["arc"]["r"], 3)})
    return {"code": label["code"], "width": round(w, 3), "steps": steps,
            "n_legs": sum(1 for s in steps if s["type"] == "leg"),
            "dims_found": sorted(set(v for v in names.values()))}


def from_file(path):
    doc = ezdxf.readfile(str(path))
    labels = find_labels(doc)
    out = {}
    for lb in labels:
        try:
            s = build_shape(doc, lb, labels)
        except Exception as e:
            s = {"code": lb["code"], "error": str(e)}
        if s:
            out[lb["code"]] = s
    return out


if __name__ == "__main__":
    import sys
    for code, s in from_file(sys.argv[1]).items():
        print(f"\n### {code}  width={s.get('width')} legs={s.get('n_legs')} dims={s.get('dims_found')}")
        for st in s.get("steps", []):
            if st["type"] == "leg":
                print(f"    leg  {str(st['letter']):>4}  drawn={st['drawn']:7.3f}  dir={st['dir']:7.1f}")
            else:
                print(f"    bend turn={st['turn']:7.1f}  r={st['drawn_r']:.3f}")
