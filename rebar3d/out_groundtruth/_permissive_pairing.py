"""Re-test every DEAD_END row from reconciliation_report.txt with a much
more permissive line-pairing pass than extract_bars/pair_lines uses.

The normal pipeline's pair_lines() has several lossy knobs tuned for
building a clean final 3D model: 60mm gap-bridging between dashed/hidden
run fragments, angle/offset rounded into small buckets before grouping,
tol_dia=1.9mm for chaining. Those are reasonable for final reconstruction
but are also exactly where a real bar's evidence could get fragmented
below the noise floor and look like "no evidence" without actually being
absent from the drawing.

This script re-derives raw parallel-line pairs directly with looser
settings (500mm gap bridging, no length floor, no rounding-bucket
approximation) to check: does *any* candidate close to the target
(diameter, length) exist anywhere in the file, even if the real pipeline's
tighter heuristics currently fail to assemble it that way.

Verdict per DEAD_END row:
  CONFIRMED_ABSENT       - no candidate within loose tolerance anywhere
  PERMISSIVE_EVIDENCE    - a candidate exists only under loose bridging --
                           real reading gap in the current pipeline
"""
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, ".")
from rebar3d.loader import dwg_to_dxf, load_entities
from rebar3d.extract import snap_diameter, MIN_DIA, MAX_DIA

ROOT = Path(__file__).resolve().parents[1]
DRAWINGS = ROOT.parent / "rebar_data" / "drawings"
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


class Seg:
    __slots__ = ("p0", "p1", "angle", "ux", "uy", "noff", "t0", "t1", "len")

    def __init__(self, p0, p1):
        self.p0, self.p1 = p0, p1
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        self.len = math.hypot(dx, dy)
        self.angle = math.atan2(dy, dx) % math.pi if self.len > 0 else 0.0
        self.ux, self.uy = math.cos(self.angle), math.sin(self.angle)
        self.noff = -self.uy * p0[0] + self.ux * p0[1]
        t0 = p0[0] * self.ux + p0[1] * self.uy
        t1 = p1[0] * self.ux + p1[1] * self.uy
        self.t0, self.t1 = min(t0, t1), max(t0, t1)


def loose_pairs(ents, angle_tol=0.01, noff_tol=3.0, gap_bridge=500.0):
    """All (diameter, length) candidates from loosely-paired parallel
    S-RBAR segments, bridging gaps up to gap_bridge along each rail before
    pairing -- much more permissive than the pipeline's own 60mm bridge."""
    segs = []
    for e in ents:
        if e.layer != "S-RBAR":
            continue
        if e.kind == "LINE":
            s = Seg(e.points[0], e.points[1])
            if s.len > 0.5:
                segs.append(s)
        elif e.kind == "LWPOLYLINE":
            pts = e.points + ([e.points[0]] if e.closed else [])
            for i in range(len(pts) - 1):
                s = Seg(pts[i], pts[i + 1])
                if s.len > 0.5:
                    segs.append(s)
    if not segs:
        return []

    # group into rails by *unrounded* proximity clustering (greedy) instead
    # of rounding into fixed buckets -- avoids a real rail being split
    # across a bucket boundary by rounding noise.
    segs.sort(key=lambda s: s.angle)
    rails = []  # list of (angle, noff, [ (t0,t1), ... ])
    for s in segs:
        placed = False
        for r in rails:
            if abs((r[0] - s.angle + math.pi / 2) % math.pi - math.pi / 2) <= angle_tol and abs(r[1] - s.noff) <= noff_tol:
                r[2].append((s.t0, s.t1))
                placed = True
                break
        if not placed:
            rails.append([s.angle, s.noff, [(s.t0, s.t1)]])

    # merge intervals within each rail with generous gap bridging
    merged_rails = []
    for angle, noff, ivs in rails:
        ivs = sorted(ivs)
        out = [list(ivs[0])]
        for t0, t1 in ivs[1:]:
            if t0 <= out[-1][1] + gap_bridge:
                out[-1][1] = max(out[-1][1], t1)
            else:
                out.append([t0, t1])
        merged_rails.append((angle, noff, out))

    # pair rails of similar angle separated by a bar-diameter gap
    out = []
    n = len(merged_rails)
    for i in range(n):
        a1, n1, ivs1 = merged_rails[i]
        for j in range(i + 1, n):
            a2, n2, ivs2 = merged_rails[j]
            if abs((a1 - a2 + math.pi / 2) % math.pi - math.pi / 2) > angle_tol:
                continue
            gap = abs(n2 - n1)
            if gap < MIN_DIA or gap > MAX_DIA:
                continue
            dia = snap_diameter(gap)
            if dia is None:
                continue
            for t0a, t1a in ivs1:
                for t0b, t1b in ivs2:
                    lo, hi = max(t0a, t0b), min(t1a, t1b)
                    if hi > lo:
                        out.append((dia, hi - lo))
    return out


def tol(length_mm):
    return max(30.0, 0.08 * length_mm)


def main():
    report = Path(ROOT / "reconciliation_report.txt").read_text().splitlines()
    dead_rows = []
    cur_panel = None
    for l in report:
        hm = re.match(r"=== (.+) ===", l)
        if hm:
            cur_panel = hm.group(1)
            continue
        m = re.match(r"\s+(\S+)\s+T(\d+)\s+need=(\d+)\s+len=(\d+)\s+have=(\d+)\s+DEAD END", l)
        if m and cur_panel:
            mark, dia, need, length, have = m.groups()
            dead_rows.append((cur_panel, mark, int(dia), int(need), float(length), int(have)))

    print(f"Re-testing {len(dead_rows)} DEAD END rows with permissive pairing...\n")

    cache = {}
    confirmed, recovered = [], []
    for panel, mark, dia, need, length, have in dead_rows:
        stems = STEMS_BY_PANEL.get(panel, [])
        pool = []
        for stem in stems:
            if stem not in cache:
                dxf = dwg_to_dxf(DRAWINGS / f"{stem}.dwg", CACHE)
                ents = load_entities(dxf)
                cache[stem] = loose_pairs(ents)
            pool.extend(cache[stem])

        t = tol(length)
        matches = [ln for (d, ln) in pool if d == dia and abs(ln - length) <= t]
        if matches:
            recovered.append((panel, mark, dia, need, length, have, len(matches), max(matches)))
            print(f"  PERMISSIVE_EVIDENCE  {panel:<18} {mark:<6} T{dia:<3} len={length:<7.0f} "
                  f"-> {len(matches)} candidate(s), best={max(matches, key=lambda x: -abs(x-length)):.0f}mm")
        else:
            confirmed.append((panel, mark, dia, need, length, have))

    print(f"\n\n===== SUMMARY =====")
    print(f"{len(recovered)} rows recovered evidence under permissive pairing (real reading gap, NOT a true dead end)")
    print(f"{len(confirmed)} rows CONFIRMED absent even under loose 500mm-bridge, no-rounding pairing")

    out = ROOT / "out_groundtruth" / "_permissive_recheck.txt"
    lines = [f"PERMISSIVE_EVIDENCE (real reading gap -- reclassify from DEAD END):"]
    for panel, mark, dia, need, length, have, nmatch, best in recovered:
        lines.append(f"  {panel:<18} {mark:<6} T{dia:<3} need={need:<3} len={length:<7.0f} have={have:<3} candidates={nmatch}")
    lines.append(f"\nCONFIRMED_ABSENT (no evidence even under loose pairing -- true dead end):")
    for panel, mark, dia, need, length, have in confirmed:
        lines.append(f"  {panel:<18} {mark:<6} T{dia:<3} need={need:<3} len={length:<7.0f} have={have:<3}")
    out.write_text("\n".join(lines))
    print(f"\nWritten to {out}")


if __name__ == "__main__":
    main()
