"""Shared fixtures. Importing app.py is side-effect-light: it builds the Flask
object and a few module globals but never calls app.run (guarded by __main__)."""
import sys
from pathlib import Path

# Ensure the repo root (where app.py lives) is importable when pytest is invoked
# from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import app as appmod
from markwright import files, sources, state


@pytest.fixture(autouse=True)
def isolated_sources_store(tmp_path_factory, monkeypatch):
    """Redirect ``sources.json`` into a throwaway cache for every test.

    Autouse and unconditional because writes are no longer opt-in: minting a
    principal seeds a recents bucket, so *any* test that touches the Flask test
    client writes to this file. Without the redirect that would be the user's
    real ``~/.cache/markwright`` state."""
    cache = tmp_path_factory.mktemp("mw-cache")
    monkeypatch.setattr(sources, "CACHE_DIR", cache)
    monkeypatch.setattr(sources, "SOURCES_FILE", cache / "sources.json")
    return cache / "sources.json"


@pytest.fixture
def content_dir(tmp_path):
    """Point the shared CONTENT_DIR at an isolated temp dir and restore it
    afterwards, so path-dependent helpers (safe_path, scan_markdown_files,
    render_markdown, _extract_doc_title) operate against a known tree.

    CONTENT_DIR now lives on the ``markwright.state`` module (swapped live at
    runtime); read/restore it there, not on ``app``."""
    previous = state.CONTENT_DIR
    # The listing/metadata/ignore caches are keyed on the root, so a fresh
    # tmp_path can't inherit another test's entry — but a single test that
    # scans, writes, and scans again would read its own stale listing for
    # SCAN_TTL_SECONDS. Clear on both edges so tests see the filesystem.
    files.invalidate_scan_cache()
    appmod.set_content_dir(tmp_path)
    yield Path(state.CONTENT_DIR)
    files.invalidate_scan_cache()
    state.CONTENT_DIR = previous
