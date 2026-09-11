"""Static configuration: cache / preset filesystem layout, upload allowlists,
git-URL prefixes, and the directory-scan ignore set.

``CACHE_DIR`` follows ``XDG_CACHE_HOME`` (handy for isolating a smoke-test cache)
and defaults to ``~/.cache/markwright``.
"""
import os
import re
import secrets
import shutil
from pathlib import Path

# Pre-rename cache dir name (the app used to be "md_viewer"); see
# ``migrate_legacy_cache`` below.
_LEGACY_CACHE_NAME = "md_viewer"

CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")) / "markwright"
REPOS_DIR = CACHE_DIR / "repos"
SOURCES_FILE = CACHE_DIR / "sources.json"
SECRET_KEY_FILE = CACHE_DIR / "secret_key"
RECENTS_LIMIT = 8
# Recents buckets are kept per principal, and an anonymous principal is minted
# per browser — so the map would grow without bound. Oldest-touched buckets are
# evicted past this cap; the shared list survives eviction, so an evicted client
# is reseeded from it rather than landing on an empty picker.
PRINCIPALS_LIMIT = 50
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
"""Directories the scanner never descends into. This is the built-in baseline;
a source can add its own via ``IGNORE_FILE_NAME`` or ``IGNORE_ENV_VAR`` — see
``markwright.files.ignored_for``."""

IGNORE_FILE_NAME = ".markwrightignore"
"""Optional file at the root of a served directory listing extra directories to
skip, one per line (``#`` comments and blank lines ignored). A bare name skips
every directory so named at any depth; a value containing ``/`` is a
root-relative directory path. Needed because the built-in set can't know about a
tree's own bulk — e.g. a repo root holding dozens of git worktrees, where the
same few hundred docs are found once per worktree."""

IGNORE_ENV_VAR = "MARKWRIGHT_IGNORE"
"""Same syntax as ``IGNORE_FILE_NAME`` but ``os.pathsep``-separated and applied
to every source, for when you can't write into the tree being served."""

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


def load_secret_key():
    """Key that signs the session cookie (which carries the per-session content
    dir). ``MARKWRIGHT_SECRET_KEY`` wins; otherwise a random key is generated
    once and **persisted** to ``CACHE_DIR/secret_key`` at 0600.

    Persisting matters more than it looks. A fresh random key per process would
    invalidate every session on each restart — and debug mode auto-reloads on
    every code edit — silently dropping clients back onto the process-default
    directory, i.e. re-creating the exact bug the session layer exists to fix.

    Never raises: a cache dir that can't be written falls back to an ephemeral
    in-memory key (sessions last until restart) rather than refusing to boot.
    """
    from_env = os.environ.get("MARKWRIGHT_SECRET_KEY")
    if from_env:
        return from_env.encode("utf-8")

    try:
        if SECRET_KEY_FILE.is_file():
            existing = SECRET_KEY_FILE.read_bytes().strip()
            if existing:
                return existing
    except OSError:
        pass

    key = secrets.token_hex(32).encode("ascii")
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # O_EXCL + mode: created 0600 from the start (no window where the key is
        # world-readable) and a concurrent worker that won the race makes this
        # raise rather than clobber its key — we then read theirs back.
        fd = os.open(SECRET_KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(key)
    except FileExistsError:
        try:
            existing = SECRET_KEY_FILE.read_bytes().strip()
            if existing:
                return existing
        except OSError:
            pass
    except OSError:
        pass
    return key


def migrate_legacy_cache():
    """One-time copy of a pre-rename ``~/.cache/md_viewer`` cache into the new
    ``markwright`` cache dir, so saved PDF presets, logos, and recent sources
    survive the rename. No-op once the new dir exists (or there's nothing to
    migrate). Called once at server startup."""
    legacy = CACHE_DIR.parent / _LEGACY_CACHE_NAME
    if legacy.is_dir() and not CACHE_DIR.exists():
        shutil.copytree(legacy, CACHE_DIR)
