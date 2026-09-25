"""Build ground-truth BBS JSON files, one per (R)-variant DWG stem, with
every independent source (R own paper-space table, sibling (S).dwg, any
PDF schedules) extracted SEPARATELY and cross-checked mark-by-mark -- no
silent merging, no staleness filtering. This is a read-only data
extraction script; it does not touch reconstruct.py/cli.py/extract.py/
schedule.py, it only calls their existing public functions.

Run: python3 _build_bbs_truth.py
"""
import json
import re
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rebar3d.loader import dwg_to_dxf
from rebar3d.schedule import extract_itemized_bbs_dwg, find_schedule_pdf, parse_itemized_bbs

DRAWINGS = Path(__file__).resolve().parents[2] / "rebar_data" / "drawings"
DXF_CACHE = Path("/tmp/dxfcache")
OUT_DIR = Path(__file__).resolve().parent

BASE_NAMES = [
    "PC-GF-01", "PW-01-PW-01", "PW-GF-01", "PW-GF-02", "PW-GF-05",
    "PW-GF-06", "PW-GF-07", "PW-GF-08", "PW-GF-09", "PW-GF-11",
    "PW-GF-18", "PW-GF-25", "PW-GF-26", "PW-GF-27", "PW-GF-30",
    "PW-GF-45", "SS-GF-01",
]


def row_to_dict(m):
    d = {
        "mark": m.mark,
        "diameter": m.diameter,
        "shape": m.shape,
        "length_mm": m.length_mm,
        "qty": m.qty,
    }
    if hasattr(m, "weight_kg"):
        d["weight_kg"] = m.weight_kg
    if hasattr(m, "total_length_mm"):
        d["total_length_mm"] = m.total_length_mm
    if hasattr(m, "segments"):
        d["segments"] = m.segments
    if hasattr(m, "location") and m.location:
        d["location"] = m.location
    if hasattr(m, "part") and m.part:
        d["part"] = m.part
    return d


def mtime_gap_days(a: Path, b: Path):
    try:
        return round(abs(a.stat().st_mtime - b.stat().st_mtime) / 86400.0, 2)
    except OSError:
        return None


def extract_r_own(stem_dwg: Path):
    dxf = dwg_to_dxf(stem_dwg, DXF_CACHE)
    rows = extract_itemized_bbs_dwg(dxf)
    return rows or []


def extract_s_dwg(base: str, stem_dwg: Path):
    s_dwg = DRAWINGS / f"{base}(S).dwg"
    if not s_dwg.exists():
        return None
    gap = mtime_gap_days(s_dwg, stem_dwg)
    try:
        dxf = dwg_to_dxf(s_dwg, DXF_CACHE)
        rows = extract_itemized_bbs_dwg(dxf) or []
    except Exception:
        rows = []
    return {"mtime_gap_days": gap, "rows": [row_to_dict(r) for r in rows], "path": str(s_dwg)}


def extract_pdfs(stem_dwg: Path):
    out = {}
    for pdf in find_schedule_pdf(stem_dwg):
        gap = mtime_gap_days(pdf, stem_dwg)
        try:
            rows = parse_itemized_bbs(pdf) or []
        except Exception:
            rows = []
        key = f"pdf:{pdf.name}"
        out[key] = {"mtime_gap_days": gap, "rows": [row_to_dict(r) for r in rows], "path": str(pdf)}
    return out


def fields_agree(rows_for_mark):
    """rows_for_mark: list of (source_name, row_dict). Returns (status, detail)."""
    if len(rows_for_mark) == 0:
        return "SINGLE_SOURCE", "no rows"
    if len(rows_for_mark) == 1:
        src, r = rows_for_mark[0]
        return "SINGLE_SOURCE", f"only in {src}: dia={r['diameter']} shape={r['shape']} len={r['length_mm']} qty={r['qty']}"

    base_src, base = rows_for_mark[0]
    diffs = []
    for src, r in rows_for_mark[1:]:
        row_diffs = []
        if r["diameter"] != base["diameter"]:
            row_diffs.append(f"diameter {base['diameter']}!={r['diameter']}")
        if r["shape"] != base["shape"]:
            row_diffs.append(f"shape '{base['shape']}'!='{r['shape']}'")
        if abs(r["length_mm"] - base["length_mm"]) > 1.0:
            row_diffs.append(f"length_mm {base['length_mm']}!={r['length_mm']}")
        if r["qty"] != base["qty"]:
            row_diffs.append(f"qty {base['qty']}!={r['qty']}")
        if row_diffs:
            diffs.append(f"{base_src} vs {src}: " + "; ".join(row_diffs))

    if not diffs:
        return "AGREE", (
            f"all {len(rows_for_mark)} sources agree: dia={base['diameter']} "
            f"shape={base['shape']} len={base['length_mm']} qty={base['qty']}"
        )
    return "DISAGREE", " | ".join(diffs)


def build_cross_check(sources: dict):
    # sources: name -> list_of_rows (R_own) OR {"rows": [...]} (S_dwg/pdf)
    by_mark: dict[str, list] = {}
    for src_name, payload in sources.items():
        rows = payload if isinstance(payload, list) else payload.get("rows", [])
        for r in rows:
            by_mark.setdefault(r["mark"], []).append((src_name, r))

    cross_check = {}
    for mark, rows_for_mark in sorted(by_mark.items()):
        status, detail = fields_agree(rows_for_mark)
        cross_check[mark] = {"status": status, "detail": detail}
    return cross_check


def discover_stems(base: str):
    pattern = f"{base}(R*.dwg"
    return sorted(DRAWINGS.glob(pattern))


def process_stem(stem_path: Path, base: str):
    stem = stem_path.stem
    sources = {}

    try:
        r_rows = extract_r_own(stem_path)
    except Exception as e:
        r_rows = []
        print(f"  [WARN] R_own extraction failed for {stem}: {e}")
    sources["R_own"] = [row_to_dict(r) for r in r_rows]

    try:
        s_result = extract_s_dwg(base, stem_path)
        if s_result is not None:
            sources["S_dwg"] = s_result
    except Exception as e:
        print(f"  [WARN] S_dwg extraction failed for {stem}: {e}")

    try:
        pdf_results = extract_pdfs(stem_path)
        sources.update(pdf_results)
    except Exception as e:
        print(f"  [WARN] PDF extraction failed for {stem}: {e}")

    cross_check = build_cross_check(sources)

    out = {"stem": stem, "sources": sources, "cross_check": cross_check}
    out_path = OUT_DIR / f"{stem}_bbs_truth.json"
    out_path.write_text(json.dumps(out, indent=2))
    return out, out_path


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_results = []
    n_s = n_pdf = n_r_only = 0
    disagreements = []

    for base in BASE_NAMES:
        stems = discover_stems(base)
        if not stems:
            print(f"[SKIP] {base}: no (R*) dwg found")
            continue
        for stem_path in stems:
            print(f"Processing {stem_path.stem} ...")
            try:
                out, out_path = process_stem(stem_path, base)
            except Exception:
                print(f"  [ERROR] failed on {stem_path.stem}:")
                traceback.print_exc()
                continue
            all_results.append(out)
            has_s = "S_dwg" in out["sources"]
            has_pdf = any(k.startswith("pdf:") for k in out["sources"])
            if has_s:
                n_s += 1
            if has_pdf:
                n_pdf += 1
            if not has_s and not has_pdf:
                n_r_only += 1
            for mark, cc in out["cross_check"].items():
                if cc["status"] == "DISAGREE":
                    disagreements.append((out["stem"], mark, cc["detail"]))
            print(f"  -> wrote {out_path.name} "
                  f"(sources: {list(out['sources'].keys())}, marks: {len(out['cross_check'])})")

    print("\n===== SUMMARY =====")
    print(f"stems processed: {len(all_results)}")
    print(f"  with S_dwg: {n_s}")
    print(f"  with PDF: {n_pdf}")
    print(f"  R_own only: {n_r_only}")
    print(f"\nDISAGREEMENTS ({len(disagreements)}):")
    for stem, mark, detail in disagreements:
        print(f"  {stem} / {mark}: {detail}")


if __name__ == "__main__":
    sys.exit(main())
