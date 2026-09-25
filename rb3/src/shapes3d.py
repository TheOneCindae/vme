"""Exact parametric 3D geometry for each BBS shape code.

Every shape is expressed as an ordered list of legs in a local 2D frame
(the bar's bending plane), driven by the BBS A..G dimensions, with real
bend radii. Dimensions in the schedule are OUTSIDE dimensions, so leg
centreline runs are reduced by the bar radius at each bend, per normal
bar-bending practice.

The BBS `bar_length_mm` remains the authoritative cut length; the
geometric centreline length is reported alongside it so the bend
allowance is explicit and auditable, never silently reconciled.
"""
import math

# Minimum former radius (centreline) as a multiple of bar diameter.
# IS 2502 / BS 8666: 2d for links up to 16mm, 3.5d for larger bars.
def bend_radius(dia, link=False):
    return (2.0 * dia) if (link or dia <= 16) else (3.5 * dia)


def _poly_from_turns(legs, turns, dia, close=False):
    """Build a centreline polyline from leg lengths and turn angles (deg).

    `legs[i]` is the centreline run of leg i between bend tangent points;
    `turns[i]` is the turn applied after leg i. Bends are filleted with
    `bend_radius(dia)` and the arc is emitted as a series of points.
    """
    r = bend_radius(dia)
    pts = [(0.0, 0.0)]
    x, y, h = 0.0, 0.0, 0.0        # position and heading (radians)
    for i, L in enumerate(legs):
        x += L * math.cos(h)
        y += L * math.sin(h)
        pts.append((x, y))
        if i < len(turns):
            t = math.radians(turns[i])
            if abs(t) < 1e-9:
                continue
            # fillet arc of radius r sweeping |t|
            sgn = 1.0 if t > 0 else -1.0
            cx = x - r * math.sin(h) * sgn * -1
            cx = x + r * math.cos(h + sgn * math.pi / 2)
            cy = y + r * math.sin(h + sgn * math.pi / 2)
            a0 = math.atan2(y - cy, x - cx)
            n = max(3, int(abs(math.degrees(t)) / 15) + 2)
            for k in range(1, n + 1):
                a = a0 + sgn * abs(t) * k / n
                pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
            x, y = pts[-1]
            h += t
    if close and math.dist(pts[0], pts[-1]) > 1e-6:
        pts.append(pts[0])
    return pts


def polyline_length(pts):
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


# --- Shape catalogue -------------------------------------------------------
# Each entry: sequence of legs, each naming its BBS dimension column, and the
# turn (deg) applied AFTER that leg. Turn sign is + for left, - for right.
# `hook` marks a 135-degree hook tail on a link.
# Verified against the (S) legend drawings -- see out/shapes_dims.png.
CRANK = 17.5          # crank slope taken from the legend; not dimensioned in the BBS

SHAPES = {
    "M_00":           {"legs": ["B"], "turns": [], "mode": "path",
                       "desc": "straight bar"},
    "M_17":           {"legs": ["B", "C", "D"], "turns": [90, 90], "mode": "outside",
                       "desc": "U-bar / staple: leg-base-leg"},
    "M_17A":          {"legs": ["C", "B"], "turns": [-90], "mode": "outside",
                       "desc": "L-bar: single 90 bend"},
    "26":             {"legs": ["A", "B", "C"], "turns": [-CRANK, CRANK], "mode": "path",
                       "desc": "cranked (dog-leg) bar"},
    "M_T1":           {"legs": ["B", "C", "D", "E"], "turns": [-90, -90, -90],
                       "close": True, "hooks": ["A", "G"], "mode": "outside",
                       "desc": "closed rectangular link with 135 hooks"},
    "M_T10":          {"legs": ["A", "B", "G"], "turns": [-135, -135], "mode": "path",
                       "desc": "open link / hat with 135 ends"},
    "Rebar Shape 8":  {"legs": ["A", "B", "C"], "turns": [-90, 90], "mode": "outside",
                       "desc": "Z / offset bar"},
    "Rebar Shape 9":  {"legs": ["C", "D", "E", "B", "A"], "turns": [-90, -90, -90, -90],
                       "mode": "outside", "desc": "multi-bend hooked bar"},
    "Rebar Shape 30": {"legs": ["A", "B", "C", "D", "E"],
                       "turns": [-CRANK, CRANK, CRANK, -CRANK], "mode": "path",
                       "desc": "double-cranked bar"},
    "Rebar Shape 31": {"legs": ["A", "B", "C", "D", "E"],
                       "turns": [CRANK, -CRANK, -CRANK, CRANK], "mode": "path",
                       "desc": "double-cranked bar (opposite hand)"},
}


def build(shape, dims, dia, missing=None):
    """Return the centreline polyline (list of (x, y), mm) for one bar.

    `dims` maps BBS column letters to outside dimensions in mm.
    Legs whose dimension is absent or non-numeric fall back to `missing`.
    """
    spec = SHAPES.get(shape)
    if spec is None:
        return None, f"unknown shape code {shape!r}"
    r = bend_radius(dia, link=shape.startswith("M_T"))
    letters = spec["legs"]
    turns = list(spec["turns"])
    raw = []
    for lt in letters:
        v = dims.get(lt)
        if v is None or v == 0:
            if missing is None:
                return None, f"missing dimension {lt}"
            v = missing
        raw.append(float(v))
    # schedule dimension -> straight centreline run between bend tangent points
    mode = spec.get("mode", "outside")
    # "outside": dim reaches the outer face of the adjacent leg
    # "inter":   dim reaches the intersection of adjacent leg centrelines
    # "along":   dim is already the centreline run
    # "path" mode: the dimensions partition the centreline path itself, so each
    # bend's arc length is shared equally between the two legs it joins.
    def cut_for(turn_deg):
        if mode == "path":
            return r * math.radians(abs(turn_deg)) / 2.0
        base = {"outside": r + dia / 2, "inter": r, "along": 0.0}[mode]
        return base * math.tan(math.radians(abs(turn_deg)) / 2)

    runs = []
    for i, v in enumerate(raw):
        cut = 0.0
        if i > 0:
            cut += cut_for(turns[i - 1])
        if i < len(turns):
            cut += cut_for(turns[i])
        runs.append(max(v - cut, 1.0))
    pts = _poly_from_turns(runs, turns, dia, close=spec.get("close", False))
    return pts, None


def _hook_tails(pts, dims, spec, dia, r):
    """Append 135-degree hook tails to a closed link (shapes M_T*)."""
    out = list(pts)
    tails = []
    for lt in spec.get("hooks", []):
        v = dims.get(lt)
        if v:
            tails.append(float(v))
    if not tails:
        return out, tails
    # tails spring from the closing corner, folded back into the link at 135
    import math
    p0, p1 = out[0], out[1]
    h = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    for k, L in enumerate(tails):
        sgn = 1 if k == 0 else -1
        a = h + sgn * math.radians(135)
        out.append((p0[0] + L * math.cos(a), p0[1] + L * math.sin(a)))
    return out, tails


def build_exact(shape, dims, dia, cut_length, missing=None):
    """Geometry for one bar, reconciled to the schedule's cut length.

    The FORM comes from the A..G dimensions; the LENGTH comes from the
    schedule, which is the verified fabrication value. Any residual between
    the two (bend allowance, hook allowance, 25 mm cutting round-off) is
    absorbed by scaling the straight runs and is reported explicitly, never
    hidden.
    """
    spec = SHAPES.get(shape)
    if spec is None:
        return {"error": f"unknown shape code {shape!r}"}
    pts, err = build(shape, dims, dia, missing=missing)
    if err:
        return {"error": err}
    r = bend_radius(dia, link=shape.startswith("M_T"))
    if spec.get("hooks"):
        pts, tails = _hook_tails(pts, dims, spec, dia, r)
    geo = polyline_length(pts)
    out = {"pts": pts, "geometric_mm": round(geo, 1),
           "cut_length_mm": cut_length, "residual_mm": round(geo - cut_length, 1)}
    if cut_length and geo > 1:
        k = cut_length / geo
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        out["pts_exact"] = [((p[0] - cx) * k + cx, (p[1] - cy) * k + cy) for p in pts]
        out["scale_applied"] = round(k, 6)
    else:
        out["pts_exact"] = pts
        out["scale_applied"] = 1.0
    return out
