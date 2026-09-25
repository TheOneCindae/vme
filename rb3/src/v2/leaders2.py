"""Direct mark -> bar binding via leader-line geometry.

Every mark tag on these drawings (a one-letter bubble such as "F", or a bare
note such as "-(14) -(T12)") has a leader: a short polyline on
``S-RBAR-IDEN`` that runs from beside the tag to an arrowhead landing
directly on the bar it labels.  That is a *pointer*, not a statistical
coincidence of length/count/diameter -- much stronger evidence than the
array-signature matching ``src/v2/bind.py`` relies on today.

Why earlier attempts called this "unreliable"
-----------------------------------------------
``src/leaders.py`` and the ``leaders()`` helper inside ``src/v2/bind.py``
either walk the leader network segment-by-segment from a fixed start point
(``src/leaders.py:_chain``), which derails at the first branch or gap, or
read ``doc.modelspace()`` directly (``bind.py:leaders``), which is exactly
the Revit-export trap the rest of this pipeline had to fix: DWG blocks are
placed at ins_pt (0,0) with world coordinates baked into the block geometry,
so anything living inside an INSERT is invisible unless the block is
exploded first.  On the sheets checked here the leader *lines* turned out to
be top-level (not block-nested) -- but the tag text and mark bubbles include
INSERT-derived geometry, and there is no guarantee every sheet keeps its
leader lines top-level either. This module sources everything from
``out/v2/raw/<sheet>.json`` (stage 1), which already explodes every INSERT
recursively (see ``src/v2/raw.py``), so both cases are covered for free.

Method
------
1.  Parse every ``S-RBAR-IDEN`` MTEXT label with ``bind.parse_note`` (mark
    bubble letters, "-(qty) -(Tdia)" notes, spacing notes -- both drawing
    dialects).  Pair notes to the nearest mark bubble with
    ``bind.pair_notes_to_marks`` to get each mark's scheduled diameter.
2.  Group every ``S-RBAR-IDEN`` LINE into connected components with a
    union-find keyed on endpoints snapped to a small grid (default 12 mm),
    not by walking segments in order.  A leader is one component.
3.  For each component, the two points with the largest pairwise distance
    are its free ends (a leader is a short open polyline, never a loop).
    Whichever end sits closer to a mark bubble is the label end; the other
    is the tip.  A component whose closer end is still far from every
    bubble (default > 200 mm) is dropped -- it is not confidently anyone's
    leader.
4.  The tip is snapped to the nearest drawn bar of the mark's scheduled
    diameter (via ``src/v2/bars2d.py``, rebuilt fresh so this module never
    reads stale cache) within a tight tolerance (default 90 mm). That IS
    the direct identification: record it as a high-confidence binding,
    separate from array-signature matching.

Standalone / not wired into the stage-4 pipeline
-------------------------------------------------
This module owns none of the stage-4 contract; it is a new, independent
source of evidence for another process to merge into ``bind.py``.
"""
from __future__ import annotations

import collections
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from v2 import bind as BIND    # noqa: E402  (parse_note, pair_notes_to_marks)
from v2 import bars2d as B2D  # noqa: E402

IDEN = "S-RBAR-IDEN"
RBAR = "S-RBAR"
RAW_DIR = ROOT / "out" / "v2" / "raw"

SNAP = 12.0            # mm: leader-segment endpoint join tolerance
LABEL_MAX = 200.0      # mm: label end must be this close to a mark bubble
TIP_MAX = 90.0         # mm: tip must be this close to a drawn bar to count
MATERIAL_MAX = 150.0   # mm: tip must be this close to ANY raw S-RBAR line to
                       # be trusted as landing on a bar at all (see
                       # `_material_dist` -- this is what actually separates a
                       # real leader from a same-layer stub/witness line that
                       # only happens to sit near a bubble)
DIAS = (8, 10, 12, 16, 20, 25, 32)


# --------------------------------------------------------------------------
# 1. raw entities
# --------------------------------------------------------------------------

def load_raw(sheet):
    """Model-space entities for a sheet, from stage-1's exploded JSON."""
    p = RAW_DIR / f"{sheet}.json"
    if not p.exists():
        raise FileNotFoundError(
            f"{p} missing -- run `venv/bin/python -m src.v2.raw {sheet}` first")
    with open(p) as fh:
        d = json.load(fh)
    return [e for e in d["entities"] if e.get("space", "model") == "model"]


# --------------------------------------------------------------------------
# 2. mark tags + their scheduled diameter (both drawing dialects)
# --------------------------------------------------------------------------

def read_labels(entities):
    """Every parsed S-RBAR-IDEN MTEXT label, as bind.read_labels() but from
    stage-1 records instead of an ezdxf doc (so INSERT-nested text -- if any
    -- is included too)."""
    out = []
    for e in entities:
        if e["layer"] != IDEN or e["type"] != "MTEXT":
            continue
        r = BIND.parse_note(e.get("text", ""))
        if r:
            r = dict(r)
            r["p"] = tuple(e["pts"][0])
            out.append(r)
    return out


def bubble_instances(labels):
    """Every mark bubble as its OWN instance: [{"idx", "mark", "p"}, ...].

    Mark letters are NOT unique across a sheet -- the same letter ("K", "F",
    ...) is reused in every view/section, so collapsing bubbles into a
    ``{letter: point}`` dict silently merges unrelated bars that happen to
    share a letter (verified: PW-GF-01_R has two separate "K" bubbles
    ~8000 mm apart). Every instance keeps its own index so a leader is
    matched to the physically nearest bubble, never to "whichever bubble
    with this letter was seen last".
    """
    return [{"idx": i, "mark": l["mark"], "p": l["p"]}
            for i, l in enumerate(labels) if l["kind"] == "mark"]


def instance_diameters(labels, bubbles, max_dist=900.0):
    """bubble idx -> {dia, qty, spacing} from the note nearest THAT instance.

    Mirrors ``bind.pair_notes_to_marks`` (nearest-bubble note pairing) but
    keyed by bubble instance instead of by letter, for the reason above.
    """
    out = {b["idx"]: {"dia": None, "qty": None, "spacing": None} for b in bubbles}
    if not bubbles:
        return out
    for l in labels:
        if l["kind"] == "mark":
            continue
        b = min(bubbles, key=lambda x: math.dist(x["p"], l["p"]))
        if math.dist(b["p"], l["p"]) <= max_dist:
            out[b["idx"]] = {"dia": l.get("dia"), "qty": l.get("qty"),
                             "spacing": l.get("spacing")}
    return out


# --------------------------------------------------------------------------
# 3. leader components: union-find over S-RBAR-IDEN LINE endpoints
# --------------------------------------------------------------------------

def _key(p, snap):
    return (round(p[0] / snap), round(p[1] / snap))


def leader_components(entities, snap=SNAP):
    """Connected components of S-RBAR-IDEN LINE geometry.

    Grouped by a union-find keyed on endpoints snapped to a grid, so a
    leader made of several short segments (a bend near the bubble, a run to
    the tip) is recovered as one component regardless of the order the
    segments were drawn in -- no sequential "walk outward" that derails at
    a branch or a gap.
    """
    segs = [tuple(map(tuple, e["pts"])) for e in entities
            if e["layer"] == IDEN and e["type"] == "LINE" and len(e.get("pts", [])) == 2]
    if not segs:
        return []

    parent = {}

    def find(x):
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[a] = b

    # each segment's own endpoints are connected to each other ...
    for a, b in segs:
        union(("k", _key(a, snap)), ("k", _key(b, snap)))
    # ... and endpoints across segments that land in the same (or an
    # adjacent) grid cell are merged too, so the join tolerance is not
    # limited to one grid cell's width.
    grid = collections.defaultdict(list)
    for a, b in segs:
        for p in (a, b):
            grid[_key(p, snap)].append(p)
    for cell, pts in list(grid.items()):
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                other = grid.get((cell[0] + dx, cell[1] + dy))
                if not other:
                    continue
                for p in pts:
                    for q in other:
                        if p is q:
                            continue
                        if math.dist(p, q) < snap:
                            union(("k", _key(p, snap)), ("k", _key(q, snap)))

    groups = collections.defaultdict(list)
    for i, (a, b) in enumerate(segs):
        groups[find(("k", _key(a, snap)))].append(i)

    comps = []
    for idxs in groups.values():
        pts = [p for i in idxs for p in segs[i]]
        comps.append({"seg_idx": idxs, "pts": pts})
    return comps


def _free_ends(pts):
    """The two points of a component farthest apart from each other.

    A leader is a short open polyline (never a loop, never branching in
    practice), so the diameter of its point set is the label end <-> tip
    axis. Components are tiny (<=~10 points), so brute force is fine.
    """
    best, bd = (pts[0], pts[0]), -1.0
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            d = math.dist(pts[i], pts[j])
            if d > bd:
                best, bd = (pts[i], pts[j]), d
    return best[0], best[1], bd


# --------------------------------------------------------------------------
# 4. tag -> tip, per component
# --------------------------------------------------------------------------

def _material_segments(entities):
    """Every raw S-RBAR edge/arc-sample as a segment (or degenerate point).

    This is the actual drawn bar material, straight from stage 1 -- lossless
    and always complete, unlike ``bars2d``'s reconstructed centrelines which
    can have gaps where the paired-edge/bend recovery fails on a busy view.
    Used to sanity-check a leader tip independently of whether ``bars2d``
    managed to reconstruct a bar there.
    """
    segs = []
    for e in entities:
        if e["layer"] != RBAR:
            continue
        pts = e.get("pts", [])
        if e["type"] in ("LINE", "LWPOLYLINE", "ARC") and len(pts) >= 2:
            for i in range(len(pts) - 1):
                segs.append((tuple(pts[i]), tuple(pts[i + 1])))
        elif e["type"] == "CIRCLE" and pts:
            c = tuple(pts[0])
            segs.append((c, c))
    return segs


def _material_dist(tip, segs):
    """Distance from `tip` to the nearest drawn S-RBAR edge (any diameter)."""
    if not segs:
        return 1e18
    return min(_pt_seg(tip, a, b) for a, b in segs)


def tag_tips(entities, label_max=LABEL_MAX, snap=SNAP, material_max=MATERIAL_MAX):
    """For every mark BUBBLE INSTANCE, the leader tip pointing at its bar.

    Returns a list of ``{"inst", "mark", "bubble", "tip", "label_dist",
    "reach", "n_seg", "material_dist"}``.  Matching is against bubble
    INSTANCES (see `bubble_instances`), not mark letters, because the same
    letter is reused across views/sections on one sheet -- keying by letter
    would silently fuse two unrelated bars that happen to share a name.
    A component is only attributed to an instance if its closer free end
    lies within ``label_max`` of that instance's bubble position --
    otherwise it is dropped as unattributed rather than guessed at.

    Same-layer clutter (a witness/dimension stub, or the short connector
    from a bubble to its own adjacent qty note) can sit within `label_max`
    of a bubble without ever reaching a bar; on its own that produces a
    "leader" whose tip lands in empty space. So every candidate tip is also
    checked against the raw S-RBAR geometry itself (`_material_dist` --
    always complete, unlike bars2d's reconstruction, which can have gaps):
    a tip farther than `material_max` from ANY drawn bar edge is not a bar
    pointer and is dropped.  When an instance has more than one surviving
    candidate (e.g. a broken/bent leader picked up as two components), the
    one landing closest to actual bar material wins.
    """
    labels = read_labels(entities)
    bubbles = bubble_instances(labels)
    if not bubbles:
        return []
    comps = leader_components(entities, snap=snap)
    material = _material_segments(entities)

    cands = []
    for c in comps:
        p, q, span = _free_ends(c["pts"])
        if span < 40.0:          # a leader that never leaves its own bubble
            continue

        def nearest(pt):
            b, d = None, 1e18
            for bub in bubbles:
                dd = math.dist(pt, bub["p"])
                if dd < d:
                    b, d = bub, dd
            return b, d

        b_p, d_p = nearest(p)
        b_q, d_q = nearest(q)
        if d_p <= d_q:
            label_end, tip, bub, label_dist = p, q, b_p, d_p
        else:
            label_end, tip, bub, label_dist = q, p, b_q, d_q
        if label_dist > label_max:
            continue
        md = _material_dist(tip, material)
        if md > material_max:
            continue
        cands.append({"inst": bub["idx"], "mark": bub["mark"], "bubble": bub["p"],
                      "label_end": label_end, "tip": tip,
                      "label_dist": round(label_dist, 1),
                      "reach": round(math.dist(tip, label_end), 1),
                      "n_seg": len(c["seg_idx"]), "material_dist": round(md, 1)})

    best = {}
    for cd in cands:
        cur = best.get(cd["inst"])
        if cur is None or cd["material_dist"] < cur["material_dist"]:
            best[cd["inst"]] = cd
    return list(best.values())


# --------------------------------------------------------------------------
# 5. snap tip -> drawn bar (src/v2/bars2d.py)
# --------------------------------------------------------------------------

def _pt_seg(p, a, b):
    ax, ay = a
    bx, by = b
    vx, vy = bx - ax, by - ay
    L = vx * vx + vy * vy
    if L < 1e-9:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - ax) * vx + (p[1] - ay) * vy) / L))
    return math.dist(p, (ax + t * vx, ay + t * vy))


def _bar_dist(tip, bar):
    pts = bar["pts"]
    if bar["kind"] == "section" or len(pts) == 1:
        return math.dist(tip, pts[0])
    best = 1e18
    for i in range(len(pts) - 1):
        best = min(best, _pt_seg(tip, pts[i], pts[i + 1]))
    return best


def _in_box(p, box, pad=2.0):
    return (box[0] - pad <= p[0] <= box[2] + pad
            and box[1] - pad <= p[1] <= box[3] + pad)


def nearest_bar(tip, view, dia=None, max_d=TIP_MAX):
    """Nearest bar in a bars2d view to `tip`, optionally constrained by dia."""
    best, bd = None, 1e18
    for b in view["bars"]:
        if dia is not None and b["dia"] != dia:
            continue
        d = _bar_dist(tip, b)
        if d < bd:
            best, bd = b, d
    if best is not None and bd <= max_d:
        return best, bd
    return None, bd


def snap_tips(sheet, tips, tip_max=TIP_MAX, inst_dia=None):
    """Snap every tag_tips() tip to a bars2d bar; report diameter agreement.

    `inst_dia`: {bubble_idx: {"dia":...}} from instance_diameters(), used to
    prefer a bar of the scheduled diameter; falls back to nearest bar of ANY
    diameter so a mismatch is visible instead of silently dropped. Keyed by
    bubble instance (not mark letter) for the same reason `tag_tips` is.
    """
    sheet_bars = B2D.build_sheet(sheet)
    out = []
    for t in tips:
        tip = t["tip"]
        view = None
        for v in sheet_bars["views"]:
            if _in_box(tip, v["box"], pad=50.0):
                view = v
                break
        if view is None:
            out.append({**t, "sheet": sheet, "view": None, "bar": None,
                       "dist": None, "expected_dia": None, "found_dia": None,
                       "dia_match": False, "status": "no_view"})
            continue
        exp = (inst_dia or {}).get(t["inst"], {}).get("dia")
        bar, d = nearest_bar(tip, view, dia=exp, max_d=tip_max)
        status = "ok"
        if bar is None:
            bar2, d2 = nearest_bar(tip, view, dia=None, max_d=tip_max)
            if bar2 is not None:
                bar, d, status = bar2, d2, "dia_mismatch"
            else:
                status = "no_bar_in_range"
        out.append({**t, "sheet": sheet, "view": view["id"],
                   "bar": bar["id"] if bar else None,
                   "dist": round(d, 1) if bar else None,
                   "expected_dia": exp,
                   "found_dia": bar["dia"] if bar else None,
                   "dia_match": bool(bar and exp and bar["dia"] == exp),
                   "status": status})
    return out


# --------------------------------------------------------------------------
# 6. single entry point
# --------------------------------------------------------------------------

def bind_leaders(sheet, label_max=LABEL_MAX, tip_max=TIP_MAX, snap=SNAP):
    """Direct leader-to-bar bindings for one sheet.

    Inputs
    ------
    sheet : str, e.g. "PW-GF-01_R" or "PW-GF-11_R1" (a key under
            out/v2/raw/<sheet>.json; run `python -m src.v2.raw <sheet>` if
            missing).

    Returns
    -------
    list[dict], one per leader component confidently attributed to a mark
    BUBBLE INSTANCE (mark letters repeat across views on one sheet, so
    "inst" -- not "mark" -- is the unique key):
        {"inst": int, "mark": str, "sheet": str, "view": str|None,
         "bar": str|None, "tip": (x,y), "bubble": (x,y),
         "label_dist": float, "reach": float, "n_seg": int,
         "material_dist": float, "dist": float|None,
         "expected_dia": int|None, "found_dia": int|None, "dia_match": bool,
         "status": "ok"|"dia_mismatch"|"no_bar_in_range"|"no_view"}
    Only entries with status == "ok" and dia_match True are a confident
    direct identification; the rest are kept so the caller can see what was
    tried and why it did not confirm.
    """
    entities = load_raw(sheet)
    labels = read_labels(entities)
    bubbles = bubble_instances(labels)
    dias = instance_diameters(labels, bubbles)
    tips = tag_tips(entities, label_max=label_max, snap=snap)
    return snap_tips(sheet, tips, tip_max=tip_max, inst_dia=dias)


# --------------------------------------------------------------------------
# CLI: standalone test / report
# --------------------------------------------------------------------------

def _report(sheet):
    binds = bind_leaders(sheet)
    n_marks_with_leader = len({b["mark"] for b in binds})
    ok = [b for b in binds if b["status"] == "ok" and b["dia_match"]]
    mism = [b for b in binds if b["status"] == "dia_mismatch"]
    nobar = [b for b in binds if b["status"] == "no_bar_in_range"]
    noview = [b for b in binds if b["status"] == "no_view"]
    print(f"## {sheet}")
    print(f"  leader components attributed to a mark: {len(binds)} "
          f"({n_marks_with_leader} distinct marks)")
    print(f"  confident direct bindings (dia matches): {len(ok)}")
    print(f"  diameter mismatch (nearest bar has wrong dia): {len(mism)}")
    print(f"  no bar within tolerance: {len(nobar)}")
    print(f"  tip outside any view box: {len(noview)}")
    if mism:
        print("  mismatches:")
        for b in mism[:15]:
            print(f"    mark={b['mark']:<3} expected T{b['expected_dia']} "
                  f"found T{b['found_dia']} dist={b['dist']}")
    return binds


if __name__ == "__main__":
    sheets = sys.argv[1:] or [
        "PW-GF-01_R", "PW-GF-11_R1", "PW-GF-11_R2",
        "PW-GF-05_R1", "PW-GF-05_R2", "PW-GF-02_R", "PW-GF-09_R1",
    ]
    for s in sheets:
        try:
            _report(s)
        except FileNotFoundError as exc:
            print(f"## {s}: SKIP ({exc})")
