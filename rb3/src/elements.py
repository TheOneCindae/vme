"""Split a drawing set into its actual elements and bind each schedule to one.

A "panel" in this set is a drawing package, not necessarily a single element.
PW-GF-09 for instance carries three: a 4000x2930 H-shaped wall on its (R)
sheet and two 1500x5095 panels on (R1)/(R2). Its schedule is likewise split
into parts (A), (B), (C). Treating the package as one element forces bars into
concrete they do not belong to, so each schedule is matched to the element
whose dimensions its bars actually fit.
"""
import glob, collections
from pathlib import Path
import ezdxf
import assemble as A
import rbar


def element_name(panel, cand, n_total):
    """Canonical name for one element, shared by every stage.

    A package with a single element keeps the plain panel name; a package
    with several (PW-GF-09 has three) disambiguates by size, matching the
    convention the v1 pipeline already used -- so v1 output, stage 3's lift,
    and stage 4's binding all agree on what to call the same element.
    """
    if n_total <= 1:
        return panel
    w, h, t = cand["key"]
    return f"{panel} [{w}x{h}x{t}]"


def candidates(panel, dxf_paths):
    """Distinct elements drawn across a package's R sheets."""
    out = []
    for p in sorted(dxf_paths):
        try:
            doc = ezdxf.readfile(str(p))
        except Exception:
            continue
        vl = A.classify(doc)
        env = A.panel_envelope(vl)
        if not env.get("height_mm") or not env.get("width_mm"):
            continue
        out.append({"sheet": Path(p).stem, "doc": doc, "views": vl, "env": env,
                    "key": (round(env["width_mm"]), round(env["height_mm"]),
                            round(env["thickness_mm"] or 0))})
    # merge sheets describing the same element; keep the one with an elevation
    best = {}
    for c in out:
        k = c["key"]
        cur = best.get(k)
        has_elev = any(v["kind"] == "elevation" for v in c["views"])
        if cur is None:
            best[k] = c
        else:
            cur_elev = any(v["kind"] == "elevation" for v in cur["views"])
            if has_elev and not cur_elev:
                best[k] = c
            elif has_elev == cur_elev and len(c["views"]) > len(cur["views"]):
                best[k] = c
    # sheets with no elevation still contribute their section cuts
    for c in out:
        k = c["key"]
        if best[k] is not c:
            best[k].setdefault("extra", []).append(c)
    return list(best.values())


def fit_score(marks, env, tol=25.0):
    """How well a schedule's bars suit an element.

    Scored on the projection each bar would need: a 5050 mm bar sits happily
    in a 5095 mm tall element but has to stick 1050 mm out of a 4000 mm one.
    The element demanding least projection is the one the schedule belongs to,
    with a mild preference for elements the bars actually fill.
    """
    W, H = env["width_mm"], env["height_mm"]
    span = max(W, H)
    if span <= 0:
        return -1e9
    proj = 0.0
    tot = 0
    longest = 0.0
    for m in marks:
        L = m["bar_length_mm"]; n = m["qty"]
        tot += n
        longest = max(longest, L)
        over = L - span - tol
        if over > 0:
            proj += over * n
    # bars far shorter than the element suggest the wrong element too
    fill = min(longest / span, 1.0)
    return -proj / 1000.0 + fill * 50.0 - (0 if tot else 1e6)
def sheet_marks(cand):
    """Mark letters actually tagged on an element's sheets."""
    out = set()
    docs = [cand] + cand.get("extra", [])
    for c in docs:
        for v in c["views"]:
            try:
                mk, _, _ = rbar.tags(c["doc"], v["box"], 3000)
            except Exception:
                continue
            out |= {t["mark"] for t in mk}
    return out


def assign(schedules, elems):
    """Bind each schedule to its element.

    The drawing itself says which marks belong to which sheet: the mark tags
    on that sheet. That evidence decides it, and the dimensional fit is only
    used to break ties or when a sheet carries no tags.
    """
    tags = [sheet_marks(e) for e in elems]
    out = {}
    for name, marks in schedules.items():
        want = {m["mark"] for m in marks}
        scored = []
        for i, e in enumerate(elems):
            overlap = len(want & tags[i]) / max(len(want), 1)
            scored.append((overlap * 200 + fit_score(marks, e["env"]), i, overlap))
        scored.sort(reverse=True)
        best = scored[0][1] if scored else None
        out[name] = {"element": best,
                     "score": round(scored[0][0], 1) if scored else None,
                     "tag_overlap": round(scored[0][2], 2) if scored else None,
                     "all": [(round(s, 1), elems[i]["key"], round(o, 2))
                             for s, i, o in scored]}
    return out


def assign_marks(marks, elems):
    """Bind each individual mark to its element, not the whole schedule at once.

    A package like PW-GF-09 can reuse the same mark letters across several
    physically distinct pieces of concrete, each drawn on its own sheet --
    every sheet tags nearly the whole mark alphabet, so scoring the schedule
    as one block picks a single "best" sheet and starves every other real
    element of its own bars. A mark tagged on exactly one sheet unambiguously
    belongs there; only marks tagged on several sheets (or none) need the
    dimensional-fit tie-break, and even then only among the sheets actually
    contending for them.

    Returns {mark_letter: element_index}.
    """
    tags = [sheet_marks(e) for e in elems]
    out = {}
    ambiguous = []
    for m in marks:
        mk = m["mark"]
        if mk in out:
            continue
        hits = [i for i, t in enumerate(tags) if mk in t]
        if len(hits) == 1:
            out[mk] = hits[0]
        else:
            ambiguous.append((mk, hits))
    if ambiguous:
        by_mark = {}
        for m in marks:
            by_mark.setdefault(m["mark"], m)
        for mk, hits in ambiguous:
            m = by_mark[mk]
            cand_idx = hits if hits else list(range(len(elems)))
            scored = [(fit_score([m], elems[i]["env"]), i) for i in cand_idx]
            scored.sort(reverse=True)
            out[mk] = scored[0][1] if scored else None
    return out
