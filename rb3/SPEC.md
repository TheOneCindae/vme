# rb3 v2 — geometry-first reconstruction

## The change

v1 built the model from the schedule and *invented* positions. That is why it
does not look like the drawing. v2 inverts this:

> **Every bar drawn in the (R) views is a real object. Recover those objects
> from the raw DWG, lift them into 3D, and use the schedule only to identify
> and verify them — never to synthesise a position.**

A bar may only appear in the model because it was found in the drawing, or
because the schedule proves it exists and the drawing shows where (spacing
note + a located array). Nothing is "spread evenly" any more. If a bar cannot
be located, it is reported as UNLOCATED — not faked.

## Pipeline stages and owners

| Stage | Module | Owns |
|---|---|---|
| 1 raw | `src/v2/raw.py` | lossless entity extraction from DWG |
| 2 bars2d | `src/v2/bars2d.py` | drawn bar objects per view (2D centrelines) |
| 3 views | `src/v2/views.py` | view registration + 2D→3D lift |
| 4 bind | `src/v2/bind.py` | bar ↔ schedule mark binding, reconciliation |
| 5 check | `src/v2/check.py` + viewer | verification, overlays, 3D viewer |

Each stage writes JSON to `out/v2/` and reads only the previous stage's JSON.
**Do not edit another stage's module.**

## Data contracts (JSON)

### stage 1 → `out/v2/raw/<sheet>.json`
```
{ "sheet": "PW-GF-09_R1",
  "layouts": {...},
  "entities": [ {"type":"LINE|ARC|CIRCLE|LWPOLYLINE|MTEXT|INSERT|HATCH|DIMENSION",
                 "layer": str, "space": "model|paper",
                 "pts": [[x,y],...],           # world coords, blocks exploded
                 "r": float, "a0": float, "a1": float,   # arcs/circles
                 "text": str, "block": str, "src": "top|block:<name>"} ],
  "viewports": [ {"center":[x,y], "w":..., "h":..., "scale":..., "title":...} ] }
```
Rules: explode every INSERT recursively (blocks carry world coords with
ins_pt at origin — see notes). Convert LWPOLYLINE bulges to arc points.
Nothing may be dropped silently; report counts in/out.

### stage 2 → `out/v2/bars2d/<sheet>.json`
```
{ "views": [ {"id":..., "kind":"elevation|plan_cut|end_cut|detail",
              "wall_polygon": [[x,y],...],      # true concrete outline
              "bars": [ {"id":..., "dia": 8, "pts": [[x,y],...],
                         "closed": bool, "kind":"run|section",
                         "len": float, "evidence":"paired_edges|circle"} ] } ] }
```
A `run` is a bar seen lengthwise (recover its full centreline including bends
and hooks — merge fragments across crossings). A `section` is a bar seen
end-on (circle, radius = d/2), giving a point.

### stage 3 → `out/v2/lift/<element>.json`
```
{ "element": "...", "envelope": {...}, "outline": [[x,z],...],
  "bars3d": [ {"id":..., "dia":..., "pts":[[x,y,z],...],
               "from_views":[...], "confidence": 0..1 } ] }
```
Register views to one element frame. A bar seen in two views must be fused
into ONE 3D bar, not duplicated.

### stage 4 → `out/v2/bound/<element>.json`
Adds `"mark"`, `"schedule"`, `"cut_length_mm"`, `"weight_kg"` to each bar and
emits a reconciliation report: per mark, scheduled qty vs located qty, and the
list of UNLOCATED marks with reasons.

### stage 5 → `out/v2/report/*`
Overlay renders (drawing vs model, per view), a numeric accuracy report, and
the 3D viewer.

## Ground truth already established (do not re-derive)

- `dwg2dxf` (LibreDWG) converts these files; DXFs are cached in `dxf/`.
- **Blocks are placed at ins_pt (0,0) with world coordinates baked into the
  block geometry** (Revit export). You MUST explode to see leader heads and
  tag bubbles. Verified: no *bars* live inside blocks, only annotation.
- Bars are drawn as OUTLINES: two parallel edges offset by the bar diameter,
  plus concentric arc pairs at bends and 180° end caps of radius d/2.
  Centreline = medial axis. Radii present: 4/5/6/8/10 → T8/T10/T12/T16/T20.
- In sections, a CIRCLE of radius d/2 is a bar seen end-on.
- Layers: `S-RBAR` = bars, `S-RBAR-IDEN` = mark tags/leaders,
  `A-WALL`/`A-WALL-HDLN` = concrete outline, `G-ANNO-SCHD` = schedule text.
- Viewports in Layout1 give each view's model window
  (`view_center_point`, `view_height`) and 1:50 / 1:25 scale.
- Elements are NOT boxes: e.g. PW-GF-09_R is an H-shape — columns x 0..820 and
  3200..4000 full height 2930, web x 820..3200 recessed to z 580..2380.
- A drawing package may hold several elements (PW-GF-09 has 3). Schedules bind
  to the sheet that tags their marks. `src/elements.py` does this already.
- Schedules are exact and already verified: `out/bbs.json`
  (256 marks / 3629 bars for the 11 (S) panels; PW-GF-27 and PW-GF-30
  schedules live in their `_R2` sheets; PC-GF-01's in `_R`).
- Mark tags read `-(62) -(T8)` on most sheets but `2 -T20` / `T8 UBAR @125 mm`
  on PW-GF-02 and PW-GF-09 — BOTH formats must be parsed.
- Spacing notes: `T8 @200 mm`, `T8 Horizontal @150 mm`, `T8 Ties @100 mm`.

## Definition of done

Accuracy is measured, not asserted:
1. every schedule bar is LOCATED or explicitly listed as unlocated with a reason
2. overlay of model vs drawing, per view, with a numeric mismatch figure
3. bar-for-bar: drawn bar count per view vs model bar count per view
