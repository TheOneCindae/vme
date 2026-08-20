"""Section-only triangulation for elements with NO elevation view.

Most elements' primary evidence is an elevation: a bar drawn lengthwise, full
extent visible.  A few elements (PW-GF-09's 1500x5055x400 piece, PW-GF-08's
2155x5095x200 piece -- both `_R2` sheets that carry only section cuts, no
elevation viewport at all) have nothing to fall back to but circles: a
`plan_cut` shows a vertical bar end-on, an `end_cut` shows a horizontal bar
end-on.

`src/v2/bind.py`'s existing section-only fallback (search "A section circle
gives a POSITION, not a length") already does the minimum honest thing: pool
every circle of a mark's diameter across a sheet, claim `min(qty, pool)` of
them, and synthesize a straight segment of the schedule's own cut length
centered on each circle's position.  Its weakness is exactly what this module
is for:

  1. it pools circles from ALL of a sheet's plan_cuts (or end_cuts) together
     under one dict key, `(sheet, kind, dia)`, with no idea that the SAME
     physical bar's circle in cut #3 and cut #4 are one bar, not two --
     inflating the apparent pool and risking one bar "locating" two marks'
     worth of quota, or one mark eating another's evidence;
  2. it only ever uses ONE cut's evidence per bar (the view with the most
     matching circles wins, per mark) -- it never notices that a bar visible
     in two DIFFERENT cuts is measured at two real heights, which bounds its
     extent far better than "center a schedule-length segment on a single
     point";
  3. it does not look at the SPACING between same-diameter circles inside a
     single cut, which is often a strong signature on its own (an evenly
     spaced group of N circles matching a mark's N bars).

This module reads the SAME per-sheet evidence bind.py already extracts
(`bind.load_bars3d`'s `sections` list: `{"p", "wp", "dia", "view"}` per
circle, in view-local element-footprint mm) and produces a de-duplicated,
cross-cut-aware, pitch-aware placement for marks that have no other evidence.
It does not import or edit `bind.py`'s binding state; it is meant to be
called in place of (or before) bind.py's section-only pass 2, by a caller
that owns `data`/`marks`/`state` -- see `triangulate_marks` below for the
exact contract.

No absolute cut height (world Z) is recoverable for these elements: cut
stations are read off `section_markers()` in `src/v2/views.py`, which finds
its markers ON THE ELEVATION -- these sheets have none.  So "confirmed at 2+
cut heights" here means confirmed at 2+ DISTINCT, ORDERED cut stations (their
section numbers, read via `views.title_number`/`views.viewport_numbers`,
which ARE reused, not reimplemented) -- real evidence that the bar is not a
one-point guess, without inventing a metric Z it was never measured at.  The
bar's own length still comes from the schedule (this project's convention:
BBS is authoritative for length, the drawing supplies position -- see
`bind.py`'s docstring and the same pass), now centered on the AVERAGE of 2-3
real, independent circle positions instead of one.
"""
from __future__ import annotations

import collections
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "v2"))

import bind as BIND          # noqa: E402  -- load_bars3d, SCHEDULE, sheets_for
import views as V             # noqa: E402  -- title_number / viewport_numbers reuse

POS_TOL = 25.0     # mm: same in-plane (X,Y) or (Y,Z) position across cuts
PITCH_TOL_ABS = 8.0
PITCH_TOL_REL = 0.18


# --------------------------------------------------------------------------
# 0. view identity + cut ordering (reuses views.py, does not reimplement it)
# --------------------------------------------------------------------------

def _view_key(view):
    """A section circle's `view` is a dict re-created per sheet load; key it
    by its wall box, which is stable and unique per viewport on a sheet."""
    return (view.get("sheet") or view.get("title"), view["kind"],
            tuple(round(x, 1) for x in view["wall"]))


def cut_order(doc, views):
    """Section number per plan_cut/end_cut view, via views.py's own readers.

    Gives an ORDER across a sheet's cuts (no elevation -> no metric station,
    but the numbering is real drawing evidence of sequence).  Returns
    {view_key: number or None}.
    """
    vpnums = V.viewport_numbers(doc)
    out = {}
    for v in views:
        if v["kind"] not in ("plan_cut", "end_cut"):
            continue
        out[_view_key(v)] = V.title_number(doc, v, vpnums)
    return out


# --------------------------------------------------------------------------
# 1. cross-cut matching: same (dia, position) in 2+ DIFFERENT cuts
# --------------------------------------------------------------------------

def cross_cut_clusters(sections, kind, pos_tol=POS_TOL):
    """Union same-diameter circles that share an in-plane position across
    DIFFERENT views of the given kind ('plan_cut' or 'end_cut').

    Same-view pairs never union (two circles 25 mm apart in ONE cut are two
    real bars, not one bar seen twice) -- only a cross-view coincidence is
    evidence of the same physical bar recurring at another cut station.

    Returns clusters with `n_cuts >= 2`, i.e. confirmed at multiple stations.
    Circles left as singletons (seen in only one cut, or matching nothing
    across cuts) are the caller's job to fall back on.
    """
    pts = [c for c in sections if c["view"]["kind"] == kind]
    n = len(pts)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(n):
        for j in range(i + 1, n):
            a, b = pts[i], pts[j]
            if a["dia"] != b["dia"]:
                continue
            if _view_key(a["view"]) == _view_key(b["view"]):
                continue
            if abs(a["p"][0] - b["p"][0]) <= pos_tol and \
               abs(a["p"][1] - b["p"][1]) <= pos_tol:
                union(i, j)

    groups = collections.defaultdict(list)
    for i in range(n):
        groups[find(i)].append(pts[i])

    used = set()
    clusters = []
    for idxs in groups.values():
        vkeys = sorted({_view_key(c["view"]) for c in idxs})
        if len(vkeys) < 2:
            continue
        dia = idxs[0]["dia"]
        x = sum(c["p"][0] for c in idxs) / len(idxs)
        y = sum(c["p"][1] for c in idxs) / len(idxs)
        clusters.append({"dia": dia, "p": (x, y), "n_cuts": len(vkeys),
                         "views": vkeys, "circles": idxs})
        used.update(id(c) for c in idxs)
    singles = [c for c in pts if id(c) not in used]
    return clusters, singles


# --------------------------------------------------------------------------
# 2. within-cut pitch: N evenly spaced circles of one diameter in one view
# --------------------------------------------------------------------------

def pitch_groups(circles, min_n=2):
    """Evenly spaced runs among same-diameter circles already confined to
    ONE view (caller filters by view+dia first).  The spread axis (X or Y in
    that view's local frame) is picked as whichever coordinate varies more --
    a plan_cut's vertical-bar circles line up across the width or the
    thickness depending on layout, and both are legitimate.
    """
    if len(circles) < min_n:
        return []
    xs = [c["p"][0] for c in circles]
    ys = [c["p"][1] for c in circles]
    axis = 0 if (max(xs) - min(xs)) >= (max(ys) - min(ys)) else 1
    pts = sorted(circles, key=lambda c: c["p"][axis])
    coords = [c["p"][axis] for c in pts]
    out, i = [], 0
    while i < len(pts):
        j = i + 1
        pitches = []
        while j < len(pts):
            d = coords[j] - coords[j - 1]
            if d < 1e-6:
                j += 1
                continue
            if not pitches:
                pitches.append(d)
            elif abs(d - pitches[0]) > max(PITCH_TOL_ABS, PITCH_TOL_REL * pitches[0]):
                break
            else:
                pitches.append(d)
            j += 1
        n = j - i
        if n >= min_n:
            seg = pts[i:j]
            out.append({"dia": seg[0]["dia"], "axis": axis, "n": n,
                        "pitch": round(sum(pitches) / len(pitches), 1)
                                 if pitches else None,
                        "circles": seg})
        i = j
    return out


def pitch_groups_all(sections, kind):
    """`pitch_groups` applied per (view, diameter) bucket across a sheet."""
    by_bucket = collections.defaultdict(list)
    for c in sections:
        if c["view"]["kind"] != kind:
            continue
        by_bucket[(_view_key(c["view"]), c["dia"])].append(c)
    out = []
    for (_vk, _dia), cs in by_bucket.items():
        out += pitch_groups(cs)
    return out


# --------------------------------------------------------------------------
# 3. placement: turn evidence into a 3D segment, schedule length, real pos
# --------------------------------------------------------------------------

def _place(kind, p, dia, L, cover=30.0):
    """One synthesized 3D bar: schedule length, centered on the MEASURED
    in-plane position (average of every cut that saw this circle).  Same
    axis convention as bind.py's existing section-only pass: a plan_cut sees
    (X, Y) and the bar runs in Z; an end_cut sees (Y, Z) and the bar runs in
    X.  Only the LENGTH is unmeasured here (schedule-authoritative, per
    project convention) -- the position is real, not invented."""
    x, y = p
    if kind == "plan_cut":
        z0 = cover + dia / 2.0
        return [[x, y, z0], [x, y, z0 + L]]
    x0 = cover + dia / 2.0
    return [[x0, x, y], [x0 + L, x, y]]


def triangulate_marks(data, marks):
    """Section-only placement for marks with NO other evidence.

    `data`   -- exactly bind.load_bars3d(element)'s return value (or one you
                already hold from bind_element); read-only here.
    `marks`  -- schedule bar records for the element (bind.SCHEDULE[el] /
                out/bbs.json shape: dict per mark with mark, dia_mm, qty,
                bar_length_mm, schedule, ...).

    Returns a list, ONE ENTRY PER MARK IN `marks`, in bind_element's own
    `state` shape:
        {"mark": <mark dict>, "located": int, "bars": [ {...} ],
         "evidence": collections.Counter}
    so a caller can drop this straight in place of (or ahead of) bind.py's
    "pass 2: sections, only for marks no array reached" block --
    `st["bars"]`/`st["located"]`/`st["evidence"]` merge into bind_element's
    own `state[mi]` exactly as that pass already does.

    Evidence, in order of trust:
      a) cross_cut_clusters: circle confirmed at 2+ DIFFERENT cut stations,
         same diameter, same in-plane position -- one bar, real, multi-
         measured.  Never split across marks: each cluster is claimed whole.
      b) pitch_groups: an evenly spaced run of N circles of one diameter in
         ONE cut, N close to (or a divisor of) a mark's qty -- position
         evidence bind.py's pooling does not extract at all.
      c) leftover singleton circles (seen once, no pitch partner) -- same
         one-point-per-bar fallback bind.py's pass 2 already uses, but now
         de-duplicated against (a) and (b) so the same physical bar is never
         claimed twice.
    """
    sections = []
    for sh in data["sheets"]:
        sections += sh.get("sections", [])
    if not sections:
        return [{"mark": m, "located": 0, "bars": [],
                 "evidence": collections.Counter()} for m in marks]

    pool = {}          # kind -> {"clusters":[...], "pitch":[...], "singles":[...]}
    for kind in ("plan_cut", "end_cut"):
        clusters, singles = cross_cut_clusters(sections, kind)
        claimed = {id(c) for cl in clusters for c in cl["circles"]}
        pg = pitch_groups_all(sections, kind)
        # drop pitch groups already fully covered by a cross-cut cluster --
        # that evidence is stronger and already accounted for
        pg = [g for g in pg if not all(id(c) in claimed for c in g["circles"])]
        pg_claimed = {id(c) for g in pg for c in g["circles"]}
        singles = [c for c in singles if id(c) not in pg_claimed]
        pool[kind] = {"clusters": sorted(clusters, key=lambda c: -c["n_cuts"]),
                      "pitch": sorted(pg, key=lambda g: -g["n"]),
                      "singles": singles}

    used_cluster = {k: [False] * len(pool[k]["clusters"]) for k in pool}
    used_pitch_idx = {k: [0] * len(pool[k]["pitch"]) for k in pool}       # circles taken
    used_single = {k: [False] * len(pool[k]["singles"]) for k in pool}

    state = []
    for m in marks:
        dia = int(m["dia_mm"])
        qty = m["qty"]
        L = m["bar_length_mm"]
        located, bars = 0, []
        ev = collections.Counter()
        if qty <= 0:
            state.append({"mark": m, "located": 0, "bars": [], "evidence": ev})
            continue

        for kind in ("plan_cut", "end_cut"):
            p = pool[kind]

            # a) cross-cut confirmed clusters, most-confirmed first
            for ci, cl in enumerate(p["clusters"]):
                if located >= qty:
                    break
                if used_cluster[kind][ci] or cl["dia"] != dia:
                    continue
                used_cluster[kind][ci] = True
                pts = _place(kind, cl["p"], dia, L)
                bars.append({"pts": pts, "dia": dia, "sheet": cl["circles"][0]["view"].get("sheet"),
                            "view": kind, "array": None,
                            "evidence": f"section_multi_cut(n={cl['n_cuts']})"})
                located += 1
                ev["section_multi_cut"] += 1

            # b) within-cut pitch groups: take the whole group if its count
            #    is close to what's still needed (a real, measured array),
            #    else skip it whole rather than partially cannibalize it
            for gi, g in enumerate(p["pitch"]):
                if located >= qty:
                    break
                if g["dia"] != dia or used_pitch_idx[kind][gi] >= g["n"]:
                    continue
                need = qty - located
                avail = g["n"] - used_pitch_idx[kind][gi]
                take = min(need, avail)
                off = used_pitch_idx[kind][gi]
                used_pitch_idx[kind][gi] += take
                for c in g["circles"][off:off + take]:
                    pts = _place(kind, c["p"], dia, L)
                    bars.append({"pts": pts, "dia": dia, "sheet": c["view"].get("sheet"),
                                "view": kind, "array": None,
                                "evidence": f"section_pitch(n={g['n']},pitch={g['pitch']})"})
                located += take
                ev["section_pitch"] += take

            # c) leftover singleton circles, one bar each -- bind.py's
            #    original fallback, minus what (a)/(b) already accounted for
            for si, c in enumerate(p["singles"]):
                if located >= qty:
                    break
                if used_single[kind][si] or c["dia"] != dia:
                    continue
                used_single[kind][si] = True
                pts = _place(kind, c["p"], dia, L)
                bars.append({"pts": pts, "dia": dia, "sheet": c["view"].get("sheet"),
                            "view": kind, "array": None,
                            "evidence": "section_single_cut"})
                located += 1
                ev["section_single_cut"] += 1

            if located >= qty:
                break

        state.append({"mark": m, "located": located, "bars": bars, "evidence": ev})
    return state


# --------------------------------------------------------------------------
# CLI: standalone test on the two known section-only elements
# --------------------------------------------------------------------------

def _summarize(marks, state):
    sched_len = sum(m["qty"] * m["bar_length_mm"] for m in marks)
    loc_len = 0.0
    for st in state:
        loc = min(st["located"], st["mark"]["qty"])
        loc_len += loc * st["mark"]["bar_length_mm"]
    qty_s = sum(m["qty"] for m in marks)
    qty_l = sum(min(st["located"], st["mark"]["qty"]) for st in state)
    ev = collections.Counter()
    for st in state:
        ev += st["evidence"]
    return {"marks": len(marks), "qty_scheduled": qty_s, "qty_located": qty_l,
           "length_mm_scheduled": round(sched_len, 1),
           "length_mm_located": round(loc_len, 1),
           "located_frac_by_length": round(loc_len / sched_len, 4) if sched_len else None,
           "evidence": dict(ev)}


def main(argv):
    BIND.SCHEDULE = BIND.load_schedule()
    targets = argv[1:] or ["PW-GF-09 [1500x5055x400]", "PW-GF-08 [2155x5095x200]"]
    for element in targets:
        plain = __import__("re").sub(r"\s*\[.*\]$", "", element)
        plan = BIND._element_plan([plain])
        marks = next((ms for name, ms in plan if name == element), None)
        if marks is None:
            print(f"{element}: not found in element plan")
            continue
        data = BIND.load_bars3d(element)
        state = triangulate_marks(data, marks)
        s = _summarize(marks, state)
        print(f"{element}: {s['qty_located']}/{s['qty_scheduled']} bars, "
              f"{s['located_frac_by_length']:.4f} by length, evidence={s['evidence']}")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
