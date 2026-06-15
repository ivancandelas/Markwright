"""File discovery and the path-safety guard, all scoped to ``state.CONTENT_DIR``.

``safe_path`` is the path-traversal guard — it must reject anything escaping the
served directory; keep the ``relative_to(CONTENT_DIR)`` check on any new
file-serving route. ``scan_markdown_files`` globs ``*.md`` / ``*.rst`` /
``README*`` and dedupes so extensionless READMEs surface; ``build_tree`` /
``collect_tree_metadata`` shape the flat path list for the sidebar.
"""
import os

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


def _is_wanted(name):
    # Matches the original glob set: ``*.md`` / ``*.rst`` (case-sensitive, as
    # rglob is on Linux) plus any ``README*`` (case-insensitive) so
    # extensionless READMEs surface alongside markdown.
    return name.endswith((".md", ".rst")) or name.lower().startswith("readme")


def scan_markdown_files():
    # Single ``os.walk`` pass with in-place pruning of IGNORED_DIRS: a tree with
    # a large vendored dir (e.g. a git submodule) used to cost three full
    # ``rglob`` sweeps (one per pattern) that visited every file before
    # filtering. Pruning ``dirnames`` stops descent into ``.git``/``node_modules``
    # entirely, and one walk replaces three.
    root = str(state.CONTENT_DIR)
    seen = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        for name in filenames:
            if not _is_wanted(name):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            seen.add(rel.replace(os.sep, "/"))
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
