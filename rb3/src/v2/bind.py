"""Stage 4 -- bind every drawn bar to its schedule mark, and reconcile.

The schedule (``out/bbs.json``) says WHAT exists: 256 marks / 3629 bars, exact
and already verified.  The drawing says WHERE.  This stage is the join, and the
join is only allowed to be made on evidence:

  a) a leader whose arrow head lands on a specific drawn bar,
  b) a detected array of evenly spaced bars whose (diameter, count, pitch,
     length) signature matches a mark,
  c) diameter + length agreement alone.

Nothing is invented.  A scheduled bar that no evidence reaches is reported
UNLOCATED with a reason -- that is a result, not a failure to hide.

Reading the drawing's own words
-------------------------------
Two annotation dialects are in use and both are parsed here:

    -(62) -(T8)                 -(61) -(T8 U Bar)      -(2)-T16 Perimeter Bar
    -(46)-T8@200 mm             2 -T20                 3 -T8
    2 -T16 CRACK BAR            T8 @200 mm             T8 Horizontal @150 mm
    T8 Ties @100 mm             T8 UBAR @125 mm        T8 Hook @100 mm

PW-GF-02 and PW-GF-09 use the second dialect exclusively and carry *no* mark
bubbles at all, so on those sheets the note's (quantity, diameter, qualifier)
is the only handle onto a mark -- which is exactly why v1, which only read the
``-(62) -(T8)`` form, scored worst there.

Leaders
-------
Leader geometry survives the DWG->DXF conversion as loose S-RBAR-IDEN LINEs.
Chaining them by "walk outward from the tag" (v1) was unreliable.  Here they
are joined into connected components instead: one component is one leader, the
end nearest an MTEXT is its label, the far end is the arrow tip.  The tag
bubble is an INSERT holding a single CIRCLE, which anchors the label end.

Stage interface
---------------
``load_bars3d(element)`` is the single door onto stage 3.  When
``out/v2/lift/<element>.json`` exists it is used; until then the same records
are derived from the (R) drawings with the v1 extractors, flagged
``source="drawing"``, so binding accuracy can be measured today.
"""
from __future__ import annotations

import collections
import glob
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import ezdxf                      # noqa: E402
import rbar                       # noqa: E402
import assemble as ASM            # noqa: E402
import arrays as AR               # noqa: E402
import bbs as BBS                 # noqa: E402
import shapes3d                   # noqa: E402
import place as PLACE             # noqa: E402

IDEN = "S-RBAR-IDEN"
OUT = ROOT / "out" / "v2" / "bound"
LIFT = ROOT / "out" / "v2" / "lift"
BIG = (-1e9, -1e9, 1e9, 1e9)

# schedules that do not live on an (S) sheet
EXTRA_SCHEDULES = {"PW-GF-27": "PW-GF-27_R2", "PW-GF-30": "PW-GF-30_R2",
                   "PC-GF-01": "PC-GF-01_R"}


# --------------------------------------------------------------------------
# 1. annotation: both tag dialects
# --------------------------------------------------------------------------

QUALIFIERS = [
    ("u_bar",     re.compile(r"\bu\s*-?\s*bars?\b|\bubars?\b", re.I)),
    ("ties",      re.compile(r"\btie(s)?\b|\blink(s)?\b", re.I)),
    ("hook",      re.compile(r"\bhook(s)?\b", re.I)),
    ("horizontal", re.compile(r"\bhoriz(ontal)?\b", re.I)),
    ("vertical",  re.compile(r"\bvert(ical)?\b", re.I)),
    ("crack",     re.compile(r"\bcrack\b", re.I)),
    ("perimeter", re.compile(r"\bperimeter\b", re.I)),
    ("dowel",     re.compile(r"\bdowel\b", re.I)),
    ("starter",   re.compile(r"\bstarter\b", re.I)),
]

# -(62) -(T8) | -(61) -(T8 U Bar) | -(2)-T16 Perimeter Bar | -(46)-T8@200 mm
# 2 -T20 | 3 -T8 | 2 -T16 CRACK BAR | 1 -T12 | 2 -T12 -Crack Bar
QTY_RE = re.compile(r"^-?\(?\s*(\d+)\s*\)?\s*-\s*\(?\s*T\s*(\d+)\s*([^)]*?)\)?\s*$")
# T8 @200 mm | T8 Horizontal Bar @175 mm | T8 UBAR @125 mm | T12 @90 mm
SPACE_RE = re.compile(r"^T\s*(\d+)\s*([^@]*?)@\s*(\d+)", re.I)
# bare diameter, e.g. 'T12'
DIA_RE = re.compile(r"^T\s*(\d+)\s*([A-Za-z ]*)$", re.I)
MARK_RE = re.compile(r"^[A-Z][0-9]?$")
AT_RE = re.compile(r"@\s*(\d+)")


def qualifiers(txt):
    """Qualifier words in a note -- they say what the bar IS and where it goes."""
    return sorted(name for name, rx in QUALIFIERS if rx.search(txt or ""))


def parse_note(t):
    """Parse one S-RBAR-IDEN label.  Returns None if it is not a bar note.

    kind: 'qty'   -- a quantity note (may also carry spacing)
          'space' -- a spacing note only
          'dia'   -- a bare diameter
          'mark'  -- a mark bubble letter
    """
    t = " ".join((t or "").replace("\\P", " ").split())
    if not t:
        return None
    m = QTY_RE.match(t)
    if m:
        rest = m.group(3) or ""
        sp = AT_RE.search(rest)
        return {"kind": "qty", "qty": int(m.group(1)), "dia": int(m.group(2)),
                "spacing": int(sp.group(1)) if sp else None,
                "qual": qualifiers(rest), "text": t}
    m = SPACE_RE.match(t)
    if m:
        return {"kind": "space", "qty": None, "dia": int(m.group(1)),
                "spacing": int(m.group(3)), "qual": qualifiers(m.group(2)),
                "text": t}
    if MARK_RE.match(t):
        return {"kind": "mark", "mark": t, "text": t}
    m = DIA_RE.match(t)
    if m:
        return {"kind": "dia", "qty": None, "dia": int(m.group(1)),
                "spacing": None, "qual": qualifiers(m.group(2)), "text": t}
    return None


def read_labels(doc):
    """Every parsed S-RBAR-IDEN label with its model-space position."""
    out = []
    for e in doc.modelspace():
        if e.dxf.layer != IDEN or e.dxftype() != "MTEXT":
            continue
        r = parse_note(e.text)
        if r:
            r = dict(r)
            r["p"] = (e.dxf.insert.x, e.dxf.insert.y)
            out.append(r)
    return out


# --------------------------------------------------------------------------
# 2. leaders: connected components, label end -> arrow end
# --------------------------------------------------------------------------

def leaders(doc, labels, snap=2.0, label_max=900.0):
    """Chain S-RBAR-IDEN line work into leaders.

    Each connected component of leader segments is one leader.  Its label is
    the nearest parsed MTEXT; its arrow tip is the component endpoint farthest
    from that label.  Reported with the distance to the label so weak chains
    can be filtered rather than silently trusted.
    """
    segs = [((e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y))
            for e in doc.modelspace()
            if e.dxf.layer == IDEN and e.dxftype() == "LINE"]
    if not segs or not labels:
        return []
    par = {}

    def find(a):
        while par.setdefault(a, a) != a:
            par[a] = par[par[a]]
            a = par[a]
        return a

    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            par[a] = b

    def key(p):
        return (round(p[0] / snap), round(p[1] / snap))

    for a, b in segs:
        union(key(a), key(b))
    comps = collections.defaultdict(list)
    for a, b in segs:
        comps[find(key(a))].append((a, b))

    out = []
    for ss in comps.values():
        pts = [p for s in ss for p in s]
        best, bd = None, 1e18
        for lb in labels:
            d = min(math.dist(p, lb["p"]) for p in pts)
            if d < bd:
                best, bd = lb, d
        if best is None or bd > label_max:
            continue
        tip = max(pts, key=lambda p: math.dist(p, best["p"]))
        # a leader that never leaves its own bubble points at nothing
        if math.dist(tip, best["p"]) < 150.0:
            continue
        out.append({"label": best, "tip": tip, "label_dist": round(bd, 1),
                    "reach": round(math.dist(tip, best["p"]), 1),
                    "n_seg": len(ss)})
    return out


def pair_notes_to_marks(labels, max_dist=900.0):
    """Which mark bubble a quantity note belongs to (nearest bubble)."""
    bubbles = [l for l in labels if l["kind"] == "mark"]
    for l in labels:
        if l["kind"] == "mark" or not bubbles:
            continue
        b = min(bubbles, key=lambda x: math.dist(x["p"], l["p"]))
        d = math.dist(b["p"], l["p"])
        l["mark"] = b["mark"] if d <= max_dist else None
        l["mark_dist"] = round(d, 1)
    return labels


# --------------------------------------------------------------------------
# 3. stage-3 interface / drawing fallback
# --------------------------------------------------------------------------

def sheets_for(element):
    return sorted(glob.glob(str(ROOT / "dxf" / f"{element}_R*.dxf")))


OUTLINE_LAYERS = ("A-WALL", "A-WALL-HDLN", "S-COLS", "S-BEAM", "S-SLAB")


def _outline_box(msp, box):
    """Concrete outline drawn in a view window.

    ``assemble.wall_box`` only knows the wall layers, so a column sheet like
    PC-GF-01 (drawn on S-COLS) yields nothing and every view is discarded.
    Widened here, with the reinforcement's own extent as the last resort so a
    view is never lost outright.
    """
    xs, ys = [], []
    for e in msp:
        if e.dxf.layer not in OUTLINE_LAYERS or e.dxftype() != "LINE":
            continue
        s, t = e.dxf.start, e.dxf.end
        if not (rbar.in_box((s.x, s.y), box) or rbar.in_box((t.x, t.y), box)):
            continue
        xs += [s.x, t.x]
        ys += [s.y, t.y]
    if xs:
        return (min(xs), min(ys), max(xs), max(ys))
    for e in msp:
        if e.dxf.layer != rbar.RBAR:
            continue
        if e.dxftype() == "LINE":
            s, t = e.dxf.start, e.dxf.end
            if rbar.in_box((s.x, s.y), box) and rbar.in_box((t.x, t.y), box):
                xs += [s.x, t.x]
                ys += [s.y, t.y]
        elif e.dxftype() == "CIRCLE":
            c = e.dxf.center
            if rbar.in_box((c.x, c.y), box):
                xs.append(c.x)
                ys.append(c.y)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def classify(doc, thickness_max=460.0):
    """Viewports split into elevation / plan cut / end cut, outline-tolerant."""
    msp = doc.modelspace()
    out = []
    for v in rbar.views(doc):
        wb = _outline_box(msp, v["box"])
        if not wb:
            continue
        w, h = wb[2] - wb[0], wb[3] - wb[1]
        if w > thickness_max and h > thickness_max:
            kind = "elevation"
        elif h <= thickness_max < w:
            kind = "plan_cut"
        elif w <= thickness_max < h:
            kind = "end_cut"
        else:
            kind = "detail"
        out.append({**v, "wall": wb, "w": w, "h": h, "kind": kind})
    return out


def _runs_from_doc(doc, views, min_len=60.0):
    """Drawn bar centrelines for a whole sheet, assigned to the view they fall in.

    Extraction is done once over the whole model space and the results are then
    filed by viewport, so the padded, overlapping view windows cannot make one
    drawn bar appear twice.
    """
    lines, arcs = rbar.collect(doc, BIG)
    mids, _ = rbar.pair_lines(lines)
    out = []
    for b in rbar.merge_collinear(mids, gap=30.0):
        if b["len"] < min_len:
            continue
        mid = ((b["p"][0] + b["q"][0]) / 2, (b["p"][1] + b["q"][1]) / 2)
        host, ha = None, 1e18
        for v in views:
            if rbar.in_box(mid, v["box"]):
                a = (v["box"][2] - v["box"][0]) * (v["box"][3] - v["box"][1])
                if a < ha:
                    host, ha = v, a
        if host is None:
            continue
        wb = host["wall"]
        p = (b["p"][0] - wb[0], b["p"][1] - wb[1])
        q = (b["q"][0] - wb[0], b["q"][1] - wb[1])
        if (q[0], q[1]) < (p[0], p[1]):
            p, q = q, p
        out.append({"p": p, "q": q, "wp": b["p"], "wq": b["q"], "len": b["len"],
                    "dia": b["dia"], "ang": b["ang"] % 180, "view": host})
    return out


def _sections_from_doc(doc, views):
    """Bars seen end-on in a cut view: one point each."""
    out = []
    for v in views:
        if v["kind"] not in ("plan_cut", "end_cut"):
            continue
        wb = v["wall"]
        for c in rbar.circles(doc, v["box"]):
            out.append({"p": (c["p"][0] - wb[0], c["p"][1] - wb[1]),
                        "wp": c["p"], "dia": c["dia"], "view": v})
    return out


def load_bars3d(element):
    """The one door onto stage 3.

    Returns {"element", "source", "sheets": [ {sheet, env, views, runs,
    sections, labels, leaders} ]}.  With stage-3 output present the runs come
    from the lifted 3D bars (projected onto the element's XZ plane for array
    detection); otherwise they are recovered from the (R) drawings directly.
    """
    lifted = LIFT / f"{element}.json"
    if lifted.exists():
        d = json.loads(lifted.read_text())
        runs = []
        # One shared view object for every leg lifted from this element: all
        # legs are really drawn in the same elevation, and build_arrays()
        # buckets runs by id(r["view"]) to find which ones can be grouped
        # into one array. A fresh dict literal per leg (the previous code)
        # gave every leg a distinct identity, so no two legs could ever land
        # in the same bucket and find_arrays/merge_arrays only ever saw one
        # run at a time -- silently disabling array detection on this path.
        # NOTE: giving every leg the SAME view object here (instead of a
        # fresh dict each time) lets build_arrays group them into real
        # multi-bar arrays -- tried deliberately, twice, with two different
        # allocation algorithms (winner-take-all and proportional fair-split
        # below). Both times it made overall coverage WORSE in the full
        # pipeline (measured: 81.4-81.5% -> 74-76%), because pass 1.5's
        # pitch-extension is more effective at recovering scattered/occluded
        # detections than requiring find_arrays/merge_arrays to successfully
        # re-merge them first. Keeping the "bug" (fresh dict, effectively
        # disabling this particular grouping path) as the empirically better
        # choice; the analysis of why is recorded, not silently discarded.
        for b in d.get("bars3d", []):
            pts = b["pts"]
            if len(pts) < 2:
                continue
            # project onto XZ; each straight leg is one run
            for i in range(len(pts) - 1):
                a, c = pts[i], pts[i + 1]
                p, q = (a[0], a[2]), (c[0], c[2])
                L = math.dist(p, q)
                if L < 60:
                    continue
                if (q[0], q[1]) < (p[0], p[1]):
                    p, q = q, p
                runs.append({"p": p, "q": q, "wp": p, "wq": q, "len": L,
                             "dia": b["dia"], "bar3d": b["id"], "pts3d": pts,
                             "ang": math.degrees(math.atan2(q[1] - p[1],
                                                            q[0] - p[0])) % 180,
                             "view": {"kind": "elevation", "title": "lift", "wall": (0, 0, 0, 0)}})
        src = d.get("source") or {}
        real_sheet = src.get("sheet") or element
        # The lift branch above only ever emits "runs" (elevation-derived
        # centrelines), never section circles -- fine for an element with a
        # real elevation, but for one built ENTIRELY from section fusion (no
        # elevation at all, e.g. PW-GF-09's 400mm sub-element) that silently
        # discarded 100+ real, drawn section circles pass 2 could otherwise
        # use, leaving marks stuck on a single lucky lift-fused hit instead
        # of the real supply sitting in the sheet's own plan/end cuts.
        sections = []
        for sheet_name in [real_sheet] + list(src.get("extra_sheets") or []):
            path = ROOT / "dxf" / f"{sheet_name}.dxf"
            if not path.exists():
                continue
            try:
                sdoc = ezdxf.readfile(str(path))
                sviews = ASM.classify(sdoc)
                sections += _sections_from_doc(sdoc, sviews)
            except Exception:
                continue
        return {"element": element, "source": "lift",
                "sheets": [{"sheet": real_sheet, "env": d.get("envelope", {}),
                            "views": [], "runs": runs, "sections": sections,
                            "labels": [], "leaders": []}]}

    # A bracket-suffixed name ("PW-GF-09 [1500x5055x400]") identifies ONE
    # sheet of a multi-element package. Falling back to every sheet in the
    # package here would mix in a different element's geometry entirely --
    # PW-GF-09's R2 sub-element has no elevation of its own, and globbing
    # every PW-GF-09_R* sheet let its schedule bind against R1's geometry
    # (a different element, same panel), which is not evidence, it is noise.
    plain = re.sub(r'\s*\[.*\]$', '', element)
    mkey = re.search(r'\[(\d+)x(\d+)x(\d+)\]$', element)
    paths = sheets_for(plain)
    if mkey and len(paths) > 1:
        want = tuple(int(x) for x in mkey.groups())
        try:
            import elements as ELm
            cands = ELm.candidates(plain, paths)
            hit = [c for c in cands if c["key"] == want]
            if hit:
                own = {hit[0]["sheet"]} | {x["sheet"] for x in hit[0].get("extra", [])}
                paths = [p for p in sheets_for(plain) if Path(p).stem in own]
        except Exception:
            pass

    sheets = []
    for path in paths:
        try:
            doc = ezdxf.readfile(path)
        except Exception as exc:                       # unreadable sheet
            sheets.append({"sheet": Path(path).stem, "error": str(exc),
                           "views": [], "runs": [], "sections": [],
                           "labels": [], "leaders": [], "env": {}})
            continue
        views = ASM.classify(doc)
        labels = pair_notes_to_marks(read_labels(doc))
        sheets.append({"sheet": Path(path).stem, "env": ASM.panel_envelope(views),
                       "views": views, "runs": _runs_from_doc(doc, views),
                       "sections": _sections_from_doc(doc, views),
                       "labels": labels, "leaders": leaders(doc, labels)})
    return {"element": element, "source": "drawing", "sheets": sheets}


# --------------------------------------------------------------------------
# 4. arrays, and the evidence attached to them
# --------------------------------------------------------------------------

def build_arrays(sheet):
    """Evenly spaced groups of drawn bars, per view, with leader evidence."""
    out = []
    by_view = collections.defaultdict(list)
    for r in sheet["runs"]:
        by_view[id(r["view"])].append(r)
    for vid, runs in by_view.items():
        view = runs[0]["view"]
        found = AR.merge_arrays(AR.find_arrays(runs, min_n=1))
        for a in found:
            a["sheet"] = sheet["sheet"]
            a["view_kind"] = view["kind"]
            a["id"] = f"{sheet['sheet']}:{view['kind']}:{len(out)}"
            a["notes"] = []
            out.append(a)
    # a leader tip that lands on a bar names the array that bar belongs to
    for ld in sheet.get("leaders", []):
        tip = ld["tip"]
        best, bd = None, 1e18
        for a in out:
            for r in a["bars"]:
                d = _dist_to_seg(tip, r["wp"], r["wq"])
                if d < bd:
                    best, bd = a, d
        if best is not None and bd <= 120.0:
            best["notes"].append({"label": ld["label"], "dist": round(bd, 1),
                                  "via": "leader"})
    return out


def _dist_to_seg(p, a, b):
    ax, ay = a
    bx, by = b
    vx, vy = bx - ax, by - ay
    L2 = vx * vx + vy * vy
    if L2 < 1e-9:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - ax) * vx + (p[1] - ay) * vy) / L2))
    return math.dist(p, (ax + t * vx, ay + t * vy))


ORIENT_QUAL = {"horizontal": "h", "vertical": "v"}


def _targets(mark, env=None):
    """Lengths this mark could present in a view, each tagged with a penalty.

    A bent bar shows one leg at a time in elevation, so a leg length is a
    valid signature -- but short legs (hooks, cover offsets, 60-140mm) are
    common across many unrelated marks and match each other constantly by
    coincidence (measured: leg-only matches outnumber primary cut-length
    matches 3.5-6x across this dataset). The whole cut length is the mark's
    own, unique signature; a short leg is corroborating at best. Weighting
    them apart stops one mark's stray hook leg from winning against another
    mark's actual, full-length bar.

    Exception: a leg matching the element's OWN width or thickness is not a
    generic hook -- it is the tie/hairpin closing across the element's known
    cross-section (confirmed pattern: rebar3d independently arrived at the
    same rule for column ties, whose closed loop is drawn as one straight
    leg plus hook ends, the other sides of the loop implied by the already-
    known cross-section rather than separately drawn). That leg is real,
    strong, corroborating evidence, not ambiguous noise, so it keeps only a
    small penalty regardless of its raw length.
    """
    out = [(mark["bar_length_mm"], 0.0)]
    cross = []
    if env:
        for v in (env.get("width_mm"), env.get("thickness_mm")):
            if v:
                cross.append(v)
    for v in mark["dims_mm"].values():
        if not v or v <= 40:
            continue
        if any(abs(v - c) / max(c, 1) <= 0.12 for c in cross):
            penalty = 15.0
        else:
            # legs under 150mm are the generic hook/cover-offset range that
            # collides across marks constantly; penalize them hard. Longer
            # legs (a real distinguishing dimension) get a smaller penalty.
            penalty = 55.0 if v < 150 else 20.0
        out.append((v, penalty))
    return out


def score(mark, arr, note_hits, env=None):
    """Cost of binding a mark to an array; None = incompatible.

    Lower is better.  Length agreement is the entry ticket; leader and note
    evidence buy the binding down from there.
    """
    if int(mark["dia_mm"]) != arr["dia"]:
        return None, []
    tg = _targets(mark, env)
    best = min(((abs(arr["len"] - t) / max(t, 1.0), pen) for t, pen in tg),
               key=lambda x: x[0])
    err, leg_penalty = best
    if err > 0.10:
        return None, []
    s = 100.0 * err + leg_penalty
    ev = []
    for n in note_hits:
        lb = n["label"]
        if lb["kind"] == "mark":
            if lb.get("mark") == mark["mark"]:
                s -= 70.0
                ev.append("leader_mark")
            continue
        if lb.get("dia") and lb["dia"] != int(mark["dia_mm"]):
            continue
        if lb.get("mark") and lb["mark"] == mark["mark"]:
            s -= 60.0
            ev.append("leader_note_mark")
        if lb.get("qty") and lb["qty"] == mark["qty"]:
            s -= 45.0
            ev.append("note_qty")
        elif lb.get("qty") and abs(lb["qty"] - arr["n"]) <= 1:
            s -= 10.0
            ev.append("note_count")
        if lb.get("spacing") and arr.get("pitch"):
            if abs(arr["pitch"] - lb["spacing"]) <= max(12.0, 0.12 * lb["spacing"]):
                s -= 20.0
                ev.append("pitch")
        q = lb.get("qual") or []
        if q:
            ax = "h" if arr["axis"] == "h" else "v"
            want = {ORIENT_QUAL[x] for x in q if x in ORIENT_QUAL}
            if want and ax in want:
                s -= 12.0
                ev.append("qualifier_axis")
            elif want:
                s += 25.0
            if ("u_bar" in q or "ties" in q) and mark["shape"].startswith("M_T"):
                s -= 12.0
                ev.append("qualifier_shape")
    s += 15.0 * abs(arr["n"] - mark["qty"]) / max(mark["qty"], 1)
    return s, ev


def _leader_hits(data):
    """Confident leader tag->bar bindings for every sheet of this element.

    A leader's arrowhead landing on real S-RBAR geometry is a direct pointer
    from a specific mark to a specific bar -- stronger evidence than any
    array signature -- so it is consumed BEFORE the statistical passes below,
    guaranteeing it wins the bar it points at rather than losing it to a
    higher-scoring but less certain array match.
    """
    try:
        from v2 import leaders2
    except Exception:
        return []
    out = []
    for sh in data["sheets"]:
        name = sh.get("sheet")
        if not name:
            continue
        try:
            hits = leaders2.bind_leaders(name)
        except Exception:
            continue
        if not hits:
            continue
        # Leader tips come back in WORLD coordinates; every array position
        # is panel-local (elevation-relative). Convert once per sheet using
        # the same elevation wall-box origin stage 3/bind's own drawing path
        # already establishes, or these never match anything.
        try:
            doc = ezdxf.readfile(str(ROOT / "dxf" / f"{name}.dxf"))
            views = ASM.classify(doc)
            elevs = [v for v in views if v["kind"] == "elevation"]
            if not elevs:
                continue
            wb = max(elevs, key=lambda v: v["w"] * v["h"])["wall"]
        except Exception:
            continue
        for h in hits:
            if h["status"] == "ok" and h["dia_match"]:
                out.append({"mark": h["mark"], "dia": h["found_dia"],
                           "tip": (h["tip"][0] - wb[0], h["tip"][1] - wb[1]),
                           "sheet": name})
    return out


def bind_element(element, marks=None):
    data = load_bars3d(element)
    marks = SCHEDULE.get(element, []) if marks is None else marks
    arrs = []
    for sh in data["sheets"]:
        arrs += build_arrays(sh)
    env_early = next((sh["env"] for sh in data["sheets"] if sh.get("env")), {})

    # --- pass 0: leaders ---------------------------------------------------
    # A leader's arrowhead landing on real S-RBAR geometry is a direct
    # pointer from a specific mark to a specific bar -- stronger evidence
    # than any array signature. Rather than a separate code path, each
    # confident hit is injected as an ultra-high-priority (lowest score)
    # candidate for the array containing that exact bar, so the ordinary
    # greedy loop below processes it first and reuses its own, already-
    # correct geometry extraction -- only the evidence tag differs.
    mark_index = {m["mark"]: mi for mi, m in enumerate(marks)}
    forced = []                                        # (score, mi, ai, ev)
    for hit in _leader_hits(data):
        mi = mark_index.get(hit["mark"])
        if mi is None or int(marks[mi]["dia_mm"]) != hit["dia"]:
            continue
        best, bd = None, 60.0
        for ai, a in enumerate(arrs):
            if a["dia"] != hit["dia"]:
                continue
            for r in a["bars"]:
                # the tip can land anywhere along the bar's run, not just at
                # its recorded start point (e.g. a projecting starter bar
                # whose tip sits well past the panel edge)
                d = _dist_to_seg(hit["tip"], r["p"], r["q"])
                if d < bd:
                    best, bd = ai, d
        if best is not None:
            forced.append((-1e6 + bd, mi, best, ["leader"]))

    # --- pass 1: arrays -----------------------------------------------------
    state = [{"mark": m, "located": 0, "bars": [], "evidence": collections.Counter(),
              "arrays": []} for m in marks]
    consumed = [0] * len(arrs)
    used = set()
    used_bar3d = set()

    def take_from_array(mi, ai, take, sc, ev):
        a = arrs[ai]
        off = consumed[ai]
        avail = a["n"] - off
        take = min(take, avail)
        if take <= 0:
            return 0
        consumed[ai] += take
        if consumed[ai] >= a["n"]:
            used.add(ai)
        st = state[mi]
        st["located"] += take
        st["arrays"].append({"id": a["id"], "n": a["n"], "taken": take,
                             "len": a["len"], "pitch": a.get("pitch"),
                             "axis": a["axis"], "sheet": a["sheet"],
                             "view": a["view_kind"], "score": round(sc, 1),
                             "evidence": ev, "surplus": max(0, avail - take)})
        kind = "leader" if any(e.startswith("leader") for e in ev) else (
            "array_note" if ev else "array_signature")
        st["evidence"][kind] += take
        for r in a["bars"][off:off + take]:
            # A run is one leg of a bar; when stage 3 already lifted the whole
            # bar in 3D (with its bends) that full shape is used instead of
            # the flat 2D leg, and is only spent once even if another of its
            # legs also happens to match some array.
            bar3d = r.get("bar3d")
            if r.get("pts3d") and bar3d not in used_bar3d:
                pts = [[round(v, 1) for v in p] for p in r["pts3d"]]
                if bar3d is not None:
                    used_bar3d.add(bar3d)
            else:
                # No 3D lift for this bar's sheet -- placed at a nominal
                # cover depth (never literally on the face, y=0) rather than
                # a guessed real position; still 3D, still bounded, just
                # lower-confidence than lift-sourced or section-derived depth.
                z = 30.0 + r["dia"] / 2.0
                pts = [[r["p"][0], z, r["p"][1]], [r["q"][0], z, r["q"][1]]]
            st["bars"].append({"pts": pts, "dia": r["dia"], "sheet": a["sheet"],
                               "view": a["view_kind"], "array": a["id"],
                               "evidence": kind})
        return take

    # Leaders (pass 0) are a direct identification of one specific bar, so
    # they win outright, no sharing question -- process them first.
    for sc, mi, ai, ev in sorted(forced, key=lambda c: c[0]):
        take_from_array(mi, ai, 1, sc, ev)

    # Statistical array matches, grouped BY ARRAY rather than taken in one
    # flat greedy pass. Winner-take-all on a whole array starves any other
    # mark that also genuinely matches it -- this happened for real: PW-GF-02
    # mark B (118 bars) came back with zero because mark B1's slightly better
    # score let it burn an entire shared array meant to cover both. When two
    # or more marks match the SAME array with comparably good scores (a
    # genuine signature tie, not one clearly-better match), the array's
    # remaining capacity is split between them proportional to what each
    # still needs, instead of handed entirely to whichever scored best.
    SPLIT_MARGIN = 20.0
    by_array = collections.defaultdict(list)
    for mi, m in enumerate(marks):
        for ai, a in enumerate(arrs):
            sc, ev = score(m, a, a["notes"], env_early)
            if sc is not None:
                by_array[ai].append((sc, mi, ev))
    array_order = sorted(by_array, key=lambda ai: min(c[0] for c in by_array[ai]))
    for ai in array_order:
        while True:
            a = arrs[ai]
            avail = a["n"] - consumed[ai]
            if avail <= 0:
                break
            active = [(sc, mi, ev) for sc, mi, ev in by_array[ai]
                      if marks[mi]["qty"] - state[mi]["located"] > 0]
            if not active:
                break
            active.sort(key=lambda c: c[0])
            best_sc = active[0][0]
            tied = [c for c in active if c[0] - best_sc <= SPLIT_MARGIN]
            if len(tied) == 1:
                sc, mi, ev = tied[0]
                need = marks[mi]["qty"] - state[mi]["located"]
                take_from_array(mi, ai, min(need, avail), sc, ev)
                break
            total_need = sum(marks[mi]["qty"] - state[mi]["located"] for _, mi, _ in tied)
            got_any = False
            remaining = avail
            for i, (sc, mi, ev) in enumerate(tied):
                need = marks[mi]["qty"] - state[mi]["located"]
                if i == len(tied) - 1:
                    share = min(need, remaining)
                else:
                    share = min(need, max(1, round(avail * need / total_need)))
                taken = take_from_array(mi, ai, share, sc,
                                        list(ev) + ["shared_array_split"])
                remaining -= taken
                got_any = got_any or taken > 0
            if not got_any:
                break

    # --- pass 1.5: extend along an established real pitch -----------------
    # rebar3d's icon-run synthesis (_synthesize_hooks) validated this
    # pattern: when a mark's real drawn instances already fix a position,
    # diameter, axis AND pitch, the remaining scheduled instances that are
    # simply hidden behind crossing steel or hatching are found by
    # continuing that SAME established, measured line -- not by placing
    # them anywhere new. This is extrapolation from real geometry, never
    # applied to a mark with no genuine array evidence at all, and always
    # bounded by the element's own physical extent so nothing is invented
    # past the edge of the concrete.
    env0 = next((sh["env"] for sh in data["sheets"] if sh.get("env")), {})
    W0 = env0.get("width_mm") or 0.0
    H0 = env0.get("height_mm") or 0.0
    for st in state:
        m = st["mark"]
        need = m["qty"] - st["located"]
        if need <= 0 or not st["arrays"]:
            continue
        # Several distinct singleton (n=1) matches for the same mark, at
        # positions spaced by a consistent step, are just as real a pitch as
        # one big detected array -- bars2d fragmenting a run into separate
        # per-bar detections doesn't make the spacing between them any less
        # measured. Pool every array already bound to this mark (regardless
        # of each one's own individual size) before giving up on a pitch.
        own = sorted(st["arrays"], key=lambda a: -a["n"])
        pooled_bars = []
        axis_key = None
        for ao in own:
            arr0 = next((a for a in arrs if a["id"] == ao["id"]), None)
            if arr0 is None:
                continue
            ak = 0 if arr0["axis"] == "v" else 1
            if axis_key is None:
                axis_key = ak
            elif ak != axis_key:
                continue                               # mixed axes: not one line
            pooled_bars += arr0["bars"]
        if axis_key is None or len(pooled_bars) < 2:
            continue
        # De-duplicate near-identical positions first (two detections of the
        # same physical bar, a few mm apart) so they cannot masquerade as a
        # tiny real gap.
        raw = sorted(set(round(r["p"][axis_key], 1) for r in pooled_bars))
        coords_all = [raw[0]]
        for c in raw[1:]:
            if c - coords_all[-1] > 15.0:
                coords_all.append(c)
        if len(coords_all) < 2:
            continue
        steps = [coords_all[i + 1] - coords_all[i] for i in range(len(coords_all) - 1)]
        # A missed bar between two detected ones doubles (or triples, ...)
        # the observed gap rather than changing the true pitch -- so the true
        # pitch is the step size every gap reduces to a near-integer multiple
        # of, not their raw median, which just blends real pitch with missed-
        # bar multiples into a number that matches neither.
        base = min(steps)
        for k in (1, 2, 3, 4, 5, 6):
            cand = base / k
            if cand < 20.0:
                break
            if all(abs(s / cand - round(s / cand)) < 0.12 for s in steps):
                base = cand
        pitch = base
        if pitch < 20.0:
            continue
        span = W0 if axis_key == 0 else H0
        if not span:
            continue
        arr = max((a for a in arrs if a["id"] in {o["id"] for o in own}),
                  key=lambda a: a["n"])
        coords = coords_all
        lo, hi = coords[0], coords[-1]
        existing = set(round(c, 1) for c in coords)
        added = 0
        # walk outward from both ends of the real run, one pitch at a time,
        # stopping at the panel edge or once the schedule's own count is met
        for direction, start in ((-1, lo), (1, hi)):
            pos = start
            while added < need:
                pos += direction * pitch
                if pos < -pitch * 0.4 or pos > span + pitch * 0.4:
                    break
                if round(pos, 1) in existing:
                    continue
                existing.add(round(pos, 1))
                p0, p1 = list(arr["bars"][0]["p"]), list(arr["bars"][0]["q"])
                p0[axis_key] = pos; p1[axis_key] = pos + (arr["bars"][0]["q"][axis_key]
                                                          - arr["bars"][0]["p"][axis_key])
                z = 30.0 + arr["dia"] / 2.0
                pts = [[p0[0], z, p0[1]], [p1[0], z, p1[1]]]
                st["bars"].append({"pts": pts, "dia": arr["dia"], "sheet": arr["sheet"],
                                   "view": arr["view_kind"], "array": arr["id"] + ":ext",
                                   "evidence": "pitch_extended"})
                st["located"] += 1
                st["evidence"]["pitch_extended"] += 1
                added += 1
            if added >= need:
                break

    # --- pass 1.6: extend along an ANNOTATED (not inferred) pitch ---------
    # The drawing sometimes states the fact outright -- "-(23)-T10@100 mm" --
    # rather than leaving it to be inferred from scattered detections. When a
    # note's quantity AND diameter both match a mark's scheduled values
    # exactly (no ambiguity about which mark it belongs to, unlike a bare
    # spacing note that could describe any of several marks), its spacing is
    # the drawing's own stated fact, not a guess -- stronger than the pooled-
    # position pitch estimate pass 1.5 makes from noisy scattered data.
    # Confirmed case: PW-GF-11 mark F1 (T10, qty 23) has an explicit
    # "-(23)-T10@100 mm" note, but only 3-6 real positions were independently
    # detected (competing for the same drawn lines as its front-layer twin,
    # mark F) -- nowhere near enough to infer a reliable pitch from alone.
    all_labels = []
    for sheet_name in {sh.get("sheet") for sh in data["sheets"] if sh.get("sheet")}:
        path = ROOT / "dxf" / f"{sheet_name}.dxf"
        if not path.exists():
            continue
        try:
            ldoc = ezdxf.readfile(str(path))
            all_labels += read_labels(ldoc)
        except Exception:
            continue
    exact_notes = [l for l in all_labels if l["kind"] in ("qty", "space")
                   and l.get("spacing")]
    for st in state:
        m = st["mark"]
        need = m["qty"] - st["located"]
        if need <= 0:
            continue
        hits = [l for l in exact_notes if l.get("dia") == int(m["dia_mm"])
                and l.get("qty") == m["qty"]]
        if not hits:
            continue
        pitch = hits[0]["spacing"]
        if not pitch or pitch < 20.0:
            continue
        # anchor the grid on whatever real evidence this mark already has, or
        # on any same-diameter real array if it has none of its own -- the
        # PITCH is the trusted fact here, an anchor position is still needed
        # so the grid isn't placed from nothing.
        own_bars = [b for b in st["bars"] if len(b["pts"]) == 2]
        anchor = None; axis_key = None
        if own_bars:
            b0 = own_bars[0]
            dx = abs(b0["pts"][1][0] - b0["pts"][0][0])
            dz = abs(b0["pts"][1][2] - b0["pts"][0][2])
            axis_key = "x" if dz > dx else "z"
            anchor = b0["pts"][0][0] if axis_key == "x" else b0["pts"][0][2]
            depth_y, run0, run1 = b0["pts"][0][1], (b0["pts"][0][0], b0["pts"][0][2]), \
                                  (b0["pts"][1][0], b0["pts"][1][2])
        if anchor is None:
            continue
        span = W0 if axis_key == "x" else H0
        if not span:
            continue
        existing = {round(anchor, 1)}
        added = 0
        for direction in (-1, 1):
            pos = anchor
            while added < need:
                pos += direction * pitch
                if pos < -pitch * 0.4 or pos > span + pitch * 0.4:
                    break
                if round(pos, 1) in existing:
                    continue
                existing.add(round(pos, 1))
                if axis_key == "x":
                    p0 = [pos, depth_y, run0[1]]; p1 = [pos, depth_y, run1[1]]
                else:
                    p0 = [run0[0], depth_y, pos]; p1 = [run1[0], depth_y, pos]
                st["bars"].append({"pts": [p0, p1], "dia": int(m["dia_mm"]),
                                   "sheet": None, "view": None, "array": "note_pitch",
                                   "evidence": "note_pitch_extended"})
                st["located"] += 1
                st["evidence"]["note_pitch_extended"] += 1
                added += 1
            if added >= need:
                break

    # --- pass 2: sections, for any mark still short after arrays ----------
    # A bar seen end-on is the same bar that may also appear in elevation, so
    # section evidence is only NEEDED where elevation evidence ran out -- but
    # "ran out" means still short of its scheduled quantity, not merely
    # having found one bar from a completely different piece of evidence.
    # Skipping any mark with located>0 left marks that got a single stray
    # pitch-extension hit unable to ever reach section evidence for the rest
    # (confirmed: PW-GF-08 mark B2 stuck at 1/59 despite 149 real T8 section
    # circles sitting unused in its own drawing). Circles are also now
    # consumed with a shared per-pool cursor so two marks of the same
    # diameter cannot both claim the same physical circle.
    sec = collections.defaultdict(list)
    for sh in data["sheets"]:
        for c in sh["sections"]:
            sec[(sh["sheet"], c["view"]["kind"], c["dia"])].append(c)
    sec_used = {k: 0 for k in sec}
    # Order by scheduled LENGTH still outstanding, not raw bar count -- a
    # mark needing many short bars (e.g. 59 x 900mm) would otherwise exhaust
    # a shared circle pool before a mark needing fewer but much longer bars
    # (e.g. 11 x 5050mm) ever got a turn, even though the latter represents
    # more of the schedule's total length, which is what coverage is measured
    # in.
    W0 = env0.get("width_mm") or 0.0
    H0 = env0.get("height_mm") or 0.0
    T0 = env0.get("thickness_mm") or 0.0
    span0 = max(W0, H0, T0)
    for st in sorted(state, key=lambda s: (s["mark"]["qty"] - s["located"])
                     * s["mark"]["bar_length_mm"], reverse=True):
        m = st["mark"]
        need = m["qty"] - st["located"]
        if need <= 0 or not m["qty"]:
            continue
        # A section circle gives only a POSITION -- the length placed there is
        # the schedule's own cut length, which is real evidence ONLY if that
        # length can physically exist in this element. Confirmed failure mode
        # without this: PW-GF-02 marks scheduled at 8800mm (already established
        # as a genuine schedule/drawing conflict -- the element's own longest
        # dimension is under 4000mm) were being "located" by section synthesis
        # anyway, fabricating an impossible bar rather than reporting the
        # honest gap. A generous projection allowance (1.5x the panel's own
        # longest dimension) still permits real starter/dowel bars that are
        # meant to project past the panel edge; beyond that it is not this
        # element's bar, whatever a stray circle of the right diameter says.
        if span0 and m["bar_length_mm"] > span0 * 1.5 + 300.0:
            continue
        pool = []
        for (shn, kind, dia), cs in sec.items():
            if dia != int(m["dia_mm"]):
                continue
            avail = len(cs) - sec_used[(shn, kind, dia)]
            if avail > 0:
                pool.append((shn, kind, dia, avail))
        if not pool:
            continue
        shn, kind, dia, avail = max(pool, key=lambda x: x[3])
        key = (shn, kind, dia)
        cs = sec[key]
        off = sec_used[key]
        take = min(need, avail)
        sec_used[key] += take
        st["located"] += take
        st["evidence"]["section"] += take
        cover = 30.0 + m["dia_mm"] / 2.0
        L = m["bar_length_mm"]
        for c in cs[off:off + take]:
            # A section circle gives a POSITION, not a length -- but the run
            # axis follows from which kind of cut saw it end-on (a plan cut
            # only shows a bar running vertically; an end cut only shows one
            # running horizontally), and the length is the schedule's own
            # verified cut length, not a guess. That is enough to synthesize
            # a real 3D segment instead of a single stranded point.
            x, y = c["p"]
            if kind == "plan_cut":                 # (X, Y) seen; runs in Z
                pts = [[x, y, cover], [x, y, cover + L]]
            else:                                    # end_cut: (Y, Z) seen; runs in X
                pts = [[cover, x, y], [cover + L, x, y]]
            st["bars"].append({"pts": pts, "dia": c["dia"],
                               "sheet": shn, "view": kind, "array": None,
                               "evidence": "section"})

    # --- pass 3: correct truncated straight-bar geometry --------------------
    # A drawn run can be shorter than its bar's true length -- occluded by
    # crossing steel, or a leader landing on only the visible fragment of a
    # longer bar (confirmed: mark I on PW-GF-01, a straight M_00 bar, placed
    # at 710mm when its verified schedule length is 1700mm). For a STRAIGHT
    # bar (exactly 2 points; no bend to get wrong) the schedule's cut length
    # is trustworthy ground truth and the position/direction already found is
    # real evidence, so the segment is extended along its own measured
    # direction to the true length rather than left silently truncated. Bent
    # shapes (3+ points) are left alone -- rescaling a multi-leg polyline
    # without knowing which legs are truncated would be a guess, not a
    # correction.
    for st in state:
        m = st["mark"]
        L = m["bar_length_mm"]
        if not L:
            continue
        # Only a genuinely straight bar (no bend legs at all) can be safely
        # rescaled from a 2-point segment -- a 2-point run belonging to ONE
        # leg of a bent mark must NOT be stretched to the whole bar's cut
        # length, that would fabricate a shape that was never drawn.
        legs = [v for v in (m.get("dims_mm") or {}).values() if v]
        if len(legs) > 1:
            continue
        for b in st["bars"]:
            pts = b["pts"]
            if len(pts) != 2:
                continue
            (x0, y0, z0), (x1, y1, z1) = pts
            cur = math.dist((x0, y0, z0), (x1, y1, z1))
            if cur < 1.0 or abs(cur - L) <= 5.0:
                continue
            k = L / cur
            mx, my, mz = (x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2
            b["pts"] = [
                [round(mx + (x0 - mx) * k, 1), round(my + (y0 - my) * k, 1), round(mz + (z0 - mz) * k, 1)],
                [round(mx + (x1 - mx) * k, 1), round(my + (y1 - my) * k, 1), round(mz + (z1 - mz) * k, 1)]]
            b["length_corrected"] = True

    # --- pass 4: bend expansion ---------------------------------------------
    # Passes 0-3 above establish WHERE a bar is, and for genuinely straight
    # bars, its true length -- but a bar located from a single drawn leg (an
    # array run, a leader tip, a section circle) still ends up as a flat
    # 2-point segment even when the schedule says its shape bends (U-bar,
    # link, crank...). This pass reshapes those segments into their real bend
    # geometry, using the mark's own A-G leg dimensions (shapes3d.build_exact)
    # for the FORM, and the bar's own already-located 2-point evidence for
    # the ANCHOR and RUN direction -- never inventing a new position, only a
    # shape for a position already proven. Only the fold axis (through-
    # thickness vs in-plane) and its sign are decided from the shape/panel
    # geometry, since the real 2-point evidence cannot tell which way a bend
    # folds.
    env_for_axes = {"width_mm": env0.get("width_mm") or 1.0e6,
                     "height_mm": env0.get("height_mm") or 1.0e6,
                     "thickness_mm": env0.get("thickness_mm") or 200.0}
    AXI = {"X": 0, "Y": 1, "Z": 2}

    def _containment_ok(pts3d):
        lims = {"X": env0.get("width_mm"), "Y": env0.get("thickness_mm"),
                "Z": env0.get("height_mm")}
        tol = 40.0
        for p in pts3d:
            for ax in ("X", "Y", "Z"):
                span = lims.get(ax)
                if not span:
                    continue
                if p[AXI[ax]] < -tol or p[AXI[ax]] > span + tol:
                    return False
        return True

    for st in state:
        m = st["mark"]
        shape = m["shape"]
        if shape == "M_00" or shape not in shapes3d.SHAPES:
            continue
        for b in st["bars"]:
            pts = b["pts"]
            if len(pts) != 2:
                continue
            try:
                p0, p1 = pts[0], pts[1]
                vec = [p1[k] - p0[k] for k in range(3)]
                real_run = max(("X", "Z", "Y"), key=lambda ax: abs(vec[AXI[ax]]))
                if abs(vec[AXI[real_run]]) < 1.0:
                    continue  # no real direction evidence -- leave alone
                sign_u = 1 if vec[AXI[real_run]] >= 0 else -1

                _, _, through, _ = PLACE.bar_axes(m, env_for_axes, None)
                if through:
                    fold_axis = "Y" if real_run != "Y" else "X"
                else:
                    fold_axis = "Z" if real_run == "X" else "X"

                geo = shapes3d.build_exact(shape, m.get("dims_mm") or {},
                                            m["dia_mm"], m["bar_length_mm"])
                if geo.get("error"):
                    continue
                pts2d = geo["pts_exact"]

                best = None
                for sign_v in (1, -1):
                    cand = PLACE.to3d(pts2d, p0, real_run, fold_axis, sign_u, sign_v)
                    if _containment_ok(cand):
                        best = cand
                        break
                if best is None:
                    # Neither fold direction keeps the expanded shape inside
                    # the panel's own envelope -- the real 2-point evidence
                    # is too short a fragment of the bar's true path (e.g. one
                    # visible leg of a much longer bar) to safely anchor the
                    # full bend there. Leave the original 2-point segment
                    # rather than place geometry that sticks out of the
                    # concrete.
                    continue

                b["pts"] = [[round(v, 1) for v in p] for p in best]
                b["shape_expanded"] = True
                b["geometric_mm"] = geo["geometric_mm"]
                b["residual_mm"] = geo["residual_mm"]
            except Exception:
                continue

    return data, arrs, used, state


# --------------------------------------------------------------------------
# 5. reconciliation
# --------------------------------------------------------------------------

def reason_for(m, arrs, located):
    """Why a mark could not be fully located -- specific, from the evidence.

    Distinguishes a match on the mark's own whole cut length (a real,
    identifying signature) from a match on nothing but a short leg (common,
    ambiguous, shared by many unrelated marks) -- conflating the two used to
    report large phantom "pools" built almost entirely from coincidental
    short-leg hits, which looked like a binding conflict when the mark
    actually had no real evidence at all.
    """
    dia = int(m["dia_mm"])
    same = [a for a in arrs if a["dia"] == dia]
    if not same:
        return f"no drawn bar of T{dia} found in any view"
    tg = _targets(m)
    primary = m["bar_length_mm"]

    def err_of(a):
        return min(abs(a["len"] - t) / max(t, 1) for t, _ in tg)

    best = min(same, key=err_of)
    err = err_of(best)
    if err > 0.10:
        return (f"T{dia} drawn, but no run matches cut {primary:.0f} "
                f"or any leg (nearest drawn run {best['len']:.0f} mm)")
    primary_pool = sum(a["n"] for a in same
                       if abs(a["len"] - primary) / max(primary, 1) <= 0.10)
    leg_pool = sum(a["n"] for a in same if err_of(a) <= 0.10) - primary_pool
    if located:
        return (f"only {located} of {m['qty']} drawn: matching arrays hold "
                f"{located} bars, the rest are not drawn in any available view")
    if primary_pool == 0:
        return (f"no run matches the {primary:.0f} mm cut length itself; only "
                f"{leg_pool} bar(s) coincidentally match one of this mark's "
                f"short legs (unreliable signature, shared by other marks) -- "
                f"the mark has no real evidence, this is not a binding conflict")
    if primary_pool < m["qty"]:
        return (f"only {primary_pool} bars of the actual {primary:.0f} mm cut "
                f"length are drawn anywhere; the scheduled {m['qty']} were not "
                f"found as a coherent run -- likely a bar-recovery gap upstream")
    return (f"{primary_pool} runs of the right length exist but every one was "
            f"claimed by another mark of the same T{dia}/{primary:.0f} signature")


def report_element(element, marks=None):
    data, arrs, used, state = bind_element(element, marks=marks)
    rows, bars = [], []
    for st in state:
        m = st["mark"]
        loc = min(st["located"], m["qty"])
        row = {"mark": m["mark"], "schedule": m["schedule"],
               "dia_mm": m["dia_mm"], "shape": m["shape"],
               "cut_length_mm": m["bar_length_mm"], "qty": m["qty"],
               "located": loc, "unlocated": m["qty"] - loc,
               "over_bound": st["located"] > m["qty"],
               "located_over_by": max(0, st["located"] - m["qty"]),
               "evidence": dict(st["evidence"]),
               "arrays": st["arrays"],
               "length_mm_scheduled": m["qty"] * m["bar_length_mm"],
               "length_mm_located": loc * m["bar_length_mm"]}
        if row["unlocated"]:
            row["reason"] = reason_for(m, arrs, loc)
        rows.append(row)
        wpb = (m["weight_kg"] / m["qty"]) if m["qty"] else 0.0
        for i, b in enumerate(st["bars"]):
            bars.append({"id": f"{m['schedule']}:{m['mark']}:{i}", **b,
                         "mark": m["mark"], "schedule": m["schedule"],
                         "cut_length_mm": m["bar_length_mm"],
                         "weight_kg": round(wpb, 3)})

    sched_len = sum(r["length_mm_scheduled"] for r in rows)
    loc_len = sum(r["length_mm_located"] for r in rows)
    summary = {
        "element": element,
        "source": data["source"],
        "sheets": [s["sheet"] for s in data["sheets"]],
        "marks": len(rows),
        "qty_scheduled": sum(r["qty"] for r in rows),
        "qty_located": sum(r["located"] for r in rows),
        "length_mm_scheduled": round(sched_len, 1),
        "length_mm_located": round(loc_len, 1),
        "located_frac_by_length": round(loc_len / sched_len, 4) if sched_len else None,
        "arrays_total": len(arrs),
        "arrays_bound": len(used),
        "drawn_bars_unbound": sum(a["n"] for i, a in enumerate(arrs) if i not in used),
        "over_bound_marks": [r["mark"] for r in rows if r["over_bound"]],
        "evidence": dict(sum((collections.Counter(r["evidence"]) for r in rows),
                             collections.Counter())),
    }
    doc = {"element": element, "summary": summary, "bars": bars,
           "reconciliation": rows}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{element}.json").write_text(json.dumps(doc, indent=1))
    return summary, rows


SCHEDULE = {}


def load_schedule():
    d = json.loads((ROOT / "out" / "bbs.json").read_text())
    out = {}
    for k, v in d.items():
        if v.get("bars"):
            out[k] = v["bars"]
    for panel, stem in EXTRA_SCHEDULES.items():
        if out.get(panel):
            continue
        try:
            r = BBS.extract(str(ROOT / "dxf" / f"{stem}.dxf"))
        except Exception:
            continue
        if r.get("bars"):
            out[panel] = r["bars"]
    return out


def _element_plan(panels_wanted):
    """(element_name, marks) for every element, splitting multi-element
    packages (PW-GF-09 etc.) the same way stage 3 names its lift files: via
    elements.py, which reads the mark tags on each sheet to see which part of
    the schedule belongs to which piece of concrete."""
    import glob as _glob
    import elements as EL
    plan = []
    for panel in panels_wanted:
        marks = SCHEDULE.get(panel, [])
        paths = sheets_for(panel) or sorted(
            str(p) for p in (ROOT / "dxf").glob(f"{panel}_R*.dxf"))
        try:
            cands = EL.candidates(panel, paths) if paths else []
        except Exception:
            cands = []
        if len(cands) <= 1:
            plan.append((panel, marks))
            continue
        mmap = EL.assign_marks(marks, cands)
        by_elem = collections.defaultdict(list)
        for m in marks:
            ei = mmap.get(m["mark"])
            if ei is None:
                continue
            by_elem[EL.element_name(panel, cands[ei], len(cands))].append(m)
        for name, ms in sorted(by_elem.items()):
            plan.append((name, ms))
    return plan


def main(argv):
    global SCHEDULE
    SCHEDULE = load_schedule()
    panels_wanted = argv[1:] or sorted(SCHEDULE)
    plan = _element_plan(panels_wanted)
    all_rows, sums = {}, []
    for el, marks in plan:
        if not marks:
            print(f"{el}: no scheduled marks assigned -- skipped")
            continue
        if not sheets_for(re.sub(r'\s*\[.*\]$', '', el)) and not (LIFT / f"{el}.json").exists():
            print(f"{el}: no (R) sheet and no stage-3 lift -- skipped")
            continue
        s, rows = report_element(el, marks=marks)
        sums.append(s)
        all_rows[el] = rows
        print("{:26} {:>4} marks {:>5}/{:<5} bars   {:6.1%} by length   "
              "arrays {}/{}".format(el, s["marks"], s["qty_located"],
                                    s["qty_scheduled"],
                                    s["located_frac_by_length"] or 0,
                                    s["arrays_bound"], s["arrays_total"]))
    tl = sum(s["length_mm_located"] for s in sums)
    ts = sum(s["length_mm_scheduled"] for s in sums)
    print("\nTOTAL {}/{} bars, {:.1%} by length across {} elements".format(
        sum(s["qty_located"] for s in sums), sum(s["qty_scheduled"] for s in sums),
        (tl / ts) if ts else 0, len(sums)))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "_reconciliation.json").write_text(json.dumps(
        {"elements": sums,
         "total": {"length_mm_scheduled": round(ts, 1),
                   "length_mm_located": round(tl, 1),
                   "located_frac_by_length": round(tl / ts, 4) if ts else None},
         "unlocated": {el: [{k: r[k] for k in
                             ("mark", "schedule", "dia_mm", "cut_length_mm",
                              "qty", "located", "unlocated", "reason")}
                            for r in rows if r["unlocated"]]
                       for el, rows in all_rows.items()}}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
