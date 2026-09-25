# Rebar Project Guide

This document describes the rebar work only. OCR and attendance are separate projects in `ocr/`, `facerecog/`, and `attendance-dashboard/`.

## Purpose

The rebar project reads precast reinforcement drawings and produces one or more of the following:

- extracted bar-bending schedules (BBS)
- detected bar geometry and callouts
- reconciliations between schedule sheets and reinforcement layouts
- 3D bar models and DXF exports
- browser-based viewers and inspection reports

There are three related pipelines in this repository:

1. `rb3/` is the newer schedule-driven reconstruction pipeline. The `(S)` schedule is the authority for bar count, diameter, shape, cut length, and weight; `(R)` drawings provide placement.
2. `rebar3d/` is the older geometry-driven 2D/3D reconstruction pipeline. It detects bars directly from `(R)` geometry, uses `(S)` schedules for filtering and reconciliation, and reconstructs depth and cast-in features.
3. `bbs_reconcile/` is an independent schedule-versus-layout verification pipeline. It is useful when the main 3D reconstruction should not be involved.

## Directory Layout

```text
rebar_paths.py                 Shared repository-relative rebar data paths

rebar_data/
  drawings/                    Authoritative DWG, DXF, and PDF drawing set
  samples/drawings/             Duplicate/sample drawings for experiments
  analysis/                     Generated inspection and extraction results
    images/                    Image inputs and image experiment outputs
    output_rebar_blocks*/       Block extraction results
    output_test/                Test extraction results
  archive/                     ZIP/RAR source archives and archived source sets

rb3/                           Schedule-driven reconstruction pipeline
rebar3d/                       Geometry-driven reconstruction and viewer pipeline
bbs_reconcile/                 Independent BBS/R-drawing reconciliation
rebar_tools/                   Small standalone inspection and image experiments
world-editor/                  Interactive uploaded-DWG editor backed by rebar3d
```

The authoritative source files are in `rebar_data/drawings/`. Do not put new DWGs at the repository root. Scripts should use `rebar_paths.py` or a repository-relative equivalent.

## Shared Paths

[rebar_paths.py](rebar_paths.py) defines:

| Name | Meaning |
| --- | --- |
| `REPO_ROOT` | Repository root directory |
| `REBAR_DATA` | `rebar_data/` |
| `DRAWINGS` | `rebar_data/drawings/` |
| `SAMPLE_DRAWINGS` | `rebar_data/samples/drawings/` |
| `ANALYSIS` | `rebar_data/analysis/` |

Drawing naming follows the panel and sheet suffix convention:

- `(S)` - bar-bending schedule or summary schedule
- `(R)`, `(R1)`, `(R2)` - reinforcement/layout drawings
- `(M)`, `(M1)`, `(M2)`, `(M3)` - mould drawings

## Pipeline 1: `rb3`

`rb3` is the schedule-first implementation. Its core rule is: schedule rows define what bars must exist, while reinforcement drawings define where those bars sit.

### Main flow

```text
rebar_data/drawings/*.dwg and *.pdf
        |
        v
src/convert.py       DWG -> cached DXF in rb3/dxf/
        |
        +--> src/bbs.py       read and verify (S) schedule tables
        +--> src/bbs_pdf.py   read PDF-only schedules when needed
        +--> src/shapelib.py / legend2.py  recover shape-code topology
        +--> src/shapes3d.py  build parametric 3D bar shapes
        +--> src/rbar.py      read bar placement evidence from (R)
        +--> src/assemble.py  place schedule bars in panel coordinates
        |
        +--> src/verify.py    compare output against schedule quantities/lengths/weights
        +--> src/export_dxf.py / build_viewer.py  export DXF and browser viewer
```

### `rb3` files

| File | Responsibility and connections |
| --- | --- |
| `README.md` | Pipeline rules, verification results, known gaps, and commands. |
| `SPEC.md` | Technical specification and implementation notes. |
| `recon.py`, `recon2.py`, `recon3.py`, `recon4.py` | Earlier reconstruction experiments and comparison implementations. They are research/history code, not the main entry point. |
| `src/convert.py` | Finds drawings in `rebar_data/drawings/`, converts DWG to DXF with `dwg2dxf`, and caches results in `rb3/dxf/`. |
| `src/bbs.py` | Parses `(S)` DWG schedules, creates schedule rows, and validates lengths, weights, and totals. It is the schedule authority for the pipeline. |
| `src/bbs_pdf.py` | Extracts BBS data from PDF schedules when a usable DWG schedule is unavailable. |
| `src/shapelib.py` | Low-level shape-code and medial-axis helpers used by the shape interpretation stage. |
| `src/legend2.py` | Reads the drawn rebar legend to recover shape topology and dimensions. |
| `src/shapes3d.py` | Converts schedule dimensions and shape codes into 3D bar polylines. |
| `src/rbar.py` | Extracts placement evidence, bar tags, spacing, and layout information from `(R)` drawings. |
| `src/arrays.py` | Handles arrays and repeated geometry that can be damaged by DWG-to-DXF conversion. |
| `src/leaders.py` | Reads leader lines that connect labels to drawing geometry. |
| `src/place.py` | Places schedule bars using tags, sections, spacing, and panel geometry. |
| `src/elements.py` | Groups drawing content into panel elements and view environments. |
| `src/assemble.py` | Combines schedule bar shapes and placement evidence into complete panel models. |
| `src/build_all.py` | Main batch builder that runs extraction and assembly for the drawing set. |
| `src/verify.py` | Checks that each scheduled bar exists once, has the right length, and preserves schedule weight. |
| `src/takeoff.py` | Produces a whole-drawing-set steel takeoff, including DWG, DXF, and PDF sources. |
| `src/export_dxf.py` | Writes reconstructed 3D bars to per-panel DXF files. |
| `src/render2.py` | Renders reconstruction or comparison views. |
| `src/render_legend.py` | Renders the shape legend used to validate shape interpretation. |
| `src/build_viewer.py` | Builds the self-contained HTML viewer from model data and viewer assets. |
| `src/viewer/app.js` | JavaScript application for the first viewer implementation. |
| `src/viewer/shell.html` | HTML shell for the first viewer implementation. |
| `src/v2/*.py` | Second-generation extraction, binding, section triangulation, per-bar reporting, and validation modules. |
| `src/v2/raw.py` | Reads raw DXF entities for the v2 pipeline. |
| `src/v2/bars2d.py` | Extracts 2D bar candidates from drawing geometry. |
| `src/v2/anchors.py` | Detects and represents anchors and related features. |
| `src/v2/leaders2.py` | v2 leader-line extraction and tag binding. |
| `src/v2/bind.py` | Binds detected geometry to schedule marks. |
| `src/v2/views.py` | Groups and interprets drawing views. |
| `src/v2/section_triangulate.py` | Uses sections to infer bar depth and placement. |
| `src/v2/check.py` | v2 validation and diagnostic checks. |
| `src/v2/per_bar_report.py` | Writes per-bar evidence and reconciliation reports. |
| `src/v2/viewer/app.js` | JavaScript application for the v2 viewer. |
| `src/v2/viewer/shell.html` | HTML shell for the v2 viewer. |

### Typical `rb3` commands

Run from `rb3/` with a Python environment that contains the project dependencies:

```powershell
python src/convert.py "*(S).dwg"
python src/build_all.py
python src/verify.py
python src/export_dxf.py
python src/build_viewer.py
```

The generated DXF cache and output files stay inside `rb3/` and are not source drawings.

## Pipeline 2: `rebar3d`

`rebar3d` reconstructs bars from actual drawing geometry. It detects centerlines and bends in `(R)` sheets, recovers depth from sections, supplements missing geometry from `(S)` schedules, and exports a 3D viewer.

### Main flow

```text
rebar_data/drawings/*.dwg
        |
        v
rebar3d/rebar3d/loader.py     convert DWG -> DXF and flatten entities
        |
        +--> views.py / extract.py       identify views and bar geometry
        +--> schedule.py                 read schedules and BBS PDFs
        +--> reconstruct.py              infer depth, bends, and 3D bars
        +--> export.py / render2d.py     write model exports and images
        +--> viewer_template.html        produce the browser viewer
```

### `rebar3d` files

| File | Responsibility and connections |
| --- | --- |
| `README.md` | Algorithm explanation, viewer behavior, limitations, and usage. |
| `cli.py` | Main command-line entry point. Accepts DWG/DXF paths, calls loader, views, extraction, reconstruction, schedule comparison, and export modules. |
| `loader.py` | Converts DWG to DXF with `dwg2dxf`, caches conversions, and flattens DXF entities into simple records. |
| `views.py` | Clusters drawing entities into elevations, sections, and other spatial views. |
| `extract.py` | Detects bar centerlines, bends, and related geometry from flattened entities. |
| `schedule.py` | Reads `(S)` schedules and schedule PDFs, including itemized BBS rows and summary rows. |
| `reconstruct.py` | Core 3D reconstruction: depth recovery, bar pairing, bends, U-bars, and feature placement. |
| `crosscheck.py` | Compares detected or reconstructed geometry against independent drawing evidence. |
| `bbs_predict.py` | Predicts a BBS from DWG content when a separate schedule is unavailable. |
| `inventory.py` | Produces an exhaustive per-DWG inventory and compares extracted steel with official documents. |
| `sanity.py` | Lightweight consistency and geometry sanity checks. |
| `export.py` | Writes model data and downloadable DXF/report assets. |
| `render2d.py` | Produces 2D projections and diagnostic renderings. |
| `viewer_template.html` | HTML/JavaScript template used to display exported models. |
| `assets_three.js` | Local three.js viewer dependency. |
| `viewer.py` | Serves `rebar3d/out/`, and with `--rebuild` runs the CLI against `(R)` drawings first. |
| `run.sh` | Batch shell wrapper that selects `(R)` drawings and invokes the CLI. |
| `viewer.sh` | Convenience launcher for the viewer. |
| `aroverlay.py` | Camera overlay tool that places a reconstructed model over a casting-bed view using ArUco or manual scale. |
| `row_by_row_report.py` | Compares official BBS rows with reconstructed bars panel by panel. |
| `evidence_sweep.py` | Searches source geometry for evidence supporting rows that appear short or unmatched. |
| `audit_tally.py` | Writes aggregate audit/tally results from generated output. |
| `BBS_RULES.md` | Rules and assumptions used when interpreting BBS data. |
| `DEBUG_REPORT.md` | Investigation notes and known reconstruction issues. |

### `rebar3d/out_groundtruth/`

These underscore-prefixed scripts are historical or diagnostic analyses, not the normal viewer pipeline:

| File | Responsibility |
| --- | --- |
| `_build_bbs_truth.py` | Builds per-panel ground-truth BBS JSON from independent drawing sources. |
| `_build_raw_inventory.py` | Builds raw per-DWG inventories. |
| `_dimension_hatch_check.py` | Checks dimensions and hatch evidence for unresolved bars. |
| `_permissive_pairing.py` | Tests relaxed bar pairing strategies. |
| `_raw_length_audit.py` | Audits raw detected lengths against expected values. |
| `_reconcile.py` | Experimental reconciliation of raw geometry and official schedule data. |

## Pipeline 3: `bbs_reconcile`

This is intentionally independent of `rebar3d`. It reconciles an `(S)` schedule against `(R)` callouts and can export data for a simpler viewer.

```text
(S) DWG -> schedule_extract.py -> schedule rows and totals
(R) DWG -> callouts.py / geometry.py -> callouts and detected bars
              |
              v
        reconcile.py / mark_fill.py
              |
              +--> run_all.py       text reports
              +--> verify.py         checks
              +--> export_viewer_data.py -> viewer JSON
```

| File | Responsibility and connections |
| --- | --- |
| `reconcile.py` | Shared path and reconciliation model; finds `(S)` and `(R)` sheets and combines schedule/callout results. |
| `schedule_extract.py` | Extracts schedule rows and summary totals from `(S)` drawings. |
| `callouts.py` | Parses explicit bar callouts from `(R)` drawings. |
| `geometry.py` | Extracts bar geometry and elevation bounds from `(R)` drawings. |
| `dxf_cache.py` | Converts DWG to DXF and caches conversions under `bbs_reconcile/out/dxf_cache/`. |
| `bent_bars.py` | Synthesizes or recognizes bent-bar geometry from schedule and drawing evidence. |
| `castin.py` | Extracts sleeves and cast-in features. |
| `mark_fill.py` | Fills or reconciles missing schedule marks against detected straight and bent bars. |
| `geo_reconcile.py` | Performs geometry-focused reconciliation and diagnostics. |
| `run_all.py` | Batch entry point; writes one report per panel and a master tally under `bbs_reconcile/out/`. |
| `verify.py` | Runs focused checks over schedule and layout evidence. |
| `export_viewer_data.py` | Builds per-panel JSON for `bbs_reconcile/viewer.html`. |
| `viewer.html` | Browser viewer for exported panel JSON. |

## Standalone Tools: `rebar_tools`

These scripts are small investigations rather than part of the main production pipelines. They use the shared drawing location and write experimental results to `rebar_data/analysis/`.

| File | Responsibility |
| --- | --- |
| `debug_dwg.py` | Prints entity and layer summaries for a selected DXF. |
| `inspect_blocks.py` | Inspects block definitions and inserts, especially `S-RBAR` blocks. |
| `inspect_s_rbar.py` | Dumps and summarizes entities on the `S-RBAR` layer. |
| `arucomarker.py` | Detects ArUco markers in an experiment image. |
| `rebardetector.py` | Experimental image-based rebar detection and marker processing. |
| `thickbars.py` | Experimental image preprocessing/detection for thick bars. |
| `test.py` | Empty/placeholder experiment file. |

Inputs and generated images for these tools are in `rebar_data/analysis/images/`; JSON/CSV results are in `rebar_data/analysis/`.

## Interactive Editor: `world-editor`

| File | Responsibility |
| --- | --- |
| `editor.py` | Local web editor for uploaded DWG/DXF files; uses rebar3d conversion and rendering logic. |
| `editor_template.html` | Editor page and controls. |
| `assets_three.js` | Local three.js dependency. |
| `uploads/` | Temporary user-uploaded drawing files and generated editor assets. |

The editor is a separate UI around rebar processing. It should not be treated as the authoritative batch pipeline.

## Data and Output Rules

- Read official drawings only from `rebar_data/drawings/`.
- Use `rebar_data/samples/drawings/` for duplicate or experimental source files.
- Keep generated JSON, CSV, DXF caches, reports, and images out of the source drawing directory.
- Treat `(S)` schedule data as authoritative for the schedule-driven `rb3` pipeline.
- Treat `(R)` drawings as the primary geometry and placement source.
- Use `(M)` mould drawings for dimensions and mould context; they are not normally the primary bar source.
- Do not mix OCR or attendance files into the rebar data directories.

## Troubleshooting Path Problems

1. Confirm the requested DWG exists under `rebar_data/drawings/`.
2. Check that the script uses `rebar_paths.py` or computes the repository root from `__file__`.
3. Remove only the relevant generated cache/output if a conversion is stale; never delete the authoritative drawings.
4. For missing schedule rows, compare the `(S)` DWG and PDF before changing extraction logic.
5. For missing bar geometry, inspect the corresponding `(R)` sheet and run the geometry/evidence tools before changing schedule data.
