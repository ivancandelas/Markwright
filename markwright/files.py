"""File discovery and the path-safety guard, all scoped to ``state.content_dir()``
— the *calling session's* directory, not the process default.

``safe_path`` is the path-traversal guard — it must reject anything escaping the
served directory; keep the ``relative_to(CONTENT_DIR)`` check on any new
file-serving route. ``scan_markdown_files`` globs ``*.md`` / ``*.rst`` /
``README*`` and dedupes so extensionless READMEs surface; ``build_tree`` /
``collect_tree_metadata`` shape the flat path list for the sidebar.

Both of those walk/stat the whole tree, so both are cached per served dir for
``SCAN_TTL_SECONDS`` and dropped by ``invalidate_scan_cache()``. A single-document
route wanting "is this a doc the sidebar lists?" must use ``is_discoverable``
rather than a ``in scan_markdown_files()`` membership test — see its docstring.
"""
import os
import threading
import time

from flask import abort

from markwright import state
from markwright.config import IGNORE_ENV_VAR, IGNORE_FILE_NAME, IGNORED_DIRS


def safe_path(relative_path):
    if not relative_path:
        abort(404)

    root = state.content_dir()
    target = (root / relative_path).resolve()
    try:
        target.relative_to(root)
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


def _parse_ignore_lines(lines):
    names, paths = set(), set()
    for raw in lines:
        entry = raw.strip().strip("/")
        if not entry or entry.startswith("#"):
            continue
        entry = entry.replace("\\", "/")
        (paths if "/" in entry else names).add(entry)
    return names, paths


def ignored_for(root):
    """``(names, paths)`` of directories not to descend into under ``root``:
    the built-in ``IGNORED_DIRS`` plus whatever ``IGNORE_ENV_VAR`` and the
    source's own ``IGNORE_FILE_NAME`` add. ``names`` match a directory at any
    depth, ``paths`` are root-relative.

    Read once per walk and cached with the listing, so the ignore file is picked
    up within ``SCAN_TTL_SECONDS`` of being edited.
    """
    root = str(root)
    cached = _cache_get(_ignore_cache, root)
    if cached is not None:
        return cached
    names, paths = set(IGNORED_DIRS), set()
    env_names, env_paths = _parse_ignore_lines(
        (os.environ.get(IGNORE_ENV_VAR) or "").split(os.pathsep)
    )
    names |= env_names
    paths |= env_paths
    try:
        with open(os.path.join(root, IGNORE_FILE_NAME), encoding="utf-8") as fh:
            file_names, file_paths = _parse_ignore_lines(fh)
        names |= file_names
        paths |= file_paths
    except (OSError, UnicodeDecodeError):
        pass
    return _cache_put(_ignore_cache, root, (names, paths))


def is_discoverable(relative_path):
    """O(1) equivalent of ``relative_path in scan_markdown_files()``.

    The scan set is exactly *(a)* an existing file under the served dir whose
    name ``_is_wanted`` matches, *(b)* with no parent directory in the source's
    ``ignored_for`` set — both decidable from the path itself plus one stat. Use
    this for the membership guard on any single-document route; a full
    ``os.walk`` there is what made a big tree crawl. ``/api/mtime`` is polled
    once a second, so on a 34k-directory source the guard alone cost seconds
    per poll and the walks overlapped.

    One deliberate divergence: ``os.walk`` doesn't follow directory symlinks, so
    a doc reachable only *through* an in-root symlink isn't listed in the sidebar
    but is accepted here. It still resolves inside the served dir (same check as
    ``safe_path``), so it widens no traversal boundary.
    """
    rel = (relative_path or "").strip().replace("\\", "/")
    if not rel:
        return False
    parts = rel.split("/")
    # Reject empty/dot components so the accepted spelling matches what the
    # scanner emits ("a/b.md", never "./a//b.md").
    if any(p in ("", ".", "..") for p in parts):
        return False
    if not _is_wanted(parts[-1]):
        return False
    root = state.content_dir()
    names, paths = ignored_for(root)
    if any(p in names for p in parts[:-1]):
        return False
    if any("/".join(parts[:i]) in paths for i in range(1, len(parts))):
        return False
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return False
    return target.is_file()


SCAN_TTL_SECONDS = 5.0
"""How long a directory listing is reused. The walk is the single most
expensive thing a request can do on a large source, and the sidebar tolerates a
few seconds of staleness — file create/rename/delete *through the app* calls
``invalidate_scan_cache()``, so only changes made outside it wait for the TTL."""

_SCAN_CACHE_LIMIT = 8  # one entry per source; sessions may hold different ones
_scan_lock = threading.Lock()
_scan_cache = {}  # root str -> (expires_at monotonic, files list)
_meta_cache = {}  # root str -> (expires_at monotonic, mtime dict)
_ignore_cache = {}  # root str -> (expires_at monotonic, (names, paths))


def invalidate_scan_cache(root=None):
    """Drop the cached listing for ``root`` (default: every root). Call after
    creating, renaming or deleting a document so the sidebar updates at once."""
    with _scan_lock:
        for cache in (_scan_cache, _meta_cache, _ignore_cache):
            if root is None:
                cache.clear()
            else:
                cache.pop(str(root), None)


def _cache_get(cache, root):
    with _scan_lock:
        entry = cache.get(root)
        if entry is not None and entry[0] > time.monotonic():
            return entry[1]
    return None


def _cache_put(cache, root, value):
    with _scan_lock:
        if len(cache) >= _SCAN_CACHE_LIMIT and root not in cache:
            cache.pop(min(cache, key=lambda k: cache[k][0]), None)
        cache[root] = (time.monotonic() + SCAN_TTL_SECONDS, value)
    return value


def _walk_markdown_files(root):
    # Single ``os.walk`` pass with in-place pruning of IGNORED_DIRS: a tree with
    # a large vendored dir (e.g. a git submodule) used to cost three full
    # ``rglob`` sweeps (one per pattern) that visited every file before
    # filtering. Pruning ``dirnames`` stops descent into ``.git``/``node_modules``
    # entirely, and one walk replaces three.
    names, paths = ignored_for(root)
    seen = set()
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        prefix = "" if rel_dir == os.curdir else rel_dir.replace(os.sep, "/") + "/"
        dirnames[:] = [
            d for d in dirnames if d not in names and (prefix + d) not in paths
        ]
        for name in filenames:
            if not _is_wanted(name):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            seen.add(rel.replace(os.sep, "/"))
    return sorted(seen, key=str.lower)


def scan_markdown_files():
    """Sorted relative paths of every document under the served dir, cached for
    ``SCAN_TTL_SECONDS``. Callers get a private copy, so the cached list can't
    be mutated out from under the next one."""
    root = str(state.content_dir())
    cached = _cache_get(_scan_cache, root)
    if cached is None:
        cached = _cache_put(_scan_cache, root, _walk_markdown_files(root))
    return list(cached)


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
        full = state.content_dir() / rel
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
    """Cached for ``SCAN_TTL_SECONDS`` like ``scan_markdown_files``: it stats
    every discovered file, so on a large source it is the second-biggest cost of
    a page load after the walk itself."""
    root = str(state.content_dir())
    cached = _cache_get(_meta_cache, root)
    if cached is None:
        cached = _cache_put(_meta_cache, root, _walk_tree_metadata(files))
    return cached


def _walk_tree_metadata(files):
    # Per-entry mtime keyed by relative path. Directories inherit the most
    # recent mtime among their descendants so "newest first" surfaces folders
    # whose contents changed recently. Prefers st_birthtime where available
    # (macOS/BSD) and falls back to st_mtime on Linux.
    meta = {}
    for rel in files:
        full = state.content_dir() / rel
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
