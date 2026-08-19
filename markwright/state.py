"""Runtime state for the directory currently being served.

There are two layers, and the distinction is the whole point of this module:

* ``CONTENT_DIR`` — the **process default**. The directory chosen at startup
  (``resolve_startup_dir``); what a brand-new client with no session cookie is
  served. Reassigned only outside a request (startup, tests).
* the **per-session override** — the directory *one browser* switched to via
  ``POST /api/source``. It lives in the signed Flask session cookie and is
  resolved (once, memoized on ``flask.g``) per request.

Read the active directory as ``state.content_dir()``. Never read
``state.CONTENT_DIR`` directly from a request path — that skips the session
override and serves the process default to everyone, which is exactly the
multi-client bug this layering fixes (browser B switching source used to yank
browser A's tree out from under it on the next reload). And never
``from markwright.state import CONTENT_DIR``: that freezes a stale binding which
never sees a swap at all.

``principal()`` is the identity hook. Today it is an anonymous per-session uuid
with no meaning beyond "this browser"; when login lands it becomes the user id,
and everything keyed on it (the active source now, the recents list next) starts
being per-user without changing shape.
"""
import uuid
from pathlib import Path

from flask import g, has_request_context, session

CONTENT_DIR = Path.cwd().resolve()
"""Process-wide default directory. Read via ``content_dir()``, which layers the
caller's session override on top; assign only via ``set_active_dir`` outside a
request context."""

SESSION_DIR_KEY = "content_dir"
SESSION_PRINCIPAL_KEY = "sid"
_G_CACHE_KEY = "_mw_content_dir"


def principal():
    """Stable identifier for whoever is making this request. Anonymous (a
    per-session uuid) until there are real accounts; returns ``None`` outside a
    request context. Key per-client state on this, not on the session cookie
    itself, so swapping in authenticated ids later is a one-line change."""
    if not has_request_context():
        return None
    return session.get(SESSION_PRINCIPAL_KEY)


def ensure_principal():
    """Mint the anonymous principal on first contact. Called from a
    ``before_request`` hook so every client has an identity before any handler
    needs one. Only touches the session when the id is missing, so the response
    doesn't carry a fresh Set-Cookie on every request.

    Returns ``True`` only on the request that *minted* a new identity. Callers
    use that edge to initialize per-principal state exactly once — see
    ``sources.seed_recents_for_new_principal``, which has to run at mint time
    rather than lazily.
    """
    if not has_request_context():
        return False
    if session.get(SESSION_PRINCIPAL_KEY):
        return False
    session[SESSION_PRINCIPAL_KEY] = uuid.uuid4().hex
    # Survive a browser restart: the app's whole premise is resuming where you
    # left off, and a session cookie that dies with the window would silently
    # drop the client back onto the process default.
    session.permanent = True
    return True


def content_dir():
    """The directory this request should be served from: the caller's session
    override when it has one, else the process default."""
    if not has_request_context():
        return CONTENT_DIR
    cached = g.get(_G_CACHE_KEY)
    if cached is not None:
        return cached
    resolved = _resolve_session_dir()
    setattr(g, _G_CACHE_KEY, resolved)
    return resolved


def _resolve_session_dir():
    raw = session.get(SESSION_DIR_KEY)
    if not raw:
        return CONTENT_DIR
    candidate = Path(raw)
    # The override is a path recorded at switch time; the directory can be
    # deleted, renamed, or unmounted afterwards. Falling back to the process
    # default beats serving a dir that no longer exists (every scan would come
    # back empty with no hint why), and dropping the key stops re-statting it.
    try:
        if candidate.is_dir():
            return candidate
    except OSError:
        pass
    session.pop(SESSION_DIR_KEY, None)
    return CONTENT_DIR


def set_active_dir(resolved):
    """Point the caller at ``resolved`` (an already-validated absolute Path).

    Inside a request this swaps **only that session's** directory. Outside one
    (startup, tests) there is no session to write to, so it moves the process
    default — which is what makes the CLI argument and the test fixtures work
    unchanged.
    """
    global CONTENT_DIR
    if has_request_context():
        session[SESSION_DIR_KEY] = str(resolved)
        setattr(g, _G_CACHE_KEY, resolved)
    else:
        CONTENT_DIR = resolved
    return resolved
