import argparse
import copy
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, send_file, url_for
from flask_babel import Babel, get_locale, get_translations, gettext as _

from markwright import state
# Helpers that moved into the markwright package during the modular split are
# re-imported here so app.py's routes (and the test suite's appmod.* surface)
# reference them unqualified. is_local_reference/resolve_reference/sanitize_html
# aren't used in this module's body — they're re-exported for the test oracle.
from markwright.files import (
    build_tree,
    collect_tree_metadata,
    safe_path,
    scan_markdown_files,
)
from markwright.frontmatter import extract_frontmatter
from markwright.links import is_local_reference, resolve_reference
from markwright.render import (
    render_markdown,
    render_markdown_source,
    render_rst,
    render_rst_source,
    sanitize_html,
)
from markwright.config import (
    ALLOWED_ASSET_EXTENSIONS,
    ALLOWED_LOGO_EXTENSIONS,
    LOGOS_DIR,
    MAX_LOGO_BYTES,
    REPOS_DIR,
    migrate_legacy_cache,
)


app = Flask(__name__)

# --- i18n (Flask-Babel) ----------------------------------------------------
# English is the source language (every msgid is the English string); Spanish is
# the only translated catalog so far. Add a locale by dropping a compiled
# translations/<code>/LC_MESSAGES/messages.mo and listing it in SUPPORTED_LOCALES.
# See the "Internationalization (i18n)" section of CLAUDE.md for the workflow.
SUPPORTED_LOCALES = ["en", "es"]
app.config["BABEL_DEFAULT_LOCALE"] = "en"


def select_locale():
    """Active UI locale: a `lang` cookie (set client-side by the language
    switcher) wins; otherwise the browser's Accept-Language, falling back to
    English. Only codes in SUPPORTED_LOCALES are honored."""
    forced = request.cookies.get("lang")
    if forced in SUPPORTED_LOCALES:
        return forced
    return request.accept_languages.best_match(SUPPORTED_LOCALES) or "en"


babel = Babel(app, locale_selector=select_locale)


def _js_catalog():
    """The active locale's msgid→msgstr map, for injection into the page so
    client JS can translate strings the same way the server/Jinja do. Drops the
    empty header entry and any plural/context tuples (JS uses simple keys)."""
    catalog = get_translations()._catalog
    return {k: v for k, v in catalog.items() if isinstance(k, str) and k and v}


@app.context_processor
def inject_i18n():
    return {"js_i18n": _js_catalog(), "current_locale": str(get_locale() or "en")}


def _env_bool(name, default=False):
    """Parse a boolean env var (1/true/yes/on, case-insensitive). Missing → default."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _asset_version(filename):
    """Cache-busting token for a static file: its mtime as an int string. Lets the
    template append `?v=<token>` so a CSS/JS edit invalidates the browser cache
    automatically (no more Ctrl+Shift+R after every change). 0 if the file is gone."""
    try:
        return str(int((Path(app.static_folder) / filename).stat().st_mtime))
    except OSError:
        return "0"


@app.context_processor
def inject_asset_helper():
    def asset_url(filename):
        return f"{url_for('static', filename=filename)}?v={_asset_version(filename)}"
    return {"asset_url": asset_url}


@app.route("/favicon.ico")
def favicon():
    # Serve the SVG icon for the browser's implicit /favicon.ico request, so it
    # no longer 404s on every page load. Modern browsers also honor the explicit
    # <link rel="icon"> in the template.
    return send_file(Path(app.static_folder) / "favicon.svg", mimetype="image/svg+xml")


# Live-reload polling hits /api/mtime once per second; drop those lines from
# werkzeug's access log so real requests stay visible.
logging.getLogger("werkzeug").addFilter(
    lambda r: "/api/mtime" not in r.getMessage()
)


def parse_args():
    parser = argparse.ArgumentParser(description="Run Markwright, a local Markdown viewer.")
    parser.add_argument(
        "directory",
        nargs="?",
        default=None,
        help="Directory to scan for markdown files. If omitted, resumes the last "
             "source you were viewing (falling back to the current directory).",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind. Defaults to 127.0.0.1.")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind. Defaults to 5000.")
    return parser.parse_args()


# Source-switching and preset-storage helpers moved into the markwright
# package; re-imported so the route handlers below (and appmod.* in tests)
# keep referencing them unqualified.
from markwright.sources import (
    fetch_repo,
    is_git_url,
    is_local_source,
    last_file_for_current,
    load_recents,
    prune_repo_cache,
    record_recent,
    remember_last_file,
    resolve_startup_dir,
    save_recents,
    set_content_dir,
)
from markwright.presets import (
    delete_cover_files,
    delete_logo_files,
    find_preset,
    load_presets,
    save_presets,
)


@app.route("/")
def index():
    files = scan_markdown_files()
    requested = request.args.get("file")
    # A stale `?file=` (e.g. reloading a URL after the source dir changed, or a
    # deleted doc) used to hard-404. Drop it and land on the resumed doc instead.
    if requested is not None and requested not in files:
        return redirect(url_for("index"))

    selected = requested
    if not selected:
        remembered = last_file_for_current()
        selected = remembered if remembered in files else (files[0] if files else None)
    content = ""
    toc = ""
    doc_title = ""

    if selected:
        path = safe_path(selected)
        if path.suffix.lower() == ".rst":
            content, toc = render_rst(path)
        else:
            content, toc = render_markdown(path)
        # Human title (frontmatter title: → first heading → filename stem) for the
        # page <title>. This is what Chrome embeds as the PDF's document title, so
        # a clean professional value beats the on-disk filename + app name.
        doc_title = _extract_doc_title(path, selected)
        remember_last_file(selected)

    return render_template(
        "index.html",
        files=files,
        tree=build_tree(files),
        tree_meta=collect_tree_metadata(files),
        selected=selected,
        doc_title=doc_title,
        content=content,
        toc=toc,
        # Only the PDF export navigates here with pdf_toc=1, to prepend a
        # clickable "Contents" page; normal viewing never sets it.
        pdf_toc=request.args.get("pdf_toc") == "1",
        content_dir=state.CONTENT_DIR,
        recents=load_recents(),
        # Edit mode writes changes back to disk; only meaningful for a local
        # source (a git clone would be clobbered on the next pull).
        editable=is_local_source(),
    )


@app.route("/api/source", methods=["POST"])
def api_set_source():
    payload = request.get_json(silent=True) or {}
    raw_source = (payload.get("source") or "").strip()
    if not raw_source:
        return jsonify({"error": _("source is required")}), 400

    try:
        if is_git_url(raw_source):
            target = fetch_repo(raw_source)
            entry = {
                "label": target.name,
                "path": str(target),
                "kind": "git",
                "url": raw_source,
            }
        else:
            target = set_content_dir(raw_source)
            entry = {
                "label": target.name or str(target),
                "path": str(target),
                "kind": "local",
            }
    except subprocess.TimeoutExpired:
        return jsonify({"error": _("git command timed out")}), 504
    except FileNotFoundError:
        return jsonify({"error": _("git is not installed or not on PATH")}), 500
    except (ValueError, RuntimeError) as exc:
        return jsonify({"error": str(exc)}), 400

    if entry["kind"] == "git":
        set_content_dir(target)

    recents = record_recent(entry)
    return jsonify({"content_dir": str(target), "recents": recents})


@app.route("/api/sources")
def api_sources():
    return jsonify({"content_dir": str(state.CONTENT_DIR), "recents": load_recents()})


@app.route("/api/source/remove", methods=["POST"])
def api_remove_source():
    payload = request.get_json(silent=True) or {}
    target = (payload.get("path") or "").strip()
    if not target:
        return jsonify({"error": _("path is required")}), 400

    try:
        resolved = Path(target).resolve()
    except OSError as exc:
        return jsonify({"error": str(exc)}), 400

    if resolved == state.CONTENT_DIR:
        return jsonify({"error": _("Cannot remove the active source")}), 400

    recents = load_recents()
    entry = next((r for r in recents if r.get("path") == target), None)
    if entry is None:
        return jsonify({"error": _("Not found in recents")}), 404

    new_recents = [r for r in recents if r.get("path") != target]
    save_recents(new_recents)

    if entry.get("kind") == "git":
        try:
            repos_root = REPOS_DIR.resolve()
            resolved.relative_to(repos_root)
        except (ValueError, OSError):
            pass
        else:
            shutil.rmtree(resolved, ignore_errors=True)

    return jsonify({"recents": new_recents})


@app.route("/asset/<path:filename>")
def asset(filename):
    target = safe_path(filename.split("#", 1)[0])
    if not target.is_file() or target.suffix.lower() not in ALLOWED_ASSET_EXTENSIONS:
        abort(404)
    return send_file(target)


@app.route("/raw/<path:filename>")
def raw(filename):
    bare = filename.split("#", 1)[0]
    if bare not in scan_markdown_files():
        abort(404)
    target = safe_path(bare)
    if not target.is_file():
        abort(404)
    return target.read_text(encoding="utf-8"), 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/api/save", methods=["POST"])
def api_save():
    """Overwrite an existing markdown/RST file with edited text. Edit mode is
    text-only and local-only: a git-clone source is rejected (its working tree is
    transient), and the same scan-set + safe_path guards as /raw apply, so only an
    already-discovered file under CONTENT_DIR can be written."""
    if not is_local_source():
        return jsonify({"error": _("This source is read-only")}), 403
    payload = request.get_json(silent=True) or {}
    bare = (payload.get("file") or "").strip().split("#", 1)[0]
    content = payload.get("content")
    if not bare or content is None:
        return jsonify({"error": _("file and content are required")}), 400
    if bare not in scan_markdown_files():
        return jsonify({"error": _("not found")}), 404
    target = safe_path(bare)
    if not target.is_file():
        return jsonify({"error": _("not found")}), 404
    try:
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"ok": True, "mtime": target.stat().st_mtime})


# File suffixes scan_markdown_files() surfaces, so a created/renamed file stays
# discoverable in the sidebar. README* (any/no extension) is allowed separately.
RECOGNIZED_DOC_SUFFIXES = {".md", ".rst"}


def _normalize_new_doc_path(raw, default_suffix=".md"):
    """Normalize a user-supplied relative path for a new or renamed document.
    Strips leading slashes/whitespace, appends ``default_suffix`` when the name
    has no extension, and validates the result is something the scanner will
    surface (.md/.rst, or a README*). Returns the posix-relative path or raises
    ValueError with a translated message. (safe_path still guards traversal.)"""
    rel = (raw or "").strip().replace("\\", "/").lstrip("/")
    if not rel or rel.endswith("/"):
        raise ValueError(_("A file name is required"))
    name = rel.rsplit("/", 1)[-1]
    if "." not in name:
        rel += default_suffix
        name += default_suffix
    suffix = "." + name.rsplit(".", 1)[-1].lower()
    if suffix not in RECOGNIZED_DOC_SUFFIXES and not name.lower().startswith("readme"):
        raise ValueError(_("Use a .md or .rst file extension"))
    return rel


@app.route("/api/file/new", methods=["POST"])
def api_file_new():
    """Create a new markdown/RST file. Local sources only (a git clone is
    read-only). safe_path keeps the target under CONTENT_DIR; an existing path is
    never overwritten."""
    if not is_local_source():
        return jsonify({"error": _("This source is read-only")}), 403
    payload = request.get_json(silent=True) or {}
    try:
        rel = _normalize_new_doc_path(payload.get("path"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    target = safe_path(rel)
    if target.exists():
        return jsonify({"error": _("A file with that name already exists")}), 409
    content = payload.get("content")
    if content is None:
        content = f"# {target.stem}\n"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"ok": True, "file": rel})


@app.route("/api/file/rename", methods=["POST"])
def api_file_rename():
    """Rename/move an existing file (local sources only). The source must already
    be in the scan set; the destination is normalized + traversal-guarded and is
    never allowed to clobber an existing path."""
    if not is_local_source():
        return jsonify({"error": _("This source is read-only")}), 403
    payload = request.get_json(silent=True) or {}
    src_rel = (payload.get("file") or "").strip().split("#", 1)[0]
    if not src_rel or src_rel not in scan_markdown_files():
        return jsonify({"error": _("not found")}), 404
    source = safe_path(src_rel)
    if not source.is_file():
        return jsonify({"error": _("not found")}), 404
    try:
        dest_rel = _normalize_new_doc_path(payload.get("to"), default_suffix=source.suffix or ".md")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    target = safe_path(dest_rel)
    if target == source:
        return jsonify({"ok": True, "file": dest_rel})
    if target.exists():
        return jsonify({"error": _("A file with that name already exists")}), 409
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
    except OSError as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"ok": True, "file": dest_rel})


@app.route("/api/file/delete", methods=["POST"])
def api_file_delete():
    """Delete a file (local sources only). Confirmation is handled client-side;
    the source must already be in the scan set."""
    if not is_local_source():
        return jsonify({"error": _("This source is read-only")}), 403
    payload = request.get_json(silent=True) or {}
    rel = (payload.get("file") or "").strip().split("#", 1)[0]
    if not rel or rel not in scan_markdown_files():
        return jsonify({"error": _("not found")}), 404
    target = safe_path(rel)
    if not target.is_file():
        return jsonify({"error": _("not found")}), 404
    try:
        target.unlink()
    except OSError as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"ok": True})


MAX_ASSET_BYTES = 10 * 1024 * 1024  # uploaded editor images


def _safe_asset_stem(name, default):
    """A filesystem-safe stem from an uploaded image's name (drop dirs, keep
    alnum/-/_, spaces→dashes, cap length). Falls back to ``default`` (pasted
    images have no name)."""
    stem = Path(name or "").stem.replace(" ", "-")
    cleaned = "".join(c for c in stem if c.isalnum() or c in ("-", "_"))
    return (cleaned or default)[:60]


@app.route("/api/upload-asset", methods=["POST"])
def api_upload_asset():
    """Save an image pasted/dropped into the editor next to the current document
    and return the relative name to insert as `![](name)`. Local sources only;
    extension-allowlisted; never overwrites (a numeric suffix disambiguates)."""
    if not is_local_source():
        return jsonify({"error": _("This source is read-only")}), 403
    doc = (request.form.get("file") or "").strip().split("#", 1)[0]
    if not doc or doc not in scan_markdown_files():
        return jsonify({"error": _("not found")}), 404
    upload = request.files.get("image")
    if not upload or not upload.filename:
        return jsonify({"error": _("No image provided")}), 400
    ext = Path(upload.filename).suffix.lower()
    if ext not in ALLOWED_LOGO_EXTENSIONS:  # png/jpg/jpeg/gif/webp/svg
        return jsonify({"error": _("Unsupported image format: %(ext)s", ext=ext or _("(no extension)"))}), 400
    blob = upload.read()
    if len(blob) > MAX_ASSET_BYTES:
        return jsonify({"error": _("The image exceeds the 10 MB limit")}), 400

    doc_dir = safe_path(doc).parent
    stem = _safe_asset_stem(upload.filename, "image")
    candidate = f"{stem}{ext}"
    i = 1
    while (doc_dir / candidate).exists():
        candidate = f"{stem}-{i}{ext}"
        i += 1
    target = doc_dir / candidate
    try:  # belt-and-suspenders: the written path must stay under CONTENT_DIR
        target.resolve().relative_to(state.CONTENT_DIR)
    except ValueError:
        abort(404)
    try:
        target.write_bytes(blob)
    except OSError as exc:
        return jsonify({"error": str(exc)}), 500
    # Saved in the doc's own dir, so the path to insert is just the file name
    # (resolves relative to the document when rendered).
    return jsonify({"ok": True, "path": candidate})


@app.route("/api/render", methods=["POST"])
def api_render():
    """Render unsaved editor text to sanitized HTML for the live preview. The
    file must already be in the scan set (gives the local-link context + format
    dispatch); the body is rendered through the same pipeline + bleach allowlist
    as a normal page view, so arbitrary content stays sanitized."""
    payload = request.get_json(silent=True) or {}
    bare = (payload.get("file") or "").strip().split("#", 1)[0]
    content = payload.get("content")
    if not bare or content is None:
        return jsonify({"error": _("file and content are required")}), 400
    if bare not in scan_markdown_files():
        return jsonify({"error": _("not found")}), 404
    rel = safe_path(bare).relative_to(state.CONTENT_DIR)
    if rel.suffix.lower() == ".rst":
        html, toc = render_rst_source(rel, content)
    else:
        html, toc = render_markdown_source(rel, content)
    return jsonify({"html": html, "toc": toc})


@app.route("/api/mtime")
def api_mtime():
    bare = (request.args.get("file") or "").strip().split("#", 1)[0]
    if not bare:
        return jsonify({"error": _("file is required")}), 400
    if bare not in scan_markdown_files():
        return jsonify({"error": _("not found")}), 404
    target = safe_path(bare)
    try:
        return jsonify({"mtime": target.stat().st_mtime})
    except OSError as exc:
        return jsonify({"error": str(exc)}), 500


# The export pipelines moved into markwright.export; re-imported so the
# /export and /api/pdf-presets routes below (and appmod.* in tests) keep
# referencing them unqualified.
from markwright.export import (
    ALLOWED_PAGE_SIZES,
    DEFAULT_FONT_SCALE,
    DEFAULT_MARGINS,
    DOCX_MIME,
    PDF_FONTS,
    _COVER_IMG_EXTS,
    _COVER_IMG_MAX_IN,
    _DOCX_PAGE_BREAK,
    _apply_datetime_tokens,
    _apply_frontmatter_tokens,
    _build_cover_html,
    _build_cover_markdown,
    _content_disposition,
    _cover_image_path,
    _doc_frontmatter,
    _export_error_message,
    _extract_doc_title,
    _fm_scalar,
    _footer_template,
    _header_template,
    _hf_markdown,
    _inline_mermaid_images,
    _is_retryable_export_error,
    _margin_mm,
    _parse_fallback_values,
    _parse_mm,
    _png_set_dpi,
    _png_width_px,
    _render_docx,
    _render_pdf,
    _resolve_cover_tokens,
    _resolve_export_filename,
    _serialize_preset,
)


@app.route("/export/pdf")
def export_pdf():
    bare = (request.args.get("file") or "").strip().split("#", 1)[0]
    if not bare or bare not in scan_markdown_files():
        abort(404)
    target = safe_path(bare)
    if not target.is_file():
        abort(404)

    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return jsonify({"error": _("Playwright is not installed. Run: uv pip install playwright")}), 503

    preset = find_preset(request.args.get("preset", "").strip()) if request.args.get("preset") else None

    def _band_parts(prefix):
        """Per-column text for a band. Query params win; fall back to the
        preset's stored columns; then to a legacy single field mapped to center
        (old `?header=`/`?footer=` clients and pre-3-column presets)."""
        cols = {}
        for side in ("left", "center", "right"):
            v = request.args.get(f"{prefix}_{side}")
            if v is None and preset is not None:
                v = preset.get(f"{prefix}{side.capitalize()}")
            cols[side] = v or ""
        if not any(cols.values()):
            legacy = request.args.get(prefix)
            if legacy is None and preset is not None:
                legacy = preset.get(prefix)
            cols["center"] = legacy or ""
        return cols

    header_parts = _band_parts("header")
    footer_parts = _band_parts("footer")
    has_header = any(header_parts.values())
    has_footer = any(footer_parts.values())

    page_format = "A4"
    landscape = False
    font_scale = DEFAULT_FONT_SCALE
    font_family = ""
    if preset:
        page_format = preset.get("pageSize") if preset.get("pageSize") in ALLOWED_PAGE_SIZES else "A4"
        landscape = preset.get("orientation") == "landscape"
        font_scale = preset.get("fontScale", DEFAULT_FONT_SCALE)
        font_family = preset.get("fontFamily", "") if preset.get("fontFamily") in PDF_FONTS else ""
        pm = preset.get("margins") or {}
        margin = {side: _margin_mm(pm.get(side), DEFAULT_MARGINS[side]) for side in DEFAULT_MARGINS}
    else:
        margin = {
            "top": "24mm" if has_header else "14mm",
            "bottom": "24mm" if has_footer else "14mm",
            "left": "12mm",
            "right": "12mm",
        }

    filename = Path(bare).name
    literals = {
        "{title}": _extract_doc_title(target, bare),
        "{filename}": filename,
        "{document_name}": filename,
    }
    # One `now` and one frontmatter dict feed the header band, footer band and
    # the cover, so {date}/{time}/{datetime} and {frontmatter-key} read
    # identically across the whole export.
    now = datetime.now()
    frontmatter = _doc_frontmatter(target)
    # Preset fallback defaults: fill placeholders the document doesn't provide
    # (no frontmatter at all, or a missing key). Real frontmatter always wins.
    if preset and preset.get("useFallback"):
        frontmatter = {**_parse_fallback_values(preset.get("fallbackValues", "")), **frontmatter}
    has_logo = bool(preset and preset.get("logo"))
    show_hf = bool(has_header or has_footer or has_logo)
    # A band with no content would still render its separator hairline, and an
    # empty Chrome template falls back to Chrome's default header — so emit a
    # blank suppressor (`<div></div>`) for a band that has nothing to show.
    header_template = (
        _header_template(header_parts, preset, literals, margin["left"], margin["right"], now, frontmatter)
        if (has_header or has_logo) else "<div></div>"
    )
    footer_template = (
        _footer_template(footer_parts, literals, margin["left"], margin["right"], now, frontmatter)
        if has_footer else "<div></div>"
    )

    # Contents page: an explicit query param wins (custom export), else the
    # preset's stored flag, else off.
    toc_param = request.args.get("include_toc")
    if toc_param is not None:
        include_toc = toc_param == "1"
    else:
        include_toc = bool(preset and preset.get("includeToc"))

    index_kwargs = {"file": bare}
    if include_toc:
        index_kwargs["pdf_toc"] = "1"
    doc_url = request.url_root.rstrip("/") + url_for("index", **index_kwargs)

    # Cover page (preset-only — its content lives in the preset). Query param
    # wins, else the preset's stored flag. Built server-side (logo/image as data
    # URIs, tokens resolved from the doc's frontmatter) and prepended into the
    # printed page by _render_pdf; a configured blank page follows it.
    cover_param = request.args.get("include_cover")
    if cover_param is not None:
        include_cover = cover_param == "1"
    else:
        include_cover = bool(preset and preset.get("coverEnabled"))

    prepend_html = ""
    if include_cover and preset:
        cover_html = _build_cover_html(preset, literals, frontmatter, now)
        if cover_html:
            prepend_html = cover_html
            if preset.get("blankAfterCover"):
                prepend_html += '<div class="pdf-blank-page">&nbsp;</div>'

    # Frontmatter panel: hidden in the PDF by default. Query param wins, else the
    # preset's stored flag.
    fm_param = request.args.get("include_frontmatter")
    if fm_param is not None:
        show_frontmatter = fm_param == "1"
    else:
        show_frontmatter = bool(preset and preset.get("includeFrontmatter"))

    pdf_bytes = None
    last_exc = None
    # One retry: headless Chrome navigation can fail transiently (slow CDN, a
    # diagram that times out on the first pass). A hard failure (no Chrome,
    # unsafe port) isn't retryable and bails immediately.
    for attempt in range(2):
        try:
            pdf_bytes = _render_pdf(
                doc_url, header_template, footer_template, show_hf, page_format,
                landscape, margin, font_scale, prepend_html, show_frontmatter,
                font_family,
            )
            break
        except Exception as exc:  # noqa: BLE001 - classified + logged below
            last_exc = exc
            logging.exception("PDF export failed (attempt %d/2)", attempt + 1)
            if attempt == 0 and _is_retryable_export_error(exc):
                continue
            break
    if pdf_bytes is None:
        message, status = _export_error_message(last_exc)
        return jsonify({"error": message}), status

    template = preset.get("fileNameTemplate") if preset else ""
    download_name = _resolve_export_filename(
        template, literals, frontmatter, now, Path(bare).stem, ".pdf"
    )
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": _content_disposition(download_name)},
    )



@app.route("/export/docx")
def export_docx():
    bare = (request.args.get("file") or "").strip().split("#", 1)[0]
    if not bare or bare not in scan_markdown_files():
        abort(404)
    target = safe_path(bare)
    if not target.is_file():
        abort(404)

    if not shutil.which("pandoc"):
        return jsonify({
            "error": _("Pandoc is not installed. Install it (e.g. `apt install pandoc`) "
                       "to export to Word."),
        }), 503

    try:
        source = target.read_text(encoding="utf-8")
    except OSError:
        abort(404)

    preset = find_preset(request.args.get("preset", "").strip()) if request.args.get("preset") else None

    # Tokens for the filename template (and the cover, below) — one `now` and one
    # frontmatter dict shared so they resolve identically.
    now = datetime.now()
    filename = Path(bare).name
    literals = {
        "{title}": _extract_doc_title(target, bare),
        "{filename}": filename,
        "{document_name}": filename,
    }
    frontmatter = _doc_frontmatter(target)
    if preset and preset.get("useFallback"):  # fill placeholders the doc lacks
        frontmatter = {**_parse_fallback_values(preset.get("fallbackValues", "")), **frontmatter}

    title = author = None
    mermaid_images = {}
    if target.suffix.lower() == ".rst":
        input_format, body = "rst", source
    else:
        # Strip frontmatter with the viewer's tested parser (tolerates the
        # doubled `---` opener) so it isn't dumped as a YAML block; surface its
        # title/author as the docx's core properties + title block.
        fm_text, body = extract_frontmatter(source)
        if fm_text:
            try:
                import yaml
                data = yaml.safe_load(fm_text)
            except Exception:  # noqa: BLE001 - missing pkg or bad YAML: skip metadata
                data = None
            if isinstance(data, dict):
                if data.get("title"):
                    title = str(data["title"]).strip()
                if data.get("author"):
                    author = _fm_scalar(data["author"]).strip()
        # Pre-render mermaid diagrams to PNGs so they appear as figures instead
        # of raw code (the viewer renders them client-side; pandoc can't).
        body, mermaid_images = _inline_mermaid_images(body)
        input_format = "gfm"

    # Word TOC field: query param wins (popover checkbox), else the preset flag.
    toc_param = request.args.get("include_toc")
    if toc_param is not None:
        include_toc = toc_param == "1"
    else:
        include_toc = bool(preset and preset.get("includeToc"))

    # Body/heading font from the preset (PDF_FONTS keys *are* the family names);
    # "" / system default leaves pandoc's theme fonts alone.
    font_name = preset.get("fontFamily") if preset and preset.get("fontFamily") in PDF_FONTS else ""

    # Cover page (preset-driven, markdown only): query param wins, else the
    # preset's coverEnabled flag. Built as a leading custom-style fragment from
    # the same fields + token resolver as the PDF cover, then a page break.
    cover_on = False
    cover_image_name = cover_image_bytes = None
    cover_param = request.args.get("include_cover")
    want_cover = (cover_param == "1") if cover_param is not None else bool(preset and preset.get("coverEnabled"))
    if want_cover and preset and target.suffix.lower() != ".rst":
        img_path = _cover_image_path(preset)
        if img_path and img_path.suffix.lower() in _COVER_IMG_EXTS:  # SVG can't embed reliably
            cover_image_name = "cover-image" + img_path.suffix.lower()
            cover_image_bytes = img_path.read_bytes()
        cover_md = _build_cover_markdown(preset, literals, frontmatter, now, cover_image_name)
        if cover_md:
            breaks = _DOCX_PAGE_BREAK * (2 if preset.get("blankAfterCover") else 1)
            body = cover_md + breaks + "\n" + body
            input_format = "gfm+fenced_divs+raw_attribute-implicit_figures"
            title = author = None  # the cover carries the title; avoid a duplicate block
            cover_on = True

    try:
        # pandoc resolves relative images against these dirs and embeds them.
        # Pre-rendered mermaid PNGs + the cover image go in a temp dir that must
        # outlive the call.
        with tempfile.TemporaryDirectory() as img_dir:
            resource_paths = [str(target.parent), str(state.CONTENT_DIR)]
            wrote_any = False
            for name, data in mermaid_images.items():
                (Path(img_dir) / name).write_bytes(data)
                wrote_any = True
            if cover_on and cover_image_bytes:
                data = cover_image_bytes
                if cover_image_name.endswith(".png"):  # cap printed width via DPI
                    w = _png_width_px(data)
                    if w:
                        data = _png_set_dpi(data, w / min(w / 96.0, _COVER_IMG_MAX_IN))
                (Path(img_dir) / cover_image_name).write_bytes(data)
                wrote_any = True
            if wrote_any:
                resource_paths.insert(0, img_dir)
            docx_bytes = _render_docx(
                body, input_format, resource_paths, title, author, include_toc,
                font_name=font_name or None, cover=cover_on,
            )
    except FileNotFoundError:
        return jsonify({
            "error": _("Pandoc is not installed. Install it (e.g. `apt install pandoc`) "
                       "to export to Word."),
        }), 503
    except Exception:  # noqa: BLE001 - logged server-side; clean message to client
        logging.exception("DOCX export failed")
        return jsonify({
            "error": _("Could not generate the DOCX. See the server logs for details."),
        }), 500

    template = preset.get("fileNameTemplate") if preset else ""
    download_name = _resolve_export_filename(
        template, literals, frontmatter, now, Path(bare).stem, ".docx"
    )
    return Response(
        docx_bytes,
        mimetype=DOCX_MIME,
        headers={"Content-Disposition": _content_disposition(download_name)},
    )



@app.route("/api/pdf-presets")
def api_pdf_presets():
    return jsonify({"presets": [_serialize_preset(p) for p in load_presets()]})


@app.route("/api/pdf-presets", methods=["POST"])
def api_pdf_presets_save():
    form = request.form
    name = (form.get("name") or "").strip()
    if not name:
        return jsonify({"error": _("Name is required")}), 400

    presets = load_presets()
    preset_id = (form.get("id") or "").strip()
    preset = next((p for p in presets if p.get("id") == preset_id), None)
    if preset is None:
        preset_id = uuid.uuid4().hex
        preset = {"id": preset_id}
        presets.append(preset)

    preset["name"] = name
    for prefix in ("header", "footer"):
        for side in ("Left", "Center", "Right"):
            preset[f"{prefix}{side}"] = form.get(f"{prefix}{side}", "")
    # Drop any legacy single-field values now that columns are authoritative.
    preset.pop("header", None)
    preset.pop("footer", None)
    position = form.get("logoPosition", "left")
    preset["logoPosition"] = position if position in {"left", "center", "right"} else "left"
    preset["pageSize"] = form.get("pageSize") if form.get("pageSize") in ALLOWED_PAGE_SIZES else "A4"
    preset["orientation"] = "landscape" if form.get("orientation") == "landscape" else "portrait"

    def _clamp(key):
        try:
            n = float(form.get(f"margin_{key}", DEFAULT_MARGINS[key]))
        except (TypeError, ValueError):
            n = DEFAULT_MARGINS[key]
        return max(0.0, min(100.0, n))

    preset["margins"] = {k: _clamp(k) for k in DEFAULT_MARGINS}

    try:
        scale = int(round(float(form.get("fontScale", DEFAULT_FONT_SCALE))))
    except (TypeError, ValueError):
        scale = DEFAULT_FONT_SCALE
    preset["fontScale"] = max(50, min(200, scale))
    font_family = form.get("fontFamily", "")
    preset["fontFamily"] = font_family if font_family in PDF_FONTS else ""
    preset["fileNameTemplate"] = form.get("fileNameTemplate", "")
    preset["includeToc"] = form.get("includeToc") == "1"
    preset["includeFrontmatter"] = form.get("includeFrontmatter") == "1"
    preset["useFallback"] = form.get("useFallback") == "1"
    preset["fallbackValues"] = form.get("fallbackValues", "")

    # Cover page fields (all optional; tokens resolved at export time).
    preset["coverEnabled"] = form.get("coverEnabled") == "1"
    preset["coverTitle"] = form.get("coverTitle", "")
    preset["coverSubtitle"] = form.get("coverSubtitle", "")
    preset["coverMeta"] = form.get("coverMeta", "")
    preset["coverFooter"] = form.get("coverFooter", "")
    cover_source = form.get("coverImageSource", "none")
    preset["coverImageSource"] = cover_source if cover_source in {"none", "logo", "custom"} else "none"
    preset.pop("coverLogo", None)  # superseded by coverImageSource
    preset["blankAfterCover"] = form.get("blankAfterCover") == "1"

    if form.get("removeLogo") == "1":
        delete_logo_files(preset_id)
        preset["logo"] = None
    upload = request.files.get("logo")
    if upload and upload.filename:
        ext = Path(upload.filename).suffix.lower()
        if ext not in ALLOWED_LOGO_EXTENSIONS:
            return jsonify({"error": _("Unsupported logo format: %(ext)s", ext=ext or _("(no extension)"))}), 400
        blob = upload.read()
        if len(blob) > MAX_LOGO_BYTES:
            return jsonify({"error": _("The logo exceeds the 2 MB limit")}), 400
        LOGOS_DIR.mkdir(parents=True, exist_ok=True)
        delete_logo_files(preset_id)  # drop any prior logo with a different ext
        (LOGOS_DIR / f"{preset_id}{ext}").write_bytes(blob)
        preset["logo"] = f"{preset_id}{ext}"

    if form.get("removeCoverImage") == "1":
        delete_cover_files(preset_id)
        preset["coverImage"] = None
    cover_upload = request.files.get("coverImage")
    if cover_upload and cover_upload.filename:
        ext = Path(cover_upload.filename).suffix.lower()
        if ext not in ALLOWED_LOGO_EXTENSIONS:
            return jsonify({"error": _("Unsupported image format: %(ext)s", ext=ext or _("(no extension)"))}), 400
        blob = cover_upload.read()
        if len(blob) > MAX_LOGO_BYTES:
            return jsonify({"error": _("The cover image exceeds the 2 MB limit")}), 400
        LOGOS_DIR.mkdir(parents=True, exist_ok=True)
        delete_cover_files(preset_id)  # drop any prior cover with a different ext
        (LOGOS_DIR / f"{preset_id}-cover{ext}").write_bytes(blob)
        preset["coverImage"] = f"{preset_id}-cover{ext}"

    save_presets(presets)
    return jsonify({"preset": _serialize_preset(preset)})


@app.route("/api/pdf-presets/copy", methods=["POST"])
def api_pdf_presets_copy():
    """Duplicate a preset (new id, name + " (copia)"), cloning its logo and cover
    image files under the new id so the copy is fully independent."""
    data = request.get_json(silent=True) or {}
    source_id = (data.get("id") or "").strip()
    presets = load_presets()
    source = next((p for p in presets if p.get("id") == source_id), None)
    if source is None:
        return jsonify({"error": _("Not found")}), 404

    new_id = uuid.uuid4().hex
    clone = copy.deepcopy(source)
    clone["id"] = new_id
    clone["name"] = f"{source.get('name', 'Preset')} (copia)"

    for key, suffix in (("logo", ""), ("coverImage", "-cover")):
        stored = source.get(key)
        if not stored:
            continue
        src_path = LOGOS_DIR / stored
        if src_path.is_file():
            ext = src_path.suffix.lower()
            LOGOS_DIR.mkdir(parents=True, exist_ok=True)
            new_name = f"{new_id}{suffix}{ext}"
            shutil.copy2(src_path, LOGOS_DIR / new_name)
            clone[key] = new_name

    presets.append(clone)
    save_presets(presets)
    return jsonify({"preset": _serialize_preset(clone)})


@app.route("/api/pdf-presets/delete", methods=["POST"])
def api_pdf_presets_delete():
    data = request.get_json(silent=True) or {}
    preset_id = (data.get("id") or "").strip()
    presets = load_presets()
    if not any(p.get("id") == preset_id for p in presets):
        return jsonify({"error": _("Not found")}), 404
    delete_logo_files(preset_id)
    delete_cover_files(preset_id)
    save_presets([p for p in presets if p.get("id") != preset_id])
    return jsonify({"ok": True})


@app.route("/api/pdf-presets/<preset_id>/logo")
def api_pdf_preset_logo(preset_id):
    preset = find_preset(preset_id)
    if not preset or not preset.get("logo"):
        abort(404)
    path = LOGOS_DIR / preset["logo"]
    if not path.is_file() or path.parent.resolve() != LOGOS_DIR.resolve():
        abort(404)
    return send_file(path)


@app.route("/api/pdf-presets/<preset_id>/cover-image")
def api_pdf_preset_cover_image(preset_id):
    preset = find_preset(preset_id)
    if not preset or not preset.get("coverImage"):
        abort(404)
    path = LOGOS_DIR / preset["coverImage"]
    if not path.is_file() or path.parent.resolve() != LOGOS_DIR.resolve():
        abort(404)
    return send_file(path)


@app.template_filter("basename")
def basename(value):
    return Path(value).name


@app.template_filter("urlquote")
def urlquote(value):
    return quote(value)


if __name__ == "__main__":
    args = parse_args()
    # Bring a pre-rename ~/.cache/md_viewer cache forward before reading recents,
    # so resuming the last source (and saved presets) survives the rename.
    migrate_legacy_cache()
    try:
        set_content_dir(resolve_startup_dir(args.directory))
    except ValueError as exc:
        raise SystemExit(str(exc))
    record_recent({
        "label": state.CONTENT_DIR.name or str(state.CONTENT_DIR),
        "path": str(state.CONTENT_DIR),
        "kind": "local",
    })
    prune_repo_cache()
    print(f"Scanning markdown files in: {state.CONTENT_DIR}")

    # Debug (auto-reload + interactive debugger) defaults on for local dev but is
    # overridable via MARKWRIGHT_DEBUG=0. The Werkzeug debugger allows arbitrary
    # code execution, so it is *force-disabled* whenever binding to a non-loopback
    # interface — you can't accidentally expose it by adding --host 0.0.0.0.
    debug = _env_bool("MARKWRIGHT_DEBUG", default=True)
    is_loopback = args.host in ("127.0.0.1", "localhost", "::1")
    if debug and not is_loopback:
        print(f"⚠ Debug disabled: binding to non-loopback host {args.host} "
              "(the interactive debugger allows remote code execution).")
        debug = False
    # threaded=True is required (not optional): PDF export drives a headless
    # Chrome that fetches this same page back, so the server must serve a second
    # request while the export request is still open.
    app.run(host=args.host, port=args.port, debug=debug, threaded=True)
