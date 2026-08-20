"""Independent, unfiltered ground-truth raw-geometry inventory.

Bypasses the normal reconstruction pipeline's clustering/pairing gate
selection: for every DWG stem in PANELS, extracts bar candidates two ways
(clustered = current pipeline behavior; unclustered = extract_bars run over
the ENTIRE unfiltered entity list, ignoring cluster_views entirely) and
dumps them to per-stem JSON files for later comparison against what the
real pipeline currently reconstructs.

READ-ONLY with respect to the rebar3d package: only imports/calls existing
loader/views/extract/reconstruct functions, never modifies them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rebar3d.loader import dwg_to_dxf, load_entities
from rebar3d.views import cluster_views
from rebar3d.extract import extract_bars, snap_diameter

DRAWINGS = Path("/Users/jonathan/elco/vme/DRAWINGS")
DXF_CACHE = Path("/tmp/dxfcache")
OUT_DIR = Path(__file__).resolve().parent

# Same panel list used elsewhere in this project (evidence_sweep.py) -- reused
# verbatim rather than re-invented, with combo members flattened into a plain
# stem list annotated with their combo label for reporting purposes.
PANEL_GROUPS: list[tuple[str, list[str]]] = [
    ("PC-GF-01(R)", ["PC-GF-01(R)"]),
    ("PW-01-PW-01(R)", ["PW-01-PW-01(R)"]),
    ("PW-GF-01(R)", ["PW-GF-01(R)"]),
    ("PW-GF-02(R)", ["PW-GF-02(R)"]),
    ("PW-GF-06(R)", ["PW-GF-06(R)"]),
    ("PW-GF-07(R)", ["PW-GF-07(R)"]),
    ("PW-GF-09(R)", ["PW-GF-09(R)"]),
    ("PW-GF-18(R)", ["PW-GF-18(R)"]),
    ("PW-GF-25(R)", ["PW-GF-25(R)"]),
    ("PW-GF-26(R)", ["PW-GF-26(R)"]),
    ("PW-GF-45(R)", ["PW-GF-45(R)"]),
    ("SS-GF-01(R)", ["SS-GF-01(R)"]),
    ("PW-GF-05", ["PW-GF-05(R1)", "PW-GF-05(R2)"]),
    ("PW-GF-08", ["PW-GF-08(R1)", "PW-GF-08(R2)"]),
    ("PW-GF-09-combo", ["PW-GF-09(R1)", "PW-GF-09(R2)"]),
    ("PW-GF-11", ["PW-GF-11(R1)", "PW-GF-11(R2)"]),
    ("PW-GF-27", ["PW-GF-27(R1)", "PW-GF-27(R2)"]),
    ("PW-GF-30", ["PW-GF-30(R1)", "PW-GF-30(R2)"]),
]


def pt(p):
    if len(p) == 2:
        return {"x": p[0], "y": p[1]}
    return {"x": p[0], "y": p[1], "z": p[2]}


def layer_for_bar(bar, source_ents):
    """Best-effort layer tag: bars come from S-RBAR only (extract_bars
    filters view_ents to layer == "S-RBAR" before pairing), so every
    candidate's underlying geometry is on S-RBAR by construction.
    """
    return "S-RBAR"


def bars_to_dicts(bars, source_pass, cluster_index):
    out = []
    for b in bars:
        d_raw = b.diameter
        d_snap = snap_diameter(d_raw)
        start = b.points[0]
        end = b.points[-1]
        out.append({
            "diameter_raw": round(d_raw, 3),
            "diameter_snapped": d_snap,
            "length_mm": round(b.length, 2),
            "start_point": pt(start),
            "end_point": pt(end),
            "layer": "S-RBAR",
            "source_pass": source_pass,
            "cluster_index": cluster_index,
        })
    return out


def process_stem(stem: str) -> dict | None:
    dwg_path = DRAWINGS / f"{stem}.dwg"
    if not dwg_path.exists():
        print(f"  [SKIP] {stem}: DWG not found at {dwg_path}")
        return None
    try:
        dxf_path = dwg_to_dxf(dwg_path, DXF_CACHE)
        ents = load_entities(dxf_path)
    except Exception as exc:
        print(f"  [FAIL] {stem}: load/convert error: {exc}")
        return None

    candidates = []

    # Pass 1: clustered (matches current pipeline behavior)
    try:
        views = cluster_views(ents)
        for idx, v in enumerate(views):
            bars = extract_bars(v.ents, min_len=50.0)
            candidates.extend(bars_to_dicts(bars, "clustered", idx))
    except Exception as exc:
        print(f"  [WARN] {stem}: clustered pass error: {exc}")

    # Pass 2: unclustered ground truth -- extract_bars over ALL entities,
    # bypassing cluster_views entirely.
    try:
        bars_full = extract_bars(ents, min_len=50.0)
        candidates.extend(bars_to_dicts(bars_full, "unclustered", None))
    except Exception as exc:
        print(f"  [WARN] {stem}: unclustered pass error: {exc}")

    summary: dict[str, dict[str, int]] = {}
    for c in candidates:
        d = c["diameter_snapped"]
        key = str(d) if d is not None else "unsnapped"
        bucket = summary.setdefault(key, {"clustered_count": 0, "unclustered_count": 0})
        if c["source_pass"] == "clustered":
            bucket["clustered_count"] += 1
        else:
            bucket["unclustered_count"] += 1

    result = {
        "stem": stem,
        "dxf_source": str(dxf_path),
        "candidates": candidates,
        "summary_by_diameter": summary,
    }
    out_path = OUT_DIR / f"{stem}_raw_geometry.json"
    out_path.write_text(json.dumps(result, indent=2))
    n_clustered = sum(1 for c in candidates if c["source_pass"] == "clustered")
    n_unclustered = sum(1 for c in candidates if c["source_pass"] == "unclustered")
    print(f"  [OK] {stem}: {n_clustered} clustered / {n_unclustered} unclustered candidates -> {out_path.name}")
    return result


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    processed, skipped = [], []
    for combo_label, members in PANEL_GROUPS:
        print(f"\n=== {combo_label} ===")
        for stem in members:
            res = process_stem(stem)
            if res is None:
                skipped.append(stem)
            else:
                processed.append(stem)

    # Batch-wide summary across unclustered pass
    grand_unclustered: dict[str, int] = {}
    for stem in processed:
        p = OUT_DIR / f"{stem}_raw_geometry.json"
        data = json.loads(p.read_text())
        for dia, counts in data["summary_by_diameter"].items():
            grand_unclustered[dia] = grand_unclustered.get(dia, 0) + counts["unclustered_count"]

    print("\n\n===== BATCH SUMMARY =====")
    print(f"Processed OK: {len(processed)}")
    print(f"Skipped/failed: {len(skipped)} -> {skipped}")
    print("\nUnclustered-pass candidate counts by diameter (all stems combined):")
    for dia in sorted(grand_unclustered, key=lambda k: (k == "unsnapped", float(k) if k != "unsnapped" else 0)):
        print(f"  {dia:>10}: {grand_unclustered[dia]}")

    summary_path = OUT_DIR / "_batch_summary.json"
    summary_path.write_text(json.dumps({
        "processed": processed,
        "skipped": skipped,
        "grand_unclustered_by_diameter": grand_unclustered,
    }, indent=2))
    print(f"\nBatch summary written to {summary_path}")


if __name__ == "__main__":
    main()
