"""Detect runs of evenly spaced bars in a drawing view.

Reinforcement is drawn as arrays: N parallel bars of one diameter, the same
length, at a constant pitch. Finding those arrays gives real positions for
every bar in them, and an array's (diameter, count, pitch, length) signature
is enough to match it to a schedule mark without relying on leader lines,
which the DWG->DXF conversion mangles.
"""
import math, collections
import rbar


def runs_in_view(doc, view, dias, min_len=60.0, gap=30.0):
    """Merged bar centrelines in a view, in panel-local coordinates."""
    wb = view["wall"]
    lines, arcs = rbar.collect(doc, view["box"])
    mids, _ = rbar.pair_lines(lines, dias=dias)
    out = []
    for b in rbar.merge_collinear(mids, gap=gap):
        if b["len"] < min_len:
            continue
        p = (b["p"][0] - wb[0], b["p"][1] - wb[1])
        q = (b["q"][0] - wb[0], b["q"][1] - wb[1])
        if (q[0], q[1]) < (p[0], p[1]):
            p, q = q, p
        out.append({"p": p, "q": q, "len": b["len"], "dia": b["dia"],
                    "ang": b["ang"] % 180})
    return out


def _axis(ang, tol=8.0):
    if ang < tol or ang > 180 - tol:
        return "h"
    if abs(ang - 90) < tol:
        return "v"
    return "d"


def find_arrays(runs, len_tol=0.06, pitch_tol=0.18, min_n=2):
    """Group runs into evenly spaced arrays of equal-length parallel bars."""
    buckets = collections.defaultdict(list)
    for r in runs:
        buckets[(r["dia"], _axis(r["ang"]))].append(r)
    arrays = []
    for (dia, ax), items in buckets.items():
        if ax == "d":
            continue
        # group by length
        items.sort(key=lambda r: r["len"])
        groups, cur = [], [items[0]] if items else []
        for r in items[1:]:
            if abs(r["len"] - cur[0]["len"]) <= max(25.0, len_tol * cur[0]["len"]):
                cur.append(r)
            else:
                groups.append(cur); cur = [r]
        if cur:
            groups.append(cur)
        for g in groups:
            # position across the array = the coordinate perpendicular to the run
            key = (lambda r: r["p"][1]) if ax == "h" else (lambda r: r["p"][0])
            g.sort(key=key)
            pos = [key(r) for r in g]
            i = 0
            while i < len(g):
                j = i + 1
                pitches = []
                while j < len(g):
                    d = pos[j] - pos[j - 1]
                    if d < 1e-6:
                        j += 1; continue
                    if not pitches:
                        pitches.append(d)
                    elif abs(d - pitches[0]) > max(8.0, pitch_tol * pitches[0]):
                        break
                    else:
                        pitches.append(d)
                    j += 1
                n = j - i
                if n >= min_n:
                    seg = g[i:j]
                    arrays.append({
                        "dia": dia, "axis": ax, "n": n,
                        "pitch": round(sum(pitches) / len(pitches), 1) if pitches else None,
                        "len": round(sum(r["len"] for r in seg) / n, 1),
                        "bars": seg,
                        "span": (round(pos[i], 1), round(pos[j - 1], 1)),
                    })
                elif n == 1:
                    seg = g[i:j]
                    arrays.append({"dia": dia, "axis": ax, "n": 1, "pitch": None,
                                   "len": round(seg[0]["len"], 1), "bars": seg,
                                   "span": (round(pos[i], 1), round(pos[i], 1))})
                i = j
    arrays.sort(key=lambda a: -a["n"])
    return arrays


# Two detections this close together (in the position-across-the-array
# coordinate) are the same physical bar seen twice -- e.g. once from each of
# two lift-fused legs that both projected to (almost) the same spot -- never
# two real neighbouring bars. Every documented spacing note in this dataset
# (SPEC.md) is >=100mm, and every genuine pitch observed empirically is
# >=90mm, so 20mm is a wide safety margin below any real bar spacing while
# comfortably covering the ~1-8mm jitter duplicate detections actually show.
DUP_TOL = 3.0


def _estimate_pitch(bars, key):
    """Infer a pitch from a set of positions once no array had one yet.

    find_arrays only ever locks a pitch from two *consecutive* raw detections
    at the finest step; a group built purely out of merged n=1 singletons
    never gets that chance and stays pitch=None forever, which blocks the
    "gap is a whole multiple of pitch" bridging below. Recovering a pitch
    from the group's own positions (after collapsing duplicate detections)
    lets that bridging kick in on later passes.
    """
    pos = sorted(key(r) for r in bars)
    ded = []
    for v in pos:
        if not ded or v - ded[-1] > DUP_TOL:
            ded.append(v)
    if len(ded) < 2:
        return None
    diffs = sorted(ded[i + 1] - ded[i] for i in range(len(ded) - 1))
    return diffs[0]


def merge_arrays(arrays, len_tol=0.06, pitch_tol=0.2):
    """Rejoin arrays split apart where other bars cross the run."""
    out = []
    used = [False] * len(arrays)
    order = sorted(range(len(arrays)), key=lambda i: (arrays[i]["dia"],
                                                     arrays[i]["axis"],
                                                     arrays[i]["span"][0]))
    for ii in order:
        if used[ii]:
            continue
        a = dict(arrays[ii]); a["bars"] = list(arrays[ii]["bars"])
        used[ii] = True
        key = (lambda r: r["p"][1]) if a["axis"] == "h" else (lambda r: r["p"][0])
        changed = True
        while changed:
            changed = False
            for jj in order:
                if used[jj]:
                    continue
                b = arrays[jj]
                if b["dia"] != a["dia"] or b["axis"] != a["axis"]:
                    continue
                if abs(b["len"] - a["len"]) > max(25.0, len_tol * a["len"]):
                    continue
                pa, pb = a.get("pitch"), b.get("pitch")
                if pa and pb and abs(pa - pb) > max(10.0, pitch_tol * pa):
                    continue                           # different established pitch: not one line
                pitch = pa or pb
                lo = min(a["span"][0], b["span"][0])
                hi = max(a["span"][1], b["span"][1])
                gap = min(abs(b["span"][0] - a["span"][1]),
                          abs(a["span"][0] - b["span"][1]))
                if pitch:
                    # bars hidden behind crossing steel leave gaps that are
                    # whole multiples of the pitch -- those still belong to
                    # the same run
                    k = round(gap / pitch)
                    if k < 1:
                        k = 1
                    if abs(gap - k * pitch) > max(12.0, 0.25 * pitch):
                        continue
                elif gap > 400:
                    continue
                a["bars"] += b["bars"]
                a["n"] = len(a["bars"])
                a["span"] = (round(lo, 1), round(hi, 1))
                # A group built out of merged n=1 singletons never had a
                # chance to lock a pitch in find_arrays (see _estimate_pitch
                # docstring) -- recover one from the merged positions so the
                # whole-multiple bridging above can keep extending the chain
                # on later passes instead of stalling at isolated pairs.
                a["pitch"] = pitch or _estimate_pitch(a["bars"], key)
                used[jj] = True
                changed = True
        a["bars"].sort(key=key)
        # drop duplicates at the same position (a bar drawn in two pieces,
        # or the same physical bar recovered twice by stage-3 fusion)
        ded, last = [], None
        for r in a["bars"]:
            v = key(r)
            if last is None or abs(v - last) > DUP_TOL:
                ded.append(r); last = v
        a["bars"] = ded
        a["n"] = len(ded)
        out.append(a)
    out.sort(key=lambda x: -x["n"])
    return out


def match_marks(marks, arrays, note_for=None, len_tol=0.08):
    """Bind schedule marks to detected arrays.

    A mark matches an array when the diameters agree and the array's bar
    length matches either the mark's cut length or one of its legs (a bent
    bar shows only one leg in a given view). Count and annotated pitch break
    ties. Arrays are consumed so two marks never claim the same bars.
    """
    free = [a for a in arrays]
    result = {}
    def score(m, a):
        if int(m["dia_mm"]) != a["dia"]:
            return None
        legs = [v for v in m["dims_mm"].values() if v]
        targets = [m["bar_length_mm"]] + legs
        best = min(abs(a["len"] - t) / max(t, 1) for t in targets)
        if best > len_tol:
            return None
        s = best * 100
        note = (note_for or {}).get(m["mark"], {})
        sp = note.get("spacing")
        if sp and a.get("pitch"):
            s += abs(a["pitch"] - sp) / sp * 40
        s += abs(a["n"] - m["qty"]) / max(m["qty"], 1) * 25
        return s
    pairs = []
    for m in marks:
        for idx, a in enumerate(free):
            sc = score(m, a)
            if sc is not None:
                pairs.append((sc, m["mark"], idx))
    pairs.sort()
    taken_m, taken_a = set(), set()
    for sc, mk, idx in pairs:
        if mk in taken_m or idx in taken_a:
            continue
        taken_m.add(mk); taken_a.add(idx)
        result[mk] = {"array": free[idx], "score": round(sc, 2)}
    return result
