"""Mutable runtime state shared across the markwright package.

CONTENT_DIR is the directory currently being served. It is swapped *live* at
runtime by ``POST /api/source`` (via ``set_content_dir``), so every consumer
must read it as an attribute on this module — ``state.CONTENT_DIR`` — and never
import it by value (``from markwright.state import CONTENT_DIR``), which would
freeze a stale binding that never sees the swap.
"""
from pathlib import Path

CONTENT_DIR = Path.cwd().resolve()
"""Directory whose markdown tree is currently served. Reassign via
``set_content_dir`` (validates + resolves); read as ``state.CONTENT_DIR``."""
