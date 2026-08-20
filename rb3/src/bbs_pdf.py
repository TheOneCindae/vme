"""Read a bar bending schedule from a PDF sheet.

Some elements have no (S) drawing at all -- their schedule exists only as a
PDF. The table is laid out on the same strict grid as the DWG version, so the
words are clustered into rows and columns and read the same way, then put
through the same reconciliation checks.
"""
import re, json, math
from pathlib import Path
import pymupdf
from bbs import (HEADER_KEYS, DIM_COLS, cluster, nearest, num, mass_per_mm)


def words(path, page=None):
    doc = pymupdf.open(str(path))
    out = []
    pages = range(doc.page_count) if page is None else [page]
    for pno in pages:
        for w in doc[pno].get_text("words"):
            x0, y0, x1, y1, txt = w[0], w[1], w[2], w[3], w[4]
            out.append({"x": (x0 + x1) / 2, "y": (y0 + y1) / 2,
                        "x0": x0, "t": txt, "page": pno})
    return out


def cells(ws, ytol=3.0, xgap=6.0):
    """Merge words on the same line into cells separated by real gaps."""
    rows = cluster([w["y"] for w in ws], ytol)
    byrow = {}
    for w in ws:
        byrow.setdefault(nearest(rows, w["y"]), []).append(w)
    out = []
    for r, items in byrow.items():
        items.sort(key=lambda w: w["x0"])
        cur = None
        for w in items:
            if cur and w["x0"] - cur["end"] <= xgap:
                cur["t"] += " " + w["t"]
                cur["end"] = max(cur["end"], w["x0"] + 2 * (w["x"] - w["x0"]))
                cur["x"] = (cur["x"] + w["x"]) / 2
            else:
                if cur:
                    out.append(cur)
                cur = {"y": rows[r], "x": w["x"], "end": w["x0"] + 2 * (w["x"] - w["x0"]),
                       "t": w["t"], "page": w["page"], "row": r}
        if cur:
            out.append(cur)
    return out, rows


def extract(path, page=None):
    ws = words(path, page)
    cs, rows = cells(ws)
    # header row: the line carrying "Schedule Mark"
    anchors = [c for c in cs if c["t"].startswith("Schedule Mark")]
    bars = []
    for a in anchors:
        # header labels wrap onto a second line ("Total Bar" / "Length"), so
        # gather a band around the anchor and merge cells sharing a column
        band = [c for c in cs if abs(c["y"] - a["y"]) < 16 and c["page"] == a["page"]]
        band.sort(key=lambda c: (c["x"], c["y"]))
        merged = []
        for c in band:
            if merged and abs(merged[-1]["x"] - c["x"]) < 22:
                lo = merged[-1]
                lo["t"] = (lo["t"] + " " + c["t"]).strip()
                lo["x"] = (lo["x"] + c["x"]) / 2
            else:
                merged.append(dict(c))
        hdr = merged
        xs = [c["x"] for c in hdr]

        def canon(t):
            t = " ".join(t.split()).lower()
            if t in ("schedule mark", "mark"):
                return "Schedule Mark"
            if "diameter" in t:
                return "Bar Diameter"
            if t == "shape":
                return "Shape"
            if "total" in t or t == "length":
                return "Total Bar Length"
            if "bar length" in t:
                return "Bar Length"
            if "quantity" in t or t == "no.":
                return "Quantity"
            if "weight" in t:
                return "Weight"
            if len(t) == 1 and t.upper() in DIM_COLS:
                return t.upper()
            return t

        names = [canon(c["t"]) for c in hdr]
        idx = {}
        for i, n in enumerate(names):
            idx.setdefault(n, i)
        # an unnamed column between Bar Length and Quantity is the running total
        if "Total Bar Length" not in idx and "Bar Length" in idx and "Quantity" in idx:
            lo, hi = idx["Bar Length"], idx["Quantity"]
            if hi - lo == 2:
                idx["Total Bar Length"] = lo + 1
        body = [c for c in cs if c["page"] == a["page"] and c["y"] > a["y"] + 2]
        brows = cluster([c["y"] for c in body], 3.0)
        grid = {}
        for c in body:
            r = nearest(brows, c["y"])
            k = nearest(xs, c["x"])
            if abs(xs[k] - c["x"]) > 26:
                continue
            grid.setdefault((r, k), []).append(c["t"])
        for r in range(len(brows)):
            def cell(nm):
                i = idx.get(nm)
                if i is None:
                    return None
                v = grid.get((r, i))
                return " ".join(v) if v else None
            mk = cell("Schedule Mark")
            dia, qty, L = num(cell("Bar Diameter") or ""), num(cell("Quantity") or ""), None
            L = num(cell("Bar Length") or "")
            if not mk or dia is None or qty is None or L is None:
                continue
            if not re.fullmatch(r"[A-Z][0-9A-Z]?", mk):
                continue
            dims, raw = {}, {}
            for dc in DIM_COLS:
                i = idx.get(dc)
                if i is None:
                    continue
                v = grid.get((r, i))
                if v:
                    raw[dc] = " ".join(v)
                    n2 = num(raw[dc])
                    if n2 is not None:
                        dims[dc] = n2
            bars.append({"schedule": Path(path).stem, "mark": mk, "dia_mm": dia,
                         "shape": cell("Shape"), "dims_mm": dims, "dims_raw": raw,
                         "bar_length_mm": L, "qty": int(qty),
                         "total_length_mm": num(cell("Total Bar Length") or ""),
                         "weight_kg": num(cell("Weight") or "")})
    issues = []
    for b in bars:
        exp = b["bar_length_mm"] * b["qty"]
        if b["total_length_mm"] and abs(exp - b["total_length_mm"]) > 1:
            issues.append(f"{b['mark']}: len*qty={exp:.0f} vs printed {b['total_length_mm']:.0f}")
        w = exp * mass_per_mm(b["dia_mm"])
        if b["weight_kg"] and abs(w - b["weight_kg"]) > max(0.05, 0.01 * b["weight_kg"]):
            issues.append(f"{b['mark']}: computed {w:.2f} kg vs printed {b['weight_kg']:.2f}")
    return {"source": Path(path).name, "bars": bars, "summary": None, "issues": issues}


if __name__ == "__main__":
    import sys
    r = extract(sys.argv[1])
    for b in r["bars"]:
        print(f"  {b['mark']:4} T{b['dia_mm']:.0f} {str(b['shape'])[:14]:16} "
              f"L={b['bar_length_mm']:7.0f} n={b['qty']:4d} "
              f"tot={b['total_length_mm']} w={b['weight_kg']}")
    q = sum(b["qty"] for b in r["bars"])
    tl = sum(b["total_length_mm"] or 0 for b in r["bars"])
    tw = sum(b["weight_kg"] or 0 for b in r["bars"])
    print(f"\nmarks={len(r['bars'])} bars={q} length={tl:.0f} mm weight={tw:.2f} kg "
          f"issues={len(r['issues'])}")
    for c in r["issues"][:10]:
        print("  !", c)
