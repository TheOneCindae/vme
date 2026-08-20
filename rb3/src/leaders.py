"""Bind mark tags to the exact bars they label, via leader lines.

The DWG places annotation blocks at the origin with world coordinates baked
into the block geometry, so the leader heads only appear once the blocks are
exploded -- reading model space alone misses them entirely. Each mark tag has
a leader running from a head beside the text to an arrow tip that lands on the
bar. Chaining head -> leader -> tip and then snapping the tip to the nearest
bar of the right diameter identifies the bar the schedule mark refers to.
"""
import math, collections
import ezdxf
import rbar

IDEN = "S-RBAR-IDEN"


def heads(doc):
    """Leader head points, recovered by exploding the annotation blocks."""
    out = []
    for e in doc.modelspace().query("INSERT"):
        try:
            ve = list(e.virtual_entities())
        except Exception:
            continue
        ps = []
        for v in ve:
            if v.dxf.layer != IDEN:
                continue
            t = v.dxftype()
            if t == "LINE":
                ps += [(v.dxf.start.x, v.dxf.start.y), (v.dxf.end.x, v.dxf.end.y)]
            elif t in ("CIRCLE", "ARC"):
                ps.append((v.dxf.center.x, v.dxf.center.y))
        if ps:
            out.append({"name": e.dxf.name,
                        "p": (sum(p[0] for p in ps) / len(ps),
                              sum(p[1] for p in ps) / len(ps))})
    return out


def segments(doc):
    """Leader polyline segments (world coordinates), model space + blocks."""
    segs = []
    msp = doc.modelspace()
    for e in msp:
        if e.dxf.layer == IDEN and e.dxftype() == "LINE":
            segs.append(((e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)))
    for e in msp.query("INSERT"):
        try:
            ve = list(e.virtual_entities())
        except Exception:
            continue
        for v in ve:
            if v.dxf.layer == IDEN and v.dxftype() == "LINE":
                segs.append(((v.dxf.start.x, v.dxf.start.y),
                             (v.dxf.end.x, v.dxf.end.y)))
    return segs


def _chain(segs, start, max_hops=6, snap=40.0):
    """Walk connected leader segments away from `start`; return the far end."""
    cur, used, visited = start, set(), 0
    while visited < max_hops:
        best, bd, bi = None, 1e9, None
        for i, (a, b) in enumerate(segs):
            if i in used:
                continue
            for p, q in ((a, b), (b, a)):
                d = math.dist(p, cur)
                if d < snap and d < bd and math.dist(p, q) > 12:
                    best, bd, bi = q, d, i
        if best is None:
            break
        used.add(bi)
        cur = best
        visited += 1
    return cur


def components(segs, snap=40.0):
    """Connected components of the leader network, as point sets."""
    n = len(segs)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i

    def uni(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # bucket endpoints so this stays cheap
    grid = collections.defaultdict(list)
    for i, (a, b) in enumerate(segs):
        for p in (a, b):
            grid[(int(p[0] // snap), int(p[1] // snap))].append((i, p))
    for key, items in grid.items():
        for dx in (0, 1):
            for dy in (0, 1):
                other = grid.get((key[0] + dx, key[1] + dy), [])
                for i, p in items:
                    for j, q in other:
                        if i != j and math.dist(p, q) < snap:
                            uni(i, j)
    comps = collections.defaultdict(list)
    for i, (a, b) in enumerate(segs):
        comps[find(i)] += [a, b]
    return list(comps.values())


def tag_tips(doc, view, marks, snap=40.0):
    """For each mark tag, the point on the bar its leader indicates.

    Leaders are followed as connected components rather than walked segment by
    segment: the component touching the tag is found, and its end lying inside
    the drawn element -- where the bars are -- is taken as the tip.
    """
    segs = [s for s in segments(doc)
            if rbar.in_box(s[0], view["box"], 4000) and rbar.in_box(s[1], view["box"], 4000)]
    comps = components(segs, snap=snap)
    wall = view["wall"]

    def inside(p, pad=120.0):
        return (wall[0] - pad <= p[0] <= wall[2] + pad
                and wall[1] - pad <= p[1] <= wall[3] + pad)

    out = []
    for m in marks:
        tp = m["p"]
        best, bd = None, 1e9
        for c in comps:
            d = min(math.dist(tp, q) for q in c)
            if d < bd:
                best, bd = c, d
        tip = None
        if best is not None and bd < 900:
            cand = [q for q in best if inside(q)]
            if cand:
                # the end deepest inside the element is the one on the bar
                tip = min(cand, key=lambda q: math.dist(q, tp)) if len(cand) < 3 else \
                      max(cand, key=lambda q: math.dist(q, tp))
                tip = min(cand, key=lambda q: abs(q[0] - (wall[0] + wall[2]) / 2))
        out.append({"mark": m["mark"], "tag": tp, "tip": tip})
    return out


def snap_to_bars(tip, prims, dia=None, max_d=90.0):
    """Nearest drawn bar to a leader tip, optionally constrained by diameter."""
    best, bd = None, 1e9
    for p in prims:
        if dia and p["dia"] != dia:
            continue
        if p["kind"] == "circle":
            d = math.dist(tip, p["p"])
        else:
            d = _pt_seg(tip, p["p"], p["q"])
        if d < bd:
            best, bd = p, d
    return (best, bd) if best and bd <= max_d else (None, bd)


def _pt_seg(p, a, b):
    ax, ay = a; bx, by = b
    vx, vy = bx - ax, by - ay
    L = vx * vx + vy * vy
    if L < 1e-9:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - ax) * vx + (p[1] - ay) * vy) / L))
    return math.dist(p, (ax + t * vx, ay + t * vy))


def primitives(doc, view, dias):
    """Every drawn bar in a view: end-on circles and centreline runs."""
    out = []
    for c in rbar.circles(doc, view["box"]):
        if c["dia"] in dias:
            out.append({"kind": "circle", "p": c["p"], "q": c["p"], "dia": c["dia"]})
    lines, _ = rbar.collect(doc, view["box"])
    mids, _ = rbar.pair_lines(lines, dias=dias)
    for b in rbar.merge_collinear(mids, gap=30.0):
        if b["len"] > 60:
            out.append({"kind": "run", "p": b["p"], "q": b["q"], "dia": b["dia"],
                        "len": b["len"]})
    return out
