"""Ground-truth reconciliation: every official BBS mark (from the cross-checked
BBS truth agent) vs every real bar candidate anywhere in the source DXF
(from the unclustered raw-geometry safety-net pass, agent 1) vs what the
live pipeline currently reconstructed (out/*.json). This supersedes
evidence_sweep.py: it uses the FULL unclustered whole-file candidate pool
(not view-clustered) as the evidence source, and BBS rows cross-checked
across R/S/PDF instead of a single itemized-table read.

Verdicts per official row:
  OK          - current reconstruction already satisfies qty within tolerance
  RECOVERABLE - reconstruction is short, but unclaimed raw evidence exists
                somewhere in the source file (real pipeline bug / gap)
  DEAD END    - reconstruction is short AND no matching raw evidence exists
                anywhere in the source file, even unclustered (genuine
                absence in the drawing -- not a pipeline bug)

Matching within a diameter bucket uses greedy NEAREST-length assignment
(not first-fit in arbitrary order) to minimize spurious mismatches.
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GT = ROOT / "out_groundtruth"
OUT = ROOT / "out"
DRAWINGS = ROOT.parent / "rebar_data" / "drawings"
DXF_CACHE = Path("/tmp/dxfcache")

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(GT))
from rebar3d.loader import dwg_to_dxf, load_entities
from _permissive_pairing import loose_pairs  # noqa: E402

_loose_cache: dict[str, list] = {}
_loose_pool_excess: dict[tuple, list] = {}
_loose_pool_claimed: dict[tuple, list] = {}


def loose_pool_for(stems: list[str]) -> list:
    """(diameter, length) candidates from the permissive re-pairing pass,
    pooled across a panel's member stems and cached per stem across the
    whole run. Only ever consulted for a row that's about to be logged
    DEAD_END -- a row must fail BOTH the pipeline's own extraction (raw_pool)
    AND this much more permissive, differently-derived pairing before it is
    ever reported absent.
    """
    pool = []
    for stem in stems:
        if stem not in _loose_cache:
            dxf = dwg_to_dxf(DRAWINGS / f"{stem}.dwg", DXF_CACHE)
            ents = load_entities(dxf)
            _loose_cache[stem] = loose_pairs(ents)
        pool.extend(_loose_cache[stem])
    return pool

COMBO_MEMBERS = {
    "PW-GF-05": ["PW-GF-05(R1)", "PW-GF-05(R2)"],
    "PW-GF-08": ["PW-GF-08(R1)", "PW-GF-08(R2)"],
    "PW-GF-09-combo": ["PW-GF-09(R1)", "PW-GF-09(R2)"],
    "PW-GF-11": ["PW-GF-11(R1)", "PW-GF-11(R2)"],
    "PW-GF-27": ["PW-GF-27(R1)", "PW-GF-27(R2)"],
    "PW-GF-30": ["PW-GF-30(R1)", "PW-GF-30(R2)"],
}
SINGLE_PANELS = {
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
}
ALL_PANELS = {**SINGLE_PANELS, **COMBO_MEMBERS}


def tol(length_mm: float) -> float:
    return max(30.0, 0.08 * length_mm)


UNIT_W = {6: 0.222, 8: 0.395, 10: 0.617, 12: 0.888, 16: 1.578, 20: 2.466, 25: 3.854, 32: 6.313}


def load_truth_rows(stem: str):
    """Best consensus rows for a stem: prefer S_dwg if present & fresh
    (mtime_gap small), else pdf source, else R_own. If cross_check flags
    DISAGREE for a mark, we still use the chosen source's literal rows
    (both duplicate entries included) rather than trying to merge -- a
    duplicate mark label is two real distinct bars, not one row to fix up.
    """
    p = GT / f"{stem}_bbs_truth.json"
    if not p.exists():
        return []
    d = json.loads(p.read_text())
    sources = d["sources"]
    if "S_dwg" in sources and sources["S_dwg"].get("rows"):
        if abs(sources["S_dwg"].get("mtime_gap_days", 999)) < 7:
            return sources["S_dwg"]["rows"]
    if sources.get("R_own"):
        return sources["R_own"]
    for k, v in sources.items():
        if k.startswith("pdf:") and v.get("rows"):
            if abs(v.get("mtime_gap_days", 999)) < 7:
                return v["rows"]
    if "S_dwg" in sources and sources["S_dwg"].get("rows"):
        return sources["S_dwg"]["rows"]
    for k, v in sources.items():
        if k.startswith("pdf:") and v.get("rows"):
            return v["rows"]
    return []


def load_raw_pool(stems: list[str]):
    """Unclustered-pass candidate lengths by diameter, pooled across all
    member stems of a panel."""
    by_dia: dict[int, list[float]] = {}
    for stem in stems:
        p = GT / f"{stem}_raw_geometry.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text())
        for c in d["candidates"]:
            if c["source_pass"] != "unclustered":
                continue
            dia = c["diameter_snapped"]
            if dia is None:
                continue
            by_dia.setdefault(dia, []).append(c["length_mm"])
    for v in by_dia.values():
        v.sort()
    return by_dia


def load_current_bars(panel_label: str, stems: list[str]):
    by_dia: dict[int, list[float]] = {}
    # Combo panels (multi-sheet: R1/R2/...) keep out/<stem>.json naming.
    # Single-sheet panels collapse to out/<base>.json (no "(R)" suffix) --
    # confirmed against the naming row_by_row_report.py already uses.
    if len(stems) == 1 and stems[0].endswith("(R)"):
        json_names = [stems[0][: -len("(R)")]]
    else:
        json_names = stems
    for stem in json_names:
        p = OUT / f"{stem}.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text())
        for b in d["bars"]:
            length = sum(math.dist(b["pts"][i], b["pts"][i + 1]) for i in range(len(b["pts"]) - 1))
            by_dia.setdefault(b["d"], []).append(length)
    for v in by_dia.values():
        v.sort()
    return by_dia


def greedy_nearest_match(demands: list[float], pool: list[float], t_fn):
    """demands, pool: lists of lengths (same diameter). Returns
    (n_matched, unmatched_demand_indices) using nearest-length greedy
    assignment instead of arbitrary first-fit."""
    pool_used = [False] * len(pool)
    matched = 0
    unmatched = []
    order = sorted(range(len(demands)), key=lambda i: demands[i])
    for i in order:
        dlen = demands[i]
        best_j, best_gap = None, None
        for j, plen in enumerate(pool):
            if pool_used[j]:
                continue
            gap = abs(plen - dlen)
            if gap <= t_fn(dlen) and (best_gap is None or gap < best_gap):
                best_j, best_gap = j, gap
        if best_j is not None:
            pool_used[best_j] = True
            matched += 1
        else:
            unmatched.append(i)
    return matched, unmatched


def main():
    report_lines = []
    grand = {"OK": 0, "RECOVERABLE": 0, "DEAD_END": 0}
    recoverable_detail = []
    json_panels = []

    for panel_label, stems in ALL_PANELS.items():
        # Combo-panel members typically share one (S).dwg / schedule that
        # already covers the WHOLE combined panel (same base filename for
        # both R1 and R2) -- pulling truth rows from every member stem and
        # concatenating them double-counts every mark. Use only the single
        # richest source across members, same approach row_by_row_report.py
        # and evidence_sweep.py already use for combo panels.
        best_rows, best_len, best_stem = [], 0, None
        for stem in stems:
            rows = load_truth_rows(stem)
            if len(rows) > best_len:
                best_rows, best_len, best_stem = rows, len(rows), stem
        truth_rows = []
        for r in best_rows:
            r = dict(r)
            r["_stem"] = best_stem
            truth_rows.append(r)
        if not truth_rows:
            continue

        raw_pool = load_raw_pool(stems)
        cur_pool = load_current_bars(panel_label, stems)

        # raw_pool and cur_pool describe the SAME underlying physical
        # bars, measured two different ways (a simple unclustered
        # extraction vs. the full pipeline's own assembly) -- they are
        # NOT independent evidence pools to be added together. Treating
        # every raw_pool candidate as "additional" evidence beyond what
        # cur_pool already has double-counts the same real bar twice:
        # once via cur_pool satisfying one mark's need, then AGAIN via
        # raw_pool's untouched copy of that same bar "recovering" a
        # different, nearby-length mark's shortfall. Confirmed concretely
        # on PW-GF-11 T10 marks F/F1 (9000mm/9050mm, only 50mm apart):
        # cur_pool had exactly 30 real bars for the whole neighborhood,
        # raw_pool (a more permissive but overlapping extraction) found
        # 35 -- F consumed 23 from cur_pool (fully satisfied), leaving
        # F1 apparently "recoverable" for 15 more via raw_pool, when the
        # true additional bars beyond what's already reconstructed is at
        # most 35-30=5. This is exactly the shared-candidate-pool bug
        # already caught and fixed once this session (82->26 false
        # "possible bugs") recurring in a different pool combination.
        # Fix: for each diameter, remove from raw_pool one nearest-length
        # match per cur_pool bar BEFORE any mark can claim "unclaimed raw"
        # evidence -- what's left in raw_pool is the genuine excess a
        # more permissive extraction finds beyond what the pipeline
        # already assembled, not a second independent copy of the same
        # steel.
        for dia, cpool in cur_pool.items():
            rpool = raw_pool.get(dia, [])
            if not rpool:
                continue
            used = [False] * len(rpool)
            for clen in cpool:
                best_j, best_gap = None, None
                for j, rlen in enumerate(rpool):
                    if used[j]:
                        continue
                    gap = abs(rlen - clen)
                    if best_gap is None or gap < best_gap:
                        best_j, best_gap = j, gap
                if best_j is not None:
                    used[best_j] = True
            raw_pool[dia] = [rlen for j, rlen in enumerate(rpool) if not used[j]]

        report_lines.append(f"\n=== {panel_label} ===")
        panel_counts = {"OK": 0, "RECOVERABLE": 0, "DEAD_END": 0}
        panel_rows_json = []

        # consume current-reconstruction pool and (now excess-only) raw
        # pool independently, each tracked per-diameter across the whole
        # panel's mark list so no candidate is double counted across marks.
        cur_used = {d: [False] * len(v) for d, v in cur_pool.items()}
        raw_used = {d: [False] * len(v) for d, v in raw_pool.items()}

        for m in sorted(truth_rows, key=lambda r: r["length_mm"]):
            qty = m.get("qty", 0)
            length_mm = m.get("length_mm", 0)
            dia = m.get("diameter")
            if qty <= 0 or length_mm <= 0 or dia is None:
                continue
            t = tol(length_mm)

            cpool = cur_pool.get(dia, [])
            cflags = cur_used.setdefault(dia, [False] * len(cpool))
            found = 0
            for i, length in enumerate(cpool):
                if cflags[i] or abs(length - length_mm) > t:
                    continue
                cflags[i] = True
                found += 1
                if found >= qty:
                    break

            mark_label = m.get("mark", "?")
            row_len = round(length_mm, 0)
            missing_kg = round(UNIT_W.get(dia, 0) * length_mm / 1000 * (qty - found), 2)

            if found >= qty:
                panel_counts["OK"] += 1
                panel_rows_json.append({
                    "mark": mark_label, "dia": dia, "need": qty, "len": row_len,
                    "have": found, "status": "OK", "missing_kg": 0.0, "evidence": None,
                })
                continue

            still_need = qty - found
            rpool = raw_pool.get(dia, [])
            rflags = raw_used.setdefault(dia, [False] * len(rpool))
            avail_idx = [i for i, f in enumerate(rflags) if not f]
            avail_len = [rpool[i] for i in avail_idx]
            n_match, _ = greedy_nearest_match([length_mm] * still_need, avail_len, tol)
            # commit the claims (nearest first) so later marks at this dia
            # don't see them as available
            claimed = 0
            for i in sorted(avail_idx, key=lambda i: abs(rpool[i] - length_mm)):
                if claimed >= n_match:
                    break
                rflags[i] = True
                claimed += 1

            if n_match > 0:
                panel_counts["RECOVERABLE"] += 1
                recoverable_detail.append(
                    f"{panel_label:<18} {mark_label:<8} T{dia:<3} "
                    f"need={qty:<3} have={found:<3} len={length_mm:<7.0f} "
                    f"raw_evidence={n_match}/{still_need} (source {m.get('_stem')})"
                )
                report_lines.append(
                    f"  {mark_label:<8} T{dia:<3} need={qty:<3} len={length_mm:<7.0f} "
                    f"have={found:<3} RECOVERABLE (raw_evidence={n_match}/{still_need})"
                )
                panel_rows_json.append({
                    "mark": mark_label, "dia": dia, "need": qty, "len": row_len,
                    "have": found, "status": "RECOVERABLE", "missing_kg": missing_kg,
                    "evidence": f"{n_match}/{still_need}",
                })
                continue

            # Before ever calling this a dead end: re-test with a second,
            # deliberately more permissive and differently-derived pairing
            # pass (500mm gap bridging, no angle/offset rounding, no length
            # floor) instead of trusting the pipeline's own tighter
            # pair_lines() heuristics. A row only becomes DEAD_END if it
            # fails BOTH checks. Same shared-pool care as raw_pool above:
            # this permissive pool is checked AFTER removing one
            # nearest-length match per cur_pool bar (already-reconstructed
            # bars are the same physical steel, not new evidence) and
            # consumed per-index across marks so two nearby-length dead
            # rows can't both "recover" off the identical loose candidate.
            key = tuple(stems)
            if key not in _loose_pool_excess:
                lp = list(loose_pool_for(stems))
                for cdia, cpool in cur_pool.items():
                    used = [False] * len(lp)
                    for clen in cpool:
                        best_j, best_gap = None, None
                        for j, (ld, ll) in enumerate(lp):
                            if used[j] or ld != cdia:
                                continue
                            gap = abs(ll - clen)
                            if best_gap is None or gap < best_gap:
                                best_j, best_gap = j, gap
                        if best_j is not None:
                            used[best_j] = True
                    lp = [x for j, x in enumerate(lp) if not used[j]]
                _loose_pool_excess[key] = lp
                _loose_pool_claimed[key] = [False] * len(lp)
            lp = _loose_pool_excess[key]
            claimed = _loose_pool_claimed[key]
            loose_matches = []
            for j, (ld, ll) in enumerate(lp):
                if not claimed[j] and ld == dia and abs(ll - length_mm) <= t:
                    claimed[j] = True
                    loose_matches.append(ll)
            if loose_matches:
                panel_counts["RECOVERABLE"] += 1
                recoverable_detail.append(
                    f"{panel_label:<18} {mark_label:<8} T{dia:<3} "
                    f"need={qty:<3} have={found:<3} len={length_mm:<7.0f} "
                    f"permissive_pairing_evidence={len(loose_matches)} (source {m.get('_stem')})"
                )
                report_lines.append(
                    f"  {mark_label:<8} T{dia:<3} need={qty:<3} len={length_mm:<7.0f} "
                    f"have={found:<3} RECOVERABLE (permissive_pairing_evidence={len(loose_matches)}, "
                    f"pipeline's own extraction missed this)"
                )
                panel_rows_json.append({
                    "mark": mark_label, "dia": dia, "need": qty, "len": row_len,
                    "have": found, "status": "RECOVERABLE", "missing_kg": missing_kg,
                    "evidence": f"permissive:{len(loose_matches)}",
                })
            else:
                panel_counts["DEAD_END"] += 1
                report_lines.append(
                    f"  {mark_label:<8} T{dia:<3} need={qty:<3} len={length_mm:<7.0f} "
                    f"have={found:<3} DEAD END (confirmed absent under both extraction pass "
                    f"and permissive 500mm-bridge re-pairing)"
                )
                panel_rows_json.append({
                    "mark": mark_label, "dia": dia, "need": qty, "len": row_len,
                    "have": found, "status": "DEAD_END", "missing_kg": missing_kg,
                    "evidence": None,
                })

        json_panels.append({
            "name": panel_label, "rows": panel_rows_json,
            "ok": panel_counts["OK"], "rec": panel_counts["RECOVERABLE"], "dead": panel_counts["DEAD_END"],
        })
        total = sum(panel_counts.values())
        report_lines.append(
            f"  -> {panel_counts['OK']} OK, {panel_counts['RECOVERABLE']} RECOVERABLE, "
            f"{panel_counts['DEAD_END']} DEAD END (of {total} official rows)"
        )
        for k in grand:
            grand[k] += panel_counts[k]

    report_lines.append(f"\n\n===== GRAND TOTAL =====")
    total = sum(grand.values())
    report_lines.append(
        f"{grand['OK']} OK, {grand['RECOVERABLE']} RECOVERABLE (real pipeline gap, evidence exists), "
        f"{grand['DEAD_END']} DEAD END (no evidence in source at all) -- of {total} official BBS rows"
    )
    report_lines.append(f"\n--- RECOVERABLE rows detail (sorted, these are the real actionable gap) ---")
    for line in recoverable_detail:
        report_lines.append("  " + line)

    out_path = ROOT / "reconciliation_report.txt"
    out_path.write_text("\n".join(report_lines))
    print("\n".join(report_lines))
    print(f"\nWritten to {out_path}")

    rec_kg = sum(r["missing_kg"] for p in json_panels for r in p["rows"] if r["status"] == "RECOVERABLE")
    dead_kg = sum(r["missing_kg"] for p in json_panels for r in p["rows"] if r["status"] == "DEAD_END")
    json_out = {
        "panels": json_panels,
        "grand": {
            "ok": grand["OK"], "rec": grand["RECOVERABLE"], "dead": grand["DEAD_END"],
            "rec_kg": round(rec_kg, 1), "dead_kg": round(dead_kg, 1),
        },
    }
    json_path = ROOT / "reconciliation_data.json"
    json_path.write_text(json.dumps(json_out))
    print(f"Written to {json_path}")


if __name__ == "__main__":
    main()
