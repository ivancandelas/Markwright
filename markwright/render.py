"""Per-format rendering + the shared HTML sanitizer.

``sanitize_html`` is the single source of truth for the bleach tag/attribute
allowlist — both ``render_markdown`` and ``render_rst`` pass through it.
Anything added to ``ALLOWED_TAGS`` / ``ALLOWED_ATTRIBUTES`` widens what
user-authored markup can render, so be deliberate. Local refs are rewritten
before sanitization: markdown via ``LocalPathTreeprocessor`` (in
``markdown_ext``), RST post-hoc via ``rewrite_local_links``.
"""
import re

import bleach
import markdown
from docutils.core import publish_parts
from flask import url_for

from markwright import state
from markwright.frontmatter import extract_frontmatter, render_frontmatter_panel
from markwright.links import is_local_reference, resolve_reference
from markwright.markdown_ext import (
    BlockquoteFenceExtension,
    EmojiExtension,
    GFMHardBreakExtension,
    GFMTableBreakExtension,
    GitHubAlertExtension,
    ListIndentNormalizeExtension,
    LocalPathExtension,
    MarkdownInHtmlAutoAttrExtension,
    MermaidExtension,
    PageBreakExtension,
    StrikethroughExtension,
    TaskListExtension,
)

ALLOWED_TAGS = set(bleach.sanitizer.ALLOWED_TAGS).union({
    "article", "p", "pre", "span", "div", "img",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "table", "thead", "tbody", "tr", "th", "td",
    "hr", "br", "del", "sup", "sub", "input",
    "section", "details", "summary",
})
ALLOWED_ATTRIBUTES = {
    **bleach.sanitizer.ALLOWED_ATTRIBUTES,
    "*": ["class", "id", "align"],
    "a": ["href", "title", "rel", "target"],
    "img": ["src", "alt", "title", "width", "height", "loading", "align"],
    "th": ["align", "scope", "colspan", "rowspan"],
    "td": ["align", "colspan", "rowspan"],
    "input": ["type", "checked", "disabled", "data-task-index"],
    "details": ["open"],
}


def sanitize_html(html):
    return bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=["http", "https", "mailto"],
        strip=True,
    )


LINK_ATTR_RE = re.compile(r"""(\s)(href|src)=(['"])([^'"]+)\3""")
INAPP_DOC_SUFFIXES = (".md", ".rst")


def rewrite_local_links(html_str, current_file):
    current_dir = current_file.parent

    def repl(match):
        prefix, attr, quote, value = match.groups()
        if not is_local_reference(value):
            return match.group(0)
        target = resolve_reference(current_dir, value)
        bare = target.split("#", 1)[0].lower()
        if attr == "src":
            new = url_for("asset", filename=target)
        elif bare.endswith(INAPP_DOC_SUFFIXES):
            new = url_for("index", file=target)
        else:
            new = url_for("asset", filename=target)
        return f"{prefix}{attr}={quote}{new}{quote}"

    return LINK_ATTR_RE.sub(repl, html_str)


def render_rst(file_path):
    return render_rst_source(file_path.relative_to(state.CONTENT_DIR),
                             file_path.read_text(encoding="utf-8"))


def render_rst_source(rel_path, source):
    """Render RST from a source string with ``rel_path`` (relative to
    CONTENT_DIR) as the local-link context. Used by the live editor preview to
    render unsaved text; ``render_rst`` is the on-disk wrapper."""
    parts = publish_parts(
        source=source,
        writer_name="html5",
        settings_overrides={
            "report_level": 5,
            "halt_level": 5,
            "embed_stylesheet": False,
            "doctitle_xform": False,
            "syntax_highlight": "none",
            "raw_enabled": False,
            "file_insertion_enabled": False,
            "input_encoding": "utf-8",
            "output_encoding": "unicode",
        },
    )
    html = parts.get("html_body") or parts.get("body") or ""
    html = rewrite_local_links(html, rel_path)
    return sanitize_html(html), ""


def render_markdown(file_path):
    return render_markdown_source(file_path.relative_to(state.CONTENT_DIR),
                                  file_path.read_text(encoding="utf-8"))


def render_markdown_source(rel_path, source):
    """Render Markdown from a source string with ``rel_path`` (relative to
    CONTENT_DIR) as the local-link context. Used by the live editor preview to
    render unsaved text; ``render_markdown`` is the on-disk wrapper."""
    frontmatter, source = extract_frontmatter(source)
    md = markdown.Markdown(
        extensions=[
            "extra",
            "tables",
            "fenced_code",
            "codehilite",
            "sane_lists",
            "toc",
            MermaidExtension(),
            BlockquoteFenceExtension(),
            PageBreakExtension(),
            ListIndentNormalizeExtension(),
            MarkdownInHtmlAutoAttrExtension(),
            GFMHardBreakExtension(),
            GFMTableBreakExtension(),
            GitHubAlertExtension(),
            StrikethroughExtension(),
            TaskListExtension(),
            EmojiExtension(),
            LocalPathExtension(rel_path),
        ],
        extension_configs={
            "codehilite": {
                "guess_lang": False,
                "linenums": False,
                "css_class": "codehilite",
            }
        },
        output_format="html5",
    )
    html = md.convert(source)
    if frontmatter:
        html = render_frontmatter_panel(frontmatter) + html
    toc_html = sanitize_html(md.toc) if getattr(md, "toc_tokens", None) else ""
    return sanitize_html(html), toc_html
