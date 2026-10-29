"""Tests for the pipeline code in ingest/ (run: python -m pytest -q tests). Makes its modules importable."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "ingest"))
