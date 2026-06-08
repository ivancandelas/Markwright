"""YAML frontmatter extraction and the GitHub-style rendered panel.

``extract_frontmatter`` peels a leading ``---\\n…\\n---`` block off ``.md``
sources before the markdown converter sees them (tolerating a doubled
``---\\n---`` opener); it is reused by the DOCX export path too.
``render_frontmatter_panel`` turns the parsed YAML into nested tables matching
GitHub's rendering, falling back to a Pygments-highlighted code block when the
YAML can't be parsed as a dict.
"""
import html
import re

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?\n)---[ \t]*(?:\n|\Z)", re.DOTALL)


def extract_frontmatter(source):
    match = FRONTMATTER_RE.match(source)
    if not match:
        return "", source
    block = match.group(1)
    # Some files (e.g. wired DESIGN.md) ship with a doubled "---\n---" opener;
    # drop a leading separator inside the captured block so we don't display it.
    block = re.sub(r"\A---[ \t]*\n", "", block, count=1)
    return block, source[match.end():]


def _yaml_value_to_html(value):
    if isinstance(value, dict):
        if not value:
            return ""
        if all(not isinstance(v, (dict, list)) for v in value.values()):
            keys = "".join(f"<th>{html.escape(str(k))}</th>" for k in value.keys())
            vals = "".join(f"<td>{_yaml_value_to_html(v)}</td>" for v in value.values())
            return (
                f'<table class="fm-horizontal">'
                f"<thead><tr>{keys}</tr></thead>"
                f"<tbody><tr>{vals}</tr></tbody>"
                f"</table>"
            )
        sections = []
        for sub_key, sub_value in value.items():
            sections.append(
                f'<div class="fm-section">'
                f'<div class="fm-section-title">{html.escape(str(sub_key))}</div>'
                f"{_yaml_value_to_html(sub_value)}"
                f"</div>"
            )
        return "".join(sections)

    if isinstance(value, list):
        if not value:
            return ""
        if all(not isinstance(x, (dict, list)) for x in value):
            return ", ".join(html.escape(str(x)) for x in value)
        items = "".join(f"<li>{_yaml_value_to_html(x)}</li>" for x in value)
        return f"<ul>{items}</ul>"

    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return html.escape(str(value))


def _frontmatter_code_panel(yaml_text):
    from pygments import highlight
    from pygments.formatters import HtmlFormatter
    from pygments.lexers import YamlLexer
    highlighted = highlight(
        yaml_text,
        YamlLexer(),
        HtmlFormatter(cssclass="codehilite", nowrap=False),
    )
    return (
        '<details class="frontmatter-panel" open>'
        "<summary>Front matter</summary>"
        f"{highlighted}"
        "</details>"
    )


def render_frontmatter_panel(yaml_text):
    if not yaml_text.strip():
        return ""
    try:
        import yaml
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        return _frontmatter_code_panel(yaml_text)
    if not isinstance(data, dict):
        return _frontmatter_code_panel(yaml_text)
    rows = "".join(
        f"<tr><th>{html.escape(str(k))}</th><td>{_yaml_value_to_html(v)}</td></tr>"
        for k, v in data.items()
    )
    return (
        '<details class="frontmatter-panel" open>'
        "<summary>Front matter</summary>"
        '<div class="fm-scroll">'
        f'<table class="fm-vertical"><tbody>{rows}</tbody></table>'
        "</div>"
        "</details>"
    )
