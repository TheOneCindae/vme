"""Shared locations for rebar source drawings and generated analysis data."""
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
REBAR_DATA = REPO_ROOT / "rebar_data"
DRAWINGS = REBAR_DATA / "drawings"
SAMPLE_DRAWINGS = REBAR_DATA / "samples" / "drawings"
ANALYSIS = REBAR_DATA / "analysis"
