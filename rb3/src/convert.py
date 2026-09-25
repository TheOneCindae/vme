"""DWG -> DXF via LibreDWG, cached."""
import subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
DWG_DIR = ROOT.parent / "rebar_data" / "drawings"
DXF_DIR = ROOT / "dxf"

def slug(p: Path) -> str:
    return p.stem.replace("(", "_").replace(")", "").replace(" ", "")

def to_dxf(dwg: Path, force=False) -> Path:
    DXF_DIR.mkdir(exist_ok=True)
    out = DXF_DIR / (slug(dwg) + ".dxf")
    if out.exists() and not force and out.stat().st_size > 0:
        return out
    r = subprocess.run(["dwg2dxf", "-o", str(out), str(dwg)],
                       capture_output=True, text=True)
    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"convert failed {dwg.name}: {r.stderr[-300:]}")
    return out

def find(pattern="*.dwg"):
    return sorted(DWG_DIR.glob(pattern))

if __name__ == "__main__":
    pat = sys.argv[1] if len(sys.argv) > 1 else "*.dwg"
    for d in find(pat):
        try:
            o = to_dxf(d)
            print(f"ok   {d.name} -> {o.name} ({o.stat().st_size//1024} KB)")
        except Exception as e:
            print(f"FAIL {d.name}: {e}")
