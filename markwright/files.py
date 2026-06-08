"""File discovery and the path-safety guard, all scoped to ``state.CONTENT_DIR``.

``safe_path`` is the path-traversal guard — it must reject anything escaping the
served directory; keep the ``relative_to(CONTENT_DIR)`` check on any new
file-serving route. ``scan_markdown_files`` globs ``*.md`` / ``*.rst`` /
``README*`` and dedupes so extensionless READMEs surface; ``build_tree`` /
``collect_tree_metadata`` shape the flat path list for the sidebar.
"""
from flask import abort

from markwright import state
from markwright.config import IGNORED_DIRS


def safe_path(relative_path):
    if not relative_path:
        abort(404)

    target = (state.CONTENT_DIR / relative_path).resolve()
    try:
        target.relative_to(state.CONTENT_DIR)
    except ValueError:
        abort(404)

    return target


def scan_markdown_files():
    seen = set()
    # Glob patterns: every .md, plus README* (case-insensitive via character classes)
    # so extensionless README files surface alongside markdown.
    for pattern in ("*.md", "*.rst", "[Rr][Ee][Aa][Dd][Mm][Ee]*"):
        for path in state.CONTENT_DIR.rglob(pattern):
            if not path.is_file():
                continue
            if any(part in IGNORED_DIRS for part in path.relative_to(state.CONTENT_DIR).parts):
                continue
            seen.add(path.relative_to(state.CONTENT_DIR).as_posix())
    return sorted(seen, key=str.lower)


def build_tree(files):
    root = {}
    for file_path in files:
        parts = file_path.split("/")
        branch = root
        for directory in parts[:-1]:
            branch = branch.setdefault(directory, {})
        branch[parts[-1]] = file_path
    return root


def collect_tree_metadata(files):
    # Per-entry mtime keyed by relative path. Directories inherit the most
    # recent mtime among their descendants so "newest first" surfaces folders
    # whose contents changed recently. Prefers st_birthtime where available
    # (macOS/BSD) and falls back to st_mtime on Linux.
    meta = {}
    for rel in files:
        full = state.CONTENT_DIR / rel
        try:
            st = full.stat()
            mtime = getattr(st, "st_birthtime", None) or st.st_mtime
        except OSError:
            mtime = 0.0
        meta[rel] = mtime
        parts = rel.split("/")
        for i in range(1, len(parts)):
            dir_rel = "/".join(parts[:i])
            if mtime > meta.get(dir_rel, 0.0):
                meta[dir_rel] = mtime
    return meta
