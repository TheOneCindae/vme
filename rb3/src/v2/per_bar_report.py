"""Every bar, individually: diameter x shape x mark x location status.

Not an aggregate percentage -- a full itemised account. Every schedule mark
is one row: its diameter, its shape family (straight / U-bar / closed link
or tie / other bent), how many of its bars are actually located in the
drawing vs merely scheduled, and what evidence backs the located ones.

Shape families (from the shape catalogue in shapes3d.py, itself decoded and
verified against the drawn legend earlier in this project):
    straight     M_00
    u_bar        M_17, M_17A            -- leg-base-leg / single-bend hooks
    link_tie     M_T1, M_T10            -- closed stirrups / open ties
    bent_other   26, Rebar Shape 8/9/30/31 -- cranked or multi-bend bars
"""
import sys, json, glob, collections
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "v2"))
import bbs as BBS

FAMILY = {
    "M_00": "straight",
    "M_17": "u_bar", "M_17A": "u_bar",
    "M_T1": "link_tie", "M_T10": "link_tie",
    "26": "bent_other", "Rebar Shape 8": "bent_other",
    "Rebar Shape 9": "bent_other", "Rebar Shape 30": "bent_other",
    "Rebar Shape 31": "bent_other",
}
FAMILY_LABEL = {"straight": "STRAIGHT", "u_bar": "U-BAR", "link_tie": "LINK/TIE",
               "bent_other": "BENT (other)"}


def load_schedule():
    out = json.loads((ROOT / "out" / "bbs.json").read_text())
    for stem, panel in (("PW-GF-27_R2", "PW-GF-27"), ("PW-GF-30_R2", "PW-GF-30"),
                        ("PC-GF-01_R", "PC-GF-01")):
        if out.get(panel, {}).get("bars"):
            continue
        try:
            r = BBS.extract(str(ROOT / "dxf" / f"{stem}.dxf"))
        except Exception:
            continue
        if r.get("bars"):
            out[panel] = r
    return out


def load_bound():
    out = {}
    for f in sorted((ROOT / "out" / "v2" / "bound").glob("*.json")):
        if f.stem.startswith("_"):
            continue
        d = json.loads(f.read_text())
        out[d["element"]] = d
    return out


def element_of(bound_key):
    import re
    return re.sub(r"\s*\[.*\]$", "", bound_key)


def build_rows():
    sched = load_schedule()
    bound = load_bound()
    located_by = collections.defaultdict(lambda: {"located": 0, "evidence": collections.Counter()})
    for key, d in bound.items():
        for r in d["reconciliation"]:
            k = (element_of(key), r["mark"], r.get("schedule"))
            located_by[k]["located"] += r["located"]
            for kind, n in (r.get("evidence") or {}).items():
                located_by[k]["evidence"][kind] += n

    rows = []
    for panel, entry in sched.items():
        for m in entry.get("bars", []):
            shape = m.get("shape") or "?"
            fam = FAMILY.get(shape, "bent_other" if shape else "?")
            key = (panel, m["mark"], m.get("schedule"))
            ev = located_by.get(key, {"located": 0, "evidence": collections.Counter()})
            rows.append({
                "panel": panel, "mark": m["mark"], "dia_mm": int(m["dia_mm"]),
                "shape": shape, "family": fam,
                "cut_length_mm": m["bar_length_mm"], "qty": m["qty"],
                "located": min(ev["located"], m["qty"]),
                "weight_kg": m.get("weight_kg") or 0.0,
                "evidence": dict(ev["evidence"]),
            })
    return rows


def print_report(rows, out_path=None):
    lines = []
    def P(s=""):
        lines.append(s)

    by_dia = collections.defaultdict(list)
    for r in rows:
        by_dia[r["dia_mm"]].append(r)

    grand_qty = grand_loc = 0
    grand_wt = grand_wt_loc = 0.0

    P("=" * 100)
    P("EVERY BAR -- by diameter, by shape family, by mark")
    P("=" * 100)

    # --- summary matrix: diameter x shape family -----------------------
    fams = ("straight", "u_bar", "link_tie", "bent_other")
    P()
    P(f"{'':8}" + "".join(f"{FAMILY_LABEL[f]:>16}" for f in fams) + f"{'TOTAL':>16}")
    for dia in sorted(by_dia):
        drows = by_dia[dia]
        cells = []
        for fam in fams:
            frows = [r for r in drows if r["family"] == fam]
            if not frows:
                cells.append(f"{'--':>16}")
                continue
            q = sum(r["qty"] for r in frows); l = sum(r["located"] for r in frows)
            cells.append(f"{l:>5d}/{q:<5d}{100*l/q:5.0f}%")
        q = sum(r["qty"] for r in drows); l = sum(r["located"] for r in drows)
        P(f"T{dia:<7}" + "".join(cells) + f"{l:>6d}/{q:<5d}{100*l/q:4.0f}%")
    tq = sum(r["qty"] for r in rows); tl = sum(r["located"] for r in rows)
    P(f"{'TOTAL':8}" + " " * (16 * len(fams)) + f"{tl:>6d}/{tq:<5d}{100*tl/tq:4.0f}%")
    P()

    for dia in sorted(by_dia):
        drows = by_dia[dia]
        dia_qty = sum(r["qty"] for r in drows)
        dia_loc = sum(r["located"] for r in drows)
        dia_wt = sum(r["weight_kg"] for r in drows)
        dia_wt_loc = sum(r["weight_kg"] * r["located"] / r["qty"] if r["qty"] else 0 for r in drows)
        grand_qty += dia_qty; grand_loc += dia_loc
        grand_wt += dia_wt; grand_wt_loc += dia_wt_loc
        P()
        P(f"### T{dia}  --  {dia_loc}/{dia_qty} bars located ({100*dia_loc/dia_qty:.1f}%)   "
          f"{dia_wt_loc:.1f}/{dia_wt:.1f} kg")
        P("-" * 100)

        by_fam = collections.defaultdict(list)
        for r in drows:
            by_fam[r["family"]].append(r)

        for fam in ("straight", "u_bar", "link_tie", "bent_other"):
            frows = by_fam.get(fam)
            if not frows:
                continue
            f_qty = sum(r["qty"] for r in frows)
            f_loc = sum(r["located"] for r in frows)
            P(f"  -- {FAMILY_LABEL[fam]:14} {f_loc:4d}/{f_qty:<4d} bars "
              f"({100*f_loc/f_qty:5.1f}%) --")
            P(f"     {'panel':16}{'mark':6}{'shape':16}{'cut mm':>9}{'qty':>6}"
              f"{'located':>9}{'%':>7}   evidence")
            frows.sort(key=lambda r: (r["panel"], r["mark"]))
            for r in frows:
                pct = 100 * r["located"] / r["qty"] if r["qty"] else 0
                ev = ", ".join(f"{k}:{v}" for k, v in sorted(r["evidence"].items()))
                flag = "" if r["located"] >= r["qty"] else (
                    " <<< MISSING" if r["located"] == 0 else " <<< partial")
                P(f"     {r['panel']:16}{r['mark']:6}{r['shape']:16}{r['cut_length_mm']:9.0f}"
                  f"{r['qty']:6d}{r['located']:9d}{pct:7.1f}   {ev}{flag}")

    P()
    P("=" * 100)
    P(f"GRAND TOTAL: {grand_loc}/{grand_qty} bars located ({100*grand_loc/grand_qty:.1f}%)   "
      f"{grand_wt_loc:.2f}/{grand_wt:.2f} kg ({100*grand_wt_loc/grand_wt:.1f}%)")
    P("=" * 100)

    text = "\n".join(lines)
    print(text)
    if out_path:
        Path(out_path).write_text(text)


if __name__ == "__main__":
    rows = build_rows()
    out = ROOT / "out" / "v2" / "per_bar_report.txt"
    print_report(rows, out)
    json.dump(rows, open(ROOT / "out" / "v2" / "per_bar_report.json", "w"), indent=1)
