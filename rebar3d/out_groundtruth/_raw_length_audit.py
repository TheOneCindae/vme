"""For every panel and every diameter with a weight gap, compute the total
raw pre-chain candidate length (pair_lines + pair_arcs, whole file, every
view) and compare against the official schedule's implied total length.

This is the same decisive check just done by hand for PW-GF-09's T16
(40,645mm raw vs ~75,000mm implied demand -- a genuine drawing-level
shortfall, not a pipeline bug) generalized across the whole batch.

Verdict per (panel, diameter):
  SHORTFALL     -- raw candidate length < official implied length: the
                   drawing itself doesn't contain enough double-line
                   geometry to close this gap, no matter how the pipeline
                   assembles it.
  RECOVERABLE   -- raw candidate length >= official implied length but the
                   pipeline's reconstructed weight is still short: the
                   steel IS drawn, something in assembly/dedup/capping is
                   losing it. Worth deeper per-mark investigation.
"""
import sys
from pathlib import Path

sys.path.insert(0, ".")
from rebar3d.loader import dwg_to_dxf, load_entities
from rebar3d.extract import pair_lines, pair_arcs, snap_diameter
from rebar3d.schedule import extract_schedule_dwg, find_schedule_pdf, extract_schedule

ROOT = Path("/Users/jonathan/elco/vme/rebar3d")
DRAWINGS = Path("/Users/jonathan/elco/vme/DRAWINGS")
DXF_CACHE = Path("/tmp/dxfcache")
OUT = ROOT / "out"

UNIT_W = {6: 0.222, 8: 0.395, 10: 0.617, 12: 0.888, 16: 1.578, 20: 2.466, 25: 3.854, 32: 6.313}

PANELS = {
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


def raw_length_by_dia(stem: str) -> dict[int, float]:
    dxf = dwg_to_dxf(DRAWINGS / f"{stem}.dwg", DXF_CACHE)
    ents = load_entities(dxf)
    rbar = [e for e in ents if e.layer == "S-RBAR"]
    bars = pair_lines(rbar, min_len=20.0) + pair_arcs(rbar)
    out: dict[int, float] = {}
    for b in bars:
        d = snap_diameter(b.diameter)
        if d:
            out[d] = out.get(d, 0.0) + b.length
    return out


def official_totals(stem: str):
    """(diameter -> total length mm) from the panel's own official
    schedule (DWG paper space Summary Schedule, else PDF)."""
    src = DRAWINGS / f"{stem}.dwg"
    dxf = dwg_to_dxf(src, DXF_CACHE)
    rows = extract_schedule_dwg(dxf)
    if not rows:
        for pdf in find_schedule_pdf(src):
            rows = extract_schedule(pdf)
            if rows:
                break
    if not rows:
        return None
    out: dict[int, float] = {}
    for r in rows:
        d = snap_diameter(r.diameter)
        if d:
            out[d] = out.get(d, 0.0) + r.length_mm
    return out or None


def main():
    lines = []
    for panel_label, stems in PANELS.items():
        raw_total: dict[int, float] = {}
        for stem in stems:
            for d, ln in raw_length_by_dia(stem).items():
                raw_total[d] = raw_total.get(d, 0.0) + ln

        off = None
        for stem in stems:
            off = official_totals(stem)
            if off:
                break
        if not off:
            lines.append(f"\n=== {panel_label} === (no official schedule found)")
            continue

        lines.append(f"\n=== {panel_label} ===")
        for d in sorted(set(off) | set(raw_total)):
            demand = off.get(d, 0.0)
            raw = raw_total.get(d, 0.0)
            if demand <= 0:
                continue
            pct = 100.0 * raw / demand if demand else 0
            verdict = "SHORTFALL (drawing itself lacks enough geometry)" if raw < demand * 0.95 else "SUFFICIENT (real gap must be in assembly, not source)"
            lines.append(f"  T{d:<3} official_len={demand:>8.0f}mm  raw_candidate_len={raw:>8.0f}mm "
                         f"({pct:>5.1f}%)  {verdict}")

    text = "\n".join(lines)
    print(text)
    (ROOT / "raw_length_audit.txt").write_text(text)
    print(f"\nWritten to {ROOT / 'raw_length_audit.txt'}")


if __name__ == "__main__":
    main()
