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
    # Matches ``*.md`` / ``*.rst`` case-insensitively (so ``.MD``, ``.RST``,
    # ``.Md``, ``.RsT`` all surface — the route dispatch already lowercases the
    # suffix) plus any ``README*`` (case-insensitive) so extensionless READMEs
    # surface alongside markdown.
    lowered = name.lower()
    return lowered.endswith((".md", ".rst")) or lowered.startswith("readme")


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


def _snippet(line, idx, qlen, radius):
    # A short window around the match for the results list. Leading/trailing
    # ellipses mark a truncated line; ``match_start``/``match_len`` are offsets
    # *into the returned text* so the client can wrap exactly the hit in <mark>.
    line = line.replace("\t", " ")
    start = max(0, idx - radius)
    end = min(len(line), idx + qlen + radius)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(line) else ""
    return {
        "line": None,  # filled by caller
        "text": prefix + line[start:end] + suffix,
        "match_start": len(prefix) + (idx - start),
        "match_len": qlen,
    }


def search_files(query, max_files=60, max_matches_per_file=5, snippet_radius=48):
    """Case-insensitive full-text search across the current source's markdown/RST.

    Scans the same file set as ``scan_markdown_files`` (so it honours the active
    ``CONTENT_DIR`` and ``IGNORED_DIRS``), reads each as UTF-8 (ignoring decode
    errors), and returns per-file match groups sorted by hit count (desc):
    ``[{"path", "count", "matches": [{"text", "match_start", "match_len", "line"}]}]``.
    Only the first ``max_matches_per_file`` snippets are returned per file, but
    ``count`` reflects every matching line.
    """
    needle = (query or "").strip().lower()
    if len(needle) < 2:
        return []
    qlen = len(needle)
    results = []
    for rel in scan_markdown_files():
        full = state.CONTENT_DIR / rel
        try:
            text = full.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        matches = []
        count = 0
        for lineno, line in enumerate(text.splitlines(), 1):
            idx = line.lower().find(needle)
            if idx == -1:
                continue
            count += 1
            if len(matches) < max_matches_per_file:
                snip = _snippet(line, idx, qlen, snippet_radius)
                snip["line"] = lineno
                matches.append(snip)
        if count:
            results.append({"path": rel, "count": count, "matches": matches})
    results.sort(key=lambda r: (-r["count"], r["path"].lower()))
    return results[:max_files]


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
