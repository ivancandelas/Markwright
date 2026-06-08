"""PDF and DOCX export pipelines + their shared token/header/footer/cover
helpers and preset serialization.

This is pure logic — no Flask routes live here. The route handlers in app.py
(``/export/pdf``, ``/export/docx``, the ``/api/pdf-presets`` CRUD) call into
these helpers. See the "PDF export and presets" and "DOCX export" sections of
CLAUDE.md for the many non-obvious requirements (Chrome readiness signal,
band-height auto-margins, @page margin override, pandoc post-processing, etc.).

``gettext`` is used for the user-facing export error messages, so the
message-returning helpers must run inside a request context.
"""
import base64
import html
import logging
import os
import re
import shutil
import struct
import subprocess
import tempfile
import unicodedata
import zlib
from pathlib import Path
from urllib.parse import quote, urlparse

from flask_babel import gettext as _

from markwright.config import LOGO_MIME, LOGOS_DIR
from markwright.frontmatter import extract_frontmatter
from markwright.markdown_ext import MERMAID_BLOCK_RE

# Chrome's header/footer templates accept these auto-filled spans; we expose
# them to users as {tokens} so they don't have to write HTML. Only Chrome can
# fill {page}/{total} (live pagination) and {url}. Everything else —
# {title}/{filename}/{document_name}, {date}/{time}/{datetime}, and any
# {frontmatter-key} — is resolved server-side in _hf_inner so the header band
# reads identically to the cover (and {date} isn't Chrome's locale-formatted
# date span anymore).
_PDF_HF_TOKENS = {
    "{page}": '<span class="pageNumber"></span>',
    "{total}": '<span class="totalPages"></span>',
    "{url}": '<span class="url"></span>',
}


DEFAULT_MARGINS = {"top": 20, "bottom": 20, "left": 12, "right": 12}
DEFAULT_FONT_SCALE = 100  # percent of the 11pt print body base

# PDF body fonts — mirror of the screen font selector (`FONTS` in
# static/js/app.js). Each key maps to a CSS font-family stack and an optional
# Google Fonts `family=` param that _render_pdf loads headless before printing.
# "" = system default (no webfont fetch). Keep the two lists in sync.
_PDF_FONT_SANS = '-apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", Arial, sans-serif'
_PDF_FONT_SERIF = 'Georgia, "Times New Roman", serif'
PDF_FONTS = {
    "": {"stack": _PDF_FONT_SANS, "google": ""},
    "Inter": {"stack": '"Inter", ' + _PDF_FONT_SANS, "google": "Inter:wght@400;600;700"},
    "Roboto": {"stack": '"Roboto", ' + _PDF_FONT_SANS, "google": "Roboto:wght@400;500;700"},
    "Open Sans": {"stack": '"Open Sans", ' + _PDF_FONT_SANS, "google": "Open+Sans:wght@400;600;700"},
    "Lato": {"stack": '"Lato", ' + _PDF_FONT_SANS, "google": "Lato:wght@400;700"},
    "Source Sans 3": {"stack": '"Source Sans 3", ' + _PDF_FONT_SANS, "google": "Source+Sans+3:wght@400;600;700"},
    "IBM Plex Sans": {"stack": '"IBM Plex Sans", ' + _PDF_FONT_SANS, "google": "IBM+Plex+Sans:wght@400;600;700"},
    "Merriweather": {"stack": '"Merriweather", ' + _PDF_FONT_SERIF, "google": "Merriweather:wght@400;700"},
    "Lora": {"stack": '"Lora", ' + _PDF_FONT_SERIF, "google": "Lora:wght@400;600;700"},
    "Source Serif 4": {"stack": '"Source Serif 4", ' + _PDF_FONT_SERIF, "google": "Source+Serif+4:wght@400;600;700"},
    "Atkinson Hyperlegible": {"stack": '"Atkinson Hyperlegible", ' + _PDF_FONT_SANS, "google": "Atkinson+Hyperlegible:wght@400;700"},
    "Montserrat": {"stack": '"Montserrat", ' + _PDF_FONT_SANS, "google": "Montserrat:wght@400;600;700"},
    "Poppins": {"stack": '"Poppins", ' + _PDF_FONT_SANS, "google": "Poppins:wght@400;500;700"},
    "Nunito": {"stack": '"Nunito", ' + _PDF_FONT_SANS, "google": "Nunito:wght@400;600;700"},
    "Raleway": {"stack": '"Raleway", ' + _PDF_FONT_SANS, "google": "Raleway:wght@400;600;700"},
    "Work Sans": {"stack": '"Work Sans", ' + _PDF_FONT_SANS, "google": "Work+Sans:wght@400;600;700"},
    "Noto Sans": {"stack": '"Noto Sans", ' + _PDF_FONT_SANS, "google": "Noto+Sans:wght@400;600;700"},
    "Nunito Sans": {"stack": '"Nunito Sans", ' + _PDF_FONT_SANS, "google": "Nunito+Sans:wght@400;600;700"},
    "Playfair Display": {"stack": '"Playfair Display", ' + _PDF_FONT_SERIF, "google": "Playfair+Display:wght@400;600;700"},
    "PT Serif": {"stack": '"PT Serif", ' + _PDF_FONT_SERIF, "google": "PT+Serif:wght@400;700"},
    "Roboto Slab": {"stack": '"Roboto Slab", ' + _PDF_FONT_SERIF, "google": "Roboto+Slab:wght@400;600;700"},
}


_ATX_HEADING_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
_SETEXT_HEADING_RE = re.compile(
    r"^[ \t]*(\S.*?)[ \t]*\n[ \t]*(=+|-+|~+|\^+|\++|\"+|'+|`+|\*+|#+)[ \t]*$",
    re.MULTILINE,
)


def _extract_doc_title(file_path, bare):
    """Best-effort human title for the {title} token.

    Order: frontmatter ``title:`` → first ATX (``# …``) or setext / RST
    underlined heading → the filename stem. Distinct from {filename}, which is
    always the on-disk name.
    """
    fallback = Path(bare).stem
    try:
        source = file_path.read_text(encoding="utf-8")
    except OSError:
        return fallback

    if file_path.suffix.lower() != ".rst":
        frontmatter, source = extract_frontmatter(source)
        if frontmatter:
            try:
                import yaml
                data = yaml.safe_load(frontmatter)
            except Exception:  # noqa: BLE001 - missing pkg or bad YAML: fall through
                data = None
            if isinstance(data, dict):
                title = data.get("title")
                if title is not None and str(title).strip():
                    return str(title).strip()

    atx = _ATX_HEADING_RE.search(source)
    setext = _SETEXT_HEADING_RE.search(source)
    # Prefer whichever heading appears first in the document.
    if atx and (not setext or atx.start() <= setext.start()):
        return atx.group(1).strip()
    if setext:
        return setext.group(1).strip()
    return fallback


# Tiny inline-markdown subset for header/footer bands. Order matters: `**` before
# `*` so bold wins over italic. Patterns run on already-HTML-escaped text, are
# non-greedy, and forbid the delimiter char inside the run so unbalanced markers
# (`a * b`) stay literal. The produced tags carry no `*`/`~`, so later passes
# don't re-match them.
# `<strong>` carries an explicit weight:700 because the header center column is
# already font-weight:600 (see `_hf_band`'s `center_style`) — a UA-default
# <strong> would barely differ there and read as "bold not working".
_HF_MD_PATTERNS = (
    (re.compile(r"\*\*([^*]+?)\*\*"), r'<strong style="font-weight:700">\1</strong>'),
    (re.compile(r"~~([^~]+?)~~"), r"<del>\1</del>"),
    (re.compile(r"\*([^*]+?)\*"), r"<em>\1</em>"),
)


def _hf_markdown(fragment):
    """Apply the tiny inline-markdown subset (bold/strike/italic) to an
    already-escaped header/footer fragment. See `_hf_inner` for why it runs on
    the literal band text only."""
    for pattern, repl in _HF_MD_PATTERNS:
        fragment = pattern.sub(repl, fragment)
    return fragment


def _hf_inner(text, literals=None, now=None, frontmatter=None):
    """Escape literal text and swap {tokens} for their values.

    Resolution order (all server-side except the last): date/time tokens from
    ``now`` → ``literals`` (e.g. ``{title}`` → the document heading, not Chrome's
    page <title>) → any ``{frontmatter-key}`` → the Chrome-filled spans
    (``{page}``/``{total}``/``{url}``). Unknown ``{key}`` tokens are left intact
    so Chrome's spans still match. ``{br}`` becomes a literal ``<br>`` (the only
    raw-HTML escape hatch — everything else is escaped).

    A tiny inline-markdown subset (``**bold**``, ``*italic*``, ``~~strike~~``) is
    applied to the literal band text *before* any token substitution, so the
    user's own text can be styled but token-inserted values (frontmatter, dates)
    stay literal — a frontmatter value containing ``*`` won't turn italic.
    """
    if not text:
        return ""
    fragment = html.escape(text)
    # `{br}` is the one HTML escape hatch: a literal <br> would have been escaped
    # above, so we swap the token in here (before token resolution, so it can't
    # be shadowed by a frontmatter key named `br`). Chrome's header/footer
    # template renders HTML, so this produces a real line break.
    fragment = fragment.replace("{br}", "<br>")
    fragment = _hf_markdown(fragment)
    if now is not None:
        fragment = _apply_datetime_tokens(fragment, now)
    for token, value in (literals or {}).items():
        fragment = fragment.replace(token, html.escape(str(value)))
    if frontmatter:
        fragment = _apply_frontmatter_tokens(fragment, frontmatter, escape=True, leave_unknown=True)
    for token, span in _PDF_HF_TOKENS.items():
        fragment = fragment.replace(token, span)
    return fragment


def _hf_band(left, center, right, literals=None, *, header=False, logo_html="",
             logo_position="left", pad_left="12mm", pad_right="12mm",
             now=None, frontmatter=None):
    """A 3-column header/footer band. `left/center/right` are raw user text
    (token-substituted here via `literals`). The center column is wider (flex:2)
    and, in headers, larger — meant for the document title. A logo, when
    present, is stacked above its column's text at `logo_position`.

    Chrome renders header/footer templates across the *full* page width, so we
    inset the row by the page's `pad_left`/`pad_right` margins; the separator
    rule lives on this inset row, so it begins and ends at the body's edges
    rather than spanning the whole sheet."""
    aligns = {"left": "flex-start", "center": "center", "right": "flex-end"}
    cols = {
        "left": _hf_inner(left, literals, now, frontmatter),
        "center": _hf_inner(center, literals, now, frontmatter),
        "right": _hf_inner(right, literals, now, frontmatter),
    }
    if logo_html:
        pos = logo_position if logo_position in cols else "left"
        cols[pos] = (
            f'<div style="display:flex; flex-direction:column; '
            f'align-items:{aligns[pos]}; gap:2px;">{logo_html}{cols[pos]}</div>'
        )
    # Center is the title slot: prominent via a larger font-size, but rendered at
    # normal weight so `**bold**` markup is visibly heavier (a semibold default
    # would swallow it on fonts that only ship 400/700 weights).
    center_style = "font-size:11px;" if header else ""
    # A hairline rule separating the band from the body, with breathing room
    # between the line and the text: under the header, above the footer.
    if header:
        rule = "border-bottom:0.5px solid rgba(0,0,0,0.22); padding-bottom:5px;"
    else:
        rule = "border-top:0.5px solid rgba(0,0,0,0.22); padding-top:5px;"
    return (
        f'<div style="width:100%; box-sizing:border-box; padding-left:{pad_left}; '
        f'padding-right:{pad_right}; font-size:9px; color:#666; font-family:sans-serif;">'
        f'<div style="display:flex; align-items:center; {rule}">'
        f'<div style="flex:1; text-align:left; overflow:hidden;">{cols["left"]}</div>'
        f'<div style="flex:2; text-align:center; overflow:hidden; {center_style}">{cols["center"]}</div>'
        f'<div style="flex:1; text-align:right; overflow:hidden;">{cols["right"]}</div>'
        "</div>"
        "</div>"
    )


def _logo_data_uri(preset):
    """base64 data: URI for a preset's logo, or '' when absent/missing."""
    logo = (preset or {}).get("logo")
    if not logo:
        return ""
    path = LOGOS_DIR / logo
    if not path.is_file() or path.parent.resolve() != LOGOS_DIR.resolve():
        return ""
    mime = LOGO_MIME.get(path.suffix.lower(), "application/octet-stream")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _cover_image_data_uri(preset):
    """base64 data: URI for a preset's cover image, or '' when absent/missing."""
    name = (preset or {}).get("coverImage")
    if not name:
        return ""
    path = LOGOS_DIR / name
    if not path.is_file() or path.parent.resolve() != LOGOS_DIR.resolve():
        return ""
    mime = LOGO_MIME.get(path.suffix.lower(), "application/octet-stream")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _doc_frontmatter(file_path):
    """Parsed YAML frontmatter dict for a `.md` file (`{}` for RST / none / bad
    YAML). Feeds the cover's `{frontmatter-key}` tokens."""
    if file_path.suffix.lower() == ".rst":
        return {}
    try:
        source = file_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    fm, _ = extract_frontmatter(source)
    if not fm:
        return {}
    try:
        import yaml
        data = yaml.safe_load(fm)
    except Exception:  # noqa: BLE001 - missing pkg or bad YAML
        return {}
    return data if isinstance(data, dict) else {}


def _fm_scalar(value):
    if isinstance(value, list):
        return ", ".join(str(x) for x in value)
    if isinstance(value, dict):
        return ""
    return str(value)


def _parse_fallback_values(text):
    """Parse a preset's fallback block (one `key: value` per line) into a dict.
    Used to fill `{placeholder}`s when a document's frontmatter lacks them."""
    out = {}
    for line in (text or "").splitlines():
        key, sep, value = line.partition(":")
        key = key.strip()
        if sep and key:
            out[key] = value.strip()
    return out


# Date/time tokens are resolved server-side (so header band, footer band and the
# cover all read identically — see export_pdf's single `now`). Each takes an
# optional inline strftime format: `{date:%d/%m/%Y}`, `{time:%I:%M %p}`,
# `{datetime:%Y-%m-%d %H:%M}`. Without one, these defaults apply.
_DATETIME_DEFAULT_FMT = {"date": "%Y-%m-%d", "time": "%H:%M", "datetime": "%Y-%m-%d %H:%M"}
_DATETIME_TOKEN_RE = re.compile(r"\{(date|time|datetime)(?::([^}]+))?\}", re.IGNORECASE)
_GENERIC_TOKEN_RE = re.compile(r"\{([a-zA-Z0-9_-]+)\}")


def _apply_datetime_tokens(text, now):
    """Replace {date}/{time}/{datetime}[:strftime] with `now` formatted. An
    invalid format string falls back to the token's default rather than erroring."""
    def repl(match):
        name = match.group(1).lower()
        fmt = match.group(2) or _DATETIME_DEFAULT_FMT[name]
        try:
            return now.strftime(fmt)
        except (ValueError, TypeError):
            return now.strftime(_DATETIME_DEFAULT_FMT[name])
    return _DATETIME_TOKEN_RE.sub(repl, text)


def _apply_frontmatter_tokens(text, frontmatter, *, escape, leave_unknown):
    """Replace any `{key}` with the matching (case-insensitive) frontmatter
    value. `leave_unknown` keeps unmatched tokens intact (header/footer, where
    Chrome later swaps {page}/{total}/{url}); otherwise they resolve to '' (the
    cover, so a row referencing a missing key drops out)."""
    def repl(match):
        key = match.group(1)
        value = None
        if key in frontmatter:
            value = _fm_scalar(frontmatter[key])
        else:
            lower = key.lower()
            for fk, fv in frontmatter.items():
                if str(fk).lower() == lower:
                    value = _fm_scalar(fv)
                    break
        if value is None:
            return match.group(0) if leave_unknown else ""
        return html.escape(value) if escape else value
    return _GENERIC_TOKEN_RE.sub(repl, text)


def _resolve_cover_tokens(text, literals, frontmatter, now):
    """Substitute tokens in cover text: date/time tokens from `now`, built-ins
    ({title}/{filename}/{document_name}) from `literals`, then any `{key}` from
    frontmatter (unknown → ''). Returns raw text; callers HTML-escape."""
    if not text:
        return ""
    out = _apply_datetime_tokens(text, now)
    for token, value in literals.items():
        out = out.replace(token, str(value))
    return _apply_frontmatter_tokens(out, frontmatter, escape=False, leave_unknown=False)


# Default filename template for new presets / preset-less exports. {title}
# always resolves (frontmatter title → first heading → filename stem), so an
# export always gets a meaningful name even with no frontmatter.
DEFAULT_FILENAME_TEMPLATE = "{title}"
# Characters illegal in filenames on Windows/macOS/Linux, plus control chars.
_FILENAME_BAD_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _resolve_export_filename(template, literals, frontmatter, now, fallback_stem, ext):
    """Resolve a preset's filename template into a safe download name.

    Reuses the shared token resolver ({title}/{filename}/{document_name},
    {date}/{time}/{datetime}[:fmt], any frontmatter {key} → '' if missing), then
    strips a trailing .pdf/.docx the user may have typed, sanitises path and
    illegal characters, and appends `ext`. Falls back to the document's stem when
    the template is empty or resolves to nothing."""
    template = (template or "").strip() or DEFAULT_FILENAME_TEMPLATE
    name = _resolve_cover_tokens(template, literals, frontmatter, now)
    name = re.sub(r"(?i)\.(pdf|docx)$", "", name.strip())
    name = _FILENAME_BAD_CHARS_RE.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    if not name:
        name = fallback_stem
    return name[:150].strip() + ext


def _content_disposition(name):
    """An `attachment` Content-Disposition carrying both an ASCII fallback and an
    RFC 5987 `filename*` so non-ASCII names (accents, spaces) survive download."""
    ascii_name = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    )
    ascii_name = ascii_name.replace('"', "").strip() or "document"
    return (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(name, safe='')}"
    )


def _cover_image_uri(preset):
    """The cover's image as a data URI, honoring `coverImageSource`:
    `"custom"` → the uploaded cover image, `"logo"` → reuse the preset logo,
    `"none"`/missing → none. Falls back for pre-`coverImageSource` presets
    (uploaded image → custom, else legacy `coverLogo` flag → logo)."""
    source = preset.get("coverImageSource")
    if not source:
        if preset.get("coverImage"):
            source = "custom"
        elif preset.get("coverLogo"):
            source = "logo"
        else:
            source = "none"
    if source == "custom":
        return _cover_image_data_uri(preset)
    if source == "logo":
        return _logo_data_uri(preset)
    return ""


def _build_cover_html(preset, literals, frontmatter, now):
    """A centered cover page from preset fields, tokens resolved + HTML-escaped.
    Every element is optional; returns '' when nothing is configured to show.
    Order (top→bottom): image, title, subtitle, metadata rows, then a footer
    line pinned to the bottom of the page."""
    def resolved(key, default=""):
        raw = preset.get(key)
        if not raw:
            raw = default
        return _resolve_cover_tokens(raw, literals, frontmatter, now)

    title = resolved("coverTitle", "{title}")
    subtitle = resolved("coverSubtitle")
    footer = resolved("coverFooter")
    image_uri = _cover_image_uri(preset)

    parts = []
    if image_uri:
        parts.append(f'<img class="pdf-cover-image" src="{image_uri}" alt="">')
    if title.strip():
        parts.append(f'<h1 class="pdf-cover-title">{html.escape(title)}</h1>')
    if subtitle.strip():
        parts.append(f'<p class="pdf-cover-subtitle">{html.escape(subtitle)}</p>')

    meta_rows = []
    for line in (preset.get("coverMeta") or "").splitlines():
        if not line.strip():
            continue
        label_raw, sep, value_raw = line.partition(":")
        if not sep:
            label_raw, value_raw = "", line
        value = _resolve_cover_tokens(value_raw.strip(), literals, frontmatter, now)
        if not value.strip():
            continue  # drop rows whose token didn't resolve, so missing keys vanish
        label = _resolve_cover_tokens(label_raw.strip(), literals, frontmatter, now)
        meta_rows.append(
            '<div class="pdf-cover-meta-row">'
            f'<span class="pdf-cover-meta-label">{html.escape(label)}</span>'
            f'<span class="pdf-cover-meta-value">{html.escape(value)}</span>'
            "</div>"
        )
    if meta_rows:
        parts.append('<div class="pdf-cover-meta">' + "".join(meta_rows) + "</div>")

    footer_html = (
        f'<div class="pdf-cover-footer">{html.escape(footer)}</div>'
        if footer.strip() else ""
    )
    if not parts and not footer_html:
        return ""
    return (
        '<section class="pdf-cover">'
        f'<div class="pdf-cover-main">{"".join(parts)}</div>'
        f"{footer_html}"
        "</section>"
    )


# Cover image formats pandoc reliably embeds in docx (SVG is skipped), and the
# max printed width for the cover image.
_COVER_IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_COVER_IMG_MAX_IN = 2.8
# Pandoc markdown punctuation — backslash-escaped so resolved cover text (titles,
# metadata) renders literally instead of being parsed as markdown.
_MD_SPECIAL_RE = re.compile(r'([\\`*_{}\[\]()#+.!|>~^<-])')


def _md_escape(text):
    return _MD_SPECIAL_RE.sub(r"\\\1", text or "")


def _cover_image_path(preset):
    """Filesystem path of the cover image per `coverImageSource` (custom upload
    or the preset logo), validated to live in LOGOS_DIR. None when unset."""
    source = preset.get("coverImageSource")
    if not source:
        source = "custom" if preset.get("coverImage") else ("logo" if preset.get("coverLogo") else "none")
    name = preset.get("coverImage") if source == "custom" else (preset.get("logo") if source == "logo" else None)
    if not name:
        return None
    path = LOGOS_DIR / name
    if path.is_file() and path.parent.resolve() == LOGOS_DIR.resolve():
        return path
    return None


def _build_cover_markdown(preset, literals, frontmatter, now, image_name=None):
    """A docx cover page as a pandoc-markdown fragment built from the same preset
    fields + token resolver as the PDF cover (`_build_cover_html`). Each element
    is a `custom-style` fenced div mapping to a `Cover*` paragraph style (see
    `_DOCX_COVER_STYLES`); resolved text is markdown-escaped so it renders
    literally. Returns "" when nothing is configured."""
    def resolved(key, default=""):
        return _resolve_cover_tokens(preset.get(key) or default, literals, frontmatter, now)

    def div(style, text):
        return f'::: {{custom-style="{style}"}}\n{text}\n:::'

    blocks = []
    if image_name:
        blocks.append(div("CoverImage", f"![]({image_name})"))
    title = resolved("coverTitle", "{title}").strip()
    if title:
        blocks.append(div("CoverTitle", _md_escape(title)))
    subtitle = resolved("coverSubtitle").strip()
    if subtitle:
        blocks.append(div("CoverSubtitle", _md_escape(subtitle)))
    for line in (preset.get("coverMeta") or "").splitlines():
        if not line.strip():
            continue
        label_raw, sep, value_raw = line.partition(":")
        if not sep:
            label_raw, value_raw = "", line
        value = _resolve_cover_tokens(value_raw.strip(), literals, frontmatter, now).strip()
        if not value:  # drop rows whose token didn't resolve, matching the PDF cover
            continue
        label = _resolve_cover_tokens(label_raw.strip(), literals, frontmatter, now).strip()
        row = f"**{_md_escape(label)}** {_md_escape(value)}" if label else _md_escape(value)
        blocks.append(div("CoverMeta", row))
    footer = resolved("coverFooter").strip()
    if footer:
        blocks.append(div("CoverFooter", _md_escape(footer)))
    return "\n\n".join(blocks)


def _header_template(parts, preset, literals=None, pad_left="12mm", pad_right="12mm",
                     now=None, frontmatter=None):
    """Header band: 3 columns of text plus the preset logo at its position."""
    data_uri = _logo_data_uri(preset)
    logo_html = (
        f'<img src="{data_uri}" style="height:11mm; max-width:48mm; object-fit:contain;">'
        if data_uri else ""
    )
    return _hf_band(
        parts.get("left", ""), parts.get("center", ""), parts.get("right", ""),
        literals,
        header=True,
        logo_html=logo_html,
        logo_position=(preset or {}).get("logoPosition", "left"),
        pad_left=pad_left,
        pad_right=pad_right,
        now=now,
        frontmatter=frontmatter,
    )


def _footer_template(parts, literals=None, pad_left="12mm", pad_right="12mm",
                     now=None, frontmatter=None):
    """Footer band: 3 columns of text, no logo."""
    return _hf_band(
        parts.get("left", ""), parts.get("center", ""), parts.get("right", ""),
        literals,
        header=False,
        pad_left=pad_left,
        pad_right=pad_right,
        now=now,
        frontmatter=frontmatter,
    )


def _margin_mm(value, fallback):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return f"{fallback}mm"
    n = max(0.0, min(100.0, n))
    return f"{n:g}mm"


def _parse_mm(value):
    """Float mm from a '<n>mm' string (or a bare number); 0.0 on garbage."""
    try:
        return float(str(value).strip().lower().replace("mm", ""))
    except (TypeError, ValueError):
        return 0.0


# CSS-px page dimensions (portrait) at 96dpi, for measuring header/footer bands
# against the actual printed page width. Keys double as the allowed `pageSize`
# values and as Playwright/Chrome `page.pdf(format=...)` names. Landscape (incl.
# "ledger" = tabloid landscape) is handled by the separate orientation flag.
_PAGE_PX = {
    "A4": (793.7, 1122.5),       # 210 × 297 mm
    "Letter": (816.0, 1056.0),   # 8.5 × 11 in
    "Legal": (816.0, 1344.0),    # 8.5 × 14 in
    "Tabloid": (1056.0, 1632.0),  # 11 × 17 in (landscape → ledger)
}
ALLOWED_PAGE_SIZES = set(_PAGE_PX)


def _render_pdf(url, header_template, footer_template, show_hf, page_format, landscape, margin, font_scale=DEFAULT_FONT_SCALE, prepend_html="", show_frontmatter=False, font_family=""):
    from playwright.sync_api import sync_playwright

    # Chrome blocks navigation to "unsafe" ports (e.g. 5060/SIP) with
    # ERR_UNSAFE_PORT. Whitelist whatever port the dev server is on.
    launch_args = ["--no-sandbox"]
    port = urlparse(url).port
    if port:
        launch_args.append(f"--explicitly-allowed-ports={port}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True, args=launch_args)
        try:
            page = browser.new_page()
            # `load` (the window load event) is deterministic; the previous
            # `networkidle` was flaky here because the live-reload poll hits
            # /api/mtime every second, so the network rarely stays idle for the
            # 500 ms networkidle requires. Diagram readiness is awaited explicitly
            # below, so we don't need networkidle to know rendering finished.
            page.goto(url, wait_until="load", timeout=30000)
            # Mermaid renders client-side; wait until every block is processed
            # so diagrams land in the PDF. Tolerate failure (CDN down, no blocks).
            try:
                page.wait_for_function(
                    "() => {const m=[...document.querySelectorAll('pre.mermaid')];"
                    "return m.length===0 || m.every(e=>e.getAttribute('data-processed')==='true');}",
                    timeout=15000,
                )
            except Exception:
                pass
            # Scale the document body. The print stylesheet sizes .markdown-body
            # as calc(11pt * var(--pdf-font-scale)); children size in em off it,
            # so setting this one variable rescales the whole body proportionally.
            if font_scale and font_scale != DEFAULT_FONT_SCALE:
                page.add_style_tag(content=f":root{{--pdf-font-scale:{font_scale / 100:g};}}")

            # Body font: load the chosen webfont (if any) and apply its stack to
            # .markdown-body only — children inherit it, but code/pre keep their
            # explicit monospace, matching the screen font selector. Tolerate a
            # blocked CDN: the stack's fallback then renders instead.
            font = PDF_FONTS.get(font_family) if font_family else None
            if font:
                try:
                    if font["google"]:
                        page.add_style_tag(
                            url=f"https://fonts.googleapis.com/css2?family={font['google']}&display=swap"
                        )
                    page.add_style_tag(
                        content=f".markdown-body{{font-family:{font['stack']} !important;}}"
                    )
                    page.evaluate("async () => { await document.fonts.ready; }")
                except Exception:
                    pass

            # The frontmatter panel is hidden in print by default (the cover /
            # header usually carry that metadata). Opt back in per export/preset.
            if show_frontmatter:
                page.add_style_tag(
                    content="@media print{.frontmatter-panel{display:block !important;}}"
                )

            # Chrome anchors the header/footer band at the page edge and starts the
            # body at the margin, reserving *no* extra space for a tall band — so a
            # logo or multi-line header collides with the body. Measure each band's
            # real rendered height (at the printed page width) and grow the margin
            # to clear it plus a gap. Never shrinks the user's configured margin.
            HF_GAP_MM = 9.0
            page_w_px, _ = _PAGE_PX.get(page_format, _PAGE_PX["A4"])
            if landscape:
                page_w_px = _PAGE_PX.get(page_format, _PAGE_PX["A4"])[1]

            def _band_height_mm(template):
                if not template or not template.strip():
                    return 0.0
                px = page.evaluate(
                    """([html, w]) => {
                        const d = document.createElement('div');
                        d.style.cssText = 'position:absolute;visibility:hidden;left:-10000px;top:0;';
                        d.style.width = w + 'px';
                        d.innerHTML = html;
                        document.body.appendChild(d);
                        const el = d.firstElementChild;
                        const h = el ? el.getBoundingClientRect().height : 0;
                        d.remove();
                        return h;
                    }""",
                    [template, page_w_px],
                )
                return (px or 0) * 25.4 / 96.0

            if show_hf:
                top_need = _band_height_mm(header_template) + HF_GAP_MM
                bot_need = _band_height_mm(footer_template) + HF_GAP_MM
                margin["top"] = f"{max(_parse_mm(margin['top']), top_need):g}mm"
                margin["bottom"] = f"{max(_parse_mm(margin['bottom']), bot_need):g}mm"

            # Cover / blank page (and anything else prepended) goes in *after*
            # margins are finalized: a full-page cover needs to know the printable
            # height (page − top/bottom margins, incl. any band growth) to center
            # its content and pin the footer to the bottom edge. Expose it as a
            # CSS var the cover sizes its min-height from, then inject the markup
            # at the very top of .markdown-body (before the contents page, if any).
            if prepend_html:
                page_h_px = _PAGE_PX.get(page_format, _PAGE_PX["A4"])[1]
                if landscape:
                    page_h_px = _PAGE_PX.get(page_format, _PAGE_PX["A4"])[0]
                content_h_px = page_h_px - (
                    _parse_mm(margin["top"]) + _parse_mm(margin["bottom"])
                ) * 96.0 / 25.4
                page.add_style_tag(
                    content=f":root{{--pdf-page-content-height:{content_h_px:g}px;}}"
                )
                page.evaluate(
                    """(html) => {
                        const body = document.querySelector('.markdown-body');
                        if (body) body.insertAdjacentHTML('afterbegin', html);
                    }""",
                    prepend_html,
                )

            # A CSS `@page { margin }` rule wins over page.pdf(margin=...), so the
            # stylesheet's default would otherwise pin every export to one margin.
            # Inject the computed margins as @page (added last → wins the cascade)
            # so the API margin actually takes effect and the body shifts to leave
            # room for the header/footer band.
            page.add_style_tag(content=(
                f"@page {{ margin: {margin['top']} {margin['right']} "
                f"{margin['bottom']} {margin['left']}; }}"
            ))
            return page.pdf(
                format=page_format,
                landscape=landscape,
                print_background=True,
                display_header_footer=show_hf,
                header_template=header_template,
                footer_template=footer_template,
                margin=margin,
            )
        finally:
            browser.close()


def _export_error_message(exc):
    """Map a render exception to a clean, translated, user-facing message and an
    HTTP status — so the client never sees a raw Playwright/Chrome traceback
    (the full exception is logged server-side instead). Returns (message, status)."""
    text = str(exc).lower()
    if (
        "executable doesn't exist" in text
        or "looking for chrome" in text
        or ("chrome" in text and "was not found" in text)
        or "no such file" in text and "chrome" in text
    ):
        return (
            _("Chrome (or Chromium) is required for PDF export but was not found. "
              "Install Google Chrome and try again."),
            503,
        )
    if "err_unsafe_port" in text:
        return (
            _("Chrome refused to load the page on this port. Restart the viewer on a different --port."),
            500,
        )
    if "timeout" in text or "timed out" in text:
        return (
            _("PDF export timed out — the document may be very large or a diagram failed to load. "
              "See the server logs for details."),
            504,
        )
    return (_("Could not generate the PDF. See the server logs for details."), 500)


def _is_retryable_export_error(exc):
    """Transient failures (navigation/timeouts) are worth one retry; a missing
    Chrome or an unsafe-port refusal will fail identically, so don't retry those."""
    text = str(exc).lower()
    if "executable doesn't exist" in text or "err_unsafe_port" in text:
        return False
    return "timeout" in text or "timed out" in text or "err_" in text or "navigation" in text



DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# CDN module the viewer itself loads mermaid from — reused for headless render.
_MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs"
# Cap a diagram's printed width to the body of an A4/Letter page (≈ 6.3in), and
# scale diagrams up from their natural size so they're legible on the page.
_MERMAID_MAX_WIDTH_IN = 6.3
_MERMAID_SCALE = 1.5
# Render at this device pixel ratio so the upscaled raster stays crisp.
_MERMAID_DEVICE_SCALE = 3


def _png_set_dpi(data, dpi):
    """Return `data` (PNG bytes) with its physical resolution set to `dpi` by
    rewriting the `pHYs` chunk. Pandoc reads this to size the image in the docx,
    so a 2×-rendered diagram tagged 192 dpi prints at its natural size but with
    double the pixels (crisp). No-ops on non-PNG input."""
    sig = b"\x89PNG\r\n\x1a\n"
    if not data.startswith(sig):
        return data
    ppm = int(round(dpi / 0.0254))  # pixels per metre (pHYs unit = 1)
    phys = struct.pack(">IIB", ppm, ppm, 1)
    phys_chunk = (
        struct.pack(">I", len(phys)) + b"pHYs" + phys
        + struct.pack(">I", zlib.crc32(b"pHYs" + phys) & 0xFFFFFFFF)
    )
    out = bytearray(sig)
    i = len(sig)
    inserted = False
    while i + 8 <= len(data):
        length = struct.unpack(">I", data[i:i + 4])[0]
        ctype = data[i + 4:i + 8]
        chunk = data[i:i + 12 + length]
        i += 12 + length
        if ctype == b"pHYs":
            continue  # drop any existing density chunk
        out += chunk
        if ctype == b"IHDR" and not inserted:
            out += phys_chunk  # pHYs must sit before IDAT; right after IHDR is valid
            inserted = True
    return bytes(out) if inserted else data


def _render_mermaid_pngs(sources):
    """Rasterize each mermaid diagram source to a PNG via headless Chrome
    (mermaid@11 from the same CDN the viewer uses).

    Returns a list aligned with `sources`; each entry is ``(png_bytes,
    width_px)`` or ``None`` when that diagram couldn't be rendered. Returns
    all-``None`` if Playwright/Chrome or the CDN are unavailable, so the caller
    can leave the original code block in place. Rendered at 2× for crispness;
    `width_px` is the CSS width so the caller can pin the on-page size."""
    if not sources:
        return []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [None] * len(sources)

    results = [None] * len(sources)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=True, args=["--no-sandbox"])
            try:
                page = browser.new_page(device_scale_factor=_MERMAID_DEVICE_SCALE)
                page.set_content('<div id="c" style="background:#fff;"></div>')
                flags = page.evaluate(
                    """async ([cdn, sources]) => {
                        const mermaid = (await import(cdn)).default;
                        mermaid.initialize({ startOnLoad: false, theme: 'default' });
                        const c = document.getElementById('c');
                        const out = [];
                        for (let i = 0; i < sources.length; i++) {
                            const d = document.createElement('div');
                            d.id = 'd' + i;
                            d.style.cssText = 'background:#fff;display:inline-block;padding:4px;';
                            c.appendChild(d);
                            try {
                                const { svg } = await mermaid.render('m' + i, sources[i]);
                                d.innerHTML = svg;
                                out.push(true);
                            } catch (e) {
                                d.remove();
                                out.push(false);
                            }
                        }
                        return out;
                    }""",
                    [_MERMAID_CDN, sources],
                )
                for i, good in enumerate(flags):
                    if not good:
                        continue
                    try:
                        loc = page.locator(f"#d{i}")
                        box = loc.bounding_box()
                        png = loc.screenshot()
                        results[i] = (png, box["width"] if box else None)
                    except Exception:  # noqa: BLE001 - skip a single bad diagram
                        results[i] = None
            finally:
                browser.close()
    except Exception:  # noqa: BLE001 - CDN/Chrome down: fall back to code blocks
        logging.exception("Mermaid pre-render failed")
        return [None] * len(sources)
    return results


def _inline_mermaid_images(body):
    """Replace ```mermaid fenced blocks in markdown `body` with PNG image refs,
    pre-rendering each diagram (see `_render_mermaid_pngs`). Returns
    ``(new_body, images)`` where `images` maps a generated filename → PNG bytes
    for the caller to drop on pandoc's resource-path. Diagrams that fail to
    render keep their original fenced block (graceful degradation)."""
    blocks = list(MERMAID_BLOCK_RE.finditer(body))
    if not blocks:
        return body, {}
    rendered = _render_mermaid_pngs([m.group("code") for m in blocks])
    images = {}
    idx = [0]

    def repl(match):
        i = idx[0]
        idx[0] += 1
        item = rendered[i] if i < len(rendered) else None
        if not item:
            return match.group(0)
        png, width_px = item
        # The PNG is rendered at _MERMAID_DEVICE_SCALE× CSS px. Tag it with a DPI
        # that makes pandoc print it at _MERMAID_SCALE× its natural width, capped
        # to the page body so wide diagrams shrink to fit. (No width attr needed,
        # which `gfm` doesn't support.)
        if width_px:
            target_in = min(width_px / 96.0 * _MERMAID_SCALE, _MERMAID_MAX_WIDTH_IN)
            png = _png_set_dpi(png, (width_px * _MERMAID_DEVICE_SCALE) / target_in)
        name = f"mermaid-{i}.png"
        images[name] = png
        return f"![]({name})"

    return MERMAID_BLOCK_RE.sub(repl, body), images


# A grid Table style (borders + gray header + zebra) that replaces pandoc's
# borderless default. `band1Horz` shades alternating body rows; pandoc's tables
# already enable row banding (`w:noHBand="0"` in their tblLook), so this renders.
_DOCX_TABLE_STYLE = (
    '<w:style w:type="table" w:default="1" w:styleId="Table">'
    '<w:name w:val="Table"/><w:basedOn w:val="TableNormal"/><w:qFormat/>'
    '<w:tblPr><w:tblInd w:type="dxa" w:w="0"/>'
    '<w:tblLayout w:type="autofit"/>'
    '<w:tblBorders>'
    '<w:top w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
    '<w:left w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
    '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
    '<w:right w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
    '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
    '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
    '</w:tblBorders>'
    '<w:tblCellMar><w:top w:type="dxa" w:w="40"/><w:left w:type="dxa" w:w="108"/>'
    '<w:bottom w:type="dxa" w:w="40"/><w:right w:type="dxa" w:w="108"/></w:tblCellMar>'
    '</w:tblPr>'
    '<w:tblStylePr w:type="firstRow"><w:rPr><w:b/></w:rPr>'
    '<w:tcPr><w:shd w:val="clear" w:color="auto" w:fill="D9D9D9"/>'
    '<w:vAlign w:val="bottom"/></w:tcPr></w:tblStylePr>'
    '<w:tblStylePr w:type="band1Horz"><w:tcPr>'
    '<w:shd w:val="clear" w:color="auto" w:fill="F2F2F2"/></w:tcPr></w:tblStylePr>'
    '</w:style>'
)

# Centered paragraph styles for the docx cover page (sizes are half-points), each
# matched by a `custom-style` div in `_build_cover_markdown`.
_DOCX_COVER_STYLES = (
    '<w:style w:type="paragraph" w:styleId="CoverImage"><w:name w:val="Cover Image"/>'
    '<w:basedOn w:val="Normal"/><w:pPr><w:jc w:val="center"/>'
    '<w:spacing w:before="2400" w:after="240"/></w:pPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="CoverTitle"><w:name w:val="Cover Title"/>'
    '<w:basedOn w:val="Normal"/><w:pPr><w:jc w:val="center"/>'
    '<w:spacing w:before="600" w:after="120"/></w:pPr>'
    '<w:rPr><w:b/><w:sz w:val="56"/><w:szCs w:val="56"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="CoverSubtitle"><w:name w:val="Cover Subtitle"/>'
    '<w:basedOn w:val="Normal"/><w:pPr><w:jc w:val="center"/><w:spacing w:after="480"/></w:pPr>'
    '<w:rPr><w:sz w:val="32"/><w:szCs w:val="32"/><w:color w:val="666666"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="CoverMeta"><w:name w:val="Cover Meta"/>'
    '<w:basedOn w:val="Normal"/><w:pPr><w:jc w:val="center"/><w:spacing w:after="40"/></w:pPr>'
    '<w:rPr><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="CoverFooter"><w:name w:val="Cover Footer"/>'
    '<w:basedOn w:val="Normal"/><w:pPr><w:jc w:val="center"/><w:spacing w:before="960"/></w:pPr>'
    '<w:rPr><w:sz w:val="20"/><w:szCs w:val="20"/><w:color w:val="888888"/></w:rPr></w:style>'
)
# Raw-OpenXML page break (pandoc `raw_attribute` block) — ends the cover page.
_DOCX_PAGE_BREAK = '\n\n```{=openxml}\n<w:p><w:r><w:br w:type="page"/></w:r></w:p>\n```\n'


def _png_width_px(data):
    """Pixel width from a PNG's IHDR, or None for non-PNG."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">I", data[16:20])[0]

# A heading pandoc emits as `<w:bookmarkStart name="slug"/>` immediately before
# `<w:p><w:pPr><w:pStyle w:val="HeadingN"/>…<w:t>text</w:t>…</w:p>`.
_DOCX_HEADING_RE = re.compile(
    r'<w:bookmarkStart\b[^>]*\bw:name="(?P<slug>[^"]*)"[^>]*/>'
    r'\s*<w:p>\s*<w:pPr>\s*<w:pStyle w:val="Heading(?P<level>[1-6])"[^>]*/>'
    r'.*?</w:pPr>(?P<runs>.*?)</w:p>',
    re.S,
)
# Pandoc's TOC field paragraph: a begin/instr/separate/end run with an *empty*
# cached result (nothing between separate and end → blank in viewers that don't
# recalc fields).
_DOCX_TOC_FIELD_RE = re.compile(
    r'<w:p>\s*<w:r>\s*<w:fldChar w:fldCharType="begin"[^>]*/>\s*'
    r'<w:instrText[^>]*>(?P<instr>TOC[^<]*)</w:instrText>\s*'
    r'<w:fldChar w:fldCharType="separate"[^>]*/>\s*'
    r'<w:fldChar w:fldCharType="end"[^>]*/>\s*</w:r>\s*</w:p>',
    re.S,
)


def _populate_toc(doc_xml):
    """Fill pandoc's empty TOC field with static, clickable entries built from
    the document's headings (levels 1–3, linking to the bookmarks pandoc already
    placed). The live field is kept so Word still regenerates it (with page
    numbers) on update — but every other viewer now shows the contents too."""
    headings = []
    for m in _DOCX_HEADING_RE.finditer(doc_xml):
        level = int(m.group("level"))
        if level > 3:
            continue
        text = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", m.group("runs"), re.S)).strip()
        if text:
            headings.append((level, m.group("slug"), text))
    if not headings:
        return doc_xml

    entries = "".join(
        f'<w:p><w:pPr><w:pStyle w:val="TOC{lvl}"/><w:ind w:left="{(lvl - 1) * 360}"/></w:pPr>'
        f'<w:hyperlink w:anchor="{slug}"><w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
        f'<w:t xml:space="preserve">{text}</w:t></w:r></w:hyperlink></w:p>'
        for lvl, slug, text in headings
    )

    def _replace(m):
        return (
            '<w:p><w:r><w:fldChar w:fldCharType="begin" w:dirty="true"/>'
            f'<w:instrText xml:space="preserve">{m.group("instr")}</w:instrText>'
            '<w:fldChar w:fldCharType="separate"/></w:r></w:p>'
            + entries +
            '<w:p><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
        )

    return _DOCX_TOC_FIELD_RE.sub(_replace, doc_xml, count=1)


# The cover's trailing page break(s) — a run of raw-OpenXML page-break
# paragraphs, which pandoc separates with a newline (hence the `\s*`).
_DOCX_PAGE_BREAK_RUN_RE = re.compile(
    r'(?:<w:p><w:r><w:br w:type="page"/></w:r></w:p>\s*)+'
)


def _move_toc_after_cover(doc_xml):
    """Relocate the TOC sdt (which pandoc emits at the top of the body) to just
    after the cover's leading page break(s), giving cover → contents → body. No-op
    if either the TOC sdt or the page break isn't found."""
    m = re.search(r"<w:sdt>.*?</w:sdt>", doc_xml, re.S)
    if not m or "Table of Contents" not in m.group(0):
        return doc_xml
    sdt = m.group(0)
    without = doc_xml[:m.start()] + doc_xml[m.end():]
    pb = _DOCX_PAGE_BREAK_RUN_RE.search(without)
    if not pb:
        return doc_xml  # leave as-is rather than risk a worse order
    return without[:pb.end()] + sdt + without[pb.end():]


def _style_docx(data, font_name=None, update_fields=False, cover=False):
    """Patch a pandoc-generated .docx (a zip) so the output matches the viewer:

    - `font_name`: set the theme's major+minor Latin typeface (pandoc styles
      everything off theme fonts, so this restyles body *and* headings).
    - table style: swap pandoc's borderless default for `_DOCX_TABLE_STYLE`
      (grid borders, gray header, zebra rows).
    - `update_fields`: add `<w:updateFields>` so Word recalculates the TOC field
      on open, *and* `_populate_toc()` fills its empty cached result with static
      clickable entries so non-recalculating viewers show the contents too.
    - tables: rewrite each table's instance width to 100% (full page body) and
      give the style `autofit` layout so columns size to content within it.
    - `cover`: register the `Cover*` paragraph styles the cover fragment uses.

    Rewrites only the touched members; everything else is copied verbatim."""
    import io
    import zipfile

    def _patch(name, xml):
        if name == "word/theme/theme1.xml" and font_name:
            for kind in ("major", "minor"):
                xml = re.sub(
                    r'(<a:' + kind + r'Font>\s*<a:latin\b[^>]*?\btypeface=")[^"]*(")',
                    r"\g<1>" + font_name + r"\g<2>", xml, count=1, flags=re.S,
                )
        elif name == "word/styles.xml":
            xml = re.sub(
                r'<w:style\b[^>]*w:styleId="Table"[^>]*>.*?</w:style>',
                _DOCX_TABLE_STYLE, xml, count=1, flags=re.S,
            )
            if cover:
                xml = xml.replace("</w:styles>", _DOCX_COVER_STYLES + "</w:styles>", 1)
        elif name == "word/document.xml":
            # Instance width overrides the style, so pandoc's `auto` tblW must be
            # rewritten here to full width; columns keep their grid proportions.
            xml = re.sub(
                r'<w:tblW\b[^>]*/>',
                '<w:tblW w:type="pct" w:w="5000"/>', xml,
            )
            if update_fields:  # contents page requested → fill the TOC field
                xml = _populate_toc(xml)
                if cover:
                    # Pandoc puts the TOC at the very top, *above* the prepended
                    # cover fragment. Move the TOC sdt to just after the cover's
                    # page break(s) so the order is cover → contents → body.
                    xml = _move_toc_after_cover(xml)
        elif name == "word/settings.xml" and update_fields and "updateFields" not in xml:
            xml = re.sub(
                r"(<w:settings\b[^>]*>)",
                r'\1<w:updateFields w:val="true"/>', xml, count=1,
            )
        return xml

    src = zipfile.ZipFile(io.BytesIO(data))
    targets = {"word/theme/theme1.xml", "word/styles.xml", "word/document.xml", "word/settings.xml"}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            raw = src.read(item.filename)
            if item.filename in targets:
                raw = _patch(item.filename, raw.decode("utf-8")).encode("utf-8")
            dst.writestr(item, raw)
    return out.getvalue()


def _render_docx(source_text, input_format, resource_paths, title=None, author=None,
                 include_toc=False, font_name=None, cover=False):
    """Convert markdown / RST source to .docx bytes via the `pandoc` binary.

    `input_format` is a pandoc reader spec (``gfm``/``rst``); `resource_paths`
    are dirs pandoc searches for relative images (it embeds them in the docx).
    `title`/`author` become the document's core properties + standalone title
    block; `include_toc` prepends a real Word TOC field; `font_name` restyles
    the body/heading font; `cover` registers the cover paragraph styles. Source
    is fed on stdin (so no temp file lands in the user's content dir). Raises
    FileNotFoundError when pandoc is missing, RuntimeError on a conversion error."""
    pandoc = shutil.which("pandoc")
    if not pandoc:
        raise FileNotFoundError("pandoc")
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "out.docx"
        cmd = [
            pandoc,
            "-f", input_format,
            "-t", "docx",
            "-o", str(out_path),
            "--standalone",
            f"--resource-path={os.pathsep.join(resource_paths)}",
        ]
        if include_toc:
            cmd += ["--toc", "--toc-depth=3"]
        if title:
            cmd += ["--metadata", f"title={title}"]
        if author:
            cmd += ["--metadata", f"author={author}"]
        proc = subprocess.run(
            cmd, input=source_text.encode("utf-8"),
            capture_output=True, timeout=60,
        )
        if proc.returncode != 0:
            detail = proc.stderr.decode("utf-8", "replace").strip()
            raise RuntimeError(detail or "pandoc exited non-zero")
        return _style_docx(out_path.read_bytes(), font_name=font_name,
                           update_fields=include_toc, cover=cover)



def _serialize_preset(preset):
    """Public view of a preset: no stored filename, just a hasLogo flag.

    Exposes header/footer as 3 columns; pre-3-column presets (single `header`/
    `footer` string) are migrated on read by mapping the old value to center."""
    def _cols(prefix):
        legacy = preset.get(prefix, "")
        return {
            "left": preset.get(f"{prefix}Left", ""),
            "center": preset.get(f"{prefix}Center", legacy),
            "right": preset.get(f"{prefix}Right", ""),
        }

    return {
        "id": preset.get("id"),
        "name": preset.get("name", ""),
        "header": _cols("header"),
        "footer": _cols("footer"),
        "logoPosition": preset.get("logoPosition", "left"),
        "hasLogo": bool(preset.get("logo")),
        "pageSize": preset.get("pageSize", "A4"),
        "orientation": preset.get("orientation", "portrait"),
        "margins": preset.get("margins", dict(DEFAULT_MARGINS)),
        "fontScale": preset.get("fontScale", DEFAULT_FONT_SCALE),
        "fontFamily": preset.get("fontFamily", "") if preset.get("fontFamily") in PDF_FONTS else "",
        "fileNameTemplate": preset.get("fileNameTemplate", ""),
        "includeToc": bool(preset.get("includeToc")),
        "includeFrontmatter": bool(preset.get("includeFrontmatter")),
        "useFallback": bool(preset.get("useFallback")),
        "fallbackValues": preset.get("fallbackValues", ""),
        "coverEnabled": bool(preset.get("coverEnabled")),
        "coverTitle": preset.get("coverTitle", ""),
        "coverSubtitle": preset.get("coverSubtitle", ""),
        "coverMeta": preset.get("coverMeta", ""),
        "coverFooter": preset.get("coverFooter", ""),
        "coverImageSource": preset.get(
            "coverImageSource",
            "custom" if preset.get("coverImage")
            else ("logo" if preset.get("coverLogo") else "none"),
        ),
        "hasCoverImage": bool(preset.get("coverImage")),
        "blankAfterCover": bool(preset.get("blankAfterCover")),
    }

