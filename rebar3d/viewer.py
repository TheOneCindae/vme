#!/usr/bin/env python3
"""Serve the rebar 3D viewer locally.

Usage:
    python3 viewer.py                 serve existing out/viewer.html
    python3 viewer.py --rebuild      re-run the pipeline on ../rebar_data/drawings first
    python3 viewer.py --port 9000    pick a port (default: first free from 8742)

Opens the browser automatically. Ctrl-C to stop.
"""
from __future__ import annotations

import argparse
import json
import http.server
import re
import socket
import socketserver
import sys
import tempfile
import webbrowser
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "out"
DRAWINGS = HERE.parent / "rebar_data" / "drawings"
MAX_UPLOAD_BYTES = 512 * 1024 * 1024
MODELS_RE = re.compile(r"const MODELS = (.*?);\s*const DIA_COLORS", re.S)


def viewer_models(path: Path) -> list[dict]:
    if not path.exists():
        return []
    match = MODELS_RE.search(path.read_text(encoding="utf-8"))
    return json.loads(match.group(1)) if match else []


def merge_viewer_models(path: Path, additional: list[dict]) -> None:
    html = path.read_text(encoding="utf-8")
    current = viewer_models(path)
    merged = {model["name"]: model for model in current if not model["name"].startswith("tmp")}
    merged.update({model["name"]: model for model in additional if not model["name"].startswith("tmp")})
    replacement = "const MODELS = " + json.dumps(list(merged.values())) + ";\n  const DIA_COLORS"
    updated, count = MODELS_RE.subn(replacement, html, count=1)
    if count:
        path.write_text(updated, encoding="utf-8")


def restore_previous_viewer() -> None:
    fallback = HERE / "rebar3d" / "out" / "viewer.html"
    if len(viewer_models(OUT / "viewer.html")) < 2 and len(viewer_models(fallback)) > 1:
        merge_viewer_models(OUT / "viewer.html", viewer_models(fallback))


def rebuild() -> None:
    sys.path.insert(0, str(HERE))
    from rebar3d.cli import main

    drawings = sorted(DRAWINGS.glob("*(R).dwg"))
    if not drawings:
        sys.exit(f"no (R) reinforcement DWGs found in {DRAWINGS}")
    main([str(p) for p in drawings] + ["-o", str(OUT)])


def free_port(start: int) -> int:
    for port in range(start, start + 50):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    sys.exit("no free port found")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rebuild", action="store_true", help="re-run the DWG pipeline first")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    if args.rebuild or not (OUT / "viewer.html").exists():
        rebuild()
    restore_previous_viewer()

    port = args.port or free_port(8742)
    url = f"http://127.0.0.1:{port}/viewer.html"

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(OUT), **kw)

        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != "/upload":
                self._json(404, {"error": "upload endpoint not found"})
                return

            content_length = int(self.headers.get("Content-Length", "0"))
            content_type = self.headers.get("Content-Type", "")
            match = re.search(r'boundary=(?:"([^"]+)"|([^;]+))', content_type)
            if content_length <= 0 or content_length > MAX_UPLOAD_BYTES or not match:
                self._json(400, {"error": "send one DWG or DXF file smaller than 512 MB"})
                return
            boundary = (match.group(1) or match.group(2)).encode("ascii")
            body = self.rfile.read(content_length)
            marker = b"Content-Disposition: form-data;"
            part_start = body.find(marker)
            if part_start < 0:
                self._json(400, {"error": "no file was uploaded"})
                return
            header_end = body.find(b"\r\n\r\n", part_start)
            if header_end < 0:
                self._json(400, {"error": "invalid multipart upload"})
                return
            file_headers = body[part_start:header_end].decode("utf-8", "replace")
            filename_match = re.search(r'filename="([^"]*)"', file_headers)
            filename = Path(filename_match.group(1)).name if filename_match else "upload.dwg"
            if Path(filename).suffix.lower() not in {".dwg", ".dxf"}:
                self._json(400, {"error": "only .dwg and .dxf files are supported"})
                return
            data_start = header_end + 4
            data_end = body.find(b"\r\n--" + boundary, data_start)
            if data_end < 0:
                self._json(400, {"error": "invalid multipart upload"})
                return

            try:
                previous_models = viewer_models(OUT / "viewer.html")
                suffix = Path(filename).suffix.lower()
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as uploaded:
                    uploaded.write(body[data_start:data_end])
                    uploaded_path = Path(uploaded.name)
                sys.path.insert(0, str(HERE))
                from rebar3d.cli import main as rebuild_from_drawings

                rebuild_from_drawings([str(uploaded_path), "-o", str(OUT)])
                generated_models = viewer_models(OUT / "viewer.html")
                for model in generated_models:
                    if model["name"] == uploaded_path.stem:
                        model["name"] = Path(filename).stem
                merge_viewer_models(OUT / "viewer.html", previous_models + generated_models)
                self._json(200, {"name": filename})
            except Exception as exc:
                self._json(500, {"error": str(exc) or exc.__class__.__name__})
            finally:
                if "uploaded_path" in locals():
                    uploaded_path.unlink(missing_ok=True)

        def log_message(self, fmt, *a):  # quieter log: one line per page load
            msg = fmt % a if a else fmt
            if ".html" in msg:
                print(f"  {msg}")

    with socketserver.TCPServer(("127.0.0.1", port), Handler) as httpd:
        print(f"rebar3d viewer: {url}   (Ctrl-C to stop)")
        if not args.no_browser:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")


if __name__ == "__main__":
    main()
