"""rb3 v2 STAGE 1 — lossless raw entity extraction from the cached DXFs.

Reads  : dxf/<sheet>.dxf          (produced by src/convert.py via dwg2dxf)
Writes : out/v2/raw/<sheet>.json  (stage-1 contract, see SPEC.md)

Contract highlights
-------------------
* EVERY INSERT is exploded recursively with ezdxf ``virtual_entities()``.
  Revit exports place blocks at ins_pt (0,0) with world coordinates baked
  into the block definition, so leader heads / mark bubbles only become
  visible after exploding.  Every emitted entity carries
  ``src = "top"`` or ``src = "block:<name>"``.
* LWPOLYLINE / POLYLINE bulges are converted into real arc point
  sequences (never straight-lined); the raw (x, y, bulge) vertices are kept
  alongside so the conversion is reversible.
* Model space AND every paper space layout are captured, together with all
  VIEWPORT definitions (view_center_point, view_height, width, height,
  derived scale, and nearby paper-space title text).
* Nothing is dropped silently: a per-sheet reconciliation of entity counts
  by type (read vs written) plus a per-reason skip tally is stored in the
  JSON and printed.

Usage
-----
    venv/bin/python -m src.v2.raw            # all *_R*.dxf and *_S.dxf
    venv/bin/python -m src.v2.raw PW-GF-09_R1 PW-GF-01_R
    venv/bin/python -m src.v2.raw --all      # every dxf/*.dxf
"""
from __future__ import annotations

import json
import math
import sys
import traceback
from collections import Counter
from pathlib import Path

import ezdxf
from ezdxf.math import bulge_to_arc

ROOT = Path(__file__).resolve().parents[2]
DXF_DIR = ROOT / "dxf"
OUT_DIR = ROOT / "out" / "v2" / "raw"

# ---------------------------------------------------------------- tuning ----
ARC_SEG_DEG = 6.0          # max sweep per sampled arc segment
ARC_MIN_SEG = 4            # min segments per arc / bulge
ARC_MAX_SEG = 360          # hard cap on segments per arc
ARC_SAG = 0.05             # max chordal deviation (mm) of the sampled arc
ROUND = 4                  # default coordinate precision (mm)
ROUND_COARSE = 1           # fallback precision for very large sheets
SIZE_LIMIT = 80 * 1024 * 1024
TITLE_PAD = 1.30           # viewport rect inflation when hunting for a title


# ------------------------------------------------------------- utilities ----
def _xy(p) -> list:
    return [float(p[0]), float(p[1])]


def _z(p) -> float:
    try:
        return float(p[2])
    except (IndexError, TypeError):
        return 0.0


def _rnd(v, nd):
    if isinstance(v, (list, tuple)):
        return [_rnd(x, nd) for x in v]
    if isinstance(v, float):
        r = round(v, nd)
        return 0.0 if r == 0 else r
    return v


def arc_points(cx, cy, r, a0, a1, ccw=True):
    """Sample an arc (angles in degrees) into a point list, endpoints included."""
    sweep = (a1 - a0) % 360.0 if ccw else -((a0 - a1) % 360.0)
    if abs(sweep) < 1e-9:
        sweep = 360.0 if ccw else -360.0
    step = ARC_SEG_DEG
    if r > 0:                       # keep chordal deviation under ARC_SAG mm
        c = 1.0 - min(1.0, ARC_SAG / r)
        step = min(step, 2.0 * math.degrees(math.acos(c)))
    n = max(ARC_MIN_SEG, int(math.ceil(abs(sweep) / max(step, 1e-6))))
    n = min(n, ARC_MAX_SEG)
    out = []
    for i in range(n + 1):
        a = math.radians(a0 + sweep * i / n)
        out.append([cx + r * math.cos(a), cy + r * math.sin(a)])
    return out


def expand_bulges(verts, closed):
    """verts: [(x, y, sw, ew, bulge), ...] -> point list with bulges as arcs.

    Returns (points, n_bulges).
    """
    pts = []
    n = len(verts)
    if n == 0:
        return pts, 0
    nb = 0
    last = n if closed else n - 1
    for i in range(last):
        a = verts[i]
        b = verts[(i + 1) % n]
        p0 = (float(a[0]), float(a[1]))
        p1 = (float(b[0]), float(b[1]))
        bulge = float(a[4]) if len(a) > 4 else 0.0
        if not pts:
            pts.append([p0[0], p0[1]])
        if abs(bulge) > 1e-12 and (abs(p1[0] - p0[0]) > 1e-12 or abs(p1[1] - p0[1]) > 1e-12):
            nb += 1
            # DXF/ezdxf convention: bulge_to_arc returns an arc traversed CCW
            # from sa to ea.  For a negative bulge sa belongs to p1, so the
            # sampled sequence has to be reversed to run p0 -> p1.
            c, sa, ea, r = bulge_to_arc(p0, p1, bulge)
            seg = arc_points(c[0], c[1], r, math.degrees(sa), math.degrees(ea),
                             ccw=True)
            if bulge < 0:
                seg.reverse()
            pts.extend(seg[1:-1])
            pts.append([p1[0], p1[1]])
        else:
            pts.append([p1[0], p1[1]])
    if not pts and n:
        pts = [[float(v[0]), float(v[1])] for v in verts]
    return pts, nb


def flatten(entity, dist=0.5):
    """Best-effort flattening for curved entities (ELLIPSE / SPLINE)."""
    try:
        return [_xy(p) for p in entity.flattening(dist)]
    except Exception:
        try:
            return [_xy(p) for p in entity.approximate(64)]
        except Exception:
            return []


def mtext_plain(e):
    for meth in ("plain_text", "text"):
        try:
            v = getattr(e, meth)
            return v() if callable(v) else str(v)
        except Exception:
            continue
    try:
        return str(e.dxf.text)
    except Exception:
        return ""


# --------------------------------------------------------- entity mapping ---
def hatch_paths(e):
    out = []
    for p in e.paths:
        pts = []
        try:
            if p.path_type_flags & 2:                       # polyline path
                vs = [(v[0], v[1], 0, 0, v[2] if len(v) > 2 else 0.0)
                      for v in p.vertices]
                pts, _ = expand_bulges(vs, bool(getattr(p, "is_closed", True)))
            else:                                           # edge path
                for edge in p.edges:
                    t = edge.type
                    if t == "LineEdge":
                        pts.append(_xy(edge.start))
                        pts.append(_xy(edge.end))
                    elif t == "ArcEdge":
                        pts.extend(arc_points(edge.center[0], edge.center[1],
                                              edge.radius, edge.start_angle,
                                              edge.end_angle, edge.ccw))
                    elif t == "EllipseEdge":
                        c = edge.center
                        maj = edge.major_axis
                        ra = math.hypot(maj[0], maj[1])
                        rb = ra * edge.ratio
                        rot = math.atan2(maj[1], maj[0])
                        a0, a1 = edge.start_angle, edge.end_angle
                        sweep = (a1 - a0) % 360.0 or 360.0
                        n = max(ARC_MIN_SEG, int(sweep / ARC_SEG_DEG))
                        for i in range(n + 1):
                            a = math.radians(a0 + sweep * i / n)
                            x, y = ra * math.cos(a), rb * math.sin(a)
                            pts.append([c[0] + x * math.cos(rot) - y * math.sin(rot),
                                        c[1] + x * math.sin(rot) + y * math.cos(rot)])
                    elif t == "SplineEdge":
                        pts.extend(_xy(p_) for p_ in edge.control_points)
        except Exception:
            pass
        if pts:
            out.append(pts)
    return out


def to_record(e, space, src):
    """Map an ezdxf entity to a stage-1 record, or return None if unsupported."""
    t = e.dxftype()
    d = e.dxf
    rec = {"type": t, "layer": str(getattr(d, "layer", "0")), "space": space,
           "src": src}
    try:
        h = getattr(d, "handle", None)
        if h:
            rec["h"] = str(h)
    except Exception:
        pass

    if t == "LINE":
        rec["pts"] = [_xy(d.start), _xy(d.end)]
        z = (_z(d.start), _z(d.end))
        if abs(z[0]) > 1e-9 or abs(z[1]) > 1e-9:
            rec["z"] = [z[0], z[1]]

    elif t == "ARC":
        c = d.center
        rec["c"] = _xy(c)
        rec["r"] = float(d.radius)
        rec["a0"] = float(d.start_angle) % 360.0
        rec["a1"] = float(d.end_angle) % 360.0
        rec["pts"] = arc_points(c[0], c[1], rec["r"], rec["a0"], rec["a1"])
        if abs(_z(c)) > 1e-9:
            rec["z"] = _z(c)

    elif t == "CIRCLE":
        c = d.center
        rec["c"] = _xy(c)
        rec["r"] = float(d.radius)
        rec["a0"] = 0.0
        rec["a1"] = 360.0
        rec["pts"] = [_xy(c)]
        if abs(_z(c)) > 1e-9:
            rec["z"] = _z(c)

    elif t in ("LWPOLYLINE", "POLYLINE"):
        if t == "LWPOLYLINE":
            verts = [tuple(float(x) for x in v) for v in e.get_points()]
            closed = bool(e.closed)
        else:
            if e.get_mode() not in ("AcDb2dPolyline", "AcDb3dPolyline"):
                return None                      # mesh / polyface -> handled below
            verts = []
            for v in e.vertices:
                verts.append((float(v.dxf.location[0]), float(v.dxf.location[1]),
                              0.0, 0.0, float(getattr(v.dxf, "bulge", 0.0) or 0.0)))
            closed = bool(e.is_closed)
        pts, nb = expand_bulges(verts, closed)
        rec["pts"] = pts
        rec["closed"] = closed
        rec["verts"] = [[v[0], v[1], (v[4] if len(v) > 4 else 0.0)] for v in verts]
        if nb:
            rec["bulges"] = nb

    elif t in ("MTEXT", "TEXT", "ATTRIB", "ATTDEF"):
        rec["type"] = "MTEXT"
        rec["etype"] = t
        rec["text"] = mtext_plain(e)
        ip = getattr(d, "insert", None) or getattr(d, "align_point", None) \
            or (0.0, 0.0, 0.0)
        rec["pts"] = [_xy(ip)]
        rec["h_txt"] = float(getattr(d, "char_height", None)
                             or getattr(d, "height", 0.0) or 0.0)
        rec["rot"] = float(getattr(d, "rotation", 0.0) or 0.0)
        if t == "MTEXT":
            rec["attach"] = int(getattr(d, "attachment_point", 1) or 1)
            rec["width"] = float(getattr(d, "width", 0.0) or 0.0)
        if t in ("ATTRIB", "ATTDEF"):
            rec["tag"] = str(getattr(d, "tag", ""))

    elif t == "HATCH" or t == "MPOLYGON":
        rec["type"] = "HATCH"
        rec["paths"] = hatch_paths(e)
        rec["pts"] = rec["paths"][0] if rec["paths"] else []
        rec["solid"] = bool(getattr(d, "solid_fill", 0))
        rec["pattern"] = str(getattr(d, "pattern_name", ""))

    elif t == "DIMENSION":
        rec["dimtype"] = int(getattr(d, "dimtype", 0))
        rec["text"] = str(getattr(d, "text", "") or "")
        rec["measurement"] = float(getattr(d, "actual_measurement", 0.0) or 0.0)
        pts = []
        for a in ("defpoint", "defpoint2", "defpoint3", "defpoint4", "defpoint5"):
            v = getattr(d, a, None)
            if v is not None:
                rec[a] = _xy(v)
                pts.append(_xy(v))
        tm = getattr(d, "text_midpoint", None)
        if tm is not None:
            rec["text_midpoint"] = _xy(tm)
            pts.append(_xy(tm))
        rec["pts"] = pts
        rec["geometry"] = str(getattr(d, "geometry", "") or "")
        rec["dimstyle"] = str(getattr(d, "dimstyle", "") or "")

    elif t == "ELLIPSE":
        c = d.center
        maj = d.major_axis
        rec["c"] = _xy(c)
        rec["major"] = _xy(maj)
        rec["ratio"] = float(d.ratio)
        rec["a0"] = float(d.start_param)
        rec["a1"] = float(d.end_param)
        rec["r"] = math.hypot(float(maj[0]), float(maj[1]))
        rec["pts"] = flatten(e, 0.2) or [_xy(c)]

    elif t in ("SPLINE", "LEADER", "POLYLINE"):
        if t == "LEADER":
            rec["pts"] = [_xy(p) for p in d.vertices] if hasattr(d, "vertices") \
                else [_xy(p) for p in e.get_vertices()]
        else:
            rec["pts"] = flatten(e, 0.2)
        if not rec["pts"]:
            return None

    elif t in ("SOLID", "TRACE", "3DFACE"):
        rec["type"] = "SOLID"
        rec["etype"] = t
        pts = []
        for a in ("vtx0", "vtx1", "vtx2", "vtx3"):
            v = getattr(d, a, None)
            if v is not None:
                pts.append(_xy(v))
        rec["pts"] = pts

    elif t == "POINT":
        rec["pts"] = [_xy(d.location)]

    elif t in ("IMAGE", "WIPEOUT"):
        rec["type"] = "IMAGE"
        rec["etype"] = t
        ip = getattr(d, "insert", (0, 0, 0))
        u = getattr(d, "u_pixel", (1, 0, 0))
        v = getattr(d, "v_pixel", (0, 1, 0))
        sz = getattr(d, "image_size", (0, 0))
        rec["pts"] = [_xy(ip),
                      [ip[0] + u[0] * sz[0], ip[1] + u[1] * sz[0]],
                      [ip[0] + u[0] * sz[0] + v[0] * sz[1],
                       ip[1] + u[1] * sz[0] + v[1] * sz[1]],
                      [ip[0] + v[0] * sz[1], ip[1] + v[1] * sz[1]]]

    elif t == "INSERT":
        rec["block"] = str(d.name)
        rec["pts"] = [_xy(d.insert)]
        rec["scale"] = [float(getattr(d, "xscale", 1.0) or 1.0),
                        float(getattr(d, "yscale", 1.0) or 1.0)]
        rec["rot"] = float(getattr(d, "rotation", 0.0) or 0.0)

    else:
        return None

    return rec


# ------------------------------------------------------------- extraction ---
MAX_DEPTH = 12


def walk(entity, space, src, out, read, written, skipped, depth=0):
    """Emit `entity`; if it is an INSERT, recursively emit its virtual children."""
    t = entity.dxftype()
    read[t] += 1
    try:
        rec = to_record(entity, space, src)
    except Exception as exc:
        skipped[f"{t}:error:{type(exc).__name__}"] += 1
        rec = None
    if rec is None:
        skipped[f"{t}:unsupported"] += 1
    else:
        written[rec["type"]] += 1
        out.append(rec)

    if t == "INSERT":
        if depth >= MAX_DEPTH:
            skipped["INSERT:max_depth"] += 1
            return
        name = str(entity.dxf.name)
        child_src = f"block:{name}"
        try:
            children = list(entity.virtual_entities())
        except Exception as exc:
            skipped[f"INSERT:explode_error:{type(exc).__name__}"] += 1
            return
        for ch in children:
            walk(ch, space, child_src, out, read, written, skipped, depth + 1)
        try:
            for at in entity.attribs:
                walk(at, space, child_src, out, read, written, skipped, depth + 1)
        except Exception:
            pass


def viewport_records(layout, texts):
    vps = []
    for vp in layout.query("VIEWPORT"):
        d = vp.dxf
        if int(getattr(d, "id", 1)) == 1 and float(getattr(d, "width", 0)) <= 0:
            continue
        c = getattr(d, "center", (0, 0, 0))
        w = float(getattr(d, "width", 0.0) or 0.0)
        h = float(getattr(d, "height", 0.0) or 0.0)
        vc = getattr(d, "view_center_point", (0, 0, 0))
        vh = float(getattr(d, "view_height", 0.0) or 0.0)
        rec = {"layout": layout.name,
               "handle": str(getattr(d, "handle", "")),
               "id": int(getattr(d, "id", 0) or 0),
               "layer": str(getattr(d, "layer", "0")),
               "status": int(getattr(d, "status", 0) or 0),
               "center": _xy(c), "w": w, "h": h,
               "view_center_point": _xy(vc), "view_height": vh,
               "view_width": (vh * w / h) if h else 0.0,
               "scale": (vh / h) if h else 0.0,
               "twist": float(getattr(d, "view_twist_angle", 0.0) or 0.0)}
        # model-space window this viewport shows
        if h:
            hw, hh = rec["view_width"] / 2.0, vh / 2.0
            rec["window"] = [rec["view_center_point"][0] - hw,
                             rec["view_center_point"][1] - hh,
                             rec["view_center_point"][0] + hw,
                             rec["view_center_point"][1] + hh]
        # nearest paper-space texts (candidate titles)
        x0, x1 = c[0] - w * TITLE_PAD / 2, c[0] + w * TITLE_PAD / 2
        y0, y1 = c[1] - h * TITLE_PAD / 2, c[1] + h * TITLE_PAD / 2
        near = []
        for tx, ty, s in texts:
            if x0 <= tx <= x1 and y0 - h * 0.25 <= ty <= y1:
                near.append((math.hypot(tx - c[0], ty - (c[1] - h / 2)), tx, ty, s))
        near.sort()
        rec["titles"] = [{"text": s, "at": [tx, ty]} for _, tx, ty, s in near[:8]]
        rec["title"] = near[0][3] if near else ""
        vps.append(rec)
    return vps


def extract(dxf_path: Path) -> dict:
    sheet = dxf_path.stem
    doc = ezdxf.readfile(str(dxf_path))
    read, written, skipped = Counter(), Counter(), Counter()
    ents = []

    msp = doc.modelspace()
    for e in msp:
        walk(e, "model", "top", ents, read, written, skipped)

    layouts = {}
    viewports = []
    for name in doc.layouts.names():
        if name == "Model":
            continue
        lay = doc.layouts.get(name)
        space = f"paper:{name}"
        start = len(ents)
        texts = []
        for e in lay:
            if e.dxftype() == "VIEWPORT":
                read["VIEWPORT"] += 1
                written["VIEWPORT"] += 1
                continue
            if e.dxftype() in ("MTEXT", "TEXT"):
                ip = getattr(e.dxf, "insert", None) or (0, 0, 0)
                texts.append((float(ip[0]), float(ip[1]), mtext_plain(e)))
            walk(e, space, "top", ents, read, written, skipped)
        vps = viewport_records(lay, texts)
        viewports.extend(vps)
        layouts[name] = {
            "type": "paper",
            "entities": len(ents) - start,
            "viewports": len(vps),
            "extents": [_xy(getattr(lay.dxf, "limmin", (0, 0))),
                        _xy(getattr(lay.dxf, "limmax", (0, 0)))],
        }
    layouts["Model"] = {"type": "model",
                        "entities": sum(1 for r in ents if r["space"] == "model")}

    hdr = doc.header
    extmin = hdr.get("$EXTMIN", (0, 0, 0))
    extmax = hdr.get("$EXTMAX", (0, 0, 0))

    # observed extents of the emitted model-space geometry
    xs, ys = [], []
    for r in ents:
        if r["space"] != "model":
            continue
        for p in r.get("pts", ()):
            xs.append(p[0])
            ys.append(p[1])
        if "c" in r and "r" in r:
            xs.extend((r["c"][0] - r["r"], r["c"][0] + r["r"]))
            ys.extend((r["c"][1] - r["r"], r["c"][1] + r["r"]))
    obs = [min(xs), min(ys), max(xs), max(ys)] if xs else [0, 0, 0, 0]

    n_top = sum(1 for r in ents if r["src"] == "top")
    n_blk = len(ents) - n_top
    recon = {
        "read_by_type": dict(sorted(read.items())),
        "written_by_type": dict(sorted(written.items())),
        "read_total": sum(read.values()),
        "written_total": sum(written.values()),
        "skipped_total": sum(skipped.values()),
        "skipped_by_reason": dict(sorted(skipped.items())),
        "entities_top": n_top,
        "entities_from_blocks": n_blk,
        "balanced": sum(read.values()) == sum(written.values()) + sum(skipped.values()),
    }

    return {
        "sheet": sheet,
        "source": str(dxf_path.relative_to(ROOT)),
        "dxfversion": doc.dxfversion,
        "units": int(hdr.get("$INSUNITS", 0) or 0),
        "extents": [_xy(extmin), _xy(extmax)],
        "observed_extents": obs,
        "layers": sorted({r["layer"] for r in ents}),
        "blocks_exploded": sorted({r["src"][6:] for r in ents
                                   if r["src"].startswith("block:")}),
        "layouts": layouts,
        "viewports": viewports,
        "recon": recon,
        "entities": ents,
    }


def dump(data: dict, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(_rnd(data, ROUND), separators=(",", ":"))
    nd = ROUND
    if len(txt.encode()) > SIZE_LIMIT:
        nd = ROUND_COARSE
        txt = json.dumps(_rnd(data, nd), separators=(",", ":"))
    path.write_text(txt)
    return len(txt.encode()), nd


def sheets(argv):
    if argv and argv[0] == "--all":
        return sorted(DXF_DIR.glob("*.dxf"))
    if argv:
        out = []
        for a in argv:
            p = DXF_DIR / (a if a.endswith(".dxf") else a + ".dxf")
            if not p.exists():
                print(f"MISSING {p}")
                continue
            out.append(p)
        return out
    return sorted(set(DXF_DIR.glob("*_R*.dxf")) | set(DXF_DIR.glob("*_S.dxf")))


def main(argv):
    files = sheets(argv)
    print(f"stage1 raw: {len(files)} sheets -> {OUT_DIR}")
    ok, fail = [], []
    grand_r, grand_w, grand_s = Counter(), Counter(), Counter()
    for f in files:
        try:
            data = extract(f)
            size, nd = dump(data, OUT_DIR / f"{data['sheet']}.json")
            rc = data["recon"]
            grand_r.update(rc["read_by_type"])
            grand_w.update(rc["written_by_type"])
            grand_s.update(rc["skipped_by_reason"])
            ok.append((data["sheet"], rc, size, nd, len(data["viewports"])))
            flag = "" if rc["balanced"] else "  ** UNBALANCED **"
            print(f"  {data['sheet']:<22} in={rc['read_total']:>7} "
                  f"out={rc['written_total']:>7} skip={rc['skipped_total']:>4} "
                  f"top={rc['entities_top']:>7} blk={rc['entities_from_blocks']:>6} "
                  f"vp={len(data['viewports']):>2} {size/1e6:>7.1f}MB nd={nd}{flag}")
            if rc["skipped_by_reason"]:
                print(f"      skipped: {rc['skipped_by_reason']}")
        except Exception as exc:
            fail.append((f.stem, f"{type(exc).__name__}: {exc}"))
            print(f"  FAIL {f.stem}: {type(exc).__name__}: {exc}")
            traceback.print_exc()
    print(f"\nok={len(ok)} fail={len(fail)}")
    print(f"read   {sum(grand_r.values())} {dict(sorted(grand_r.items()))}")
    print(f"write  {sum(grand_w.values())} {dict(sorted(grand_w.items()))}")
    print(f"skip   {sum(grand_s.values())} {dict(sorted(grand_s.items()))}")
    for s, r in fail:
        print(f"FAILED {s}: {r}")
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
