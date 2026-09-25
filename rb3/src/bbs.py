"""Exact BBS extraction from (S) schedule DWG/DXF files.

The schedule lives in paperspace Layout1 as MTEXT on layer G-ANNO-SCHD,
laid out on a strict grid. We cluster by Y (rows) and X (columns) and read
the table verbatim -- no geometry reconstruction, no inference.
"""
import re, json, math
from pathlib import Path
import ezdxf

SCHD = "G-ANNO-SCHD"
NUM = re.compile(r"-?\d+(?:\.\d+)?")

# Nominal mass per metre, kg/m, for Fe500 deformed bar: pi/4 d^2 * 7850e-9
def kg_per_m(dia_mm: float) -> float:
    return math.pi / 4.0 * dia_mm ** 2 * 7850e-9 * 1000 / 1000 * 1000 / 1000


def mass_per_mm(dia_mm: float) -> float:
    """kg per mm of bar."""
    area_mm2 = math.pi / 4.0 * dia_mm ** 2
    return area_mm2 * 7850e-9  # 7850 kg/m3 -> kg/mm3 = 7850e-9


def clean(s: str) -> str:
    """Strip AutoCAD MTEXT formatting codes."""
    s = s.replace("\\P", " ").replace("\n", " ")
    s = re.sub(r"\\[A-Za-z][^;\\]*;", "", s)
    s = re.sub(r"\\[LlOoKkPpXx]", "", s)
    s = s.replace("{", "").replace("}", "")
    return " ".join(s.split())


def num(s):
    m = NUM.search(s or "")
    return float(m.group()) if m else None


def collect_text(path):
    doc = ezdxf.readfile(str(path))
    items = []
    for lay in doc.layouts:
        for e in lay:
            t = e.dxftype()
            if t == "MTEXT":
                txt, ins = e.text, e.dxf.insert
            elif t == "TEXT":
                txt, ins = e.dxf.text, e.dxf.insert
            else:
                continue
            c = clean(txt)
            if c:
                items.append({"x": ins.x, "y": ins.y, "t": c, "layer": e.dxf.layer,
                              "layout": lay.name})
    return doc, items


def cluster(vals, tol):
    """Cluster 1-D values; return sorted list of cluster centres."""
    out = []
    for v in sorted(vals):
        if out and v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return [sum(c) / len(c) for c in out]


def nearest(centres, v):
    return min(range(len(centres)), key=lambda i: abs(centres[i] - v))


HEADER_KEYS = ["Schedule Mark", "Bar Diameter", "Shape", "Bar Length",
               "Total Bar Length", "Quantity", "Weight"]
DIM_COLS = ["A", "B", "C", "D", "E", "F", "G", "H"]


def parse_tables(items):
    """Locate each rebar schedule table and read it verbatim."""
    sch = [i for i in items if i["layer"] == SCHD]
    if not sch:
        sch = items
    # anchors: every "Schedule Mark" cell starts a table header row
    anchors = [i for i in sch if i["t"] == "Schedule Mark"]
    tables = []
    for a in anchors:
        hy = a["y"]
        # header cells share the header row's y (within tolerance)
        hdr = [i for i in sch if abs(i["y"] - hy) < 4.0 and i["x"] >= a["x"] - 1]
        hdr.sort(key=lambda i: i["x"])
        cols = [(i["x"], i["t"]) for i in hdr]
        xs = [c[0] for c in cols]
        x_lo, x_hi = min(xs) - 8, max(xs) + 12
        # body cells: below header, inside the column band
        body = [i for i in sch if i["y"] < hy - 1 and x_lo <= i["x"] <= x_hi]
        # stop at the next anchor above-to-below or at a title line
        stops = [i["y"] for i in sch
                 if i["y"] < hy - 1 and (i["t"] == "Schedule Mark"
                                         or i["t"].startswith("Rebar schedule")
                                         or i["t"] == "Summary Schedule")]
        if stops:
            floor = max(stops)
            body = [i for i in body if i["y"] > floor + 1]
        if not body:
            continue
        rows = cluster([i["y"] for i in body], 2.0)
        grid = {}
        for i in body:
            r = nearest(rows, i["y"])
            c = nearest(xs, i["x"])
            if abs(xs[c] - i["x"]) > 12:
                continue
            grid.setdefault((r, c), []).append(i["t"])
        tables.append({"header": cols, "xs": xs, "rows": rows, "grid": grid,
                       "hy": hy, "anchor_x": a["x"]})
    return tables


def table_title(items, tbl):
    """The '(Rebar schedule for XXX)' caption sitting just above the header."""
    best, bd = None, 1e9
    for i in items:
        if i["t"].lower().startswith("rebar schedule"):
            d = i["y"] - tbl["hy"]
            if 0 < d < 30 and d < bd:
                best, bd = i["t"], d
    return best


def read_bars(items, tbl, title):
    hdr_names = [t for _, t in tbl["header"]]
    idx = {}
    for c, name in enumerate(hdr_names):
        idx.setdefault(name, c)
    bars = []
    nrows = len(tbl["rows"])
    for r in range(nrows):
        def cell(name):
            c = idx.get(name)
            if c is None:
                return None
            v = tbl["grid"].get((r, c))
            return " ".join(v) if v else None
        mark = cell("Schedule Mark")
        if not mark:
            continue
        dia = num(cell("Bar Diameter") or "")
        qty = num(cell("Quantity") or "")
        length = num(cell("Bar Length") or "")
        if dia is None or qty is None or length is None:
            continue
        dims, dims_raw = {}, {}
        for dc in DIM_COLS:
            c = idx.get(dc)
            if c is None:
                continue
            v = tbl["grid"].get((r, c))
            if v:
                txt = " ".join(v)
                dims_raw[dc] = txt
                n = num(txt)
                if n is not None:
                    dims[dc] = n
        bars.append({
            "schedule": title,
            "mark": mark,
            "dia_mm": dia,
            "shape": cell("Shape"),
            "dims_mm": dims,
            "dims_raw": dims_raw,
            "bar_length_mm": length,
            "qty": int(qty),
            "total_length_mm": num(cell("Total Bar Length") or "") ,
            "weight_kg": num(cell("Weight") or ""),
        })
    return bars


def read_summary(items):
    """The 'Summary Schedule' block: per-diameter total length + weight."""
    sch = [i for i in items if i["layer"] == SCHD]
    anc = [i for i in sch if i["t"] == "Summary Schedule"]
    if not anc:
        return None
    a = anc[0]
    hdr = [i for i in sch if i["t"] == "Bar Diameter" and i["y"] < a["y"]
           and abs(i["x"] - a["x"]) < 60]
    if not hdr:
        return None
    h = max(hdr, key=lambda i: i["y"])
    band = [i for i in sch if i["y"] < h["y"] - 1 and abs(i["x"] - a["x"]) < 60]
    stops = [i["y"] for i in band if i["t"].lower().startswith("rebar schedule")]
    if stops:
        band = [i for i in band if i["y"] > max(stops) + 1]
    rows = cluster([i["y"] for i in band], 2.0)
    per, total = {}, None
    for r, ry in enumerate(rows):
        cells = sorted([i for i in band if nearest(rows, i["y"]) == r],
                       key=lambda i: i["x"])
        vals = [c["t"] for c in cells]
        if len(vals) == 3 and "mm" in vals[0] and "kg" in vals[2]:
            per[int(num(vals[0]))] = {"length_mm": num(vals[1]),
                                      "weight_kg": num(vals[2])}
        elif len(vals) == 2 and "kg" in vals[1]:
            total = {"length_mm": num(vals[0]), "weight_kg": num(vals[1])}
    return {"by_diameter": per, "total": total}


def extract(dxf_path):
    doc, items = collect_text(dxf_path)
    tables = parse_tables(items)
    bars = []
    for t in tables:
        bars += read_bars(items, t, table_title(items, t))
    summary = read_summary(items)
    # --- verification against the drawing's own printed numbers ---
    checks = []
    for b in bars:
        exp = b["bar_length_mm"] * b["qty"]
        if b["total_length_mm"] is not None and abs(exp - b["total_length_mm"]) > 1:
            checks.append(f"{b['schedule']}/{b['mark']}: len*qty={exp:.0f} but "
                          f"drawing says {b['total_length_mm']:.0f}")
        w = b["bar_length_mm"] * b["qty"] * mass_per_mm(b["dia_mm"])
        if b["weight_kg"] is not None and abs(w - b["weight_kg"]) > max(0.05, 0.01 * b["weight_kg"]):
            checks.append(f"{b['schedule']}/{b['mark']}: computed {w:.2f} kg vs "
                          f"drawing {b['weight_kg']:.2f} kg")
    if summary and summary.get("total"):
        tl = sum(b["total_length_mm"] or 0 for b in bars)
        tw = sum(b["weight_kg"] or 0 for b in bars)
        st, sw = summary["total"]["length_mm"], summary["total"]["weight_kg"]
        if abs(tl - st) > 1:
            checks.append(f"TOTAL length rows={tl:.0f} vs summary={st:.0f}")
        if abs(tw - sw) > 0.5:
            checks.append(f"TOTAL weight rows={tw:.2f} vs summary={sw:.2f}")
    return {"source": Path(dxf_path).name, "bars": bars, "summary": summary,
            "issues": checks}


if __name__ == "__main__":
    import sys
    r = extract(sys.argv[1])
    print(json.dumps(r, indent=1)[:4000])
    print(f"\nbars={len(r['bars'])} issues={len(r['issues'])}")
    for c in r["issues"][:20]:
        print("  !", c)
