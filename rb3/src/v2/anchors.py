"""Extract cast-in lifting anchor hardware (spread anchors / lifting inserts)
from the (M) mould drawings, additive to and separate from the rebar pipeline.

An anchor appears in the DXF as an INSERT of a block whose name encodes its
type, e.g.

    RR spread anchor face based - RR-SA-2_5-200-1726821-Elevation Front
    12_7Ø_ Lifting Insert_COLUMN - 12_9Ø Lifting insert-1653057-3D Ortho

The trailing segment (``Elevation Front`` / ``Elevation Right`` / ``Elevation
Top`` / ``3D Ortho`` / ``Detail N``) is NOT a separate physical anchor -- it
is which detail-view representation of the block library this particular
INSERT renders. Revit re-exports the *same* physical anchor once per
viewport that shows the panel, so a panel drawn in an ELEVATION viewport and
a SECTION viewport carries two INSERTs per real anchor, at the same physical
point but in each viewport's own local drawing patch of modelspace.

Confirmed empirically (see investigation notes / PW-GF-01): an M2 sheet's
"Insert Schedule" MTEXT table (Ref No / Type / Count) gives verified,
human-checked totals per anchor type for that element. Extracting anchor
INSERTs from ONLY the panel's single largest ELEVATION viewport (mirroring
assemble.classify's own view classification), clustering by the visual
centre of each block reference (ezdxf virtual_entities bbox -- the INSERT's
own dxf.insert base point is an arbitrary block-family origin, often far
from the drawn symbol), reproduces the Insert Schedule counts exactly. That
is the dedup method used here: one viewport, bbox-centre clustering.

Depth (Y, through panel thickness) is recovered, not fabricated, from the
element's end_cut/plan_cut viewport where present -- the same anchors are
drawn a second time there and their local coordinate along that view's
in-plane axis gives real thickness position, matched to the elevation
instance by height (Z) proximity. Where no such view exists, depth falls
back to panel mid-thickness and is flagged "assumed_mid_thickness".
"""
from __future__ import annotations

import glob
import json
import re
import sys
import collections
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import ezdxf                       # noqa: E402
from ezdxf import bbox as EBB      # noqa: E402
import rbar                        # noqa: E402
import assemble as A               # noqa: E402
import elements as EL              # noqa: E402

ANCHOR_LAYER = {"A-GENM", "A-GENM-HDLN"}
ANCHOR_NAME_RE = re.compile(
    r"spread anchor|lifting insert|RR-SA|lifting anchor", re.I)

RR_RE = re.compile(
    r"^RR spread anchor face based - RR-SA-(?P<cap>[\d_]+)-(?P<embed>\d+)-"
    r"(?P<id>[^-]+)-(?P<suffix>.+)$", re.I)
LIFT_RE = re.compile(
    r"^(?P<d1>[\d_]+)Ø_?\s*Lifting Insert_COLUMN - (?P<d2>[\d_]+)Ø"
    r"\s*Lifting insert-(?P<id>[^-]+)-(?P<suffix>.+)$", re.I)

CLUSTER_TOL = 60.0      # mm: two INSERTs closer than this = same physical anchor
Z_MATCH_TOL = 80.0      # mm: matching an elevation instance to a section-view depth reading


def parse_block(name):
    m = RR_RE.match(name)
    if m:
        cap = float(m.group("cap").replace("_", "."))
        return {"family": "RR-SA", "capacity_t": cap,
                "embed_length_mm": int(m.group("embed")),
                "type_key": f"RR-SA-{m.group('cap')}-{m.group('embed')}",
                "ref_id": m.group("id"), "view_suffix": m.group("suffix"),
                "source_block": name}
    m = LIFT_RE.match(name)
    if m:
        return {"family": "lifting_insert", "capacity_t": None,
                "embed_length_mm": None,
                "type_key": f"LIFT-{m.group('d2')}",
                "ref_id": m.group("id"), "view_suffix": m.group("suffix"),
                "source_block": name}
    return {"family": "unknown", "capacity_t": None, "embed_length_mm": None,
            "type_key": "UNKNOWN:" + name[:40], "ref_id": None,
            "view_suffix": None, "source_block": name}


def insert_center(e):
    """Real drawn location of a block reference: bbox centre of its virtual
    geometry, not e.dxf.insert (an arbitrary family-origin base point that is
    frequently offset far from the symbol actually drawn)."""
    try:
        ents = list(e.virtual_entities())
        bb = EBB.extents(ents)
        if bb.has_data:
            return ((bb.extmin.x + bb.extmax.x) / 2.0,
                    (bb.extmin.y + bb.extmax.y) / 2.0)
    except Exception:
        pass
    return (e.dxf.insert.x, e.dxf.insert.y)


def raw_anchor_inserts(doc):
    out = []
    for e in doc.modelspace():
        if e.dxftype() != "INSERT":
            continue
        if e.dxf.layer not in ANCHOR_LAYER:
            continue
        if not ANCHOR_NAME_RE.search(e.dxf.name):
            continue
        cx, cy = insert_center(e)
        info = parse_block(e.dxf.name)
        out.append({**info, "cx": cx, "cy": cy})
    return out


def cluster(points, tol=CLUSTER_TOL):
    """Greedy proximity clustering of 2D points -> list of cluster member-index lists."""
    used = [False] * len(points)
    clusters = []
    for i in range(len(points)):
        if used[i]:
            continue
        grp = [i]
        used[i] = True
        for j in range(i + 1, len(points)):
            if used[j]:
                continue
            if abs(points[j][0] - points[i][0]) <= tol and abs(points[j][1] - points[i][1]) <= tol:
                grp.append(j)
                used[j] = True
        clusters.append(grp)
    return clusters


def best_view(vlist, kinds):
    cands = [v for v in vlist if v["kind"] in kinds]
    if not cands:
        return None
    return max(cands, key=lambda v: v["w"] * v["h"])


def anchors_in_view(inserts, view):
    """Anchor inserts whose drawn centre lies inside a classified view's box."""
    wb = view["wall"]
    out = []
    for a in inserts:
        if rbar.in_box((a["cx"], a["cy"]), view["box"], pad=25.0):
            out.append({**a, "local_x": a["cx"] - wb[0], "local_z": a["cy"] - wb[1]})
    return out


def extract_from_doc(doc, env_hint=None):
    """One M-sheet doc -> deduped anchor list with panel-local (x, y, z), mm.

    Primary source: the single largest ELEVATION viewport, bbox-centre
    clustered (one cluster = one physical anchor). Depth is cross-read from
    the largest end_cut/plan_cut viewport by matching height; falls back to
    mid-thickness, flagged.
    """
    vlist = A.classify(doc)
    env = A.panel_envelope(vlist)
    elev = best_view(vlist, ("elevation",))
    if elev is None:
        return [], env, "no_elevation_view"

    inserts = raw_anchor_inserts(doc)
    in_elev = anchors_in_view(inserts, elev)
    if not in_elev:
        return [], env, "no_anchors_in_elevation"

    pts = [(a["local_x"], a["local_z"]) for a in in_elev]
    clusters = cluster(pts)

    depth_view = best_view(vlist, ("end_cut", "plan_cut"))
    depth_pts = []
    if depth_view is not None:
        in_depth = anchors_in_view(inserts, depth_view)
        # end_cut: view["wall"] local x-axis == Y (depth); local_z == Z (height), matches end_bars()
        # plan_cut: local x-axis == X (width); local_z == Y (depth), matches plan_bars() naming
        for a in in_depth:
            if depth_view["kind"] == "end_cut":
                depth_pts.append((a["local_z"], a["local_x"]))   # (z, y)
            else:  # plan_cut
                depth_pts.append((None, a["local_z"]))           # no z reference available

    thickness = env.get("thickness_mm") or 0.0
    out = []
    for grp in clusters:
        members = [in_elev[i] for i in grp]
        # prefer a member whose block name carries type info over "unknown"
        members.sort(key=lambda m: 0 if m["family"] != "unknown" else 1)
        rep = members[0]
        x = sum(m["local_x"] for m in members) / len(members)
        z = sum(m["local_z"] for m in members) / len(members)
        y, y_src = None, "assumed_mid_thickness"
        best_dz = None
        for dz, dy in depth_pts:
            if dz is None:
                continue
            d = abs(dz - z)
            if d <= Z_MATCH_TOL and (best_dz is None or d < best_dz):
                best_dz, y = d, dy
                y_src = "section_view"
        if y is None:
            y = thickness / 2.0
        out.append({
            "type_key": rep["type_key"], "family": rep["family"],
            "capacity_t": rep["capacity_t"], "embed_length_mm": rep["embed_length_mm"],
            "source_block": rep["source_block"],
            "n_view_duplicates": len(members),
            "pt": [round(x, 1), round(y, 1), round(z, 1)],
            "depth_source": y_src,
        })
    out.sort(key=lambda a: (a["pt"][2], a["pt"][0]))
    return out, env, "ok"


# ---------------------------------------------------------------------- #
# Insert Schedule table (ground-truth counts printed on the M-sheet)
# ---------------------------------------------------------------------- #

def parse_insert_schedule(doc):
    """Read the 'Insert Schedule' MTEXT table (Ref No / Type / Count) if present.

    The sheet's title block/legend often sits at a nearly-identical y to the
    table rows but in unrelated columns further to the right (e.g. "GRADE OF
    CONCRETE" / "- M40" beside "N1 RR-SA-3.0-200 2"). Grouping cells by y
    alone pulls those stray columns into a table row and corrupts the count
    (a legend value like "- M40" becomes count 40). Cells are therefore first
    assigned to the nearest of the three known column x-positions (Ref No /
    Type / Count, read off the header row) and discarded if they are not
    close to any of them.
    """
    try:
        lay = doc.layout("Layout1")
    except Exception:
        return []
    rows = []
    for e in lay:
        if e.dxftype() != "MTEXT":
            continue
        t = " ".join(e.text.replace("\\P", " ").split())
        if not t:
            continue
        rows.append((e.dxf.insert.x, e.dxf.insert.y, t))
    header = next((r for r in rows if r[2].strip() == "Insert Schedule"), None)
    if header is None:
        return []
    hy = header[1]
    col_hdr = {r[2].strip(): r[0] for r in rows
               if abs(r[1] - hy) < 12 and r[1] < hy
               and r[2].strip() in ("Ref No.", "Type", "Count")}
    if len(col_hdr) < 3:
        return []
    col_x = {"ref": col_hdr["Ref No."], "type": col_hdr["Type"], "count": col_hdr["Count"]}
    col_names = list(col_x.items())
    max_col_x = max(col_x.values())

    band = [r for r in rows if r[1] < hy - 4 and r[0] <= max_col_x + 15]
    band.sort(key=lambda r: -r[1])
    out = []
    cur_y = None
    row_cells = []
    for x, y, t in band:
        if t.strip() in ("Ref No.", "Type", "Count"):
            continue
        if "Schedule" in t or t.strip().startswith("\\L"):
            break  # next table section
        # discard anything not plausibly in one of the three columns
        if min(abs(x - cx) for _, cx in col_names) > 20:
            continue
        if cur_y is None or abs(y - cur_y) > 3:
            if row_cells:
                out.append(row_cells)
            row_cells = []
            cur_y = y
        col = min(col_names, key=lambda kv: abs(x - kv[1]))[0]
        row_cells.append((col, t))
    if row_cells:
        out.append(row_cells)
    entries = []
    for cells in out:
        d = dict(cells)
        if not all(k in d for k in ("ref", "type", "count")):
            continue
        try:
            cnt_i = int(re.sub(r"[^\d]", "", d["count"]))
        except ValueError:
            continue
        entries.append({"ref": d["ref"], "type": d["type"], "count": cnt_i})
    return entries


# ---------------------------------------------------------------------- #
# Per-panel driver
# ---------------------------------------------------------------------- #

def panel_names():
    files = sorted(glob.glob(str(ROOT / "dxf" / "*.dxf")))
    names = sorted({re.sub(r"_(M\d?|R\d?|S)$", "", Path(f).stem) for f in files})
    return names


def sheets_for(panel):
    return sorted(glob.glob(str(ROOT / "dxf" / f"{panel}_*.dxf")))


def _sheet_env(path):
    try:
        doc = ezdxf.readfile(path)
    except Exception:
        return None
    vl = A.classify(doc)
    env = A.panel_envelope(vl)
    if not env.get("height_mm") or not env.get("thickness_mm"):
        return None
    return {"sheet": Path(path).stem, "doc": doc, "env": env}


def canonical_elements(panel, paths):
    """The panel's real distinct physical elements.

    Trusts R-sheet envelopes first -- elements.py's splitting is already
    verified for rebar binding on exactly this data. When a panel has no R
    sheet at all (most of this set: only 15 panels carry a rebar drawing),
    falls back to its M1 (or unsuffixed M) sheet, which -- unlike M2/M3 -- is
    consistently a full elevation+section profile of the whole element, not
    a partial corbel/end/schedule-table sheet. M2/M3 measure only a partial
    region (e.g. a corner detail) and are NOT used to seed new elements;
    they get fuzzy-matched onto a canonical element below instead.
    """
    r_paths = [p for p in paths if re.search(r"_R\d?\.dxf$", p)]
    seed_paths = r_paths
    if not seed_paths:
        # "_M1" is this project's reliable full elevation+section profile
        # sheet; "_M2"/"_M3" are partial detail/section-table sheets that
        # must NOT seed new elements (fuzzy-matched onto M1's element below).
        # An unnumbered "_M" that coexists with "_M1" (e.g. PW-GF-23) is a
        # stray duplicate/superseded export, not a second element, so "_M1"
        # wins when both exist.
        seed_paths = [p for p in paths if re.search(r"_M1\.dxf$", p)]
    if not seed_paths:
        seed_paths = [p for p in paths if re.search(r"_M\.dxf$", p)]
    if not seed_paths:
        seed_paths = paths
    return EL.candidates(panel, seed_paths)


def assign_sheet(env, canon):
    """Nearest canonical element for one sheet's envelope, by height+thickness.

    Width is deliberately ignored: M2/M3 "elevation" viewports are often a
    partial-width detail crop, but height and wall thickness are stable
    across every sheet of the same physical element.
    """
    best, best_score = None, 1e9
    for i, c in enumerate(canon):
        ch = c["env"]["height_mm"]; ct = c["env"]["thickness_mm"] or 0
        eh = env["height_mm"]; et = env["thickness_mm"] or 0
        if not ch or ct is None:
            continue
        dh = abs(eh - ch) / max(ch, 1)
        dt = abs(et - ct)
        if dh > 0.3 or dt > max(30, 0.3 * ct):
            continue
        score = dh + dt / 100.0
        if score < best_score:
            best, best_score = i, score
    return best


def process_panel(panel, report):
    paths = sheets_for(panel)
    if not paths:
        return
    canon = canonical_elements(panel, paths)
    n = len(canon)
    groups = [{"canon": c, "sheets": [{"sheet": c["sheet"], "doc": c["doc"], "env": c["env"]}]}
              for c in canon]

    seeded_sheets = {c["sheet"] for c in canon}
    for p in paths:
        stem = Path(p).stem
        if stem in seeded_sheets or stem.endswith("_S"):
            continue
        se = _sheet_env(p)
        if se is None:
            continue
        idx = assign_sheet(se["env"], canon)
        if idx is None:
            continue
        groups[idx]["sheets"].append(se)

    for g in groups:
        cand = g["canon"]
        name = EL.element_name(panel, cand, n)
        docs_m, docs_r = [], []
        for c in g["sheets"]:
            (docs_m if re.search(r"_M\d?$", c["sheet"]) else docs_r).append(c)
        def _m_sort_key(c):
            m = re.search(r"_M(\d)?$", c["sheet"])
            return int(m.group(1)) if m and m.group(1) else 99  # numbered M1..M9 before bare M
        docs_m.sort(key=_m_sort_key)

        chosen, anchors, env, status, src_sheet = None, [], cand["env"], "no_anchors_found", None
        for c in docs_m:
            a, e, st = extract_from_doc(c["doc"])
            if st == "ok" and a:
                anchors, env, status, src_sheet = a, e, st, c["sheet"]
                chosen = c
                break
            elif st != "ok" and status == "no_anchors_found":
                status = st

        cross_r = None
        for c in docs_r:
            a, e, st = extract_from_doc(c["doc"])
            if st == "ok" and a:
                cross_r = {"sheet": c["sheet"], "n": len(a),
                           "by_type": dict(collections.Counter(x["type_key"] for x in a))}
                if chosen is None:
                    anchors, env, status, src_sheet = a, e, st, c["sheet"]
                break

        # ground-truth Insert Schedule, searched across every sheet of this element
        schedule = []
        for c in docs_m + docs_r:
            sched = parse_insert_schedule(c["doc"])
            if sched:
                schedule = sched
                break

        by_type = collections.Counter(a["type_key"] for a in anchors)
        sched_anchor_rows = [s for s in schedule
                              if re.search(r"RR-SA|lifting insert", s["type"], re.I)
                              and "dowel" not in s["type"].lower()]
        sched_total = sum(s["count"] for s in sched_anchor_rows)

        report["elements"].append({
            "element": name, "panel": panel, "source_sheet": src_sheet,
            "sheets_used": [c["sheet"] for c in g["sheets"]],
            "status": status, "n_anchors": len(anchors),
            "by_type": dict(by_type),
            "schedule_rows": sched_anchor_rows,
            "schedule_total": sched_total,
            "cross_check_R": cross_r,
            "env": env,
        })

        out_path = ROOT / "out" / "v2" / "anchors" / f"{name}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({
            "element": name, "panel": panel, "sheet": src_sheet,
            "sheets_considered": [c["sheet"] for c in g["sheets"]],
            "envelope": env, "anchors": anchors,
            "insert_schedule": sched_anchor_rows,
        }, indent=2))


def main():
    out_dir = ROOT / "out" / "v2" / "anchors"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"elements": []}
    for panel in panel_names():
        try:
            process_panel(panel, report)
        except Exception as ex:
            report["elements"].append({"element": panel, "panel": panel,
                                        "status": f"error: {ex}", "n_anchors": 0,
                                        "by_type": {}})

    total = sum(e["n_anchors"] for e in report["elements"])
    by_type_all = collections.Counter()
    for e in report["elements"]:
        for k, v in e["by_type"].items():
            by_type_all[k] += v

    lines = []
    lines.append("Cast-in lifting anchor extraction report")
    lines.append("=" * 60)
    lines.append(f"Elements processed : {len(report['elements'])}")
    lines.append(f"Total anchors found: {total}")
    lines.append("")
    lines.append("By type:")
    for k, v in sorted(by_type_all.items()):
        lines.append(f"  {k:30s} {v:4d}")
    lines.append("")
    lines.append("By element:")
    mismatches = []
    zero_geo_with_schedule = []
    for e in report["elements"]:
        tag = ""
        if e.get("schedule_total") and e["n_anchors"] != e["schedule_total"]:
            tag = f"  ** MISMATCH geometry={e['n_anchors']} schedule={e['schedule_total']} **"
            mismatches.append(e)
        cr = e.get("cross_check_R")
        cr_tag = ""
        if cr and cr["n"] != e["n_anchors"]:
            cr_tag = f"  (R-sheet cross-check found {cr['n']}, differs)"
        lines.append(f"  {e['element']:35s} n={e['n_anchors']:3d} "
                      f"sheet={e.get('source_sheet')!s:16s} status={e['status']}{tag}{cr_tag}")
        if e["n_anchors"] == 0 and e.get("schedule_total"):
            zero_geo_with_schedule.append(e)

    lines.append("")
    lines.append(f"Elements with a schedule/geometry count mismatch: {len(mismatches)}")
    for e in mismatches:
        lines.append(f"  {e['element']}: geometry={e['n_anchors']} vs schedule={e['schedule_total']}")
    lines.append("")
    lines.append(f"Elements where a schedule exists but zero anchors were located in geometry: {len(zero_geo_with_schedule)}")
    for e in zero_geo_with_schedule:
        lines.append(f"  {e['element']}")

    (ROOT / "out" / "v2" / "anchor_report.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:20]))
    print(f"... wrote out/v2/anchor_report.txt and {len(report['elements'])} element JSONs to out/v2/anchors/")


if __name__ == "__main__":
    main()
