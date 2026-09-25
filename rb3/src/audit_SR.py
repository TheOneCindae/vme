"""Audit: how much of the (S) schedule can actually be found in the (R) drawings.

For every scheduled mark this asks three separate questions and reports the
answer in bar-length, because length -- not bar count -- is what the schedule
is measured in:

  tagged   - does the R drawing label this mark anywhere at all?
  located  - can real positions be found for its bars, from a section cut or
             from a detected array of evenly spaced bars in the elevation?
  covered  - how many of the mark's bars got a real position, and therefore
             how many millimetres of the scheduled length are accounted for
             by drawing evidence rather than by assumption.
"""
import sys, json, glob, collections
sys.path.insert(0, 'src')
import ezdxf, rbar, place, arrays as ARR
import assemble as A


def audit_panel(panel, entry, dxf_paths):
    marks = entry["bars"]
    doc = None; vlist = []; env = {}
    for p in dxf_paths:
        try:
            dd = ezdxf.readfile(str(p))
        except Exception:
            continue
        vv = A.classify(dd); ee = A.panel_envelope(vv)
        if ee.get("thickness_mm") and ee.get("height_mm"):
            if not env or ee["height_mm"] * ee["width_mm"] > env.get("height_mm", 0) * env.get("width_mm", 0):
                doc, vlist, env = dd, vv, ee
    if doc is None:
        return None

    dias = sorted({int(b["dia_mm"]) for b in marks})
    ann = place.annotation_index(doc, vlist)

    # every mark tagged anywhere in any R file for this panel
    tagged = set()
    for p in dxf_paths:
        try:
            dd = ezdxf.readfile(str(p))
        except Exception:
            continue
        for v in A.classify(dd):
            mk, _, _ = rbar.tags(dd, v["box"], 3000)
            tagged |= {t["mark"] for t in mk}

    found = collections.defaultdict(int)      # mark -> bars with a real position
    how = {}

    for pv in [v for v in vlist if v["kind"] == "plan_cut"]:
        a, _, _ = A.assign_plan(marks, A.plan_bars(doc, pv), env)
        for k, v in a.items():
            if len(v["pos"]) > found[k]:
                found[k] = len(v["pos"]); how[k] = v["how"]
    ends = [v for v in vlist if v["kind"] == "end_cut"]
    if ends:
        a, _ = A.assign_end(marks, A.end_bars(doc, ends[0]), env)
        for k, v in a.items():
            if len(v["pos"]) > found[k]:
                found[k] = len(v["pos"]); how[k] = v["how"]
    elevs = [v for v in vlist if v["kind"] == "elevation"]
    if elevs:
        ev = max(elevs, key=lambda e: e["w"] * e["h"])
        try:
            aa = ARR.merge_arrays(ARR.find_arrays(ARR.runs_in_view(doc, ev, dias)))
            for k, v in ARR.match_marks(marks, aa, ann).items():
                n = v["array"]["n"]
                if n > found[k]:
                    found[k] = n; how[k] = "elevation_array"
        except Exception:
            pass

    rows = []
    for m in marks:
        n = min(found.get(m["mark"], 0), m["qty"])
        L = m["bar_length_mm"]
        rows.append({"mark": m["mark"], "dia": m["dia_mm"], "qty": m["qty"],
                     "cut_mm": L, "sched_mm": L * m["qty"], "found_bars": n,
                     "found_mm": L * n, "tagged": m["mark"] in tagged,
                     "how": how.get(m["mark"]),
                     "weight_kg": m["weight_kg"] or 0,
                     "found_kg": (m["weight_kg"] or 0) * n / max(m["qty"], 1)})
    return {"panel": panel, "rows": rows, "envelope": env}


def main():
    bbs = json.load(open('out/bbs.json'))
    extra = {}
    # panels whose schedule lives in an (R2) sheet rather than an (S) sheet
    import bbs as BBS
    for stem, panel in (("PW-GF-27_R2", "PW-GF-27"), ("PW-GF-30_R2", "PW-GF-30"),
                        ("PC-GF-01_R", "PC-GF-01")):
        try:
            extra[panel] = BBS.extract(f"dxf/{stem}.dxf")
        except Exception:
            pass
    src = {**{k: v for k, v in bbs.items() if v["bars"]}, **extra}

    out, tot = [], collections.Counter()
    tl = tf = 0.0
    twl = twf = 0.0
    print("{:12}{:>7}{:>8}{:>13}{:>13}{:>7}".format(
        "panel", "marks", "found", "sched mm", "found mm", "%"))
    print("-" * 60)
    for panel in sorted(src):
        rs = sorted(glob.glob(f'dxf/{panel}_R*.dxf'))
        if not rs:
            continue
        r = audit_panel(panel, src[panel], rs)
        if not r:
            continue
        out.append(r)
        sm = sum(x["sched_mm"] for x in r["rows"])
        fm = sum(x["found_mm"] for x in r["rows"])
        sw = sum(x["weight_kg"] for x in r["rows"])
        fw = sum(x["found_kg"] for x in r["rows"])
        nm = sum(1 for x in r["rows"] if x["found_bars"] > 0)
        tl += sm; tf += fm; twl += sw; twf += fw
        print("  {:12}{:5d}{:8d}{:13.0f}{:13.0f}{:6.0f}%".format(
            panel, len(r["rows"]), nm, sm, fm, 100 * fm / sm if sm else 0))
    print("-" * 60)
    print("  {:12}{:>5}{:>8}{:13.0f}{:13.0f}{:6.0f}%".format(
        "TOTAL", "", "", tl, tf, 100 * tf / tl if tl else 0))
    print(f"\n  scheduled : {tl/1000:9.1f} m   {twl:9.2f} kg")
    print(f"  found in R: {tf/1000:9.1f} m   {twf:9.2f} kg")
    print(f"  NOT found : {(tl-tf)/1000:9.1f} m   {twl-twf:9.2f} kg")
    json.dump(out, open('out/audit_SR.json', 'w'), indent=1)

    # marks with no trace at all
    print("\n  marks with NO position found anywhere in R:")
    for r in out:
        bad = [x for x in r["rows"] if x["found_bars"] == 0]
        if bad:
            miss = sum(x["sched_mm"] for x in bad)
            print("    {:12} {:2d} marks, {:8.0f} mm : {}".format(
                r["panel"], len(bad), miss,
                " ".join(f"{x['mark']}{'' if x['tagged'] else '*'}" for x in bad)))
    print("    (* = mark is not even labelled anywhere in the R drawing)")


if __name__ == "__main__":
    main()
