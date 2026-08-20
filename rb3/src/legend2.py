"""Isolate each legend shape as a connected geometry cluster and attach the
DIMENSIONs that actually measure it (via their extension-line origins)."""
import sys, math, re, glob, json
sys.path.insert(0, 'src')
import ezdxf, shapelib
from pathlib import Path

def entity_pts(e):
    t = e.dxftype()
    if t == 'LINE':
        return [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
    if t == 'ARC':
        c, r = e.dxf.center, e.dxf.radius
        pts = []
        a0, a1 = e.dxf.start_angle, e.dxf.end_angle
        sw = (a1 - a0) % 360
        for i in range(9):
            a = math.radians(a0 + sw * i / 8)
            pts.append((c.x + r*math.cos(a), c.y + r*math.sin(a)))
        return pts
    return []

def clusters(doc, gap=3.0):
    """Connected components of legend outline geometry (paper space)."""
    lay = doc.layout('Layout1')
    ents = [e for e in lay if e.dxftype() in ('LINE', 'ARC')
            and e.dxf.layer in shapelib.LEGEND_LAYERS]
    boxes = []
    for e in ents:
        p = entity_pts(e)
        if not p: continue
        xs = [q[0] for q in p]; ys = [q[1] for q in p]
        boxes.append([e, min(xs), min(ys), max(xs), max(ys)])
    parent = list(range(len(boxes)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    def uni(a, b):
        ra, rb = find(a), find(b)
        if ra != rb: parent[rb] = ra
    for i in range(len(boxes)):
        for j in range(i+1, len(boxes)):
            _, x0, y0, x1, y1 = boxes[i]
            _, a0, b0, a1, b1 = boxes[j]
            if x0-gap <= a1 and a0-gap <= x1 and y0-gap <= b1 and b0-gap <= y1:
                uni(i, j)
    groups = {}
    for i, b in enumerate(boxes):
        groups.setdefault(find(i), []).append(b)
    out = []
    for g in groups.values():
        if len(g) < 3: continue
        xs0 = min(b[1] for b in g); ys0 = min(b[2] for b in g)
        xs1 = max(b[3] for b in g); ys1 = max(b[4] for b in g)
        out.append({'ents': [b[0] for b in g], 'bbox': (xs0, ys0, xs1, ys1)})
    return out

def dims_for(doc, bbox, pad=6.0):
    x0, y0, x1, y1 = bbox
    out = []
    for e in doc.layout('Layout1').query('DIMENSION'):
        p2, p3 = e.dxf.get('defpoint2'), e.dxf.get('defpoint3')
        if p2 is None or p3 is None: continue
        mx, my = (p2.x+p3.x)/2, (p2.y+p3.y)/2
        if x0-pad <= mx <= x1+pad and y0-pad <= my <= y1+pad:
            out.append({'text': (e.dxf.text or '').strip(),
                        'p2': (p2.x, p2.y), 'p3': (p3.x, p3.y),
                        'm': e.dxf.get('actual_measurement', None)})
    return out

def label_for(labels, bbox):
    x0, y0, x1, y1 = bbox
    cy = (y0+y1)/2
    best, bd = None, 1e9
    for l in labels:
        if l['x'] > x0: continue
        d = abs(l['y'] - cy)
        if d < bd: best, bd = l, d
    return best['code'] if best and bd < (y1-y0)/2 + 8 else None
