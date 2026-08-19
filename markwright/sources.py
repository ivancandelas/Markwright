"""Runtime source switching: validating local dirs, cloning/pulling git repos,
and the ``sources.json`` recents list (with last-viewed-file memory).

``set_content_dir`` is the only sanctioned way to swap the served directory — it
validates + resolves, then hands off to ``state.set_active_dir``, which scopes
the swap to the calling session inside a request and to the process default
outside one. Read the result back as ``state.content_dir()``.

``sources.json`` holds two things (see ``_load_store``): a per-principal recents
bucket, and one **shared** list that is the boot-time / new-client fallback.
Public accessors (``load_recents``/``save_recents``/``record_recent``/
``remember_last_file``) pick the right one from the request context, so callers
never think about it.
"""
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from markwright import state
from markwright.config import (
    CACHE_DIR,
    PRINCIPALS_LIMIT,
    RECENTS_LIMIT,
    REPOS_DIR,
    SAFE_NAME_RE,
    SOURCES_FILE,
    URL_PREFIXES,
)

# sources.json is read-modify-written from request threads (the server runs
# threaded=True) as well as at startup. Reentrant because the public helpers
# compose — record_recent loads and saves inside one critical section.
_STORE_LOCK = threading.RLock()


def set_content_dir(directory):
    """Validate + resolve ``directory`` and make it the active source. In a
    request context only the calling session moves; at startup (no session) the
    process default moves. Raises ValueError — not SystemExit — so the route
    handler can turn a bad path into a clean 400."""
    selected = Path(directory).expanduser().resolve()
    if not selected.is_dir():
        raise ValueError(f"Directory not found: {selected}")
    state.set_active_dir(selected)
    return selected


def resolve_startup_dir(explicit):
    """Directory to serve at launch. An explicit CLI argument always wins.
    Otherwise resume the most recently used source — restarting the server keeps
    you where you were instead of snapping back to the cwd (which 404s the
    `?file=` of whatever you had open). Falls back to the first recent that still
    exists on disk, then to the current directory."""
    if explicit is not None:
        return explicit
    for entry in load_recents():
        path = entry.get("path")
        if path and Path(path).expanduser().is_dir():
            return path
    return "."


def is_local_source():
    """True when the active content dir is a real local folder rather than a git
    clone living under the cache's ``repos/`` dir. Edit mode (writing changes back
    to disk) is only offered for local sources — a cloned repo would just be
    overwritten on the next pull, so editing it is meaningless."""
    try:
        state.content_dir().resolve().relative_to(REPOS_DIR.resolve())
        return False
    except (ValueError, OSError):
        return True


def is_git_url(value):
    if value.startswith(URL_PREFIXES):
        return True
    return value.endswith(".git")


def repo_dir_for_url(url):
    name = url.rstrip("/").rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    safe = SAFE_NAME_RE.sub("_", name).strip("_") or "repo"
    return REPOS_DIR / safe


def fetch_repo(url):
    target = repo_dir_for_url(url)
    target.parent.mkdir(parents=True, exist_ok=True)
    if (target / ".git").is_dir():
        proc = subprocess.run(
            ["git", "-C", str(target), "pull", "--ff-only"],
            capture_output=True, text=True, timeout=180,
        )
    else:
        proc = subprocess.run(
            ["git", "clone", "--depth", "1", url, str(target)],
            capture_output=True, text=True, timeout=300,
        )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip() or "git command failed")
    return target


def _load_store():
    """The whole ``sources.json`` document, normalized to::

        {"recents": [...],                       # shared / fallback list
         "principals": {"<id>": {"recents": [...], "updated": <epoch>}}}

    ``recents`` predates per-principal buckets, which is why it stays the
    top-level key: an existing file already parses as a store with no
    ``principals``, so there is no migration step. It keeps two jobs that a
    per-principal bucket structurally cannot do — ``resolve_startup_dir`` reads
    it at boot, when no request and therefore no principal exists, and a
    first-time client is seeded from it so a new browser opens on a populated
    picker instead of an empty one.
    """
    if not SOURCES_FILE.is_file():
        return {"recents": [], "principals": {}}
    try:
        data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"recents": [], "principals": {}}
    if not isinstance(data, dict):
        return {"recents": [], "principals": {}}
    recents = data.get("recents")
    principals = data.get("principals")
    return {
        "recents": recents if isinstance(recents, list) else [],
        "principals": principals if isinstance(principals, dict) else {},
    }


def _save_store(store):
    principals = store.get("principals", {})
    if len(principals) > PRINCIPALS_LIMIT:
        # Evict least-recently-touched buckets. Losing one is not lossy in any
        # way the user sees: that client is simply reseeded from the shared list.
        keep = sorted(principals.items(), key=lambda kv: kv[1].get("updated", 0), reverse=True)
        store["principals"] = dict(keep[:PRINCIPALS_LIMIT])
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Write-then-rename: concurrent readers see either the old document or the
    # new one, never a half-written file. Same directory, so the rename is atomic.
    tmp = SOURCES_FILE.with_name(SOURCES_FILE.name + f".tmp{os.getpid()}")
    try:
        tmp.write_text(json.dumps(store, indent=2), encoding="utf-8")
        os.replace(tmp, SOURCES_FILE)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def load_recents():
    """The caller's recents list: their own bucket when they have one, else a
    copy of the shared list (seeding a first-time client). Outside a request
    context — startup — there is no principal, so the shared list is used."""
    with _STORE_LOCK:
        store = _load_store()
        bucket = store["principals"].get(state.principal() or "")
        if isinstance(bucket, dict) and isinstance(bucket.get("recents"), list):
            return bucket["recents"]
        return [dict(r) for r in store["recents"]]


def save_recents(recents):
    """Persist ``recents`` as the caller's list.

    The shared list is updated too, mirroring the most recent writer. That is
    exactly what its two consumers want: ``resolve_startup_dir`` resumes wherever
    activity last happened, and a new client is seeded with a live history rather
    than a blank picker. Once real accounts exist, seeding across principals is
    the part to revisit — an authenticated user should not inherit another's
    history.
    """
    with _STORE_LOCK:
        store = _load_store()
        principal = state.principal()
        if principal:
            store["principals"][principal] = {"recents": recents, "updated": time.time()}
        store["recents"] = recents
        _save_store(store)


def seed_recents_for_new_principal():
    """Copy the shared list into a freshly-minted principal's own bucket.

    This has to happen at mint time, not lazily on first divergence. Seeding
    lazily looks equivalent but isn't: a client that only ever *reads* — never
    switching sources, never opening a different doc than the one already
    recorded — writes nothing, so it keeps no bucket and keeps resolving through
    the shared list. Another client then reorders that list or moves its
    ``last_file``, and the passive client's picker and resume point follow along:
    a quieter re-run of the very bug the per-session work removed. Materializing
    at mint guarantees every identity owns its state from its first request.

    Deliberately does not go through ``save_recents``: the point is a private
    copy, so the shared list must not be touched.
    """
    with _STORE_LOCK:
        principal = state.principal()
        if not principal:
            return
        store = _load_store()
        if principal in store["principals"]:
            return
        store["principals"][principal] = {
            "recents": [dict(r) for r in store["recents"]],
            "updated": time.time(),
        }
        _save_store(store)


def all_referenced_paths():
    """Every source path any principal still remembers, plus the shared list.

    The destructive paths (repo-cache pruning, deleting a clone on removal) key
    off this rather than off one caller's recents — otherwise one client removing
    a git source would ``rmtree`` a clone another client is actively browsing.
    """
    with _STORE_LOCK:
        store = _load_store()
        paths = {r.get("path") for r in store["recents"]}
        for bucket in store["principals"].values():
            if isinstance(bucket, dict):
                paths.update(r.get("path") for r in bucket.get("recents", []))
    paths.discard(None)
    return paths


def prune_repo_cache():
    if not REPOS_DIR.is_dir():
        return
    referenced = all_referenced_paths()
    referenced.add(str(state.content_dir()))
    for child in REPOS_DIR.iterdir():
        if not child.is_dir():
            continue
        if str(child) in referenced:
            continue
        shutil.rmtree(child, ignore_errors=True)


def record_recent(entry):
    # The whole read-modify-write is one critical section: two clients switching
    # sources at once would otherwise each write a list built from the state
    # before the other's insert, losing one of them.
    with _STORE_LOCK:
        current = load_recents()
        recents = [r for r in current if r.get("path") != entry["path"]]
        # Preserve a previously-remembered last_file for this path across re-records
        # (e.g. the startup re-record), so resuming a source reopens its last doc.
        if "last_file" not in entry:
            prior = next((r for r in current if r.get("path") == entry["path"]), None)
            if prior and prior.get("last_file"):
                entry["last_file"] = prior["last_file"]
        recents.insert(0, entry)
        recents = recents[:RECENTS_LIMIT]
        save_recents(recents)
        return recents


def last_file_for_current():
    """The doc last viewed under the active content dir, if remembered."""
    current = str(state.content_dir())
    for r in load_recents():
        if r.get("path") == current:
            return r.get("last_file")
    return None


def remember_last_file(rel_path):
    """Persist the doc currently being viewed onto the active source's recent
    entry, so a bare `/` (after a restart or reload) reopens it. Writes only on
    change to avoid rewriting sources.json on every page view — which also keeps
    a drive-by page view from materializing a bucket for a fresh principal."""
    current = str(state.content_dir())
    with _STORE_LOCK:
        recents = load_recents()
        for r in recents:
            if r.get("path") == current:
                if r.get("last_file") != rel_path:
                    r["last_file"] = rel_path
                    save_recents(recents)
                return
