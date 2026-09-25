"""Stage 5 — verification: does the model actually look like the drawing?

Nothing here trusts the pipeline. The drawing is read again, straight from the
DXF, and the model is projected into each drawn view so the two can be laid on
top of each other and measured:

  * overlay PNGs   out/v2/report/overlay_<element>.png
  * numbers        out/v2/report/accuracy.json / accuracy.txt
  * 3D viewer      out/v2/viewer.html

The model is loaded by `load_model()` alone: it prefers stage 4's
`out/v2/bound/<element>.json` and falls back to the v1 `out/model3d.json`, so
the same harness measures both and the comparison is like for like.

Run:  venv/bin/python src/v2/check.py [--elements A,B] [--no-viewer]
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import ezdxf

ROOT = Path(__file__).resolve().parents[2]
DXF_DIR = ROOT / "dxf"
REPORT = ROOT / "out" / "v2" / "report"

RBAR = "S-RBAR"
WALL_LAYERS = ("A-WALL", "A-WALL-HDLN")
# Columns (PC-*) outline on S-COLS, beams on S-BEAM, slabs/stairs on S-SLAB or
# A-FLOR -- restricting to wall layers alone silently dropped every such
# sheet's views here (see the matching fix in assemble.wall_box / outline.py).
OUTLINE_LAYER_GROUPS = (("A-WALL", "A-WALL-HDLN"), ("S-COLS",), ("S-BEAM",),
                        ("S-SLAB",), ("A-FLOR",))
DIAS = [8, 10, 12, 16, 20, 25, 32]
THICK_MAX = 460.0          # anything thinner than this in one axis is a cut
NEAR_MM = 25.0             # "spatially agreeing" threshold


# ----------------------------------------------------------------- model load

def _plen(pts):
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def load_model(prefer_v2: bool = True):
    """The one place the model comes from.

    Returns {element_name: {"sheet", "envelope", "bars": [...], "source"}} with
    every bar as {"mark", "dia", "pts" (3D, mm), "cut_length_mm"}.
    """
    bound = ROOT / "out" / "v2" / "bound"
    out = {}
    v1 = json.loads((ROOT / "out" / "model3d.json").read_text())
    if prefer_v2 and bound.is_dir() and any(bound.glob("*.json")):
        skipped = []
        for f in sorted(bound.glob("*.json")):
            if f.stem.startswith("_"):
                continue                       # e.g. _reconciliation.json: not an element
            d = json.loads(f.read_text())
            name = d.get("element", f.stem)
            bars, flat = [], 0
            for b in d.get("bars3d") or d.get("bars") or []:
                pts = [list(map(float, p)) for p in b["pts"]]
                if any(len(p) != 3 for p in pts):
                    flat += 1
                    continue
                bars.append({"mark": b.get("mark"),
                             "dia": float(b.get("dia") or b.get("dia_mm") or 0),
                             "pts": pts,
                             "cut_length_mm": b.get("cut_length_mm"),
                             "extra": {k: v for k, v in b.items()
                                       if k not in ("mark", "dia", "dia_mm", "pts")}})
            if flat:
                skipped.append(f"{name}: {flat} bars are not 3D yet")
            ref = v1.get(name) or next((v for k, v in v1.items()
                                        if k.split(" [")[0] == name), {})
            env = (d.get("envelope") or ref.get("envelope")
                   or _env_from_drawing(name) or _env_from(bars))
            sheets = d.get("sheets") or (d.get("summary") or {}).get("sheets")
            out[name] = {
                "sheet": d.get("sheet") or (sheets[0] if sheets else None)
                          or ref.get("sheet") or _sheet_guess(name),
                "envelope": env, "outline": d.get("outline"), "bars": bars,
                "source": str(f.parent.relative_to(ROOT)) + "/*.json"}
        for s in skipped:
            print(f"  ! {s}", file=sys.stderr)
        if any(el["bars"] for el in out.values()):
            return out
        print("  ! stage 4 output carries no 3D bars yet — falling back to v1",
              file=sys.stderr)
    m = v1
    for name, e in m.items():
        bars = [{"mark": b.get("mark"), "dia": float(b["dia_mm"]),
                 "pts": [list(map(float, p)) for p in b["pts"]],
                 "cut_length_mm": b.get("cut_length_mm"),
                 "extra": {k: v for k, v in b.items()
                           if k not in ("mark", "dia_mm", "pts")}}
                for b in e["bars"]]
        out[name] = {"sheet": e["sheet"], "envelope": e["envelope"],
                     "outline": None, "bars": bars,
                     "source": "out/model3d.json"}
    return out


def _sheet_guess(name):
    return re.sub(r"\s*\[.*\]$", "", name or "") + "_R"


def _env_from_drawing(name):
    """The true concrete envelope, read the same way stage 3/4 read it.

    Bound files carry no envelope of their own, and inferring one from the
    sparse recovered bar cloud (``_env_from``) undershoots -- not every bar
    reaches every edge of the concrete, so the guessed box never lines up
    with any real drawn view. This asks the same question elements.py already
    answered when it built the model, instead of re-guessing from bars.
    """
    plain = re.sub(r'\s*\[.*\]$', '', name)
    mkey = re.search(r'\[(\d+)x(\d+)x(\d+)\]$', name)
    try:
        sys.path.insert(0, str(ROOT / "src"))
        import elements as ELm
        paths = sorted(str(p) for p in DXF_DIR.glob(f"{plain}_R*.dxf"))
        if not paths:
            return None
        cands = ELm.candidates(plain, paths)
        if not cands:
            return None
        if mkey:
            want = tuple(int(x) for x in mkey.groups())
            hit = [c for c in cands if c["key"] == want]
            c = hit[0] if hit else cands[0]
        else:
            c = cands[0]
        w, h, t = c["key"]
        return {"width_mm": float(w), "height_mm": float(h), "thickness_mm": float(t)}
    except Exception:
        return None


def _env_from(bars):
    """Fallback envelope: the bounding box of the bars themselves, when stage 4
    supplied no envelope and there is no matching v1 element to borrow one from."""
    xs = [p[0] for b in bars for p in b["pts"]]
    ys = [p[1] for b in bars for p in b["pts"]]
    zs = [p[2] for b in bars for p in b["pts"]]
    if not xs:
        return {"width_mm": 0.0, "height_mm": 0.0, "thickness_mm": None}
    return {"width_mm": round(max(xs) - min(xs), 1),
            "height_mm": round(max(zs) - min(zs), 1),
            "thickness_mm": round(max(ys) - min(ys), 1)}


# ------------------------------------------------------- drawing (ground truth)

def _in(p, box, pad=0.0):
    return box[0] - pad <= p[0] <= box[2] + pad and box[1] - pad <= p[1] <= box[3] + pad


def viewports(doc):
    """Model-space window of every real viewport in Layout1, with its title."""
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
            continue
        vh = dx.view_height
        vw = vh * (dx.width / dx.height)
        cx, cy = dx.view_center_point.x, dx.view_center_point.y
        best, bd = None, 1e9
        for tx, ty, t in titles:
            if "REINF" not in t.upper():
                continue
            d = (abs(tx - (dx.center.x - dx.width / 2) - 6)
                 + abs(ty - (dx.center.y - dx.height / 2)))
            if d < bd:
                best, bd = t, d
        out.append({"title": best, "scale": round(vh / dx.height, 1),
                    "box": (cx - vw / 2, cy - vh / 2, cx + vw / 2, cy + vh / 2)})
    return out


def read_sheet(stem):
    """Every drawn primitive we care about on one (R) sheet, per view."""
    path = DXF_DIR / f"{stem}.dxf"
    doc = ezdxf.readfile(str(path))
    msp = doc.modelspace()
    rlines, rarcs, rcircles = [], [], []
    wlines_by_group = [[] for _ in OUTLINE_LAYER_GROUPS]
    group_of = {}
    for gi, grp in enumerate(OUTLINE_LAYER_GROUPS):
        for lay in grp:
            group_of[lay] = gi
    for e in msp:
        lay = e.dxf.layer
        t = e.dxftype()
        if lay == RBAR:
            if t == "LINE":
                s, q = e.dxf.start, e.dxf.end
                rlines.append(((s.x, s.y), (q.x, q.y)))
            elif t == "ARC":
                c = e.dxf.center
                rarcs.append({"c": (c.x, c.y), "r": e.dxf.radius,
                              "a0": e.dxf.start_angle, "a1": e.dxf.end_angle})
            elif t == "CIRCLE":
                c = e.dxf.center
                rcircles.append({"p": (c.x, c.y), "dia": round(e.dxf.radius * 2)})
            elif t in ("LWPOLYLINE", "POLYLINE"):
                pts = [(p[0], p[1]) for p in e.get_points("xy")] if t == "LWPOLYLINE" \
                    else [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
                for i in range(len(pts) - 1):
                    rlines.append((pts[i], pts[i + 1]))
        elif lay in group_of and t == "LINE":
            s, q = e.dxf.start, e.dxf.end
            wlines_by_group[group_of[lay]].append(((s.x, s.y), (q.x, q.y)))

    views = []
    for v in viewports(doc):
        box = v["box"]
        wl = []
        for grp_lines in wlines_by_group:
            wl = [(p, q) for p, q in grp_lines if _in(p, box) or _in(q, box)]
            if wl:
                break
        if not wl:
            continue
        xs = [c for p, q in wl for c in (p[0], q[0])]
        ys = [c for p, q in wl for c in (p[1], q[1])]
        wb = (min(xs), min(ys), max(xs), max(ys))
        w, h = wb[2] - wb[0], wb[3] - wb[1]
        if w > THICK_MAX and h > THICK_MAX:
            kind = "elevation"
        elif h <= THICK_MAX < w:
            kind = "plan_cut"
        elif w <= THICK_MAX < h:
            kind = "end_cut"
        else:
            kind = "detail"
        lines = [(p, q) for p, q in rlines if _in(p, box) and _in(q, box)]
        arcs = [a for a in rarcs if _in(a["c"], box)]
        circ = [c for c in rcircles if _in(c["p"], box)]
        mids, _ = pair_lines(lines)
        # bars are broken at every crossing, so collinear pieces are rejoined
        # across gaps up to one bar spacing; slivers below 50 mm are pairing noise
        runs = [r for r in merge_collinear(mids, gap=40.0) if r["len"] >= 50.0]
        views.append({"kind": kind, "title": v["title"], "scale": v["scale"],
                      "box": box, "wall": wb, "w": w, "h": h,
                      "wall_lines": wl, "raw_lines": lines, "raw_arcs": arcs,
                      "runs": runs, "sections": circ})
    return {"sheet": stem, "views": views}


# --- medial-axis recovery: bars are drawn as two edges offset by the diameter

def _norm_line(p, q):
    a = math.atan2(q[1] - p[1], q[0] - p[0]) % math.pi
    ux, uy = math.cos(a), math.sin(a)
    nx, ny = -uy, ux
    off = p[0] * nx + p[1] * ny
    s0, s1 = p[0] * ux + p[1] * uy, q[0] * ux + q[1] * uy
    return a, off, min(s0, s1), max(s0, s1)


def pair_lines(lines, dias=DIAS, atol=0.6, dtol=0.35, min_overlap=1.0):
    """Pair parallel edges separated by a bar diameter -> centreline pieces."""
    recs = []
    for p, q in lines:
        if math.dist(p, q) < 1e-6:
            continue
        a, off, s0, s1 = _norm_line(p, q)
        recs.append({"a": a, "off": off, "s0": s0, "s1": s1, "used": False})
    buckets = collections.defaultdict(list)
    step = math.radians(atol)
    for i, r in enumerate(recs):
        k = int(r["a"] / step)
        for kk in (k - 1, k, k + 1):
            buckets[kk].append(i)
    mids, seen = [], set()
    for idxs in buckets.values():
        idxs = sorted(set(idxs), key=lambda i: recs[i]["off"])
        for ii, i in enumerate(idxs):
            ri = recs[i]
            if ri["used"]:
                continue
            for j in idxs[ii + 1:]:
                rj = recs[j]
                if rj["used"]:
                    continue
                d = rj["off"] - ri["off"]
                if d > max(dias) + 1:
                    break
                da = abs(ri["a"] - rj["a"])
                if min(da, math.pi - da) > math.radians(atol):
                    continue
                hit = [D for D in dias if abs(d - D) < dtol]
                if not hit:
                    continue
                lo, hi = max(ri["s0"], rj["s0"]), min(ri["s1"], rj["s1"])
                if hi - lo < min_overlap:
                    continue
                key = (min(i, j), max(i, j))
                if key in seen:
                    continue
                seen.add(key)
                ri["used"] = rj["used"] = True
                a = ri["a"]
                ux, uy = math.cos(a), math.sin(a)
                nx, ny = -uy, ux
                moff = (ri["off"] + rj["off"]) / 2
                mids.append({"p": (ux * lo + nx * moff, uy * lo + ny * moff),
                             "q": (ux * hi + nx * moff, uy * hi + ny * moff),
                             "dia": hit[0]})
                break
    return mids, [r for r in recs if not r["used"]]


def merge_collinear(mids, atol=0.6, otol=0.4, gap=1.5):
    groups = collections.defaultdict(list)
    for m in mids:
        a, off, s0, s1 = _norm_line(m["p"], m["q"])
        groups[(m["dia"], round(a / math.radians(atol)), round(off / otol))].append(
            {"a": a, "off": off, "s0": s0, "s1": s1, "dia": m["dia"]})
    bars = []
    for items in groups.values():
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
        out.append({"p": P, "q": Q, "dia": b["dia"], "len": b["s1"] - b["s0"]})
    return out


# ------------------------------------------------------------ view <-> model

def project(pts3, kind):
    """Model (X across, Y through thickness, Z up) -> the plane of a drawn view."""
    if kind == "elevation":
        return [(p[0], p[2]) for p in pts3]
    if kind == "plan_cut":
        return [(p[0], p[1]) for p in pts3]
    if kind == "end_cut":
        return [(p[1], p[2]) for p in pts3]
    return None


def view_matches(view, env, tol=30.0):
    """Is this view a view *of this element* (and not of its neighbour)?"""
    W = env.get("width_mm") or 0
    H = env.get("height_mm") or 0
    T = env.get("thickness_mm") or 0
    k = view["kind"]
    if k == "elevation":
        return abs(view["w"] - W) <= tol and abs(view["h"] - H) <= tol
    if k == "plan_cut":
        return abs(view["w"] - W) <= tol and (not T or abs(view["h"] - T) <= tol)
    if k == "end_cut":
        return abs(view["h"] - H) <= tol and (not T or abs(view["w"] - T) <= tol)
    return False


def to_local(view, seg):
    """Drawn world coords -> element-local mm, origin at the wall box corner."""
    x0, y0 = view["wall"][0], view["wall"][1]
    return [(p[0] - x0, p[1] - y0) for p in seg]


# ------------------------------------------------------------------- geometry

def _seg_arrays(segs):
    if not segs:
        return np.zeros((0, 2)), np.zeros((0, 2))
    A = np.array([s[0] for s in segs], float)
    B = np.array([s[1] for s in segs], float)
    return A, B


def point_seg_dist(P, A, B, chunk=256):
    """min distance from each point (M,2) to a set of segments -> (M,)"""
    if len(A) == 0 or len(P) == 0:
        return np.full(len(P), np.inf)
    D = B - A
    LL = np.einsum("ij,ij->i", D, D)
    LL[LL == 0] = 1e-9
    out = np.empty(len(P))
    for i in range(0, len(P), chunk):
        p = P[i:i + chunk][:, None, :]              # m,1,2
        t = np.einsum("mnj,nj->mn", p - A[None], D) / LL[None]
        t = np.clip(t, 0.0, 1.0)
        proj = A[None] + t[..., None] * D[None]
        out[i:i + chunk] = np.hypot(*(p - proj).transpose(2, 0, 1)).min(axis=1)
    return out


def sample(pts, step=40.0):
    """Points along a polyline, roughly every `step` mm, ends included."""
    out = [pts[0]]
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        L = math.dist(a, b)
        n = max(1, int(L / step))
        for k in range(1, n + 1):
            t = k / n
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def polyline_segments(pts):
    return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)
            if math.dist(pts[i], pts[i + 1]) > 1e-9]


def hist_profile(segs, lo, hi, axis, bins=20):
    """Length-weighted bar density along one axis of a view."""
    h = np.zeros(bins)
    if hi - lo < 1e-6:
        return h
    for a, b in segs:
        L = math.dist(a, b)
        if L < 1e-9:                      # a bar seen end-on: one unit of steel
            i = int((a[axis] - lo) / (hi - lo) * bins)
            if 0 <= i < bins:
                h[i] += 1.0
            continue
        n = max(1, int(L / 10.0))
        for k in range(n):
            t = (k + 0.5) / n
            v = a[axis] + (b[axis] - a[axis]) * t
            i = int((v - lo) / (hi - lo) * bins)
            if 0 <= i < bins:
                h[i] += L / n
    return h


def tv_mismatch(a, b):
    """Total-variation distance between two profiles, as a percentage."""
    sa, sb = a.sum(), b.sum()
    if sa <= 0 or sb <= 0:
        return None
    return float(100.0 * 0.5 * np.abs(a / sa - b / sb).sum())


# ------------------------------------------------------------------ measuring

def measure_view(view, bars, near=NEAR_MM):
    """Compare one drawn view with the model bars projected into it."""
    kind = view["kind"]
    W, H = view["w"], view["h"]

    drawn_runs = [{"dia": r["dia"],
                   "seg": to_local(view, (r["p"], r["q"])),
                   "len": r["len"]} for r in view["runs"]]
    drawn_secs = [{"dia": s["dia"], "p": to_local(view, (s["p"], s["p"]))[0]}
                  for s in view["sections"]]

    # The drawing shows one line where several model bars project onto each
    # other (the two reinforcement layers, for instance), so coincident
    # projections are collapsed before counting — otherwise the model is
    # penalised for being 3D.
    mod_runs, mod_secs = [], []
    seen_run, seen_sec = {}, {}
    for b in bars:
        pts = project(b["pts"], kind)
        if pts is None:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        extent = max(max(xs) - min(xs), max(ys) - min(ys))
        dia = int(round(b["dia"]))
        if extent < 15.0:                      # seen end-on: a section
            key = (dia, round(pts[0][0] / 5), round(pts[0][1] / 5))
            if key in seen_sec:
                seen_sec[key]["n"] += 1
                continue
            rec = {"dia": dia, "p": pts[0], "mark": b.get("mark"), "n": 1}
            seen_sec[key] = rec
            mod_secs.append(rec)
        else:
            key = (dia,) + tuple((round(p[0] / 5), round(p[1] / 5)) for p in pts)
            if key in seen_run:
                seen_run[key]["n"] += 1
                continue
            rec = {"dia": dia, "pts": pts, "mark": b.get("mark"),
                   "len": _plen(pts), "n": 1}
            seen_run[key] = rec
            mod_runs.append(rec)
    n_collapsed = (sum(r["n"] for r in mod_runs) + sum(s["n"] for s in mod_secs)
                   - len(mod_runs) - len(mod_secs))

    # --- counts and lengths per diameter
    per_dia = {}
    dias = sorted({r["dia"] for r in drawn_runs} | {s["dia"] for s in drawn_secs}
                  | {r["dia"] for r in mod_runs} | {s["dia"] for s in mod_secs})
    for d in dias:
        dr = [r for r in drawn_runs if r["dia"] == d]
        ds = [s for s in drawn_secs if s["dia"] == d]
        mr = [r for r in mod_runs if r["dia"] == d]
        ms = [s for s in mod_secs if s["dia"] == d]
        per_dia[f"T{d}"] = {
            "drawn_runs": len(dr), "model_runs": len(mr),
            "drawn_sections": len(ds), "model_sections": len(ms),
            "drawn_len_mm": round(sum(r["len"] for r in dr), 1),
            "model_len_mm": round(sum(r["len"] for r in mr), 1)}

    # --- spatial agreement: model bar -> nearest drawn geometry of same diameter
    #
    # An elevation shows every bar, so everything is compared there. A section
    # cut only shows the steel it happens to slice, and the model does not say
    # which bars that is, so in cut views only the unambiguous evidence is
    # scored: bars seen end-on, whose (x,y) or (y,z) the cut states exactly.
    sections_only = kind != "elevation"
    scored = mod_secs if sections_only else (mod_runs + mod_secs)
    drawn_by_dia = collections.defaultdict(list)
    if not sections_only:
        for r in drawn_runs:
            drawn_by_dia[r["dia"]].append((r["seg"][0], r["seg"][1]))
    for s in drawn_secs:
        drawn_by_dia[s["dia"]].append((s["p"], s["p"]))
    dists, nodia = [], 0
    for b in scored:
        segs = drawn_by_dia.get(b["dia"])
        if not segs:
            nodia += 1
            continue
        A, B = _seg_arrays(segs)
        pts = b["pts"] if "pts" in b else [b["p"]]
        P = np.array(sample(pts) if len(pts) > 1 else pts, float)
        dists.append(float(np.median(point_seg_dist(P, A, B))))
    dists = np.array(dists) if dists else np.zeros(0)

    # --- density profiles across the view's two axes
    if sections_only:
        dsegs = [(s["p"], s["p"]) for s in drawn_secs]
        msegs = [(s["p"], s["p"]) for s in mod_secs]
    else:
        dsegs = [tuple(r["seg"]) for r in drawn_runs] + \
                [(s["p"], s["p"]) for s in drawn_secs]
        msegs = [s for r in mod_runs for s in polyline_segments(r["pts"])] + \
                [(s["p"], s["p"]) for s in mod_secs]
    prof = {}
    axis_names = {"elevation": ("X", "Z"), "plan_cut": ("X", "Y"),
                  "end_cut": ("Y", "Z")}.get(kind, ("U", "V"))
    for ax, (name, hi) in enumerate(zip(axis_names, (W, H))):
        d = hist_profile(dsegs, 0.0, hi, ax)
        m = hist_profile(msegs, 0.0, hi, ax)
        prof[name] = {"mismatch_pct": tv_mismatch(d, m),
                      "drawn": [round(v, 1) for v in d],
                      "model": [round(v, 1) for v in m]}

    n = len(dists)
    return {
        "kind": kind, "title": view["title"], "scale": view["scale"],
        "size_mm": [round(W, 1), round(H, 1)],
        "counts": {"drawn_runs": len(drawn_runs), "model_runs": len(mod_runs),
                   "drawn_sections": len(drawn_secs),
                   "model_sections": len(mod_secs),
                   "model_coincident_collapsed": n_collapsed},
        "per_dia": per_dia,
        "scored": "sections only" if sections_only else "all bars",
        "spatial": {
            "n_model_bars": len(scored),
            "no_drawn_bar_of_that_dia": nodia,
            "median_mm": round(float(np.median(dists)), 1) if n else None,
            "p90_mm": round(float(np.percentile(dists, 90)), 1) if n else None,
            "frac_within_25mm": round(float((dists <= near).mean()), 3) if n else None},
        "density": prof,
        "_render": {"drawn_runs": drawn_runs, "drawn_secs": drawn_secs,
                    "mod_runs": mod_runs, "mod_secs": mod_secs},
    }


def measure_element(name, el, sheet_cache):
    stem = el["sheet"]
    if stem not in sheet_cache:
        sheet_cache[stem] = read_sheet(stem)
    sheet = sheet_cache[stem]
    views = [v for v in sheet["views"] if view_matches(v, el["envelope"])]
    res = {"element": name, "sheet": stem, "envelope": el["envelope"],
           "n_model_bars": len(el["bars"]), "views": []}
    for v in views:
        res["views"].append(measure_view(v, el["bars"]))
    prim = next((m for m in res["views"] if m["kind"] == "elevation"), None)
    if prim is None and res["views"]:
        prim = max(res["views"], key=lambda m: m["size_mm"][0] * m["size_mm"][1])
    res["primary"] = prim["kind"] if prim else None
    if prim:
        res["summary"] = {
            "view": prim["kind"],
            "drawn_bars": prim["counts"]["drawn_runs"] + prim["counts"]["drawn_sections"],
            "model_bars": prim["counts"]["model_runs"] + prim["counts"]["model_sections"],
            "median_mm": prim["spatial"]["median_mm"],
            "p90_mm": prim["spatial"]["p90_mm"],
            "frac_within_25mm": prim["spatial"]["frac_within_25mm"],
            "density_mismatch_pct": _mean([p["mismatch_pct"]
                                           for p in prim["density"].values()])}
    else:
        res["summary"] = None
    return res


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


# -------------------------------------------------------------------- drawing

DIACOL = {8: "#5fa8ff", 10: "#4bbf7a", 12: "#ff6b7f", 16: "#b18cf0",
          20: "#ffa040", 25: "#c08a6a", 32: "#aaaabb"}
DRAWN_C = "#39d0ff"
MODEL_C = "#ff8a3d"


def render_overlay(name, meas, sheet, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle

    views = meas["views"]
    if not views:
        return None
    # tall views (elevation, end cut) beside each other on top, wide plan cuts
    # stacked below, so nothing is squashed into a sliver
    tall = [v for v in views if v["size_mm"][1] >= v["size_mm"][0]]
    wide = [v for v in views if v["size_mm"][1] < v["size_mm"][0]]
    rows = [r for r in (tall, wide) if r]
    hr = [3.0 if r is tall else max(1.0, 0.9 * len(r)) for r in rows]
    fig_w = max(9.0, 2.6 * max(len(r) for r in rows) + 4)
    fig = plt.figure(figsize=(fig_w, 12), facecolor="#0d1015")
    gs = fig.add_gridspec(len(rows), 1, height_ratios=hr, hspace=0.28)
    axmap = []
    for gi, row in enumerate(rows):
        if row is tall:
            wr = [max(v["size_mm"][0] / max(v["size_mm"][1], 1), 0.08) for v in row]
            sub = gs[gi].subgridspec(1, len(row), width_ratios=wr, wspace=0.35)
            for i, v in enumerate(row):
                axmap.append((fig.add_subplot(sub[0, i]), v))
        else:
            sub = gs[gi].subgridspec(len(row), 1, hspace=0.9)
            for i, v in enumerate(row):
                axmap.append((fig.add_subplot(sub[i, 0]), v))
    for ax, v in axmap:
        r = v["_render"]
        ax.set_facecolor("#0d1015")
        W, H = v["size_mm"]
        # concrete outline
        wl = next((sv for sv in sheet["views"]
                   if sv["kind"] == v["kind"] and
                   abs(sv["w"] - W) < 0.5 and abs(sv["h"] - H) < 0.5), None)
        if wl:
            for p, q in wl["wall_lines"]:
                lp, lq = to_local(wl, (p, q))
                ax.plot([lp[0], lq[0]], [lp[1], lq[1]], color="#4a5563",
                        lw=0.7, zorder=1)
        # drawn bars
        for b in r["drawn_runs"]:
            (p, q) = b["seg"]
            ax.plot([p[0], q[0]], [p[1], q[1]], color=DRAWN_C, lw=1.0, zorder=2)
        for s in r["drawn_secs"]:
            ax.add_patch(Circle(s["p"], max(s["dia"] / 2, 6), fill=False,
                                ec=DRAWN_C, lw=0.8, zorder=2))
        # model bars
        for b in r["mod_runs"]:
            xs = [p[0] for p in b["pts"]]
            ys = [p[1] for p in b["pts"]]
            ax.plot(xs, ys, color=MODEL_C, lw=0.9, alpha=0.85, zorder=3)
        for s in r["mod_secs"]:
            ax.add_patch(Circle(s["p"], max(s["dia"] / 2, 6), fill=False,
                                ec=MODEL_C, lw=0.8, alpha=0.85, zorder=3))
        sp = v["spatial"]
        c = v["counts"]
        ax.set_title(
            f'{v["kind"]}  {W:.0f}×{H:.0f} mm\n'
            f'drawn {c["drawn_runs"]} runs + {c["drawn_sections"]} sections   '
            f'model {c["model_runs"]} + {c["model_sections"]}\n'
            f'offset median {sp["median_mm"]} mm  p90 {sp["p90_mm"]} mm  '
            f'≤25mm {"–" if sp["frac_within_25mm"] is None else str(int(100*sp["frac_within_25mm"]))+"%"}'
            f'  ({v["scored"]})',
            color="#c8d2de", fontsize=7.5, linespacing=1.5)
        ax.set_aspect("equal")
        ax.margins(0.04)
        for s in ax.spines.values():
            s.set_color("#232a33")
        ax.tick_params(colors="#5d6875", labelsize=6)
    s = meas["summary"] or {}
    fig.suptitle(
        f'{name}   —   drawing (cyan) vs model (orange)\n'
        f'{meas["n_model_bars"]} model bars · sheet {meas["sheet"]} · '
        f'median offset {s.get("median_mm")} mm, p90 {s.get("p90_mm")} mm, '
        f'{"" if s.get("frac_within_25mm") is None else int(100*s["frac_within_25mm"])}% within 25 mm, '
        f'density mismatch {s.get("density_mismatch_pct")}%',
        color="#e7ecf2", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(path, dpi=140, facecolor="#0d1015")
    plt.close(fig)
    return path


# --------------------------------------------------------------------- report

def text_report(results, model_src):
    L = []
    L.append("rb3 v2 — accuracy of the reconstruction against the drawing")
    L.append(f"model source: {model_src}")
    L.append("")
    L.append("Per element, primary view (elevation where one exists):")
    L.append(f'{"element":30}{"view":11}{"drawn":>7}{"model":>7}'
             f'{"med mm":>8}{"p90 mm":>8}{"<=25mm":>8}{"dens%":>7}')
    agg = collections.defaultdict(list)
    for r in results:
        s = r["summary"]
        if not s:
            L.append(f'{r["element"]:30}no matching view on {r["sheet"]}')
            continue
        L.append(f'{r["element"]:30}{s["view"]:11}{s["drawn_bars"]:7d}'
                 f'{s["model_bars"]:7d}{_f(s["median_mm"]):>8}{_f(s["p90_mm"]):>8}'
                 f'{_pct(s["frac_within_25mm"]):>8}{_f(s["density_mismatch_pct"]):>7}')
        for k in ("median_mm", "p90_mm", "frac_within_25mm", "density_mismatch_pct"):
            if s[k] is not None:
                agg[k].append(s[k])
        agg["drawn"].append(s["drawn_bars"])
        agg["model"].append(s["model_bars"])
    L.append("")
    L.append(f'OVERALL  drawn {sum(agg["drawn"])} bars vs model {sum(agg["model"])} '
             f'in the primary views')
    L.append(f'  median offset      {_mean(agg["median_mm"])} mm (mean over elements)')
    L.append(f'  p90 offset         {_mean(agg["p90_mm"])} mm')
    L.append(f'  within 25 mm       {_pct(_mean(agg["frac_within_25mm"]) )}')
    L.append(f'  density mismatch   {_mean(agg["density_mismatch_pct"])} %')
    L.append("")
    L.append("Per view detail (counts by diameter, drawn vs model):")
    for r in results:
        L.append("")
        L.append(f'{r["element"]}   sheet {r["sheet"]}   '
                 f'{r["n_model_bars"]} model bars')
        for v in r["views"]:
            sp = v["spatial"]
            L.append(f'  {v["kind"]:10} {v["size_mm"][0]:.0f}x{v["size_mm"][1]:.0f} mm'
                     f'   median {_f(sp["median_mm"])} p90 {_f(sp["p90_mm"])}'
                     f'   within25 {_pct(sp["frac_within_25mm"])}'
                     f'   density X/Y {"/".join(_f(p["mismatch_pct"]) for p in v["density"].values())}%')
            for d, c in sorted(v["per_dia"].items()):
                L.append(f'      {d:5} runs {c["drawn_runs"]:4d}/{c["model_runs"]:<4d}'
                         f' sections {c["drawn_sections"]:4d}/{c["model_sections"]:<4d}'
                         f' length {c["drawn_len_mm"]:>10.0f}/{c["model_len_mm"]:<10.0f} mm')
    return "\n".join(L)


def _f(v):
    return "-" if v is None else f"{v:.1f}"


def _pct(v):
    return "-" if v is None else f"{100*v:.0f}%"


# ---------------------------------------------------------------------- viewer

def build_viewer(model, results, sheets, out_path):
    """Self-contained 3D viewer: model, schedule, and the drawn 2D overlay."""
    here = Path(__file__).resolve().parent / "viewer"
    shell = (here / "shell.html").read_text()
    app = (here / "app.js").read_text()

    bbs_path = ROOT / "out" / "bbs.json"
    bbs = json.loads(bbs_path.read_text()) if bbs_path.exists() else {}
    sched = {}
    for k, el in model.items():
        p0 = re.sub(r"\s*\[.*\]$", "", k)
        marks = {b["mark"] for b in el["bars"]}
        src = bbs.get(p0)
        if src:
            sched[k] = {"bars": [b for b in src["bars"] if b["mark"] in marks],
                        "summary": src.get("summary")}
    m_out = {}
    for k, el in model.items():
        m_out[k] = {"envelope": el["envelope"], "sheet": el["sheet"],
                    "bars": [{"mark": b["mark"], "dia": b["dia"],
                              "pts": [[round(c, 1) for c in p] for p in b["pts"]]}
                             for b in el["bars"]]}
    # drawn 2D geometry, lifted to 3D at the plane of its view, for the overlay
    overlay = {}
    acc = {}
    for r in results:
        el = model[r["element"]]
        env = el["envelope"]
        T = env.get("thickness_mm") or 200.0
        segs = []
        sheet = sheets[r["sheet"]]
        for v in r["views"]:
            for b in v["_render"]["drawn_runs"]:
                (p, q) = b["seg"]
                if v["kind"] == "elevation":
                    segs.append([p[0], 0, p[1], q[0], 0, q[1], b["dia"]])
                elif v["kind"] == "plan_cut":
                    segs.append([p[0], p[1], 0, q[0], q[1], 0, b["dia"]])
                elif v["kind"] == "end_cut":
                    segs.append([0, p[0], p[1], 0, q[0], q[1], b["dia"]])
        overlay[r["element"]] = [[round(c, 1) for c in s] for s in segs]
        acc[r["element"]] = r["summary"]
    payload = ("const MODEL=" + json.dumps(m_out, separators=(",", ":")) +
               ";\nconst BBS=" + json.dumps(sched, separators=(",", ":")) +
               ";\nconst OVERLAY=" + json.dumps(overlay, separators=(",", ":")) +
               ";\nconst ACC=" + json.dumps(acc, separators=(",", ":")) + ";\n")
    html = shell + "\n<script>\n" + payload + app + "\n</script>\n"
    out_path.write_text(html)
    return len(html)


# ------------------------------------------------------------------------ main

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--elements", help="comma-separated subset")
    ap.add_argument("--no-viewer", action="store_true")
    ap.add_argument("--no-renders", action="store_true")
    ap.add_argument("--v1", action="store_true",
                    help="force the v1 model even if stage 4 output exists")
    a = ap.parse_args(argv)

    REPORT.mkdir(parents=True, exist_ok=True)
    model = load_model(prefer_v2=not a.v1)
    if a.elements:
        want = set(a.elements.split(","))
        model = {k: v for k, v in model.items() if k in want}
    src = next(iter(model.values()))["source"] if model else "?"
    print(f"model: {src}  ({len(model)} elements, "
          f"{sum(len(v['bars']) for v in model.values())} bars)")

    sheets, results = {}, []
    for name in sorted(model):
        r = measure_element(name, model[name], sheets)
        results.append(r)
        s = r["summary"]
        if s:
            print(f'  {name:30} drawn {s["drawn_bars"]:4d}  model {s["model_bars"]:4d}'
                  f'  median {_f(s["median_mm"])} mm')
        else:
            print(f'  {name:30} no matching view on {r["sheet"]}')
        if not a.no_renders:
            render_overlay(name, r, sheets[r["sheet"]],
                           REPORT / f"overlay_{_safe(name)}.png")

    clean = json.loads(json.dumps(results, default=str))
    for r in clean:
        for v in r["views"]:
            v.pop("_render", None)
    (REPORT / "accuracy.json").write_text(
        json.dumps({"model_source": src, "elements": clean}, indent=1))
    txt = text_report(results, src)
    (REPORT / "accuracy.txt").write_text(txt + "\n")
    print("\n" + txt.split("Per view detail")[0])

    if not a.no_viewer:
        n = build_viewer(model, results, sheets, ROOT / "out" / "v2" / "viewer.html")
        print(f"viewer: out/v2/viewer.html  {n//1024} KB")
    print(f"report: {REPORT}")


def _safe(name):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


if __name__ == "__main__":
    main()
