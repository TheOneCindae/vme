# Project structure

This workspace contains three separate applications/data areas:

- `ocr/` - OCR utility and its `images/` input folder.
- `facerecog/` - face recognition attendance service, employee data, known faces, logs, and attendance workbook.
- `attendance-dashboard/` - the separate attendance dashboard frontend.
- `bbs_reconcile/`, `rebar3d/`, `rb3/`, and `world-editor/` - rebar tooling.
- `rebar_tools/` - standalone rebar inspection and image experiments.
- `rebar_data/drawings/` - authoritative DWG/PDF/DXF drawing set.
- `rebar_data/samples/drawings/` - duplicate/sample DWGs kept for experiments.
- `rebar_data/analysis/` - generated rebar inspection and extraction artifacts.
- `rebar_data/analysis/images/` - image inputs and outputs for standalone experiments.
- `rebar_data/archive/` - source archives and the archived `Ground Floor` set.

Rebar scripts should resolve source drawings through `rebar_paths.py` or the equivalent repository-relative path. No attendance or OCR code depends on `rebar_data`.
