"""Runtime source switching: validating local dirs, cloning/pulling git repos,
and the ``sources.json`` recents list (with last-viewed-file memory).

``set_content_dir`` is the only sanctioned way to swap the served directory — it
validates + resolves, then assigns ``state.CONTENT_DIR`` (read elsewhere as
``state.CONTENT_DIR`` so the live swap is visible across modules).
"""
import json
import shutil
import subprocess
from pathlib import Path

from markwright import state
from markwright.config import (
    CACHE_DIR,
    RECENTS_LIMIT,
    REPOS_DIR,
    SAFE_NAME_RE,
    SOURCES_FILE,
    URL_PREFIXES,
)


def set_content_dir(directory):
    selected = Path(directory).expanduser().resolve()
    if not selected.is_dir():
        raise ValueError(f"Directory not found: {selected}")
    state.CONTENT_DIR = selected
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
        state.CONTENT_DIR.resolve().relative_to(REPOS_DIR.resolve())
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


def load_recents():
    if not SOURCES_FILE.is_file():
        return []
    try:
        data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data.get("recents", []) if isinstance(data, dict) else []


def save_recents(recents):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SOURCES_FILE.write_text(
        json.dumps({"recents": recents}, indent=2),
        encoding="utf-8",
    )


def prune_repo_cache():
    if not REPOS_DIR.is_dir():
        return
    referenced = {r.get("path") for r in load_recents()}
    referenced.add(str(state.CONTENT_DIR))
    for child in REPOS_DIR.iterdir():
        if not child.is_dir():
            continue
        if str(child) in referenced:
            continue
        shutil.rmtree(child, ignore_errors=True)


def record_recent(entry):
    recents = [r for r in load_recents() if r.get("path") != entry["path"]]
    # Preserve a previously-remembered last_file for this path across re-records
    # (e.g. the startup re-record), so resuming a source reopens its last doc.
    if "last_file" not in entry:
        prior = next((r for r in load_recents() if r.get("path") == entry["path"]), None)
        if prior and prior.get("last_file"):
            entry["last_file"] = prior["last_file"]
    recents.insert(0, entry)
    recents = recents[:RECENTS_LIMIT]
    save_recents(recents)
    return recents


def last_file_for_current():
    """The doc last viewed under the active content dir, if remembered."""
    current = str(state.CONTENT_DIR)
    for r in load_recents():
        if r.get("path") == current:
            return r.get("last_file")
    return None


def remember_last_file(rel_path):
    """Persist the doc currently being viewed onto the active source's recent
    entry, so a bare `/` (after a restart or reload) reopens it. Writes only on
    change to avoid rewriting sources.json on every page view."""
    current = str(state.CONTENT_DIR)
    recents = load_recents()
    for r in recents:
        if r.get("path") == current:
            if r.get("last_file") != rel_path:
                r["last_file"] = rel_path
                save_recents(recents)
            return
