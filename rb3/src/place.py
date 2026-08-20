"""Bind schedule marks to real positions using the drawing's own annotation.

The (R) drawings label reinforcement explicitly: a mark tag ("B"), a quantity
note ("-(61) -(T8 U Bar)"), an optional spacing note ("T8 @200 mm"), and a
leader line whose arrow head lands on the bar being labelled. That annotation
-- not a geometric guess -- is what tells us which bar is which and how it
sits in the panel.
"""
import math, re, collections
import ezdxf
import rbar

IDEN = "S-RBAR-IDEN"


def _pt(p):
    return (p.x, p.y)


def leader_tips(doc, view, tags_marks, max_gap=60.0):
    """Chain S-RBAR-IDEN leader segments from each mark tag to its arrow head.

    Returns {index of tag: (x, y)} in model coordinates -- the point on the bar.
    """
    msp = doc.modelspace()
    segs = []
    for e in msp:
        if e.dxf.layer != IDEN or e.dxftype() != "LINE":
            continue
        a, b = _pt(e.dxf.start), _pt(e.dxf.end)
        if rbar.in_box(a, view["box"], 3000) and rbar.in_box(b, view["box"], 3000):
            segs.append((a, b))
    # arrow heads are drawn as small closed triangles (~26-80mm legs)
    short = [s for s in segs if math.dist(*s) < 110]
    long_ = [s for s in segs if math.dist(*s) >= 110]
    heads = []
    for a, b in short:
        heads.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))

    out = {}
    for i, t in enumerate(tags_marks):
        tp = t["p"]
        # walk outward from the tag along connected long segments
        best, bd = None, 1e9
        for a, b in long_:
            for p, q in ((a, b), (b, a)):
                d = math.dist(p, tp)
                if d < max_gap * 8 and d < bd:
                    best, bd = q, d
        if best is None:
            continue
        # snap to the nearest arrow head if one is close to that end
        if heads:
            h = min(heads, key=lambda h: math.dist(h, best))
            if math.dist(h, best) < 160:
                best = h
        out[i] = best
    return out


def mark_annotations(doc, view):
    """Mark -> annotation: quantity, diameter, free text, and spacing."""
    marks, notes, spacing = rbar.tags(doc, view["box"], 3000)
    tips = leader_tips(doc, view, marks)
    recs = []
    for i, m in enumerate(marks):
        # the quantity note belongs to the tag it sits closest to
        best, bd = None, 1e9
        for n in notes:
            d = math.dist(n["p"], m["p"])
            if d < bd:
                best, bd = n, d
        sp = None
        for s in spacing:
            if math.dist(s["p"], m["p"]) < 900:
                mm = re.search(r"@\s*(\d+)", s["t"])
                if mm:
                    sp = int(mm.group(1))
                    break
        recs.append({"mark": m["mark"], "tag": m["p"], "tip": tips.get(i),
                     "qty": best["qty"] if bd < 900 else None,
                     "dia": best["dia"] if bd < 900 else None,
                     "extra": (best["extra"] if bd < 900 else "") or "",
                     "spacing": sp})
    return recs


SPACING_RE = re.compile(r"@\s*(\d+)")


def annotation_index(doc, vlist):
    """One record per mark, merged over all views.

    View windows are padded and therefore overlap, so the same tag can be seen
    from several viewports; tags are de-duplicated by position before their
    quantities are combined.
    """
    # Each view carries its own copy of the mark labels, so quantities must be
    # taken from ONE view -- the elevation, which is where the runs of bars are
    # actually laid out. Other views only contribute descriptive text.
    elev = [v for v in vlist if v["kind"] == "elevation"]
    src = [max(elev, key=lambda e: e["w"] * e["h"])] if elev else vlist[:1]
    seen, recs = set(), []
    for v in src:
        try:
            rs = mark_annotations(doc, v)
        except Exception:
            continue
        for r in rs:
            key = (r["mark"], round(r["tag"][0], 1), round(r["tag"][1], 1))
            if key in seen:
                continue
            seen.add(key)
            recs.append(r)
    out = {}
    for r in recs:
        k = r["mark"]
        cur = out.setdefault(k, {"mark": k, "qty": 0, "extra": set(),
                                 "spacing": None, "tips": [], "groups": []})
        if r["qty"]:
            cur["qty"] += r["qty"]
            cur["groups"].append(r["qty"])
        if r["extra"]:
            cur["extra"].add(r["extra"])
        sp = r["spacing"]
        if sp is None and r["extra"]:
            m = SPACING_RE.search(r["extra"])
            if m:
                sp = int(m.group(1))
        if sp:
            cur["spacing"] = sp
        if r["tip"]:
            cur["tips"].append(r["tip"])
    for v in out.values():
        v["extra"] = " ".join(sorted(v["extra"]))
    return out


def bar_axes(mark, env, note, clear_tol=18.0):
    """Decide how a bar sits in the panel, from meaning rather than fit.

    Returns (run_axis, fold_axis, through_thickness, why).
      run_axis   - the axis the bar's first leg follows
      fold_axis  - the axis its bends fold into
    A bar is 'through thickness' when the drawing calls it a U bar / link, or
    when one of its legs equals the clear distance between covers -- which is
    only possible if that leg spans the panel thickness.
    """
    T = env.get("thickness_mm") or 200.0
    W, H = env["width_mm"], env["height_mm"]
    d = mark["dia_mm"]
    clear = T - 2 * (30.0 + d / 2.0)
    legs = {k: v for k, v in mark["dims_mm"].items() if v}
    txt = (note or {}).get("extra", "").lower()

    spanning = [k for k, v in legs.items() if abs(v - clear) <= clear_tol]
    is_u = ("u bar" in txt) or ("link" in txt) or mark["shape"].startswith("M_T")
    through = bool(spanning) or is_u

    # the longest leg tells us what the bar mainly follows
    longest = max(legs.values()) if legs else mark["bar_length_mm"]
    # Which way the bar runs is decided by which panel dimension it actually
    # fits. A 3.7 m bar in a 3.76 x 2.93 m panel runs across the width; the
    # same bar in a 1.3 x 9.1 m panel runs up the height.
    def pick_run(extent):
        opts = []
        for ax, span in (("X", W), ("Z", H)):
            slack = span - extent
            opts.append((0 if slack >= -20 else 1, abs(slack), ax))
        opts.sort()
        return opts[0][2]

    if through:
        # legs lie in the panel plane, the fold crosses the thickness
        run = pick_run(longest)
        return run, "Y", True, ("annotated U bar/link" if is_u
                                else f"leg {spanning[0]}={legs[spanning[0]]:.0f} = clear {clear:.0f}")
    run = pick_run(longest)
    fold = "Z" if run == "X" else "X"
    return run, fold, False, f"in-plane, follows panel {'width' if run == 'X' else 'height'}"


def to3d(pts2d, origin, run, fold, sign_u=1, sign_v=1):
    """Map a bending-plane polyline onto the chosen panel axes."""
    ox, oy, oz = origin
    idx = {"X": 0, "Y": 1, "Z": 2}
    out = []
    for (u, v) in pts2d:
        p = [ox, oy, oz]
        p[idx[run]] += sign_u * u
        p[idx[fold]] += sign_v * v
        out.append(tuple(p))
    return out
