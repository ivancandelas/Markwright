"""Static configuration: cache / preset filesystem layout, upload allowlists,
git-URL prefixes, and the directory-scan ignore set.

``CACHE_DIR`` follows ``XDG_CACHE_HOME`` (handy for isolating a smoke-test cache)
and defaults to ``~/.cache/markwright``.
"""
import os
import re
import shutil
from pathlib import Path

# Pre-rename cache dir name (the app used to be "md_viewer"); see
# ``migrate_legacy_cache`` below.
_LEGACY_CACHE_NAME = "md_viewer"

CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")) / "markwright"
REPOS_DIR = CACHE_DIR / "repos"
SOURCES_FILE = CACHE_DIR / "sources.json"
RECENTS_LIMIT = 8
PRESETS_FILE = CACHE_DIR / "pdf_presets.json"
LOGOS_DIR = CACHE_DIR / "pdf_logos"
ALLOWED_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
LOGO_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}
MAX_LOGO_BYTES = 2 * 1024 * 1024  # 2 MB
URL_PREFIXES = ("http://", "https://", "git://", "ssh://", "git@")
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

IGNORED_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache"}
ALLOWED_ASSET_EXTENSIONS = {
    ".apng",
    ".avif",
    ".gif",
    ".jpg",
    ".jpeg",
    ".png",
    ".svg",
    ".webp",
    ".bmp",
    ".ico",
    ".pdf",
}


def migrate_legacy_cache():
    """One-time copy of a pre-rename ``~/.cache/md_viewer`` cache into the new
    ``markwright`` cache dir, so saved PDF presets, logos, and recent sources
    survive the rename. No-op once the new dir exists (or there's nothing to
    migrate). Called once at server startup."""
    legacy = CACHE_DIR.parent / _LEGACY_CACHE_NAME
    if legacy.is_dir() and not CACHE_DIR.exists():
        shutil.copytree(legacy, CACHE_DIR)
