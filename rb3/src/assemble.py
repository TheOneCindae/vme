"""Assemble the full 3D rebar model for a panel.

Coordinate frame (millimetres, panel-local):
    X  across the panel width
    Y  through the panel thickness (0 = back face)
    Z  up the panel height

Evidence used, in order of authority:
  1. The (S) schedule -- the verified bar list: every mark's diameter,
     shape, dimensions, cut length, quantity and weight. This drives the
     model, so no bar can be silently lost.
  2. Horizontal sections in the (R) drawing -- exact (X, Y) of every bar
     seen end-on, i.e. the vertical bars in plan.
  3. The vertical section -- exact (Y, Z) of the horizontal bars.
  4. The elevation -- extents and spacings.

Every placed bar records how its position was obtained, so derived
placements are never mistaken for measured ones.
"""
import math, json, collections
from pathlib import Path
import ezdxf
import rbar
import shapes3d as S

WALL_LAYERS = ("A-WALL", "A-WALL-HDLN")
OUTLINE_LAYER_GROUPS = (("A-WALL", "A-WALL-HDLN"), ("S-COLS",), ("S-BEAM",), ("S-SLAB",), ("A-FLOR",))


def wall_box(msp, box):
    """Extent of the element outline drawn in a view.

    A line only partly inside the viewport window still belongs to this view --
    requiring both endpoints inside truncates long wall lines and makes the
    element measure smaller than it is.

    Wall panels outline on A-WALL/A-WALL-HDLN, but columns (PC-*) outline on
    S-COLS and beams on S-BEAM. These are tried IN PRIORITY ORDER, stopping at
    the first group with geometry in this window -- pooling them together
    picks up incidental beam/corbel detailing that sits inside a wall sheet's
    own viewports and invents bogus extra elements. If none of those layers
    have geometry either, the reinforcement's own extent is the last resort
    so a view is never discarded outright.
    """
    for group in OUTLINE_LAYER_GROUPS:
        xs, ys = [], []
        for e in msp:
            if e.dxf.layer not in group or e.dxftype() != "LINE":
                continue
            s, t = e.dxf.start, e.dxf.end
            a_in = rbar.in_box((s.x, s.y), box)
            b_in = rbar.in_box((t.x, t.y), box)
            if not (a_in or b_in):
                continue
            xs += [s.x, t.x]; ys += [s.y, t.y]
        if xs:
            return (min(xs), min(ys), max(xs), max(ys))
    xs, ys = [], []
    for e in msp:
        if e.dxf.layer != rbar.RBAR or e.dxftype() != "LINE":
            continue
        s, t = e.dxf.start, e.dxf.end
        if rbar.in_box((s.x, s.y), box) and rbar.in_box((t.x, t.y), box):
            xs += [s.x, t.x]; ys += [s.y, t.y]
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def classify(doc, thickness_max=460.0):
    """Split the drawing's viewports into elevation / plan-cut / end-cut."""
    msp = doc.modelspace()
    out = []
    for v in rbar.views(doc):
        wb = wall_box(msp, v["box"])
        if not wb:
            continue
        w, h = wb[2] - wb[0], wb[3] - wb[1]
        if w > thickness_max and h > thickness_max:
            kind = "elevation"
        elif h <= thickness_max < w:
            kind = "plan_cut"        # horizontal cut: width x thickness
        elif w <= thickness_max < h:
            kind = "end_cut"         # vertical cut: thickness x height
        else:
            kind = "detail"
        out.append({**v, "wall": wb, "w": w, "h": h, "kind": kind})
    return out


def panel_envelope(vlist):
    elev = [v for v in vlist if v["kind"] == "elevation"]
    plan = [v for v in vlist if v["kind"] == "plan_cut"]
    end = [v for v in vlist if v["kind"] == "end_cut"]
    W = max((v["w"] for v in elev), default=None) or max((v["w"] for v in plan), default=0)
    H = max((v["h"] for v in elev), default=None) or max((v["h"] for v in end), default=0)
    T = None
    if plan:
        T = min(v["h"] for v in plan)
    elif end:
        T = min(v["w"] for v in end)
    return {"width_mm": round(W, 1), "height_mm": round(H, 1),
            "thickness_mm": round(T, 1) if T else None,
            "n_elevation": len(elev), "n_plan_cut": len(plan), "n_end_cut": len(end)}


def plan_bars(doc, view):
    """Vertical bars seen end-on in a horizontal cut -> (X, Y, dia), panel-local."""
    wb = view["wall"]
    out = []
    for c in rbar.circles(doc, view["box"]):
        x = c["p"][0] - wb[0]
        y = c["p"][1] - wb[1]
        out.append({"x": round(x, 1), "y": round(y, 1), "dia": c["dia"]})
    return out


def end_bars(doc, view):
    """Horizontal bars seen end-on in a vertical cut -> (Y, Z, dia), panel-local."""
    wb = view["wall"]
    out = []
    for c in rbar.circles(doc, view["box"]):
        y = c["p"][0] - wb[0]
        z = c["p"][1] - wb[1]
        out.append({"y": round(y, 1), "z": round(z, 1), "dia": c["dia"]})
    return out


def best_plan(vlist):
    """The horizontal cut showing the most bars (the most representative)."""
    plans = [v for v in vlist if v["kind"] == "plan_cut"]
    return plans


def orientation(mark, env):
    """Guess whether a mark runs vertically, horizontally, or is a link."""
    L = mark["bar_length_mm"]
    H, W = env["height_mm"], env["width_mm"]
    sh = mark["shape"]
    if sh.startswith("M_T"):
        return "link"
    if H and abs(L - H) <= 0.12 * H:
        return "vertical"
    if W and abs(L - W) <= 0.15 * W:
        return "horizontal"
    if H and L > 0.5 * H:
        return "vertical"
    return "other"


def assign_plan(marks, obs, env):
    """Match schedule marks to the bar positions observed in a plan cut.

    Matching is by diameter and count only -- no geometry is invented.
    Returns {mark: [positions]} plus the marks and observations left over.
    """
    by_dia_obs = collections.defaultdict(list)
    for o in obs:
        by_dia_obs[o["dia"]].append(o)
    vmarks = [m for m in marks if orientation(m, env) == "vertical"]
    by_dia_mark = collections.defaultdict(list)
    for m in vmarks:
        by_dia_mark[int(m["dia_mm"])].append(m)

    assigned, leftover_marks, leftover_obs = {}, [], []
    for dia, ms in by_dia_mark.items():
        pool = sorted(by_dia_obs.get(dia, []), key=lambda o: (o["x"], o["y"]))
        need = sum(m["qty"] for m in ms)
        if not pool:
            for m in ms:
                leftover_marks.append((m, 0, need))
            continue
        # Count match is the strong case; otherwise still use the real observed
        # positions for as many bars as the drawing actually shows, and label
        # the weaker evidence honestly.
        how = "section_exact" if len(pool) == need else "section_matched"
        i = 0
        for m in sorted(ms, key=lambda m: m["mark"]):
            take = pool[i:i + m["qty"]]
            if take:
                assigned[m["mark"]] = {"pos": take, "how": how}
            i += m["qty"]
        if len(pool) != need:
            for m in ms:
                leftover_marks.append((m, len(pool), need))
    used = {id(o) for v in assigned.values() for o in v["pos"]}
    leftover_obs = [o for o in obs if id(o) not in used]
    return assigned, leftover_marks, leftover_obs


def assign_end(marks, obs, env):
    """Match marks to bars seen end-on in the vertical cut (bars running in X)."""
    by_dia_obs = collections.defaultdict(list)
    for o in obs:
        by_dia_obs[o["dia"]].append(o)
    hmarks = [m for m in marks if orientation(m, env) == "horizontal"]
    by_dia_mark = collections.defaultdict(list)
    for m in hmarks:
        by_dia_mark[int(m["dia_mm"])].append(m)
    assigned, leftover = {}, []
    for dia, ms in by_dia_mark.items():
        pool = sorted(by_dia_obs.get(dia, []), key=lambda o: (o["y"], o["z"]))
        need = sum(m["qty"] for m in ms)
        if not pool:
            leftover += ms
            continue
        how = "section_exact" if len(pool) == need else "section_matched"
        i = 0
        for m in sorted(ms, key=lambda m: m["mark"]):
            take = pool[i:i + m["qty"]]
            if take:
                assigned[m["mark"]] = {"pos": take, "how": how}
            i += m["qty"]
        if len(pool) != need:
            leftover += ms
    return assigned, leftover


def elevation_caps(doc, vlist, dias):
    """U-bar return bends detected in the elevation -> exact (X, Z) positions."""
    elev = [v for v in vlist if v["kind"] == "elevation"]
    if not elev:
        return []
    v = elev[0]
    wb = v["wall"]
    _, arcs = rbar.collect(doc, v["box"])
    caps = rbar.endcaps(arcs, dias=dias)
    return [{"x": round(c["p"][0] - wb[0], 1), "z": round(c["p"][1] - wb[1], 1),
             "dia": c["dia"], "n": c["n"]} for c in caps]


def place_bar(mark_geom, origin, plane, flip=False):
    """Map a 2D centreline (bending-plane) polyline into panel 3D coordinates.

    plane: 'XZ' bar lies in the panel face; 'XY' bar lies in a horizontal
    plane; 'YZ' bar lies in a vertical plane across the thickness.
    """
    ox, oy, oz = origin
    out = []
    for (u, v) in mark_geom:
        if flip:
            v = -v
        if plane == "XZ":
            out.append((ox + u, oy, oz + v))
        elif plane == "XY":
            out.append((ox + u, oy + v, oz))
        elif plane == "YZ":
            out.append((ox, oy + v, oz + u))
        elif plane == "ZY":
            out.append((ox, oy + v, oz + u))
        else:
            out.append((ox + u, oy, oz + v))
    return out


def build_panel(panel, bbs_entry, dxf_paths, only_marks=None, element=None):
    """Build the complete 3D model for one panel.

    Every bar in the schedule is emitted exactly once per unit of quantity.
    How a bar SITS is decided from the drawing's own annotation and from what
    its dimensions can physically mean -- never by picking whichever plane
    happens to fit. `placement` records the evidence:
      section_exact  - position read from a section cut, count matched
      section_matched- position read from a section, count differed
      spaced         - arrayed at the spacing the drawing annotates
      distributed    - spread evenly; the drawing gave no spacing or position
    """
    import place
    marks = bbs_entry["bars"] if only_marks is None else only_marks
    doc = None
    vlist, env = [], {}
    if element is not None:
        doc, vlist, env = element["doc"], list(element["views"]), element["env"]
    for p in ([] if element is not None else dxf_paths):
        try:
            dd = ezdxf.readfile(str(p))
        except Exception:
            continue
        vv = classify(dd)
        ee = panel_envelope(vv)
        if ee.get("thickness_mm") and ee.get("height_mm"):
            if not env or ee["height_mm"] * ee["width_mm"] > env.get("height_mm", 0) * env.get("width_mm", 0):
                doc, vlist, env = dd, vv, ee
    if doc is None:
        return None

    import arrays as ARR
    import outline as OUT
    W, H = env["width_mm"], env["height_mm"]
    T = env["thickness_mm"] or 200.0
    ann = place.annotation_index(doc, vlist)

    # runs of evenly spaced bars detected in the elevation give real in-plane
    # positions for marks the sections cannot show
    dias = sorted({int(b["dia_mm"]) for b in marks})
    arr_assign = {}
    elevs = [v for v in vlist if v["kind"] == "elevation"]
    if elevs:
        ev = max(elevs, key=lambda e: e["w"] * e["h"])
        try:
            runs = ARR.runs_in_view(doc, ev, dias)
            aa = ARR.merge_arrays(ARR.find_arrays(runs))
            arr_assign = ARR.match_marks(marks, aa, ann)
        except Exception:
            arr_assign = {}

    # positional evidence from the section cuts (exact where counts agree)
    plan_assign = {}
    for pv in best_plan(vlist):
        a, _, _ = assign_plan(marks, plan_bars(doc, pv), env)
        for k, v in a.items():
            plan_assign.setdefault(k, v)
    end_assign = {}
    ends = [v for v in vlist if v["kind"] == "end_cut"]
    if ends:
        a, _ = assign_end(marks, end_bars(doc, ends[0]), env)
        end_assign.update(a)

    # the true concrete outline, so bars are not placed in fresh air
    prof = None
    if elevs:
        try:
            prof = OUT.profile(doc, max(elevs, key=lambda e: e["w"] * e["h"]))
        except Exception:
            prof = None

    def concrete_z(x0, x1):
        """Vertical extent of concrete spanning an X range, panel-local."""
        if not prof:
            return 0.0, H
        step = prof["step"]; pr = prof["profile"]
        i0 = max(0, min(len(pr) - 1, int(x0 / step)))
        i1 = max(0, min(len(pr) - 1, int(x1 / step)))
        vals = [v for v in pr[min(i0, i1):max(i0, i1) + 1] if v]
        if not vals:
            return 0.0, H
        return max(v[0] for v in vals), min(v[1] for v in vals)

    zones_deep = []
    if prof:
        try:
            zs_all = OUT.zones(prof)
            mx = max((z["depth"] for z in zs_all), default=0)
            zones_deep = [z for z in zs_all if z["depth"] > 0.92 * mx]
        except Exception:
            zones_deep = []

    bars, stats = [], collections.Counter()
    AX = {"X": 0, "Y": 1, "Z": 2}
    SPAN = {"X": W, "Y": T, "Z": H}

    for m in marks:
        d = m["dia_mm"]
        cover = 30.0 + d / 2.0
        dims = dict(m["dims_mm"])
        spec = S.SHAPES.get(m["shape"])
        if spec:
            absent = [lt for lt in spec["legs"] if not dims.get(lt)]
            if len(absent) == 1 and m.get("dims_raw", {}).get(absent[0]):
                bal = m["bar_length_mm"] - sum(v for v in dims.values() if v)
                if bal > 0:
                    dims[absent[0]] = bal
        geo = S.build_exact(m["shape"], dims, d, m["bar_length_mm"])
        if "error" in geo:
            stats["geometry_failed"] += m["qty"]
            continue
        pts2d = geo["pts_exact"]

        note = ann.get(m["mark"], {})
        run, fold, through, why = place.bar_axes(m, env, note)

        # extent of the shape along each of its two local axes
        us = [u for (u, v) in pts2d]; vs = [v for (u, v) in pts2d]
        u0, u1 = min(us), max(us); v0, v1 = min(vs), max(vs)

        # A bar can only fold through the thickness if it physically fits
        # between the covers. A link deeper than that ties the face mesh
        # instead, so its plane lies in the panel face.
        if fold == "Y" and (v1 - v0) > (T - 2 * cover) + 20.0:
            fold = "Z" if run == "X" else "X"
            through = False
            why = (f"fold {v1 - v0:.0f} exceeds clear {T - 2 * cover:.0f}"
                   f" -- lies in the panel face")

        # the fold axis: a through-thickness bar is seated on the far cover so
        # its legs reach both faces; an in-plane bar sits on the near cover
        if through:
            fold_org = cover - v0
        else:
            fold_org = cover - v0

        # Bars repeat ACROSS the panel face, never through its thickness:
        # a bar running along X is stacked up Z, and vice versa. The remaining
        # axis is the bar's depth position, which sits on the cover.
        spread = "Z" if run == "X" else "X"
        depth = [a for a in ("X", "Y", "Z") if a not in (run, spread)][0]
        spacing = note.get("spacing")
        n = m["qty"]
        span = SPAN[spread]
        # A mark tagged more than once is more than one run of bars -- e.g. an
        # edge U bar tagged "61" at each end is two stacks of 61, not 122 in a
        # line. Honour the grouping the drawing shows.
        groups = [g for g in note.get("groups", []) if g]
        if len(groups) > 1 and sum(groups) == n:
            pass
        else:
            groups = [n]
        # A bar shorter than the panel does not sit in a single line: the
        # drawing repeats it along the panel as well as across it. Work out how
        # many fit end to end, and lay the quantity out as a grid so the bars
        # cover the element the way the reinforcement actually does.
        run_span = SPAN[run]
        extent = max(u1 - u0, 1.0)
        ncol = max(1, int(run_span // (extent + 2 * cover)))

        offs, sides, runoff, how0 = [], [], [], "distributed"
        for gi, gq in enumerate(groups):
            cols = 1 if ncol <= 1 else min(ncol, gq)
            per = [gq // cols + (1 if k < gq % cols else 0) for k in range(cols)]
            for ci, cq in enumerate(per):
                if cols > 1:
                    base = cover + ci * (run_span - extent - 2 * cover) / max(cols - 1, 1)
                else:
                    base = cover
                if spacing and cq > 1 and spacing * (cq - 1) <= span:
                    start = (span - spacing * (cq - 1)) / 2.0
                    o = [start + k * spacing for k in range(cq)]
                    how0 = "spaced"
                else:
                    o = [span * (k + 0.5) / cq for k in range(cq)]
                offs += o
                runoff += [base] * cq
                sides += [1 if gi % 2 == 0 else -1] * cq
        if ncol > 1:
            how0 += "+tiled"
        if len(groups) > 1:
            how0 += "+grouped"

        pos = None; how_pos = None
        if m["mark"] in plan_assign:
            pos, how_pos = plan_assign[m["mark"]]["pos"], plan_assign[m["mark"]]["how"]
        elif m["mark"] in end_assign:
            pos, how_pos = end_assign[m["mark"]]["pos"], end_assign[m["mark"]]["how"]
        elif m["mark"] in arr_assign:
            a = arr_assign[m["mark"]]["array"]
            pos = [{"ax": a["axis"], "p": r["p"], "q": r["q"]} for r in a["bars"]]
            how_pos = "array_matched"

        for i in range(n):
            how_i = how0
            org = [0.0, 0.0, 0.0]
            org[AX[depth]] = cover
            if sides[i] > 0:
                org[AX[run]] = runoff[i] - u0
            else:
                org[AX[run]] = SPAN[run] - cover - u1 - (runoff[i] - cover)
            org[AX[spread]] = offs[i]
            if fold == depth:
                org[AX[fold]] = fold_org
            elif fold == spread:
                org[AX[fold]] = offs[i] - v0
            if pos and i < len(pos):
                p = pos[i]
                how_i = how_pos
                if "ax" in p:                        # elevation array: X and Z
                    org[AX["X"]] = p["p"][0] - (u0 if run == "X" else 0)
                    org[AX["Z"]] = p["p"][1] - (u0 if run == "Z" else 0)
                    org[AX["Y"]] = cover
                    if fold == "Y":
                        org[AX["Y"]] = cover - v0
                    elif fold == "X":
                        org[AX["X"]] -= v0
                    elif fold == "Z":
                        org[AX["Z"]] -= v0
                elif "x" in p and "y" in p:          # plan cut: gives X and Y
                    for ax, val in (("X", p["x"]), ("Y", p["y"])):
                        if ax == run:
                            org[AX[ax]] = val - u0
                        elif ax == fold:
                            org[AX[ax]] = val - v0
                        else:
                            org[AX[ax]] = val
                else:                                # end cut: gives Y and Z
                    for ax, val in (("Y", p["y"]), ("Z", p["z"])):
                        if ax == run:
                            org[AX[ax]] = val - u0
                        elif ax == fold:
                            org[AX[ax]] = val - v0
                        else:
                            org[AX[ax]] = val
            # keep the bar inside the concrete that actually exists at its
            # position: a web bar belongs in the web, not in the notch above it
            if prof and spread == "Z" and how_i.startswith(("distributed", "spaced")):
                bx0 = org[AX["X"]] + u0 if run == "X" else org[AX["X"]]
                bx1 = org[AX["X"]] + u1 if run == "X" else org[AX["X"]]
                lo, hi = concrete_z(min(bx0, bx1), max(bx0, bx1))
                if hi - lo > 4 * cover:
                    frac = (offs[i] - 0.0) / max(span, 1.0)
                    org[AX["Z"]] = lo + cover + frac * max(hi - lo - 2 * cover, 1.0)
            o3 = place.to3d(pts2d, tuple(org), run, fold)

            # Final containment against the real outline. A bar taller than the
            # concrete at its position cannot be there: shift it into the
            # concrete, and if it still will not fit, move it sideways into a
            # zone deep enough to hold it (a column rather than the web).
            if prof:
                xs = [q[0] for q in o3]; zs = [q[2] for q in o3]
                need = max(zs) - min(zs)
                lo, hi = concrete_z(min(xs), max(xs))
                if need > (hi - lo) + 2 * cover and zones_deep:
                    tgt = min(zones_deep, key=lambda z: abs((z["x0"] + z["x1"]) / 2
                                                            - (min(xs) + max(xs)) / 2))
                    want = tgt["x0"] + cover
                    if max(xs) - min(xs) < tgt["x1"] - tgt["x0"]:
                        dx = want - min(xs)
                        o3 = [(q[0] + dx, q[1], q[2]) for q in o3]
                        xs = [q[0] for q in o3]
                        lo, hi = concrete_z(min(xs), max(xs))
                        how_i += "+rezoned"
                zs = [q[2] for q in o3]
                dz = 0.0
                if min(zs) < lo:
                    dz = lo - min(zs)
                elif max(zs) > hi:
                    dz = hi - max(zs)
                if dz and abs(dz) < H:
                    o3 = [(q[0], q[1], q[2] + dz) for q in o3]

            # a bar longer than the panel is a starter/dowel and may protrude
            if m["bar_length_mm"] <= max(W, H, T) + 20:
                o3 = clamp_into(o3, W, H, T, cover)
            else:
                how_i += "+projecting"
            stats[how_i] += 1
            bars.append({
                "panel": panel, "mark": m["mark"], "schedule": m["schedule"],
                "dia_mm": d, "shape": m["shape"], "dims_mm": dims,
                "cut_length_mm": m["bar_length_mm"],
                "weight_kg": round((m["weight_kg"] or 0) / max(m["qty"], 1), 5),
                "geometric_mm": geo.get("geometric_mm"),
                "residual_mm": geo.get("residual_mm"),
                "shape_scale": geo.get("scale_applied"),
                "run_axis": run, "fold_axis": fold,
                "through_thickness": through, "axis_reason": why,
                "spacing_mm": spacing,
                "placement": how_i,
                "pts": [[round(a, 1), round(b, 1), round(c, 1)] for a, b, c in o3],
            })
    return {"panel": panel, "envelope": env, "n_bars": len(bars),
            "placement_stats": dict(stats), "bars": bars}


def S_mass(dia):
    return math.pi / 4.0 * dia ** 2 * 7850e-9


def elevation_bars(doc, vlist, dias):
    """Bar centrelines read from the elevation -> panel-local (X, Z) runs.

    Returns separate horizontal and vertical families; each entry carries the
    run length so it can be matched against a schedule mark's cut length.
    """
    elev = [v for v in vlist if v["kind"] == "elevation"]
    if not elev:
        return {"h": [], "v": []}
    v = max(elev, key=lambda e: e["w"] * e["h"])
    wb = v["wall"]
    lines, _ = rbar.collect(doc, v["box"])
    mids, _ = rbar.pair_lines(lines, dias=dias)
    runs = [b for b in rbar.merge_collinear(mids, gap=30.0) if b["len"] > 60]
    H, V = [], []
    for b in runs:
        a = b["ang"] % 180
        x0, z0 = b["p"][0] - wb[0], b["p"][1] - wb[1]
        x1, z1 = b["q"][0] - wb[0], b["q"][1] - wb[1]
        rec = {"x0": round(x0, 1), "z0": round(z0, 1), "x1": round(x1, 1),
               "z1": round(z1, 1), "len": round(b["len"], 1), "dia": b["dia"]}
        if a < 8 or a > 172:
            H.append(rec)
        elif 82 < a < 98:
            V.append(rec)
    return {"h": H, "v": V}


def assign_elevation(marks, ev, env, already):
    """Match remaining marks to elevation runs by diameter and run length."""
    out = {}
    for fam, key in (("h", "horizontal"), ("v", "vertical")):
        pool = collections.defaultdict(list)
        for r in ev[fam]:
            pool[r["dia"]].append(r)
        cands = [m for m in marks if m["mark"] not in already
                 and m["mark"] not in out]
        for m in sorted(cands, key=lambda m: -m["bar_length_mm"]):
            d = int(m["dia_mm"])
            avail = pool.get(d)
            if not avail:
                continue
            # a bar's drawn run should be close to its cut length, or to the
            # longest leg of a bent bar
            L = m["bar_length_mm"]
            legs = [v for v in m["dims_mm"].values() if v]
            targets = [L] + legs
            hit = [r for r in avail
                   if any(abs(r["len"] - t) <= max(30.0, 0.06 * t) for t in targets)]
            if len(hit) < 1:
                continue
            hit.sort(key=lambda r: (r["z0"], r["x0"]))
            take = hit[:m["qty"]]
            for r in take:
                avail.remove(r)
            out[m["mark"]] = {"pos": take, "how": "elevation_matched", "fam": fam}
    return out


def _bbox(pts):
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]; zs = [p[2] for p in pts]
    return min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)


def _overflow(pts, W, H, T, tol=25.0):
    x0, y0, z0, x1, y1, z1 = _bbox(pts)
    return max(0.0, -x0 - tol) + max(0.0, x1 - W - tol) \
         + max(0.0, -y0 - tol) + max(0.0, y1 - T - tol) \
         + max(0.0, -z0 - tol) + max(0.0, z1 - H - tol)


def fit_envelope(pts2d, anchor, W, H, T, cover):
    """Choose the bending plane and sense that keeps a bar inside the panel.

    A bar's plane is not stated in the schedule; the drawing view it came
    from implies it. Where that is ambiguous we pick the orientation with
    the least overflow rather than letting bars float outside the concrete.
    """
    ax, ay, az = anchor
    best, bestcost = None, None
    for plane in ("XZ", "XY", "YZ"):
        for su in (1, -1):
            for sv in (1, -1):
                if plane == "XZ":
                    o = [(ax + su * u, ay, az + sv * v) for (u, v) in pts2d]
                elif plane == "XY":
                    o = [(ax + su * u, ay + sv * v, az) for (u, v) in pts2d]
                else:
                    o = [(ax, ay + sv * v, az + su * u) for (u, v) in pts2d]
                c = _overflow(o, W, H, T)
                if bestcost is None or c < bestcost:
                    best, bestcost = o, c
                if bestcost == 0.0:
                    return best, 0.0
    return best, bestcost


def clamp_into(pts, W, H, T, cover):
    """Translate a bar so it sits inside the panel, preserving its shape."""
    x0, y0, z0, x1, y1, z1 = _bbox(pts)
    dx = dy = dz = 0.0
    if x0 < 0: dx = -x0
    elif x1 > W: dx = W - x1
    if y0 < 0: dy = -y0
    elif y1 > T: dy = T - y1
    if z0 < 0: dz = -z0
    elif z1 > H: dz = H - z1
    if dx or dy or dz:
        return [(p[0] + dx, p[1] + dy, p[2] + dz) for p in pts]
    return pts
