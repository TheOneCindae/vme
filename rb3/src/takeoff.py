"""Complete steel take-off for the whole drawing set -- every cm accounted.

Sources of bar data, in order of authority:
  1. an (S) bar bending schedule -- mark-level, checked and signed off
  2. a schedule table carried in an (R) drawing (some elements have no S sheet)
  3. a Summary Schedule only -- per-diameter totals, no mark breakdown
  4. a schedule that exists only as a PDF
  5. a cross-reference: the element's mould drawing states
     "FOR REINFORCEMENT DETAILS REFER <other element>", so it is reinforced
     to that element's design and carries the same steel.
"""
import sys, re, glob, json, collections
sys.path.insert(0, 'src')
import bbs, bbs_pdf
from pathlib import Path

DWG = Path(__file__).resolve().parents[2] / "rebar_data" / "drawings"


def element_of(stem):
    return re.sub(r'_(S|R\d*|M\d*)$', '', stem)


ALL_ELEMENTS = set()


def gather():
    """Every schedule and summary found anywhere in the set."""
    marks, summaries = {}, {}
    for f in sorted(glob.glob('dxf/*.dxf')):
        stem = Path(f).stem
        el = element_of(stem)
        try:
            r = bbs.extract(f)
        except Exception:
            continue
        if r['bars']:
            marks.setdefault(el, []).append((stem, r))
        if r['summary'] and r['summary'].get('total'):
            summaries.setdefault(el, []).append((stem, r['summary']))
    # PDF-only schedules
    for p in sorted(DWG.glob('*.pdf')):
        m = re.match(r'^(.*?)\((\w+)\)', p.stem.strip())
        if not m:
            continue
        el = m.group(1).strip()
        # a schedule sheet may be named for the element's short form
        # (PW-01(S).pdf belongs to element PW-01-PW-01)
        if el not in ALL_ELEMENTS:
            cand = [e for e in ALL_ELEMENTS if e.startswith(el + "-") or e == el]
            if len(cand) == 1:
                el = cand[0]
        if el in marks:
            continue
        try:
            r = bbs_pdf.extract(p)
        except Exception:
            continue
        if r['bars']:
            marks.setdefault(el, []).append((p.name, r))
    return marks, summaries


def references():
    """Elements whose mould drawing points at another element's reinforcement."""
    pat = re.compile(r'REINFORCEMENT\s+DETAILS?\s*(?:REFER|SEE)?\s*[:\-]?\s*'
                     r'([A-Z]{2}-[A-Z0-9\-]+)', re.I)
    out = {}
    for f in sorted(glob.glob('dxf/*_M*.dxf')):
        el = element_of(Path(f).stem)
        if el in out:
            continue
        try:
            _, items = bbs.collect_text(f)
        except Exception:
            continue
        t = re.sub(r'\s+', ' ', " ".join(i['t'] for i in items))
        m = pat.search(t)
        if m:
            out[el] = m.group(1).strip()
    # the same note in the issued PDFs, for elements whose DWG text misses it
    try:
        import pymupdf
        for p in sorted(DWG.glob('*.pdf')):
            mm = re.match(r'^(.*?)\((\w+)\)', p.stem.strip())
            if not mm:
                continue
            el = mm.group(1).strip()
            if el in out:
                continue
            try:
                doc = pymupdf.open(p)
            except Exception:
                continue
            t = re.sub(r'\s+', ' ', " ".join(pg.get_text() for pg in doc))
            m2 = pat.search(t)
            if m2:
                out[el] = m2.group(1).strip()
    except ImportError:
        pass
    return out


def all_elements():
    els = collections.defaultdict(set)
    for d in DWG.glob('*.dwg'):
        m = re.match(r'^(.*?)\((\w+)\)\s*$', d.stem.strip())
        if m:
            els[m.group(1).strip()].add(m.group(2))
        else:
            els[d.stem.strip()].add('-')
    return els


def totals_from_marks(r):
    L = sum(b['total_length_mm'] or (b['bar_length_mm'] * b['qty']) for b in r['bars'])
    W = sum(b['weight_kg'] or 0 for b in r['bars'])
    n = sum(b['qty'] for b in r['bars'])
    return L, W, n, len(r['bars'])


def build():
    global ALL_ELEMENTS
    ALL_ELEMENTS = set(all_elements())
    marks, summaries = gather()
    refs = references()
    els = all_elements()
    own = {}
    for el in els:
        best = None
        # prefer a mark-level schedule, S sheet first
        for stem, r in marks.get(el, []):
            L, W, n, nm = totals_from_marks(r)
            rank = 3 if stem.endswith('_S') else (2 if '_R' in stem else 1)
            if best is None or rank > best[0]:
                best = (rank, 'marks', stem, L, W, n, nm)
        if best is None:
            for stem, s in summaries.get(el, []):
                L, W = s['total']['length_mm'], s['total']['weight_kg']
                if best is None or W > best[4]:
                    best = (0, 'summary', stem, L, W, None, None)
        if best:
            own[el] = best
    rows = []
    for el in sorted(els):
        if el in own:
            rank, kind, stem, L, W, n, nm = own[el]
            rows.append({"element": el, "source": kind, "file": stem,
                         "length_mm": L, "weight_kg": W, "bars": n, "marks": nm,
                         "via": None})
        elif el in refs and refs[el] in own:
            t = refs[el]
            rank, kind, stem, L, W, n, nm = own[t]
            rows.append({"element": el, "source": "reference", "file": stem,
                         "length_mm": L, "weight_kg": W, "bars": n, "marks": nm,
                         "via": t})
        else:
            rows.append({"element": el, "source": "NONE", "file": None,
                         "length_mm": None, "weight_kg": None, "bars": None,
                         "marks": None, "via": refs.get(el)})
    return rows, own, refs


if __name__ == "__main__":
    rows, own, refs = build()
    hdr = "{:16}{:11}{:22}{:>7}{:>13}{:>11}".format(
        'element', 'source', 'from', 'bars', 'length mm', 'weight kg')
    print(hdr); print('-' * len(hdr))
    tL = tW = tB = 0; miss = []
    for r in rows:
        if r['weight_kg'] is None:
            miss.append(r['element'])
            print("  {:16}{:11}{:22}{:>7}{:>13}{:>11}".format(
                r['element'], 'NONE', '-', '-', '-', '-'))
            continue
        tL += r['length_mm']; tW += r['weight_kg']; tB += r['bars'] or 0
        src = r['source'] if not r['via'] else f"ref {r['via']}"
        print("  {:16}{:11}{:22}{:>7}{:13.0f}{:11.2f}".format(
            r['element'], src, r['file'] or '-',
            r['bars'] if r['bars'] else '-', r['length_mm'], r['weight_kg']))
    print('-' * len(hdr))
    print("  {:16}{:11}{:22}{:7d}{:13.0f}{:11.2f}".format(
        f"{len(rows)} elements", '', '', tB, tL, tW))
    print(f"\n  = {tL/1000:.1f} m of bar, {tW/1000:.3f} tonnes of steel")
    if miss:
        print("  unaccounted elements:", ", ".join(miss))
    json.dump(rows, open('out/takeoff.json', 'w'), indent=1)
