# rb3 — 3D rebar reconstruction from VME precast drawings

Reconstructs every reinforcement bar in the `DRAWINGS/` panel set as exact 3D
geometry, driven by the verified bar bending schedules.

**Result: 11 panels · 256 schedule marks · 3,629 bars · 4,086.19 kg**, with every
bar present in 3D at its scheduled cut length.

This is a fresh implementation; it does not share code with the older `rebar3d/`.

## Why the schedule drives the model

The `(S)` files are the bar bending schedules — checked and signed-off, with every
bar's diameter, shape code, A–G dimensions, cut length, quantity and weight. They
are the authority. The model is built *from* that list, so a bar cannot be silently
lost by a geometry-extraction failure: the bar count and weight are correct by
construction, and the `(R)` reinforcement drawings supply position.

## Pipeline

| Step | Module | What it does |
|---|---|---|
| 1 | `convert.py` | DWG → DXF via LibreDWG (`dwg2dxf`), cached in `dxf/` |
| 2 | `bbs.py` | Reads the `(S)` schedule tables verbatim and self-verifies |
| 3 | `shapelib.py`, `legend2.py` | Recovers each shape code's leg topology from the drawn legend (medial axis of the bar outline) |
| 4 | `shapes3d.py` | Parametric 3D geometry per shape code from the A–G dimensions |
| 5 | `rbar.py` | True-scale bar centrelines, bar ends and cross-sections from `(R)` |
| 6 | `assemble.py` | Places every bar in panel-local 3D coordinates |
| 7 | `export_dxf.py`, `build_viewer.py` | 3D DXF per panel, and a self-contained WebGL viewer |
| 8 | `verify.py` | End-to-end check of the model against the schedules |

## Verification

`bbs.py` reconciles every schedule row three independent ways — bar length ×
quantity against the printed total, computed steel weight (πd²/4 × 7850 kg/m³)
against the printed weight, and the sum of rows against the printed grand total.
**All 256 marks across 11 panels reconcile with zero discrepancies.**

`verify.py` then checks the assembled model: every scheduled bar exists once per
unit of quantity, each polyline's length equals its scheduled cut length, and each
panel's weight matches its schedule.

## Geometry: form vs length

Shape dimensions and cut lengths use different conventions, so both are kept:

- **Form** comes from the A–G dimensions with real bend radii. The dimension
  convention was derived from the legend drawings and verified against them
  (reproduces the drawn geometry to ~0.06 paper units on M_17 and M_17A).
- **Length** comes from the schedule — the fabrication cut length, always rounded
  to 25 mm with the shop's bend and hook allowances applied.

249 of 255 marks agree within 40 mm before reconciliation. The residual is absorbed
by scaling the straight runs, and is recorded per bar as `residual_mm` and
`shape_scale`, so the bend allowance is auditable and never hidden.

## Placement provenance

How a bar SITS is decided from the drawing's own annotation and from what its
dimensions can physically mean — never by picking whichever orientation happens
to fit. A bar hooks through the panel thickness when the drawing labels it a
"U Bar"/link, or when one of its legs equals the clear distance between covers
(only possible if that leg spans the thickness). A fold deeper than the clear
distance cannot go through the panel, so it lies in the face instead.
**1,235 of 3,629 bars hook through the thickness.**

Bars repeat *across* the panel face, never through it: a bar running along X is
stacked up Z. A mark tagged more than once is more than one run — an edge U bar
tagged "61" at each end is two stacks of 61, not 122 in a line. Grouping is only
applied when the tag quantities sum to the scheduled quantity (129 of 256 marks).

Every bar records how its position was obtained:

- `section_exact` (528) — read from a section cut whose bar count matched the schedule
- `section_matched` (283) — read from a section, count did not match exactly
- `spaced` (902) — arrayed at the spacing the drawing annotates ("T8 @200 mm")
- `distributed` (1,916) — the drawing gave neither a position nor a spacing, so
  the bar is spread evenly. **Geometry, length and weight are still exact; only
  position is approximate.**
- `+grouped` — split into the runs the drawing's repeated tags imply
- `+projecting` — bar is longer than the panel (starter/dowel), left protruding

**1,713 of 3,629 bars (47%) are positioned from drawing evidence.**

## Outputs

- `out/bbs.json` — the extracted schedules
- `out/model3d.json` — the full 3D model, every bar with its polyline and provenance
- `out/dxf3d/*.dxf` — 3D DXF per panel, one 3D polyline per bar, layered `RBAR-T{dia}-{mark}`
- `out/viewer.html` — self-contained 3D viewer (no network needed)
- `out/shapes_dims.png` — the shape catalogue with its dimension mapping

## Known gaps

- **PW-GF-27** is excluded: its `(S)` file contains only the legend sheet — the
  schedule table is absent from the source DWG (confirmed against the PDF).
- **Crank angle** for shapes `26`, `Rebar Shape 30/31` is taken from the legend
  (17.5°); it is not a dimensioned quantity in the schedule.
- **PW-GF-02 and PW-GF-09** are the weakest: their mark tags do not reconcile
  with the schedule quantities, so grouping and spacing cannot be trusted there
  and nearly all their bars fall back to even distribution.
- **Leader lines** (which bind a tag to the exact bar it labels) are extracted but
  not yet reliable enough to use for positioning; only the tag text, quantity and
  spacing are consumed. Wiring these up is the main remaining accuracy gain.

## Running it

```sh
./venv/bin/python src/convert.py "*(S).dwg"     # DWG -> DXF
./venv/bin/python src/build_all.py              # extract + assemble
./venv/bin/python src/verify.py                 # check against schedules
./venv/bin/python src/export_dxf.py             # 3D DXF exports
./venv/bin/python src/build_viewer.py           # viewer
```
