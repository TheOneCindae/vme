"""Third, independent evidence check for the 67 rows confirmed absent by
BOTH the pipeline's own line-pairing AND the permissive re-pairing pass.

This does NOT reuse pair_lines/extract_bars/loose_pairs at all -- it is a
different signal entirely: DIMENSION entities (explicit measured lengths
AutoCAD/Revit stamped into the drawing) and HATCH entities (solid-fill
bar/section representations), neither of which load_entities() has ever
captured (it only builds LINE/ARC/CIRCLE/LWPOLYLINE/TEXT/INSERT, and only
from modelspace -- paperspace layouts are never read at all). If a
DIMENSION's measured value equals a "confirmed absent" mark's declared
length, that is direct, decisive evidence the length is really drawn in
the file -- the line-pairing step is just failing to synthesize it into a
Bar2D, not that the steel is undrawn.

For every layout (modelspace + all paperspace layouts) in every member
stem of a dead-end panel, collect:
  - every DIMENSION's measured value (rounded)
  - every HATCH's bounding-box diagonal and long-axis extent

Then match those against each CONFIRMED_ABSENT row's declared length.
"""
import math
import re
import sys
from pathlib import Path

import ezdxf

sys.path.insert(0, ".")
from rebar3d.loader import dwg_to_dxf

ROOT = Path("/Users/jonathan/elco/vme/rebar3d")
DRAWINGS = Path("/Users/jonathan/elco/vme/DRAWINGS")
CACHE = Path("/tmp/dxfcache")

STEMS_BY_PANEL = {
    "PC-GF-01": ["PC-GF-01(R)"],
    "PW-01-PW-01": ["PW-01-PW-01(R)"],
    "PW-GF-01": ["PW-GF-01(R)"],
    "PW-GF-02": ["PW-GF-02(R)"],
    "PW-GF-06": ["PW-GF-06(R)"],
    "PW-GF-07": ["PW-GF-07(R)"],
    "PW-GF-09": ["PW-GF-09(R)"],
    "PW-GF-18": ["PW-GF-18(R)"],
    "PW-GF-25": ["PW-GF-25(R)"],
    "PW-GF-26": ["PW-GF-26(R)"],
    "PW-GF-45": ["PW-GF-45(R)"],
    "SS-GF-01": ["SS-GF-01(R)"],
    "PW-GF-05": ["PW-GF-05(R1)", "PW-GF-05(R2)"],
    "PW-GF-08": ["PW-GF-08(R1)", "PW-GF-08(R2)"],
    "PW-GF-09-combo": ["PW-GF-09(R1)", "PW-GF-09(R2)"],
    "PW-GF-11": ["PW-GF-11(R1)", "PW-GF-11(R2)"],
    "PW-GF-27": ["PW-GF-27(R1)", "PW-GF-27(R2)"],
    "PW-GF-30": ["PW-GF-30(R1)", "PW-GF-30(R2)"],
}


def tol(length_mm):
    return max(30.0, 0.08 * length_mm)


def collect_signals(stem):
    dxf = dwg_to_dxf(DRAWINGS / f"{stem}.dwg", CACHE)
    doc = ezdxf.readfile(str(dxf))
    dim_values = []
    hatch_extents = []
    for layout_name in [l.name for l in doc.layouts]:
        layout = doc.layout(layout_name) if layout_name != "Model" else doc.modelspace()
        for e in layout:
            t = e.dxftype()
            if t == "DIMENSION":
                try:
                    v = e.get_measurement()
                    if isinstance(v, (int, float)) and 20 < v < 15000:
                        dim_values.append((layout_name, round(v, 1)))
                except Exception:
                    pass
            elif t == "HATCH":
                try:
                    xs, ys = [], []
                    for path in e.paths:
                        for v in getattr(path, "vertices", []):
                            xs.append(v[0]); ys.append(v[1])
                    if xs and ys:
                        w, h = max(xs) - min(xs), max(ys) - min(ys)
                        diag = math.hypot(w, h)
                        long_axis = max(w, h)
                        hatch_extents.append((layout_name, round(long_axis, 1), round(diag, 1)))
                except Exception:
                    pass
    return dim_values, hatch_extents


def main():
    recheck = Path(ROOT / "out_groundtruth" / "_permissive_recheck.txt").read_text().splitlines()
    dead_rows = []
    section = None
    for l in recheck:
        if l.startswith("CONFIRMED_ABSENT"):
            section = "dead"
            continue
        if section == "dead":
            m = re.match(r"\s+(\S.*?)\s{2,}(\S+)\s+T(\d+)\s+need=(\d+)\s+len=(\d+)\s+have=(\d+)", l)
            if m:
                panel, mark, dia, need, length, have = m.groups()
                dead_rows.append((panel.strip(), mark, int(dia), int(need), float(length), int(have)))

    print(f"Checking {len(dead_rows)} CONFIRMED_ABSENT rows against DIMENSION/HATCH signals...\n")

    cache = {}
    hits, misses = [], []
    for panel, mark, dia, need, length, have in dead_rows:
        stems = STEMS_BY_PANEL.get(panel, [])
        all_dims, all_hatches = [], []
        for stem in stems:
            if stem not in cache:
                cache[stem] = collect_signals(stem)
            d, h = cache[stem]
            all_dims.extend(d)
            all_hatches.extend(h)

        t = tol(length)
        dim_hits = [(ln, v) for ln, v in all_dims if abs(v - length) <= t]
        hatch_hits = [(ln, la, dg) for ln, la, dg in all_hatches if abs(la - length) <= t or abs(dg - length) <= t]

        if dim_hits or hatch_hits:
            hits.append((panel, mark, dia, need, length, have, dim_hits, hatch_hits))
            print(f"  HIT  {panel:<18} {mark:<6} T{dia:<3} len={length:<7.0f} "
                  f"dim_matches={len(dim_hits)} hatch_matches={len(hatch_hits)}  "
                  f"{'DIMS:'+str(dim_hits) if dim_hits else ''} {'HATCH:'+str(hatch_hits) if hatch_hits else ''}")
        else:
            misses.append((panel, mark, dia, need, length, have))

    print(f"\n\n===== SUMMARY =====")
    print(f"{len(hits)} rows have DIMENSION/HATCH corroboration (third independent signal, real gap confirmed)")
    print(f"{len(misses)} rows still show zero evidence across all three independent checks")

    out = ROOT / "out_groundtruth" / "_dimension_hatch_recheck.txt"
    lines = ["DIMENSION/HATCH_EVIDENCE (third independent signal -- reclassify from DEAD END):"]
    for panel, mark, dia, need, length, have, dim_hits, hatch_hits in hits:
        lines.append(f"  {panel:<18} {mark:<6} T{dia:<3} need={need:<3} len={length:<7.0f} have={have:<3} "
                      f"dims={dim_hits} hatches={hatch_hits}")
    lines.append("\nSTILL_CONFIRMED_ABSENT (zero evidence across three independent checks):")
    for panel, mark, dia, need, length, have in misses:
        lines.append(f"  {panel:<18} {mark:<6} T{dia:<3} need={need:<3} len={length:<7.0f} have={have:<3}")
    out.write_text("\n".join(lines))
    print(f"\nWritten to {out}")


if __name__ == "__main__":
    main()
