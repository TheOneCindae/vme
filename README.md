# VME Projects

This repository contains three main application areas:

1. **OCR** - extracts handwritten tables from images with Google Gemini and writes Excel output.
2. **Attendance** - face-recognition gate services, attendance storage, Google Sheets sync, and a Next.js dashboard.
3. **Rebar** - DWG/DXF schedule extraction, reinforcement reconciliation, 3D reconstruction, and viewers.

The projects are independent. Install and run only the project you need.

For the detailed rebar file map, see [REBARPROJECT.md](REBARPROJECT.md).

## Repository Structure

```text
ocr/                    OCR script and input images
facerecog/              Face-recognition attendance services
attendance-dashboard/   Next.js attendance dashboard

rb3/                    Schedule-driven rebar reconstruction
rebar3d/                Geometry-driven rebar reconstruction and viewer
bbs_reconcile/          Independent BBS versus layout reconciliation
rebar_tools/            Small rebar inspection/image experiments
world-editor/           Interactive rebar panel editor
rebar_data/             Rebar drawings, samples, archives, and outputs
rebar_paths.py          Shared rebar data path definitions
```

Do not place new DWG, DXF, or PDF source drawings at the repository root. Put official drawing files in `rebar_data/drawings/`.

## General Prerequisites

- Git
- Python 3.11 or newer for the Python applications
- Node.js 20 or newer and npm for `attendance-dashboard`
- A virtual environment per Python project
- Windows PowerShell commands below assume PowerShell. Use `python3` instead of `python` on macOS/Linux when needed.

## 1. OCR Project

### What it does

`ocr/ocr.py` reads supported images from `ocr/images/`, sends each image to the Gemini API, extracts tables as JSON, and writes them to `ocr/output.xlsx`.

Supported image types include JPG, JPEG, PNG, BMP, TIF, TIFF, WEBP, and HEIC.

### Dependencies

The OCR folder currently has no `requirements.txt`. Install these packages:

- `google-genai` - Gemini API client
- `pandas` - table/dataframe handling
- `python-dotenv` - loads `.env`
- `openpyxl` - Excel writer used by pandas

### Windows installation and run

```powershell
cd ocr
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install google-genai pandas python-dotenv openpyxl
```

Create `ocr/.env`:

```dotenv
GEMINI_API_KEY=your-gemini-api-key
```

Put input images in `ocr/images/`, then run:

```powershell
python ocr.py
```

The result is written to `ocr/output.xlsx`. Keep the API key in `.env`; do not commit it.

### macOS/Linux

```bash
cd ocr
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install google-genai pandas python-dotenv openpyxl
python ocr.py
```

## 2. Attendance System

### What it does

`facerecog/` contains the local attendance system:

- `gate_server.py` runs in-gate and out-gate recognition services.
- `admin_server.py` provides the administration service.
- `face_engine.py` loads employee face data from `known_faces/` and `employees.json`.
- `attendance.py` records attendance locally in `attendance.xlsx`.
- `sheets_sync.py` mirrors events to Google Sheets when configured.

The bundled startup scripts run three services:

| Service | Port | Purpose |
| --- | ---: | --- |
| In gate | 5050 | Records employee entry |
| Out gate | 5051 | Records employee exit |
| Admin | 5052 | Administrative UI and login |

### Dependencies

The exact Python dependencies are listed in [facerecog/requirements.txt](facerecog/requirements.txt):

- Flask and pyOpenSSL
- `face_recognition`, `face_recognition_models`, and `dlib`
- OpenCV and NumPy
- OpenPyXL
- Google API and authentication libraries

`dlib` needs native build tools. On Windows this means CMake and Visual Studio C++ Build Tools. On macOS/Linux the setup script installs or checks the required compiler packages.

### Windows installation and run

Install Python 3.11+ from python.org and ensure `python` is on `PATH`. Then run:

```powershell
cd facerecog
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\setup.ps1
.\start_all.ps1
```

The setup script installs CMake and Visual Studio Build Tools when needed, creates `facerecog/.venv`, and installs `requirements.txt`.

### macOS/Linux/WSL installation and run

```bash
cd facerecog
chmod +x setup.sh start_all.sh
./setup.sh
./start_all.sh
```

The shell setup supports macOS and apt-based Linux/WSL. It installs Python, CMake, compiler dependencies, creates `.venv`, and installs `requirements.txt`.

### Attendance configuration

Create `facerecog/secrets/google-service-account.json` with the Google service-account key used for Sheets sync. The startup scripts set:

```text
GOOGLE_SHEET_ID=<spreadsheet id>
GOOGLE_SERVICE_ACCOUNT_FILE=<path to service-account JSON>
```

Add employee records to `facerecog/employees.json` and face images under `facerecog/known_faces/<employee-id>/`. Do not commit service-account keys, face data, or other secrets.

The local workbook remains the attendance source of truth. Google Sheets synchronization is a secondary mirror.

## 3. Attendance Dashboard

### What it does

`attendance-dashboard/` is a Next.js application that displays attendance data. Its API route reads the `Attendance` tab from Google Sheets and falls back to mock data when credentials are not configured.

### Dependencies

Dependencies are declared in [attendance-dashboard/package.json](attendance-dashboard/package.json):

- Next.js
- React and React DOM
- `googleapis`
- TypeScript and type definitions
- Tailwind CSS and ESLint tooling

### Installation and development run

```powershell
cd attendance-dashboard
npm install
npm run dev
```

Open `http://localhost:3000`.

For a production build:

```powershell
npm run lint
npm run build
npm start
```

### Dashboard configuration

Create `attendance-dashboard/.env.local` when using live Google Sheets data:

```dotenv
GOOGLE_SHEET_ID=your-spreadsheet-id
GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account","project_id":"..."}
```

`GOOGLE_SERVICE_ACCOUNT_JSON` must contain the complete service-account JSON as one environment-variable value. If either variable is missing, the dashboard intentionally uses generated mock rows.

## 4. Rebar Projects

### What they do

The rebar tools process precast reinforcement drawings:

- `(S)` sheets provide bar-bending schedule data.
- `(R)`, `(R1)`, and `(R2)` sheets provide reinforcement layout and placement.
- `(M)` sheets provide mould and dimensional context.

The main rebar data is in `rebar_data/drawings/`. Generated data belongs in project `out/` folders or `rebar_data/analysis/`.

There are three connected but separate implementations:

| Project | Role |
| --- | --- |
| `rb3/` | Newer schedule-driven 3D reconstruction. Schedule rows define bar count, length, shape, and weight; `(R)` drawings define placement. |
| `rebar3d/` | Geometry-driven 2D/3D reconstruction with depth recovery, bent bars, sleeves, anchors, and a viewer. |
| `bbs_reconcile/` | Independent schedule-versus-layout reconciliation and report generation. |

Read [REBARPROJECT.md](REBARPROJECT.md) for the module-by-module connection map.

### Rebar dependencies

The rebar folders do not currently provide one shared requirements file. The commonly required Python packages are:

```powershell
python -m pip install ezdxf matplotlib numpy pymupdf opencv-python
```

Some experimental scripts may need additional packages such as SciPy. Install those only when the selected script reports that they are missing.

The DWG pipelines also require `dwg2dxf` from LibreDWG on `PATH`.

Create a separate environment for rebar work:

```powershell
python -m venv .venv-rebar
.\.venv-rebar\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install ezdxf matplotlib numpy pymupdf opencv-python
```

### `rebar3d` commands

Run from the `rebar3d/` directory:

```powershell
cd rebar3d
python viewer.py
```

Use `--rebuild` to process the `(R)` drawings before serving the viewer:

```powershell
python viewer.py --rebuild --no-browser
```

The viewer serves generated files from `rebar3d/out/`. The lower-level CLI can be run directly:

```powershell
python -m rebar3d.cli ..\rebar_data\drawings\PW-GF-02(R).dwg -o out
```

### `bbs_reconcile` commands

Run from the reconciliation directory:

```powershell
cd bbs_reconcile
python run_all.py
python verify.py
python export_viewer_data.py
```

Reports and viewer JSON are written below `bbs_reconcile/out/`.

### `rb3` commands

Run from `rb3/`:

```powershell
cd rb3
python src/convert.py "*(S).dwg"
python src/build_all.py
python src/verify.py
python src/export_dxf.py
python src/build_viewer.py
```

`convert.py` creates DXF cache files, `build_all.py` extracts and assembles models, `verify.py` checks them against schedules, and the export/viewer scripts create deliverables.

### `world-editor` commands

The editor is a separate local UI backed by the `rebar3d` pipeline:

```powershell
cd world-editor
python editor.py
```

It uses `world-editor/uploads/` for uploaded drawings and `rebar3d/out/` for the panel palette.

## Security and Generated Files

- Never commit Gemini API keys, Google service-account JSON, `.env` files, face images, or attendance exports containing sensitive data.
- Keep official drawings in `rebar_data/drawings/` and generated files outside that source directory.
- The attendance dashboard may use mock data when credentials are absent; verify the reported data source before treating it as live attendance data.

## Quick Start by Project

```text
OCR:       cd ocr; install Python packages; add .env; python ocr.py
Attendance: cd facerecog; .\setup.ps1; .\start_all.ps1
Dashboard: cd attendance-dashboard; npm install; npm run dev
Rebar 3D:  cd rebar3d; install Python packages + dwg2dxf; python viewer.py --rebuild
```
