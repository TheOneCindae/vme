"""Extract true-scale rebar centrelines from an (R) reinforcement drawing.

Bars are drawn as outlines (two parallel edges + bend arcs) on layer S-RBAR,
at 1:1 in millimetres. The centreline is recovered as the medial axis, using
the true bar diameter as the pairing offset.
"""
import math, collections
import ezdxf

RBAR = "S-RBAR"
IDEN = "S-RBAR-IDEN"
DIAS = [8, 10, 12, 16, 20, 25, 32]


def views(doc):
    """Model-space window and title of every viewport in Layout1."""
    lay = doc.layout("Layout1")
    titles = []
    for e in lay:
        if e.dxftype() == "MTEXT":
            t = " ".join(e.text.replace("\\P", " ").split())
            if t:
                titles.append((e.dxf.insert.x, e.dxf.insert.y, t))
    out = []
    for v in lay.query("VIEWPORT"):
        dx = v.dxf
        if dx.width < 20 or dx.height < 20:
            continue                      # the dummy 12x9 viewport
        ar = dx.width / dx.height
        vh = dx.view_height
        vw = vh * ar
        cx, cy = dx.view_center_point.x, dx.view_center_point.y
        # title sits just below the viewport in paper space
        best, bd = None, 1e9
        for tx, ty, t in titles:
            if "REINF" not in t.upper():
                continue
            d = abs(tx - (dx.center.x - dx.width / 2) - 6) + abs(ty - (dx.center.y - dx.height / 2))
            if d < bd:
                best, bd = t, d
        out.append({"title": best, "scale": round(vh / dx.height, 1),
                    "cx": cx, "cy": cy, "w": vw, "h": vh,
                    "box": (cx - vw / 2, cy - vh / 2, cx + vw / 2, cy + vh / 2),
                    "paper": (dx.center.x, dx.center.y, dx.width, dx.height)})
    return out


def in_box(p, box, pad=0.0):
    return box[0] - pad <= p[0] <= box[2] + pad and box[1] - pad <= p[1] <= box[3] + pad


def seg_of(e):
    s, t = e.dxf.start, e.dxf.end
    return (s.x, s.y), (t.x, t.y)


def collect(doc, box, pad=0.0):
    """S-RBAR lines and arcs whose whole extent lies inside a view window."""
    msp = doc.modelspace()
    lines, arcs = [], []
    for e in msp:
        if e.dxf.layer != RBAR:
            continue
        t = e.dxftype()
        if t == "LINE":
            p, q = seg_of(e)
            if in_box(p, box, pad) and in_box(q, box, pad):
                lines.append((p, q))
        elif t == "ARC":
            c = e.dxf.center
            if in_box((c.x, c.y), box, pad):
                arcs.append({"c": (c.x, c.y), "r": e.dxf.radius,
                             "a0": e.dxf.start_angle, "a1": e.dxf.end_angle})
    return lines, arcs


def circles(doc, box, pad=0.0):
    """Bar cross-sections (bars seen end-on) with their inferred diameter."""
    out = []
    for e in doc.modelspace():
        if e.dxf.layer != RBAR or e.dxftype() != "CIRCLE":
            continue
        c = e.dxf.center
        if not in_box((c.x, c.y), box, pad):
            continue
        d = round(e.dxf.radius * 2)
        out.append({"p": (c.x, c.y), "dia": d})
    return out


def tags(doc, box, pad=0.0):
    """Mark tags on S-RBAR-IDEN: the mark letter and its '-(qty) -(Tdd)' note."""
    import re
    msp = doc.modelspace()
    items = []
    for e in msp:
        if e.dxf.layer != IDEN or e.dxftype() != "MTEXT":
            continue
        p = (e.dxf.insert.x, e.dxf.insert.y)
        if not in_box(p, box, pad):
            continue
        t = " ".join(e.text.replace("\\P", " ").split())
        items.append({"p": p, "t": t})
    marks, notes, spacing = [], [], []
    for it in items:
        t = it["t"]
        m = re.match(r"^-\((\d+)\)\s*-?\(?\s*T(\d+)(.*?)\)?$", t)
        if m:
            notes.append({"p": it["p"], "qty": int(m.group(1)),
                          "dia": int(m.group(2)), "extra": m.group(3).strip()})
        elif re.fullmatch(r"[A-Z][0-9]?", t):
            marks.append({"p": it["p"], "mark": t})
        elif re.match(r"^T\d+", t):
            spacing.append({"p": it["p"], "t": t})
    return marks, notes, spacing


def _norm_line(p, q):
    """Canonical (angle mod pi, signed offset) for a segment, plus extent."""
    a = math.atan2(q[1] - p[1], q[0] - p[0]) % math.pi
    ux, uy = math.cos(a), math.sin(a)
    nx, ny = -uy, ux
    off = p[0] * nx + p[1] * ny
    s0 = p[0] * ux + p[1] * uy
    s1 = q[0] * ux + q[1] * uy
    return a, off, min(s0, s1), max(s0, s1)


def pair_lines(lines, dias=DIAS, atol=0.6, dtol=0.35, min_overlap=1.0):
    """Pair parallel edges separated by a bar diameter -> centreline segments.

    Angle-bucketed so this stays near-linear on drawings with 10k+ segments.
    """
    recs = []
    for p, q in lines:
        L = math.dist(p, q)
        if L < 1e-6:
            continue
        a, off, s0, s1 = _norm_line(p, q)
        recs.append({"p": p, "q": q, "a": a, "off": off, "s0": s0, "s1": s1,
                     "L": L, "used": False})
    buckets = collections.defaultdict(list)
    step = math.radians(atol)
    for i, r in enumerate(recs):
        k = int(r["a"] / step)
        for kk in (k - 1, k, k + 1):
            buckets[kk].append(i)
    mids, pairs = [], []
    seen = set()
    for k, idxs in buckets.items():
        idxs = sorted(set(idxs), key=lambda i: recs[i]["off"])
        for ii in range(len(idxs)):
            i = idxs[ii]
            ri = recs[i]
            if ri["used"]:
                continue
            for jj in range(ii + 1, len(idxs)):
                j = idxs[jj]
                rj = recs[j]
                if rj["used"]:
                    continue
                d = rj["off"] - ri["off"]
                if d > max(dias) + 1:
                    break
                da = abs(ri["a"] - rj["a"])
                da = min(da, math.pi - da)
                if da > math.radians(atol):
                    continue
                hit = [D for D in dias if abs(d - D) < dtol]
                if not hit:
                    continue
                ov = min(ri["s1"], rj["s1"]) - max(ri["s0"], rj["s0"])
                if ov < min_overlap:
                    continue
                key = (min(i, j), max(i, j))
                if key in seen:
                    continue
                seen.add(key)
                ri["used"] = rj["used"] = True
                # mid-segment over the overlapping span
                a = ri["a"]
                ux, uy = math.cos(a), math.sin(a)
                nx, ny = -uy, ux
                moff = (ri["off"] + rj["off"]) / 2
                lo = max(ri["s0"], rj["s0"])
                hi = min(ri["s1"], rj["s1"])
                P = (ux * lo + nx * moff, uy * lo + ny * moff)
                Q = (ux * hi + nx * moff, uy * hi + ny * moff)
                mids.append({"p": P, "q": Q, "dia": hit[0], "len": hi - lo})
                break
    unpaired = [r for r in recs if not r["used"]]
    return mids, unpaired


def pair_arcs(arcs, dias=DIAS, dtol=0.35, ctol=0.5):
    out, used = [], set()
    by_c = collections.defaultdict(list)
    for i, a in enumerate(arcs):
        by_c[(round(a["c"][0] / 2), round(a["c"][1] / 2))].append(i)
    keys = list(by_c)
    for k in keys:
        cand = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                cand += by_c.get((k[0] + dx, k[1] + dy), [])
        cand = sorted(set(cand))
        for ii in range(len(cand)):
            i = cand[ii]
            if i in used:
                continue
            for jj in range(ii + 1, len(cand)):
                j = cand[jj]
                if j in used:
                    continue
                A, B = arcs[i], arcs[j]
                if math.dist(A["c"], B["c"]) > ctol:
                    continue
                d = abs(A["r"] - B["r"])
                hit = [D for D in dias if abs(d - D) < dtol]
                if not hit:
                    continue
                sw = (A["a1"] - A["a0"]) % 360
                out.append({"c": A["c"], "r": (A["r"] + B["r"]) / 2,
                            "a0": A["a0"], "a1": A["a1"], "sweep": sw,
                            "dia": hit[0]})
                used.add(i); used.add(j)
                break
    return out


def merge_collinear(mids, atol=0.6, otol=0.4, gap=1.5):
    """Merge centreline pieces lying on the same infinite line into whole bars."""
    groups = collections.defaultdict(list)
    for m in mids:
        a, off, s0, s1 = _norm_line(m["p"], m["q"])
        groups[(m["dia"], round(a / math.radians(atol)), round(off / otol))].append(
            {"a": a, "off": off, "s0": s0, "s1": s1, "dia": m["dia"]})
    bars = []
    for key, items in groups.items():
        items.sort(key=lambda r: r["s0"])
        cur = None
        for r in items:
            if cur and r["s0"] <= cur["s1"] + gap:
                cur["s1"] = max(cur["s1"], r["s1"])
            else:
                if cur:
                    bars.append(cur)
                cur = dict(r)
        if cur:
            bars.append(cur)
    out = []
    for b in bars:
        ux, uy = math.cos(b["a"]), math.sin(b["a"])
        nx, ny = -uy, ux
        P = (ux * b["s0"] + nx * b["off"], uy * b["s0"] + ny * b["off"])
        Q = (ux * b["s1"] + nx * b["off"], uy * b["s1"] + ny * b["off"])
        out.append({"p": P, "q": Q, "dia": b["dia"], "len": b["s1"] - b["s0"],
                    "ang": math.degrees(b["a"])})
    return out


def endcaps(arcs, dias=DIAS, rtol=0.3):
    """Arc groups of radius d/2 mark a bar end at the arc centre."""
    caps = collections.defaultdict(lambda: {"n": 0})
    for a in arcs:
        hit = [D for D in dias if abs(a["r"] - D / 2) < rtol]
        if not hit:
            continue
        k = (hit[0], round(a["c"][0], 1), round(a["c"][1], 1))
        caps[k]["n"] += 1
    return [{"dia": k[0], "p": (k[1], k[2]), "n": v["n"]} for k, v in caps.items()]
