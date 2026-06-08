"""Shared fixtures. Importing app.py is side-effect-light: it builds the Flask
object and a few module globals but never calls app.run (guarded by __main__)."""
import sys
from pathlib import Path

# Ensure the repo root (where app.py lives) is importable when pytest is invoked
# from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import app as appmod
from markwright import state


@pytest.fixture
def content_dir(tmp_path):
    """Point the shared CONTENT_DIR at an isolated temp dir and restore it
    afterwards, so path-dependent helpers (safe_path, scan_markdown_files,
    render_markdown, _extract_doc_title) operate against a known tree.

    CONTENT_DIR now lives on the ``markwright.state`` module (swapped live at
    runtime); read/restore it there, not on ``app``."""
    previous = state.CONTENT_DIR
    appmod.set_content_dir(tmp_path)
    yield Path(state.CONTENT_DIR)
    state.CONTENT_DIR = previous
