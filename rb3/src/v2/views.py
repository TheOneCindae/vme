"""Stage 3 -- view registration and the 2D->3D lift.

A reinforcement sheet draws one element several times: an elevation, and a
number of section cuts taken through it. Each drawing is a projection of the
same physical steel, so the same bar is drawn more than once -- lengthwise in
the elevation and end-on as a circle in a section. This stage puts every view
into ONE element frame and then FUSES those repeated appearances back into
single 3D bars. Nothing here invents a bar: a bar exists only because a view
drew it, and its position along an axis is only known when a view measured it.

Element frame (millimetres):
    X  across the element width      (elevation horizontal)
    Y  through the thickness         (0 = the face the sections put first)
    Z  up the element height         (elevation vertical)

Registration evidence, in order of authority:
  1. the section marker symbols on G-ANNO-SYMB, which sit on the elevation at
     the exact station of each cut, numbered to match the section's title;
  2. the concrete outline -- the height of concrete at a cut's station must
     equal the height the section draws, which both confirms the marker and
     catches a mis-paired one;
  3. agreement of the bars themselves: a section's X ordinate must line up
     with the elevation's vertical runs, which fixes whether the section was
     drawn in the same sense as the elevation or mirrored.

Reads stage 2 (`out/v2/bars2d/<sheet>.json`) through `load_bars2d`; until that
exists it falls back to the v1 extractors, which read the same DXF geometry.
Writes `out/v2/lift/<element>.json`.
"""
import json, math, re, sys, glob, collections
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import ezdxf
import rbar
import assemble as A
import outline as OUT
import elements as EL

BARS2D_DIR = ROOT / "out" / "v2" / "bars2d"
LIFT_DIR = ROOT / "out" / "v2" / "lift"
DXF_DIR = ROOT / "dxf"

SYMB = "G-ANNO-SYMB"
DIAS = [8, 10, 12, 16, 20, 25, 32]

XTOL = 3.0          # a section ordinate and an elevation run are the same bar
ZTOL = 6.0
COVER = 30.0


# ---------------------------------------------------------------- stage 2 in

def load_bars2d(sheet, doc=None, vlist=None):
    """Drawn 2D bar objects per view, in the sheet's model coordinates.

    Prefers stage 2's JSON. The fallback reproduces the same contract from the
    v1 extractors so this stage can be developed and tested before stage 2
    lands; switching over is a matter of stage 2 writing the file.
    """
    f = BARS2D_DIR / f"{sheet}.json"
    if f.exists():
        d = json.loads(f.read_text())
        return align(d["views"], vlist), "bars2d"
    return align(_bars2d_v1(sheet, doc, vlist), vlist), "v1"


def align(views2d, vlist):
    """Key stage 2's views by this stage's view index.

    Stage 2 names its views however it likes; both stages enumerate the same
    viewports, so match on the model window each view frames and fall back to
    order. This stage's own classification of the view stands -- it is derived
    from the concrete outline, which is the thing that actually decides whether
    a cut is horizontal or vertical.
    """
    out, taken = {}, set()
    for j, v2 in enumerate(views2d):
        b = v2.get("box")
        k = None
        if b:
            best, bd = None, 1e9
            for i, v in enumerate(vlist):
                if i in taken:
                    continue
                d = sum(abs(p - q) for p, q in zip(b, v["box"]))
                if d < bd:
                    best, bd = i, d
            if best is not None and bd < 5.0:
                k = best
        if k is None and j < len(vlist) and j not in taken:
            k = j
        if k is None:
            continue
        taken.add(k)
        out[k] = v2
    return out


def _bars2d_v1(sheet, doc=None, vlist=None):
    if doc is None:
        doc = ezdxf.readfile(str(DXF_DIR / f"{sheet}.dxf"))
    if vlist is None:
        vlist = A.classify(doc)
    out = []
    for i, v in enumerate(vlist):
        bars = []
        lines, _arcs = rbar.collect(doc, v["box"])
        mids, _ = rbar.pair_lines(lines, dias=DIAS)
        for b in rbar.merge_collinear(mids, gap=30.0):
            if b["len"] < 60.0:
                continue
            bars.append({"id": f"{sheet}:{i}:r{len(bars)}", "dia": b["dia"],
                         "pts": [list(b["p"]), list(b["q"])], "closed": False,
                         "kind": "run", "len": round(b["len"], 1),
                         "evidence": "paired_edges"})
        for c in rbar.circles(doc, v["box"]):
            bars.append({"id": f"{sheet}:{i}:c{len(bars)}", "dia": c["dia"],
                         "pts": [list(c["p"])], "closed": False,
                         "kind": "section", "len": 0.0, "evidence": "circle"})
        out.append({"id": i, "kind": v["kind"], "sheet": sheet,
                    "wall_polygon": _rect(v["wall"]), "bars": bars})
    return out


def _rect(wb):
    x0, y0, x1, y1 = wb
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


# ------------------------------------------------------------- cut positions

def section_markers(doc, elev):
    """Numbered section markers drawn on the elevation -> cut stations.

    A marker is a pair of short stub lines just outside the element, both
    horizontal (a cut across the element: gives Z) or both vertical (a cut
    down through it: gives X), with a number beside them.
    """
    wb = elev["wall"]
    box = elev["box"]
    stubs, nums = [], []
    for e in doc.modelspace():
        if e.dxf.layer != SYMB:
            continue
        t = e.dxftype()
        if t == "LINE":
            p = (e.dxf.start.x, e.dxf.start.y)
            q = (e.dxf.end.x, e.dxf.end.y)
            if not (rbar.in_box(p, box, 400) or rbar.in_box(q, box, 400)):
                continue
            dx, dy = abs(q[0] - p[0]), abs(q[1] - p[1])
            if dy < 0.5 and dx > 0.5:
                stubs.append(("Z", (p[1] + q[1]) / 2, (p[0] + q[0]) / 2))
            elif dx < 0.5 and dy > 0.5:
                stubs.append(("X", (p[0] + q[0]) / 2, (p[1] + q[1]) / 2))
        elif t == "MTEXT":
            s = " ".join(e.text.replace("\\P", " ").split())
            if re.fullmatch(r"\d+", s):
                p = (e.dxf.insert.x, e.dxf.insert.y)
                if rbar.in_box(p, box, 1200):
                    nums.append((int(s), p))

    # stubs at the same station are the two ends of one cut line
    groups = collections.defaultdict(list)
    for axis, st, other in stubs:
        groups[(axis, round(st, 1))].append(other)

    out = []
    for (axis, st), others in groups.items():
        if len(others) < 2:
            continue                       # a lone stub is not a section line
        # the number sits at one end of the cut line, beyond the element
        far = max(others, key=lambda o: abs(o - (st if False else o)))
        best, bd = None, 1e9
        for n, p in nums:
            if axis == "Z":
                d = abs(p[1] - st) + 0.15 * min(abs(p[0] - o) for o in others)
            else:
                d = abs(p[0] - st) + 0.15 * min(abs(p[1] - o) for o in others)
            if d < bd:
                best, bd = n, d
        if best is None or bd > 1500:
            continue
        loc = st - (wb[0] if axis == "X" else wb[1])
        out.append({"n": best, "axis": axis, "pos": round(loc, 1),
                    "world": round(st, 1), "match_dist": round(bd, 1)})
    out.sort(key=lambda m: m["n"])
    # a number may only label one cut
    seen, uniq = set(), []
    for m in out:
        if m["n"] in seen:
            continue
        seen.add(m["n"])
        uniq.append(m)
    return uniq


def viewport_numbers(doc):
    """The number printed beside each section's title, in viewport order.

    `rbar.views` already finds the title MTEXT below a viewport; the bare
    integer sitting immediately left of it is the section number that the
    elevation's markers refer to.
    """
    lay = doc.layout("Layout1")
    texts = []
    for e in lay:
        if e.dxftype() != "MTEXT":
            continue
        s = " ".join(e.text.replace("\\P", " ").split())
        texts.append((e.dxf.insert.x, e.dxf.insert.y, s))
    titles = [(x, y, s) for x, y, s in texts if "REINF" in s.upper()]
    nums = [(x, y, int(s)) for x, y, s in texts if re.fullmatch(r"\d+", s)]
    out = {}
    for tx, ty, s in titles:
        best, bd = None, 1e9
        for nx, ny, n in nums:
            d = math.hypot(nx - tx, ny - ty)
            if d < bd:
                best, bd = n, d
        out[(round(tx, 2), round(ty, 2))] = (best if bd < 15 else None, round(bd, 2))
    return out


def title_number(doc, view, vpnums):
    """The section number of a view, via the title `rbar.views` matched to it."""
    if not view.get("title"):
        return None
    lay = doc.layout("Layout1")
    px, py, pw, ph = view["paper"]
    best, bd = None, 1e9
    for k, (n, _d) in vpnums.items():
        tx, ty = k
        d = abs(tx - (px - pw / 2) - 6) + abs(ty - (py - ph / 2))
        if d < bd:
            best, bd = n, d
    return best


# -------------------------------------------------------- concrete envelope

def concrete(doc, elev):
    """Depth profile and constant-depth zones of the real concrete outline."""
    prof = OUT.profile(doc, elev)
    return prof, coalesce(OUT.zones(prof))


def coalesce(zones, tol=1.5, gap=25.0):
    """Join zones of equal depth split only by the profile's sampling step."""
    out = []
    for z in sorted(zones, key=lambda z: z["x0"]):
        if out and abs(out[-1]["lo"] - z["lo"]) < tol \
                and abs(out[-1]["hi"] - z["hi"]) < tol \
                and z["x0"] - out[-1]["x1"] <= gap:
            out[-1]["x1"] = z["x1"]
        else:
            out.append(dict(z))
        out[-1]["depth"] = round(out[-1]["hi"] - out[-1]["lo"], 1)
    return out


def outline_polygon(zones, H):
    """The element's (X, Z) outline as a single closed ring."""
    if not zones:
        return []
    zs = sorted(zones, key=lambda z: z["x0"])
    top, bot = [], []
    for z in zs:
        top += [[z["x0"], z["hi"]], [z["x1"], z["hi"]]]
        bot += [[z["x0"], z["lo"]], [z["x1"], z["lo"]]]
    return [[round(a, 1), round(b, 1)] for a, b in top + bot[::-1]]


def z_span(zones, x0, x1, H):
    """Vertical extent of concrete over an X range (the intersection)."""
    hit = [z for z in zones if z["x1"] > x0 - 1 and z["x0"] < x1 + 1]
    if not hit:
        return 0.0, H
    return max(z["lo"] for z in hit), min(z["hi"] for z in hit)


def inside(zones, x, z, tol=15.0):
    for zn in zones:
        if zn["x0"] - tol <= x <= zn["x1"] + tol:
            if zn["lo"] - tol <= z <= zn["hi"] + tol:
                return True
    return False


# ------------------------------------------------------------- registration

def classify_2d(bars, wb, axes, sense, span):
    """Split a view's bars into runs and section points, in element ordinates.

    `axes` names which element axes the view's (u, v) measure; `sense` flips a
    view drawn mirrored with respect to the elevation.
    """
    au, av = axes
    su, sv = sense
    Su, Sv = span

    def conv(p):
        u = p[0] - wb[0]
        v = p[1] - wb[1]
        if su < 0:
            u = Su - u
        if sv < 0:
            v = Sv - v
        return round(u, 1), round(v, 1)

    runs, pts = [], []
    for b in bars:
        if b["kind"] == "section":
            u, v = conv(b["pts"][0])
            pts.append({"id": b["id"], "dia": b["dia"], au: u, av: v})
        else:
            cs = [conv(p) for p in b["pts"]]
            runs.append({"id": b["id"], "dia": b["dia"], "pts": cs,
                         "len": b.get("len", 0.0), "axes": (au, av)})
    return runs, pts


def clip_to_element(items, axes, span, tol=25.0):
    """Drop geometry a viewport window caught from a neighbouring detail.

    A viewport window is bigger than the element it frames, so a circle from
    the detail next to it can fall inside the window. A bar of THIS element
    lies within its concrete: anything measuring outside the element's own
    extent, most tellingly outside the thickness, belongs to another view.
    """
    au, av = axes
    Su, Sv = span
    keep, drop = [], []
    for it in items:
        if au in it:
            u, v = it[au], it[av]
            ok = -tol <= u <= Su + tol and -tol <= v <= Sv + tol
        else:
            ok = all(-tol <= p[0] <= Su + tol and -tol <= p[1] <= Sv + tol
                     for p in it["pts"])
        (keep if ok else drop).append(it)
    return keep, drop


def elevation_families(runs, ang_tol=8.0):
    """Elevation runs split into vertical and horizontal families."""
    vert, horiz, other = [], [], []
    for r in runs:
        (x0, z0), (x1, z1) = r["pts"][0], r["pts"][-1]
        a = math.degrees(math.atan2(z1 - z0, x1 - x0)) % 180
        rec = dict(r, x0=x0, z0=z0, x1=x1, z1=z1)
        if a < ang_tol or a > 180 - ang_tol:
            horiz.append(rec)
        elif abs(a - 90) < ang_tol:
            vert.append(rec)
        else:
            other.append(rec)
    return vert, horiz, other


def _sense_score(pts, key, runs, rkey, span):
    """How many section ordinates land on an elevation run, each way round."""
    best = {}
    for s in (1, -1):
        n = 0
        for p in pts:
            u = p[key] if s > 0 else span - p[key]
            if any(r["dia"] == p["dia"] and abs(r[rkey] - u) <= XTOL for r in runs):
                n += 1
        best[s] = n
    return best


# ---------------------------------------------------------------- the lift

def lift_element(cand, verbose=False, element=None):
    doc, vlist, env = cand["doc"], cand["views"], cand["env"]
    sheet = cand["sheet"]
    element = element or sheet
    elevs = [v for v in vlist if v["kind"] == "elevation"]
    if not elevs:
        return None
    elev = max(elevs, key=lambda v: v["w"] * v["h"])
    W, H = env["width_mm"], env["height_mm"]
    T = env["thickness_mm"] or 200.0

    prof, zones = concrete(doc, elev)
    poly = outline_polygon(zones, H)

    markers = section_markers(doc, elev)
    vpnums = viewport_numbers(doc)

    by_id, src = load_bars2d(sheet, doc, vlist)

    # ---- register the elevation first: it defines the frame
    ebars = by_id.get(vlist.index(elev), {}).get("bars", [])
    eruns, epts = classify_2d(ebars, elev["wall"], ("X", "Z"), (1, 1), (W, H))
    evert, ehoriz, eother = elevation_families(eruns)

    reg = [{"view": vlist.index(elev), "kind": "elevation", "sheet": sheet,
            "axes": ["X", "Z"], "sense": [1, 1], "cut": None, "number": None,
            "n_runs": len(eruns), "n_sections": len(epts)}]

    # ---- register each section
    sections = []
    for i, v in enumerate(vlist):
        if v["kind"] not in ("plan_cut", "end_cut"):
            continue
        num = title_number(doc, v, vpnums)
        mk = next((m for m in markers if m["n"] == num), None)
        axes = ("X", "Y") if v["kind"] == "plan_cut" else ("Y", "Z")
        span = (W, T) if v["kind"] == "plan_cut" else (T, H)
        bars = by_id.get(i, {}).get("bars", [])

        # sense: does this section read the same way round as the elevation?
        runs0, pts0 = classify_2d(bars, v["wall"], axes, (1, 1), span)
        pts0, _ = clip_to_element(pts0, axes, span)
        note = []
        if v["kind"] == "plan_cut":
            sc = _sense_score(pts0, "X", evert, "x0", W)
            su = 1 if sc[1] >= sc[-1] else -1
            conf_sense = _conf_from(sc)
            note.append(f"X sense {su} ({sc[1]}v{sc[-1]} bars agree with elevation)")
            sense = (su, 1)
        else:
            sc = _sense_score(pts0, "Z", ehoriz, "z0", H)
            sv = 1 if sc[1] >= sc[-1] else -1
            conf_sense = _conf_from(sc)
            note.append(f"Z sense {sv} ({sc[1]}v{sc[-1]} bars agree with elevation)")
            sense = (1, sv)
        runs, pts = classify_2d(bars, v["wall"], axes, sense, span)
        pts, dropped_p = clip_to_element(pts, axes, span)
        runs, dropped_r = clip_to_element(runs, axes, span)
        if dropped_p or dropped_r:
            note.append(f"{len(dropped_p)} section points and {len(dropped_r)} "
                        f"runs fall outside the element -- another view's detail")

        cut = None
        cut_how = "unlocated"
        if mk and ((v["kind"] == "plan_cut" and mk["axis"] == "Z")
                   or (v["kind"] == "end_cut" and mk["axis"] == "X")):
            cut = mk["pos"]
            cut_how = "marker"
        clamped = False
        lim = H if v["kind"] == "plan_cut" else W
        if cut is not None and not (0 <= cut <= lim):
            cut = min(max(cut, 0.0), lim)
            clamped = True

        # the concrete itself checks an end cut: the height of concrete at the
        # cut station must be the height the section draws
        ok = None
        if v["kind"] == "end_cut" and cut is not None:
            lo, hi = z_span(zones, cut - 40, cut + 40, H)
            ok = abs((hi - lo) - v["h"]) < 60
            note.append(f"concrete at X={cut:.0f} is {hi - lo:.0f} high, "
                        f"section draws {v['h']:.0f}" + ("" if ok else "  MISMATCH"))
        rec = {"view": i, "kind": v["kind"], "sheet": sheet,
               "axes": list(axes), "sense": list(sense), "number": num,
               "cut": cut, "cut_axis": "Z" if v["kind"] == "plan_cut" else "X",
               "cut_how": cut_how, "cut_clamped": clamped,
               "cut_verified": ok, "sense_confidence": conf_sense,
               "n_runs": len(runs), "n_sections": len(pts), "notes": note}
        reg.append(rec)
        sections.append((rec, runs, pts))

    # ---- Y sense: the end cuts must measure the thickness the same way the
    # plan cuts do. Only an asymmetric steel layout can tell them apart.
    ymeans = {}
    for k in ("plan_cut", "end_cut"):
        ys = [p["Y"] for r, _rr, pp in sections if r["kind"] == k for p in pp
              if 0 <= p["Y"] <= T]
        ymeans[k] = sum(ys) / len(ys) if ys else None
    y_note = "thickness sense undetermined (layout symmetric)"
    if ymeans["plan_cut"] is not None and ymeans["end_cut"] is not None:
        a, b = ymeans["plan_cut"] - T / 2, ymeans["end_cut"] - T / 2
        if abs(a) > 2.0 and abs(b) > 2.0 and a * b < 0:
            for rec, runs, pts in sections:
                if rec["kind"] != "end_cut":
                    continue
                rec["sense"][0] *= -1
                for p in pts:
                    p["Y"] = round(T - p["Y"], 1)
                for r in runs:
                    r["pts"] = [(round(T - u, 1), w) for u, w in r["pts"]]
            y_note = f"end cuts flipped in Y (means {a:+.1f} vs {b:+.1f} about mid)"

    bars3d, stats = fuse(sections, evert, ehoriz, eother, epts, zones, W, H, T)

    return {"element": element,
            "source": {"sheet": sheet, "bars2d": src,
                       "extra_sheets": [c["sheet"] for c in cand.get("extra", [])]},
            "envelope": {"width_mm": W, "height_mm": H, "thickness_mm": T},
            "outline": poly,
            "zones": [{k: z[k] for k in ("x0", "x1", "lo", "hi", "depth")}
                      for z in zones],
            "views": reg,
            "markers": markers,
            "y_registration": y_note,
            "bars3d": bars3d,
            "stats": stats}


def _conf_from(sc):
    a, b = sc[1], sc[-1]
    if a + b == 0:
        return 0.0
    return round(abs(a - b) / float(a + b), 2)


# ------------------------------------------------------------------ fusion

def _merge_spans(spans, gap=40.0):
    spans = sorted(spans)
    out = []
    for s, e in spans:
        if out and s <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def _extent(cand, cuts, gap):
    """The extent of the drawn bar a section cut is standing on.

    A centreline arrives in pieces -- crossings and hooks break it up -- so the
    pieces on this line are merged first and only then is the piece the cut
    passes through chosen. Picking a fragment before merging would report a
    90 mm bar where the drawing shows a full-height one.
    """
    spans = _merge_spans([[min(a, b), max(a, b)] for a, b in cand], gap=gap)
    on = [s for s in spans
          if any(s[0] - gap <= c <= s[1] + gap for c in cuts)] if cuts else []
    pick = max(on or spans, key=lambda s: s[1] - s[0])
    return pick[0], pick[1], bool(on)


def fuse(sections, evert, ehoriz, eother, epts, zones, W, H, T):
    """Collapse every appearance of a bar in every view into one 3D bar.

    A vertical bar is a circle at (X, Y) in a horizontal cut and a vertical run
    at that same X in the elevation; those are not two bars. The section fixes
    X and Y exactly, the elevation gives the run's extent in Z, and the fused
    object carries both views as its evidence. The same holds, transposed, for
    a horizontal bar between an end cut and the elevation.
    """
    bars, stats = [], collections.Counter()
    used_runs = set()
    n = [0]

    def nid(p):
        n[0] += 1
        return f"{p}{n[0]:04d}"

    # --- vertical bars: plan cuts x elevation
    plan = [(r, rr, pp) for r, rr, pp in sections if r["kind"] == "plan_cut"]
    end = [(r, rr, pp) for r, rr, pp in sections if r["kind"] == "end_cut"]

    clusters = collections.defaultdict(list)
    for rec, _rr, pts in plan:
        for p in pts:
            clusters[(p["dia"], round(p["X"] / 2.0), round(p["Y"] / 2.0))].append(
                (rec, p))
    for key, items in sorted(clusters.items()):
        dia = key[0]
        X = sum(p["X"] for _r, p in items) / len(items)
        Y = sum(p["Y"] for _r, p in items) / len(items)
        cuts = [r["cut"] for r, _p in items if r["cut"] is not None]
        views = sorted({r["view"] for r, _p in items})
        cand = [r for r in evert if r["dia"] == dia and abs(r["x0"] - X) <= XTOL]
        how, conf, from_views = None, 0.0, list(views)
        if cand:
            z0, z1, on = _extent([(r["z0"], r["z1"]) for r in cand], cuts, 60.0)
            how = ("fused:plan_cut+elevation" if on or not cuts
                   else "fused:plan_cut+elevation(cut not on run)")
            conf = min(0.98, 0.90 + 0.04 * (len(views) - 1)) if on else 0.70
            from_views = ["elevation"] + [f"view{v}" for v in views]
            used_runs |= {r["id"] for r in cand}
        else:
            lo, hi = z_span(zones, X, X, H)
            c = COVER + dia / 2.0
            z0, z1 = lo + c, hi - c
            how = "plan_cut only; extent from concrete outline"
            conf = 0.55
        bars.append({"id": nid("V"), "dia": dia, "axis": "Z",
                     "pts": [[round(X, 1), round(Y, 1), round(z0, 1)],
                             [round(X, 1), round(Y, 1), round(z1, 1)]],
                     "from_views": from_views, "n_views": len(from_views),
                     "cuts_seen": cuts, "how": how, "confidence": round(conf, 2)})
        stats[how] += 1

    # --- horizontal bars: end cuts x elevation
    clusters = collections.defaultdict(list)
    for rec, _rr, pts in end:
        for p in pts:
            clusters[(p["dia"], round(p["Y"] / 2.0), round(p["Z"] / 2.0))].append(
                (rec, p))
    for key, items in sorted(clusters.items()):
        dia = key[0]
        Y = sum(p["Y"] for _r, p in items) / len(items)
        Z = sum(p["Z"] for _r, p in items) / len(items)
        cuts = [r["cut"] for r, _p in items if r["cut"] is not None]
        views = sorted({r["view"] for r, _p in items})
        cand = [r for r in ehoriz if r["dia"] == dia and abs(r["z0"] - Z) <= ZTOL]
        if cand:
            x0, x1, on = _extent([(r["x0"], r["x1"]) for r in cand], cuts, 60.0)
            how = ("fused:end_cut+elevation" if on or not cuts
                   else "fused:end_cut+elevation(cut not on run)")
            conf = min(0.98, 0.90 + 0.04 * (len(views) - 1)) if on else 0.70
            from_views = ["elevation"] + [f"view{v}" for v in views]
            used_runs |= {r["id"] for r in cand}
        else:
            lo, hi = 0.0, W
            c = COVER + dia / 2.0
            x0, x1 = lo + c, hi - c
            how = "end_cut only; extent from concrete outline"
            conf = 0.55
            from_views = [f"view{v}" for v in views]
        bars.append({"id": nid("H"), "dia": dia, "axis": "X",
                     "pts": [[round(x0, 1), round(Y, 1), round(Z, 1)],
                             [round(x1, 1), round(Y, 1), round(Z, 1)]],
                     "from_views": from_views, "n_views": len(from_views),
                     "cuts_seen": cuts, "how": how, "confidence": round(conf, 2)})
        stats[how] += 1

    # --- bars drawn lengthwise inside a section cut: the cut fixes the third
    #     ordinate exactly, so these lift without any guess at all
    for rec, runs, _pp in sections:
        cut = rec["cut"]
        for r in runs:
            pts3 = []
            for (u, v) in r["pts"]:
                if rec["kind"] == "plan_cut":
                    pts3.append([u, v, cut if cut is not None else H / 2.0])
                else:
                    pts3.append([cut if cut is not None else W / 2.0, u, v])
            how = ("section run at known cut" if cut is not None
                   else "section run, cut station unknown")
            bars.append({"id": nid("S"), "dia": r["dia"],
                         "axis": "XY" if rec["kind"] == "plan_cut" else "YZ",
                         "pts": [[round(a, 1) for a in p] for p in pts3],
                         "from_views": [f"view{rec['view']}"], "n_views": 1,
                         "cuts_seen": [cut] if cut is not None else [],
                         "how": how,
                         "confidence": 0.70 if cut is not None else 0.30})
            stats[how] += 1

    # --- elevation runs no section ever accounted for. Their Y is genuinely
    #     unmeasured: the nearest same-diameter layer the sections did measure
    #     is the honest estimate, and it is labelled as one.
    layers = collections.defaultdict(list)
    for rec, _rr, pts in sections:
        for p in pts:
            layers[p["dia"]].append(p["Y"])
    layer_mode = {}
    for d, ys in layers.items():
        c = collections.Counter(round(y, 1) for y in ys)
        layer_mode[d] = c.most_common(1)[0][0]

    for fam, r in [("v", r) for r in evert] + [("h", r) for r in ehoriz] \
            + [("o", r) for r in eother]:
        if r["id"] in used_runs:
            continue
        Y = layer_mode.get(r["dia"])
        if Y is None:
            Y, conf, how = T / 2.0, 0.25, "elevation only; Y assumed mid-thickness"
        else:
            conf, how = 0.40, "elevation only; Y from a measured layer of same dia"
        bars.append({"id": nid("E"), "dia": r["dia"], "axis": "XZ",
                     "pts": [[round(x, 1), round(Y, 1), round(z, 1)]
                             for x, z in r["pts"]],
                     "from_views": ["elevation"], "n_views": 1,
                     "cuts_seen": [], "how": how, "confidence": conf})
        stats[how] += 1

    # --- containment against the real concrete, not a bounding box
    outside = 0
    for b in bars:
        bad = [p for p in b["pts"] if not inside(zones, p[0], p[2])]
        b["in_concrete"] = not bad
        if bad:
            outside += 1
            b["confidence"] = round(b["confidence"] * 0.6, 2)
    st = dict(stats)
    st["_total"] = len(bars)
    st["_fused_multiview"] = sum(1 for b in bars if b["n_views"] > 1)
    st["_single_view"] = sum(1 for b in bars if b["n_views"] == 1)
    st["_outside_concrete"] = outside
    st["_elevation_runs"] = len(evert) + len(ehoriz) + len(eother)
    st["_elevation_runs_consumed"] = len(used_runs)
    return bars, st


# --------------------------------------------------------------------- CLI

def panels(pattern=None):
    got = collections.defaultdict(list)
    for f in sorted(DXF_DIR.glob("*_R*.dxf")):
        p = re.sub(r"_R\d*$", "", f.stem)
        got[p].append(f)
    if pattern:
        got = {k: v for k, v in got.items() if pattern in k}
    return got


def run(pattern=None, write=True):
    out = []
    for panel, paths in sorted(panels(pattern).items()):
        try:
            cands = EL.candidates(panel, paths)
        except Exception as ex:
            print(f"{panel}: candidates failed: {ex}")
            continue
        for c in cands:
            try:
                d = lift_element(c, element=EL.element_name(panel, c, len(cands)))
            except Exception as ex:
                import traceback; traceback.print_exc()
                print(f"{c['sheet']}: lift failed: {ex}")
                continue
            if d is None:
                continue
            if write:
                LIFT_DIR.mkdir(parents=True, exist_ok=True)
                (LIFT_DIR / f"{d['element']}.json").write_text(json.dumps(d, indent=1))
            s = d["stats"]
            print(f"{d['element']:16s} {d['envelope']['width_mm']:.0f}x"
                  f"{d['envelope']['height_mm']:.0f}x{d['envelope']['thickness_mm']:.0f}"
                  f"  bars3d={s['_total']:5d} fused={s['_fused_multiview']:5d}"
                  f" single={s['_single_view']:5d} outside={s['_outside_concrete']:4d}"
                  f"  cuts={[v.get('cut') for v in d['views'][1:]]}")
            out.append(d)
    return out


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else None)
