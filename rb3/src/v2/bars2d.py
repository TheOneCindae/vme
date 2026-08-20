"""Stage 2 - recover every drawn bar in every view as a 2D centreline.

Bars are drawn as OUTLINES on layer S-RBAR: two parallel edges offset by the
bar diameter, concentric arc pairs at every bend, and a 180 degree end cap of
radius d/2 at each free end.  A bar seen end-on in a section is a CIRCLE of
radius d/2.

The recovery is therefore:

  edges  -> medial axis        (pair parallel lines offset by d)
  bends  -> concentric arcs    (pair arcs about one centre whose radii differ
                                by d; both arcs are merged from the fragments
                                left behind by hidden-line trimming first)
  ends   -> 180 degree caps    (an unpaired arc of radius d/2)

Drawn geometry is fragmented wherever another bar passes in front, so every
stage works on *intervals* (along a line, along a circle) that are merged back
together, and merging is only ever blocked by an end cap - the one piece of
evidence that says "the bar really stops here".  Finally the straight runs and
the bend arcs are chained through their shared endpoints so a U-bar or a
hooked bar comes out as one polyline.

Reads stage 1 (`out/v2/raw/<sheet>.json`) when it exists, otherwise the cached
DXF directly - both through `load_entities()`.
"""
from __future__ import annotations

import collections
import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DXF_DIR = os.path.join(ROOT, "dxf")
RAW_DIR = os.path.join(ROOT, "out", "v2", "raw")
OUT_DIR = os.path.join(ROOT, "out", "v2", "bars2d")

RBAR = "S-RBAR"
WALL_LAYERS = ("A-WALL", "A-WALL-HDLN")
DIAS = (8, 10, 12, 16, 20, 25, 32)

# tolerances (drawing units = mm, drawn 1:1)
A_TOL = math.radians(0.4)   # two edges count as parallel within this
D_TOL = 0.35                # offset must match a diameter this closely
O_TOL = 0.6                 # centrelines this close are the same line
GAP = 30.0                  # bridge a hidden-line break up to this long
JOIN = 4.0                  # endpoints this close are the same node
CAP_REACH = 14.0            # how far a run may be stretched onto an end cap


# --------------------------------------------------------------------------
# stage 1 interface
# --------------------------------------------------------------------------

def load_entities(sheet):
    """Normalised entities + viewports for a sheet.

    Returns ``{"sheet":..., "entities":[...], "viewports":[...]}`` where an
    entity is ``{"type","layer","pts","r","a0","a1","text"}``.  Prefers the
    stage 1 JSON; falls back to reading the cached DXF.
    """
    raw = os.path.join(RAW_DIR, sheet + ".json")
    if os.path.exists(raw):
        with open(raw) as fh:
            d = json.load(fh)
        if d.get("entities"):
            return d
    return _from_dxf(sheet)


def _from_dxf(sheet):
    import ezdxf
    doc = ezdxf.readfile(os.path.join(DXF_DIR, sheet + ".dxf"))
    ents = []
    for e in doc.modelspace():
        t = e.dxftype()
        lay = e.dxf.layer
        if t == "LINE":
            s, q = e.dxf.start, e.dxf.end
            ents.append({"type": t, "layer": lay, "pts": [[s.x, s.y], [q.x, q.y]]})
        elif t == "ARC":
            c = e.dxf.center
            ents.append({"type": t, "layer": lay, "c": [c.x, c.y],
                         "pts": [[c.x, c.y]], "r": e.dxf.radius,
                         "a0": e.dxf.start_angle, "a1": e.dxf.end_angle})
        elif t == "CIRCLE":
            c = e.dxf.center
            ents.append({"type": t, "layer": lay, "c": [c.x, c.y],
                         "pts": [[c.x, c.y]], "r": e.dxf.radius})
        elif t == "LWPOLYLINE":
            pts = [[p[0], p[1]] for p in e.get_points()]
            if e.closed and len(pts) > 2:
                pts = pts + [pts[0]]
            ents.append({"type": t, "layer": lay, "pts": pts})
    vps = []
    try:
        lay = doc.layout("Layout1")
    except Exception:
        lay = None
    titles = []
    if lay is not None:
        for e in lay:
            if e.dxftype() == "MTEXT":
                t = " ".join(e.text.replace("\\P", " ").split())
                if t:
                    titles.append((e.dxf.insert.x, e.dxf.insert.y, t))
        for v in lay.query("VIEWPORT"):
            dx = v.dxf
            if dx.width < 20 or dx.height < 20:
                continue
            vh = dx.view_height
            vw = vh * dx.width / dx.height
            cx, cy = dx.view_center_point.x, dx.view_center_point.y
            best, bd = None, 1e9
            for tx, ty, t in titles:
                if "REINF" not in t.upper():
                    continue
                d = (abs(tx - (dx.center.x - dx.width / 2) - 6)
                     + abs(ty - (dx.center.y - dx.height / 2)))
                if d < bd:
                    best, bd = t, d
            vps.append({"center": [cx, cy], "w": vw, "h": vh,
                        "scale": round(vh / dx.height, 1), "title": best})
    return {"sheet": sheet, "entities": ents, "viewports": vps}


def _box(vp):
    """Model-space window of a viewport (stage 1 gives it directly)."""
    if vp.get("window"):
        return tuple(vp["window"])
    cx, cy = vp["center"]
    return (cx - vp["w"] / 2, cy - vp["h"] / 2, cx + vp["w"] / 2, cy + vp["h"] / 2)


def viewports(d):
    """Real drawing viewports, largest first, skipping the dummy 12x9 one."""
    out = []
    for vp in d.get("viewports", []):
        b = _box(vp)
        if b[2] - b[0] < 100 or b[3] - b[1] < 100:
            continue
        out.append(vp)
    return out


def _inside(p, box, pad=0.0):
    return (box[0] - pad <= p[0] <= box[2] + pad
            and box[1] - pad <= p[1] <= box[3] + pad)


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def _cluster(vals, tol):
    """Single-link 1-D clustering -> list of index lists (vals is a list)."""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    out, cur = [], []
    for i in order:
        if cur and vals[i] - vals[cur[-1]] > tol:
            out.append(cur)
            cur = []
        cur.append(i)
    if cur:
        out.append(cur)
    return out


def _merge_iv(ivs, gap, blocks=()):
    """Merge 1-D intervals, refusing to bridge a gap that contains a block."""
    ivs = sorted(ivs)
    blocks = sorted(blocks)
    out = [list(ivs[0])]
    for a, b in ivs[1:]:
        if a - out[-1][1] <= gap and not any(
                out[-1][1] - O_TOL <= x <= a + O_TOL for x in blocks):
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _norm(p, q):
    """(angle mod pi, signed normal offset, s-lo, s-hi) of a segment."""
    a = math.atan2(q[1] - p[1], q[0] - p[0]) % math.pi
    ux, uy = math.cos(a), math.sin(a)
    off = -p[0] * uy + p[1] * ux
    s0 = p[0] * ux + p[1] * uy
    s1 = q[0] * ux + q[1] * uy
    return a, off, min(s0, s1), max(s0, s1)


def _pt(a, off, s):
    ux, uy = math.cos(a), math.sin(a)
    return (ux * s - uy * off, uy * s + ux * off)


def _apt(c, r, deg):
    t = math.radians(deg)
    return (c[0] + r * math.cos(t), c[1] + r * math.sin(t))


def _plen(pts):
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


# --------------------------------------------------------------------------
# arcs: merge fragments, then pair concentric radii
# --------------------------------------------------------------------------

def _arc_rings(arcs):
    """Group arc fragments into (centre, radius) rings with merged angle spans."""
    rings = []
    bycell = collections.defaultdict(list)
    for i, a in enumerate(arcs):
        bycell[(round(a["c"][0] / 4), round(a["c"][1] / 4))].append(i)
    seen = set()
    for key, idxs in list(bycell.items()):
        cand = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                cand += bycell.get((key[0] + dx, key[1] + dy), [])
        cand = sorted(set(cand))
        # centre clusters
        groups = collections.defaultdict(list)
        for i in cand:
            groups[(round(arcs[i]["c"][0] * 4), round(arcs[i]["c"][1] * 4))].append(i)
        for gk, gi in groups.items():
            if gk in seen:
                continue
            seen.add(gk)
            rs = [arcs[i]["r"] for i in gi]
            for cl in _cluster(rs, 0.3):
                ii = [gi[k] for k in cl]
                cx = sum(arcs[i]["c"][0] for i in ii) / len(ii)
                cy = sum(arcs[i]["c"][1] for i in ii) / len(ii)
                r = sum(arcs[i]["r"] for i in ii) / len(ii)
                spans = []
                for i in ii:
                    a0 = arcs[i]["a0"] % 360
                    a1 = arcs[i]["a1"] % 360
                    if a1 <= a0:
                        a1 += 360
                    spans.append((a0, a1))
                    spans.append((a0 - 360, a1 - 360))
                gapdeg = math.degrees(GAP / max(r, 1.0))
                m = _merge_iv(spans, min(gapdeg, 40.0))
                # keep the canonical copies
                m = [s for s in m if -180 <= s[0] < 360]
                rings.append({"c": (cx, cy), "r": r, "spans": m})
    return rings


def _bends_and_caps(arcs):
    """Split arc rings into bend centrelines (paired) and 180-degree end caps."""
    rings = _arc_rings(arcs)
    bycen = collections.defaultdict(list)
    for rg in rings:
        bycen[(round(rg["c"][0] * 4), round(rg["c"][1] * 4))].append(rg)
    bends, caps, used = [], [], set()
    for cen, rgs in bycen.items():
        rgs.sort(key=lambda r: r["r"])
        for i in range(len(rgs)):
            if id(rgs[i]) in used:
                continue
            for j in range(i + 1, len(rgs)):
                if id(rgs[j]) in used:
                    continue
                d = rgs[j]["r"] - rgs[i]["r"]
                hit = [D for D in DIAS if abs(d - D) < D_TOL]
                if not hit:
                    continue
                spans = _merge_iv(rgs[i]["spans"] + rgs[j]["spans"], 45.0)
                rm = (rgs[i]["r"] + rgs[j]["r"]) / 2
                for s0, s1 in spans:
                    if s1 - s0 < 2.0:
                        continue
                    bends.append({"c": rgs[i]["c"], "r": rm, "dia": hit[0],
                                  "a0": s0, "a1": min(s1, s0 + 359.0)})
                used.add(id(rgs[i]))
                used.add(id(rgs[j]))
                break
    for rg in rings:
        if id(rg) in used:
            continue
        hit = [D for D in DIAS if abs(rg["r"] - D / 2) < 0.35]
        if not hit:
            continue
        for s0, s1 in rg["spans"]:
            if s1 - s0 < 100:
                continue
            mid = math.radians((s0 + s1) / 2)
            caps.append({"p": rg["c"], "dia": hit[0],
                         "out": (math.cos(mid), math.sin(mid)),
                         "sweep": s1 - s0})
    return bends, caps


# --------------------------------------------------------------------------
# lines: pair edges into centreline runs
# --------------------------------------------------------------------------

def _pair_edges(lines):
    """Pair parallel edges offset by a bar diameter -> centreline intervals."""
    recs = []
    for p, q in lines:
        if math.dist(p, q) < 0.15:
            continue
        a, off, s0, s1 = _norm(p, q)
        recs.append({"a": a, "off": off, "s0": s0, "s1": s1})
    # bucket by angle (with wrap at pi so 0 and 180 meet)
    step = A_TOL
    buckets = collections.defaultdict(list)
    for i, r in enumerate(recs):
        k = int(r["a"] / step)
        for kk in (k - 1, k, k + 1):
            buckets[kk].append(i)
    kmax = int(math.pi / step)
    for i, r in enumerate(recs):
        if r["a"] < step:
            buckets[kmax].append(i)
        if r["a"] > math.pi - step:
            buckets[-1].append(i)

    cand = collections.defaultdict(list)      # (i,j) -> overlap len, dia
    for _, idxs in buckets.items():
        idxs = sorted(set(idxs), key=lambda i: recs[i]["off"])
        for x in range(len(idxs)):
            i = idxs[x]
            ri = recs[i]
            for y in range(x + 1, len(idxs)):
                j = idxs[y]
                rj = recs[j]
                d = rj["off"] - ri["off"]
                if d > max(DIAS) + D_TOL:
                    break
                if d < DIAS[0] - D_TOL:
                    continue
                da = abs(ri["a"] - rj["a"])
                da = min(da, math.pi - da)
                if da > A_TOL:
                    continue
                hit = [D for D in DIAS if abs(d - D) < D_TOL]
                if not hit:
                    continue
                ov = min(ri["s1"], rj["s1"]) - max(ri["s0"], rj["s0"])
                if ov <= 0.2:
                    continue
                key = (i, j) if i < j else (j, i)
                cand[key] = (ov, hit[0])

    # a drawn edge belongs to exactly one bar, so it has exactly one diameter:
    # pick the diameter with the most supporting overlap and keep only pairs
    # both edges agree on.
    vote = collections.defaultdict(lambda: collections.Counter())
    for (i, j), (ov, D) in cand.items():
        vote[i][D] += ov
        vote[j][D] += ov
    best = {i: c.most_common(1)[0][0] for i, c in vote.items()}

    segs = []
    for (i, j), (ov, D) in cand.items():
        if best[i] != D or best[j] != D:
            continue
        ri, rj = recs[i], recs[j]
        a = (ri["a"] + rj["a"]) / 2
        off = (ri["off"] + rj["off"]) / 2
        segs.append({"a": a, "off": off,
                     "s0": max(ri["s0"], rj["s0"]),
                     "s1": min(ri["s1"], rj["s1"]), "dia": D})
    return segs


def _runs(segs, caps):
    """Merge centreline pieces on the same infinite line into whole runs."""
    bydia = collections.defaultdict(list)
    for s in segs:
        bydia[s["dia"]].append(s)
    runs = []
    for dia, ss in bydia.items():
        capp = [c for c in caps if c["dia"] == dia]
        angs = [s["a"] for s in ss]
        for acl in _cluster(angs, A_TOL * 2):
            grp = [ss[i] for i in acl]
            # a near-0 / near-pi split is the same direction
            offs = [g["off"] for g in grp]
            for ocl in _cluster(offs, O_TOL):
                gg = [grp[i] for i in ocl]
                a = sum(g["a"] for g in gg) / len(gg)
                off = sum(g["off"] for g in gg) / len(gg)
                ux, uy = math.cos(a), math.sin(a)
                blocks = []
                for c in capp:
                    d = abs(-c["p"][0] * uy + c["p"][1] * ux - off)
                    if d < 1.5:
                        blocks.append(c["p"][0] * ux + c["p"][1] * uy)
                ivs = [(g["s0"], g["s1"]) for g in gg]
                for s0, s1 in _merge_iv(ivs, GAP, blocks):
                    if s1 - s0 < 1.0:
                        continue
                    runs.append({"dia": dia, "a": a, "off": off,
                                 "p": _pt(a, off, s0), "q": _pt(a, off, s1)})
    return runs


def _snap_caps(runs, caps):
    """Stretch a run onto an end cap sitting just beyond its end."""
    bydia = collections.defaultdict(list)
    for c in caps:
        bydia[c["dia"]].append(c)
    for r in runs:
        a, off = r["a"], r["off"]
        ux, uy = math.cos(a), math.sin(a)
        s0 = r["p"][0] * ux + r["p"][1] * uy
        s1 = r["q"][0] * ux + r["q"][1] * uy
        r["cap0"] = r["cap1"] = False
        for c in bydia.get(r["dia"], ()):
            if abs(-c["p"][0] * uy + c["p"][1] * ux - off) > 1.5:
                continue
            t = c["p"][0] * ux + c["p"][1] * uy
            if abs(t - s0) < CAP_REACH and (t < s0 or abs(t - s0) < 1.0):
                s0 = min(s0, t)
                r["cap0"] = True
            elif abs(t - s1) < CAP_REACH and (t > s1 or abs(t - s1) < 1.0):
                s1 = max(s1, t)
                r["cap1"] = True
        r["p"], r["q"] = _pt(a, off, s0), _pt(a, off, s1)
    return runs


# --------------------------------------------------------------------------
# chaining runs + bends into whole bars
# --------------------------------------------------------------------------

def _arc_pts(b, step=12.0):
    n = max(2, int(math.ceil(abs(b["a1"] - b["a0"]) / step)))
    return [_apt(b["c"], b["r"], b["a0"] + (b["a1"] - b["a0"]) * k / n)
            for k in range(n + 1)]


def _chain(runs, bends):
    """Join straight runs and bend arcs that share an endpoint."""
    items = []
    for r in runs:
        items.append({"kind": "run", "dia": r["dia"], "pts": [r["p"], r["q"]],
                      "cap": (r.get("cap0", False), r.get("cap1", False))})
    for b in bends:
        pts = _arc_pts(b)
        items.append({"kind": "bend", "dia": b["dia"], "pts": pts,
                      "cap": (False, False)})

    # node index over endpoints
    cell = collections.defaultdict(list)
    for i, it in enumerate(items):
        for e in (0, 1):
            p = it["pts"][0] if e == 0 else it["pts"][-1]
            cell[(int(p[0] // JOIN), int(p[1] // JOIN))].append((i, e))

    def neigh(i, e):
        it = items[i]
        p = it["pts"][0] if e == 0 else it["pts"][-1]
        # a genuine end cap terminates the bar
        if it["cap"][e]:
            return []
        cx, cy = int(p[0] // JOIN), int(p[1] // JOIN)
        out = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for (j, f) in cell.get((cx + dx, cy + dy), ()):
                    if j == i:
                        continue
                    jt = items[j]
                    if jt["dia"] != it["dia"] or jt["cap"][f]:
                        continue
                    q = jt["pts"][0] if f == 0 else jt["pts"][-1]
                    if math.dist(p, q) <= JOIN:
                        out.append((j, f, math.dist(p, q)))
        # prefer straight->bend joins and the closest match
        out.sort(key=lambda t: (items[t[0]]["kind"] == it["kind"], t[2]))
        return out

    def tangent(i, e):
        pts = items[i]["pts"]
        if e == 1:
            u, v = pts[-2], pts[-1]
        else:
            u, v = pts[1], pts[0]
        L = math.dist(u, v) or 1.0
        return ((v[0] - u[0]) / L, (v[1] - u[1]) / L)

    used = [False] * len(items)
    bars = []
    order = sorted(range(len(items)), key=lambda i: -_plen(items[i]["pts"]))
    for start in order:
        if used[start]:
            continue
        used[start] = True
        pts = list(items[start]["pts"])
        dia = items[start]["dia"]
        closed = False
        for side in (1, 0):
            cur, e = start, side
            while True:
                nb = [t for t in neigh(cur, e) if not used[t[0]]]
                if not nb:
                    # closing a loop?
                    if any(t[0] == start for t in neigh(cur, e)) and len(pts) > 3:
                        closed = True
                    break
                if len(nb) > 1:
                    tx, ty = tangent(cur, e)
                    def score(t):
                        j, f, _ = t
                        v = tangent(j, 1 - f)
                        return -(tx * v[0] + ty * v[1])
                    nb.sort(key=score)
                j, f, _ = nb[0]
                used[j] = True
                add = items[j]["pts"] if f == 0 else items[j]["pts"][::-1]
                if side == 1:
                    pts = pts + add[1:]
                else:
                    pts = add[::-1][:-1] + pts
                cur, e = j, 1 - f
        bars.append({"dia": dia, "pts": pts, "closed": closed})
    return bars


# --------------------------------------------------------------------------
# concrete outline
# --------------------------------------------------------------------------

def _wall_segments(ents, box):
    segs = []
    for e in ents:
        if e["layer"] not in WALL_LAYERS:
            continue
        t = e["type"]
        if t == "LINE":
            p, q = e["pts"]
            if _inside(p, box) or _inside(q, box):
                segs.append((tuple(p), tuple(q)))
        elif t == "LWPOLYLINE":
            pts = [tuple(p) for p in e["pts"]]
            if not any(_inside(p, box) for p in pts):
                continue
            for i in range(len(pts) - 1):
                segs.append((pts[i], pts[i + 1]))
    return segs


def wall_polygon(ents, box, min_run=25.0):
    """True concrete outline of the view as a closed rectilinear polygon.

    Built from a depth profile: for every X station the topmost and bottommost
    outline edge give the concrete extent there, so steps, notches and H-shaped
    panels survive (a bounding box does not).  The profile is then walked as a
    polygon - left to right along the top, right to left along the bottom.
    """
    segs = _wall_segments(ents, box)
    if not segs:
        return []
    xs = [p[0] for s in segs for p in s]
    ys = [p[1] for s in segs for p in s]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    W = x1 - x0
    if W <= 0:
        return []
    bins = max(60, min(1200, int(W / 3)))
    step = W / bins
    top = [None] * bins
    bot = [None] * bins
    for p, q in segs:
        if abs(p[1] - q[1]) > 2.0 or abs(p[0] - q[0]) < min_run:
            continue
        y = (p[1] + q[1]) / 2
        a, b = sorted((p[0], q[0]))
        i0 = max(0, min(bins - 1, int((a - x0) / step + 0.5)))
        i1 = max(0, min(bins - 1, int((b - x0) / step - 0.5)))
        for i in range(i0, i1 + 1):
            if top[i] is None or y > top[i]:
                top[i] = y
            if bot[i] is None or y < bot[i]:
                bot[i] = y
    # largest run of defined bins
    runs, cur = [], None
    for i in range(bins):
        if top[i] is None or bot[i] is None or top[i] - bot[i] < 1.0:
            cur = None
            continue
        if cur is None:
            cur = [i, i]
            runs.append(cur)
        else:
            cur[1] = i
    if not runs:
        return []
    i0, i1 = max(runs, key=lambda r: r[1] - r[0])
    up, dn = [], []
    for i in range(i0, i1 + 1):
        xa = x0 + i * step
        xb = x0 + (i + 1) * step
        if up and abs(up[-1][1] - top[i]) < 1.0:
            up[-1] = (xb, up[-1][1])
        else:
            if up:
                up.append((xa, top[i]))
            up.append((xa, top[i]))
            up.append((xb, top[i]))
        if dn and abs(dn[-1][1] - bot[i]) < 1.0:
            dn[-1] = (xb, dn[-1][1])
        else:
            if dn:
                dn.append((xa, bot[i]))
            dn.append((xa, bot[i]))
            dn.append((xb, bot[i]))
    poly = up + dn[::-1]
    # drop duplicate / collinear vertices
    out = []
    for p in poly:
        if out and math.dist(out[-1], p) < 0.5:
            continue
        out.append(p)
    clean = []
    n = len(out)
    for i, p in enumerate(out):
        a, b = out[i - 1], out[(i + 1) % n]
        cr = (p[0] - a[0]) * (b[1] - a[1]) - (p[1] - a[1]) * (b[0] - a[0])
        if abs(cr) < 1e-6:
            continue
        clean.append([round(p[0], 2), round(p[1], 2)])
    return clean


# --------------------------------------------------------------------------
# per view / per sheet
# --------------------------------------------------------------------------

def _view_kind(title, poly, box):
    t = (title or "").upper()
    if "ELEV" in t:
        return "elevation"
    if "SECT" in t:
        if poly:
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            w, h = max(xs) - min(xs), max(ys) - min(ys)
            return "plan_cut" if w > h * 1.4 else "end_cut"
        return "end_cut"
    return "detail"


def build_view(ents, vp, vid):
    box = _box(vp)
    lines, arcs, circles = [], [], []
    for e in ents:
        if e["layer"] != RBAR:
            continue
        t = e["type"]
        if t == "LINE":
            p, q = e["pts"]
            if _inside(p, box, 2) and _inside(q, box, 2):
                lines.append((tuple(p), tuple(q)))
        elif t == "ARC":
            c = e.get("c") or e["pts"][0]
            if _inside(c, box, 2):
                arcs.append({"c": tuple(c), "r": e["r"], "a0": e["a0"], "a1": e["a1"]})
        elif t == "CIRCLE":
            c = e.get("c") or e["pts"][0]
            if _inside(c, box, 2):
                circles.append({"c": tuple(c), "r": e["r"]})

    bends, caps = _bends_and_caps(arcs)
    segs = _pair_edges(lines)
    runs = _snap_caps(_runs(segs, caps), caps)
    chained = _chain(runs, bends)

    poly = wall_polygon(ents, box)
    bars = []
    for b in chained:
        pts = [[round(x, 2), round(y, 2)] for x, y in b["pts"]]
        L = _plen(b["pts"])
        if L < 3.0:
            continue
        bars.append({"id": "%s-b%d" % (vid, len(bars)), "dia": b["dia"],
                     "pts": pts, "closed": b["closed"], "kind": "run",
                     "len": round(L, 1), "evidence": "paired_edges"})
    seen = set()
    for c in circles:
        hit = [D for D in DIAS if abs(c["r"] - D / 2) < 0.35]
        if not hit:
            continue
        k = (round(c["c"][0], 1), round(c["c"][1], 1))
        if k in seen:
            continue
        seen.add(k)
        bars.append({"id": "%s-s%d" % (vid, len(bars)), "dia": hit[0],
                     "pts": [[round(c["c"][0], 2), round(c["c"][1], 2)]],
                     "closed": False, "kind": "section", "len": 0.0,
                     "evidence": "circle"})
    return {"id": vid, "title": vp.get("title"), "scale": vp.get("scale"),
            "kind": _view_kind(vp.get("title"), poly, box),
            "box": [round(v, 2) for v in box],
            "wall_polygon": poly, "bars": bars,
            "stats": {"lines": len(lines), "arcs": len(arcs),
                      "circles": len(circles), "caps": len(caps),
                      "bends": len(bends), "runs": len(runs)}}


def build_sheet(sheet):
    d = load_entities(sheet)
    ents = [e for e in d["entities"] if e.get("space", "model") == "model"]
    views = []
    for i, vp in enumerate(viewports(d)):
        views.append(build_view(ents, vp, "v%d" % i))
    return {"sheet": sheet, "views": views}


def write_sheet(sheet):
    out = build_sheet(sheet)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, sheet + ".json"), "w") as fh:
        json.dump(out, fh)
    return out


if __name__ == "__main__":
    import sys
    for s in sys.argv[1:]:
        o = write_sheet(s)
        print("##", s)
        for v in o["views"]:
            runs = [b for b in v["bars"] if b["kind"] == "run"]
            secs = [b for b in v["bars"] if b["kind"] == "section"]
            per = collections.Counter(b["dia"] for b in runs)
            tot = collections.Counter()
            for b in runs:
                tot[b["dia"]] += b["len"]
            print("  %-4s %-22s %-10s runs=%d sect=%d poly=%d" % (
                v["id"], v["title"], v["kind"], len(runs), len(secs),
                len(v["wall_polygon"])))
            for dia in sorted(per):
                print("        T%-3d n=%-4d len=%.0f" % (dia, per[dia], tot[dia]))
