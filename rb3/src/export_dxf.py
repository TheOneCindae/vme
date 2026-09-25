"""Export the assembled model as 3D DXF -- one 3D polyline per bar.

Bars are layered by panel and diameter so they can be isolated in CAD.
"""
import sys, json
sys.path.insert(0, 'src')
import ezdxf
from pathlib import Path

COLOR = {8: 1, 10: 2, 12: 3, 16: 4, 20: 5, 25: 6, 32: 7}


def export(panel, model, path):
    doc = ezdxf.new("R2010", setup=True)
    msp = doc.modelspace()
    for b in model["bars"]:
        d = int(b["dia_mm"])
        lay = f"RBAR-T{d}-{b['mark']}"
        if lay not in doc.layers:
            doc.layers.add(lay, color=COLOR.get(d, 7))
        pts = [tuple(p) for p in b["pts"]]
        if len(pts) < 2:
            continue
        pl = msp.add_polyline3d(pts, dxfattribs={"layer": lay})
    doc.saveas(str(path))
    return len(model["bars"])


if __name__ == "__main__":
    models = json.load(open("out/model3d.json"))
    Path("out/dxf3d").mkdir(parents=True, exist_ok=True)
    tot = 0
    for panel, m in sorted(models.items()):
        safe = panel.replace(" ", "_").replace("[", "").replace("]", "")
        p = Path("out/dxf3d") / f"{safe}_3D.dxf"
        n = export(panel, m, p)
        tot += n
        print(f"{panel:12} {n:5d} bars -> {p} ({p.stat().st_size//1024} KB)")
    print(f"TOTAL {tot} bars exported")
