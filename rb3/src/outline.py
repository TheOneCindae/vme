"""Recover the true concrete outline of an element from its elevation.

Panels are not boxes. A shear wall has thicker boundary columns at each end,
notches and shear keys, and the reinforcement follows that shape -- dense tie
cages in the columns, wider-spaced horizontals across the web. Placing bars
inside a plain bounding box puts steel where there is no concrete.
"""
import math, collections
import rbar

WALL = ("A-WALL", "A-WALL-HDLN")
OUTLINE_LAYER_GROUPS = (("A-WALL", "A-WALL-HDLN"), ("S-COLS",), ("S-BEAM",), ("S-SLAB",), ("A-FLOR",))


def _segments_on(doc, view, layers):
    segs = []
    for e in doc.modelspace():
        if e.dxf.layer not in layers:
            continue
        t = e.dxftype()
        if t == "LINE":
            p = (e.dxf.start.x, e.dxf.start.y); q = (e.dxf.end.x, e.dxf.end.y)
            if rbar.in_box(p, view["box"]) or rbar.in_box(q, view["box"]):
                segs.append((p, q))
        elif t == "LWPOLYLINE":
            pts = [(x[0], x[1]) for x in e.get_points()]
            if not any(rbar.in_box(x, view["box"]) for x in pts):
                continue
            if e.closed and len(pts) > 2:
                pts = pts + [pts[0]]
            for i in range(len(pts) - 1):
                segs.append((pts[i], pts[i + 1]))
    return segs


def wall_segments(doc, view, layers=None):
    """Outline edges in a view.

    Wall panels outline on A-WALL/A-WALL-HDLN; columns (PC-*) outline on
    S-COLS, beams on S-BEAM. When the caller does not pin a layer set these
    are tried in priority order, stopping at the first with any geometry in
    this window -- a column sheet has no A-WALL at all, so defaulting to that
    layer alone left every column with an empty (and therefore zero-depth)
    profile, and every one of its bars measuring as outside the concrete.
    """
    if layers is not None:
        return _segments_on(doc, view, layers)
    for group in OUTLINE_LAYER_GROUPS:
        segs = _segments_on(doc, view, group)
        if segs:
            return segs
    return []


def profile(doc, view, bins=200, min_run=40.0):
    """Vertical extent of concrete at each X station, in panel-local mm.

    Built from the outline's horizontal edges: for each column of the element,
    the topmost and bottommost wall edge give the concrete depth there. This
    captures steps and notches that a bounding box hides.
    """
    wb = view["wall"]
    W = wb[2] - wb[0]; H = wb[3] - wb[1]
    segs = wall_segments(doc, view)
    step = W / bins
    tops = [None] * bins
    bots = [None] * bins
    for (p, q) in segs:
        x0, y0 = p[0] - wb[0], p[1] - wb[1]
        x1, y1 = q[0] - wb[0], q[1] - wb[1]
        if abs(y1 - y0) > 3.0:            # only near-horizontal edges
            continue
        if abs(x1 - x0) < min_run:
            continue
        y = (y0 + y1) / 2
        a, b = sorted((x0, x1))
        i0 = max(0, min(bins - 1, int(a / step)))
        i1 = max(0, min(bins - 1, int(b / step)))
        for i in range(i0, i1 + 1):
            if tops[i] is None or y > tops[i]:
                tops[i] = y
            if bots[i] is None or y < bots[i]:
                bots[i] = y
    prof = []
    for i in range(bins):
        if tops[i] is None or bots[i] is None:
            prof.append(None)
        else:
            prof.append((round(bots[i], 1), round(tops[i], 1)))
    return {"W": W, "H": H, "bins": bins, "step": step, "profile": prof}


def zones(prof, tol=60.0):
    """Split the element into runs of constant depth: columns vs web."""
    p = prof["profile"]; step = prof["step"]
    out, cur = [], None
    for i, v in enumerate(p):
        if v is None:
            if cur:
                out.append(cur); cur = None
            continue
        if cur and abs(v[0] - cur["lo"]) < tol and abs(v[1] - cur["hi"]) < tol:
            cur["i1"] = i
        else:
            if cur:
                out.append(cur)
            cur = {"i0": i, "i1": i, "lo": v[0], "hi": v[1]}
    if cur:
        out.append(cur)
    for z in out:
        z["x0"] = round(z["i0"] * step, 1)
        z["x1"] = round((z["i1"] + 1) * step, 1)
        z["depth"] = round(z["hi"] - z["lo"], 1)
    return [z for z in out if z["x1"] - z["x0"] > 60]
