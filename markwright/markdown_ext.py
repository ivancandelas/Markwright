"""Custom Python-Markdown extensions that patch the parser toward
GitHub-Flavored / viewer-specific behavior.

The registration *priorities* are load-bearing — see the "GFM extras" and
"Mermaid blocks" sections of CLAUDE.md. In short: anything that stashes raw HTML
must land in the 25–30 window (above ``fenced_code_block`` at 25, below
``normalize_whitespace`` at 30), and any preprocessor that mutates raw text must
bail on 4-space/tab-indented lines so it doesn't corrupt indented code blocks.
"""
import html
import re
from xml.etree import ElementTree as etree

from flask import url_for
from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor
from markdown.preprocessors import Preprocessor
from markdown.treeprocessors import Treeprocessor

from markwright.links import is_local_reference, resolve_reference

try:
    import emoji as _emoji_lib
except ImportError:
    _emoji_lib = None


MERMAID_BLOCK_RE = re.compile(
    r"^[ ]{0,3}```mermaid[ \t]*\n(?P<code>.*?)\n[ ]{0,3}```[ \t]*$",
    re.MULTILINE | re.DOTALL,
)


class MermaidPreprocessor(Preprocessor):
    def run(self, lines):
        text = "\n".join(lines)

        def replace(match):
            placeholder = self.md.htmlStash.store(
                f'<pre class="mermaid">{html.escape(match.group("code"))}</pre>'
            )
            return f"\n\n{placeholder}\n\n"

        return MERMAID_BLOCK_RE.sub(replace, text).split("\n")


class MermaidExtension(Extension):
    def extendMarkdown(self, md):
        md.preprocessors.register(MermaidPreprocessor(md), "mermaid", 27)


# A list-item marker at line start: ordered (`1.` / `1)`) or unordered
# (`-` / `*` / `+`), followed by at least one space. The `---` horizontal rule
# has no trailing space so it never matches.
LIST_ITEM_RE = re.compile(r"^([ \t]*)(\d{1,9}[.)]|[-*+])([ \t]+)(.*)$")


class ListIndentNormalizePreprocessor(Preprocessor):
    """Normalize GitHub/CommonMark-style list indentation onto the 4-space grid
    Python-Markdown needs to nest sublists.

    Plain Python-Markdown only nests a sublist when it's indented a full
    ``tab_length`` (4 spaces); GitHub/CommonMark nest by the *parent marker's*
    width, so a list under ``5. `` (3 columns) or a ``- `` bullet (2 columns)
    indents its children by 2–3 spaces — which Python-Markdown instead folds
    into the parent item's text.

    A fixed-width replacement (e.g. mdx_truly_sane_lists) can't win both ways:
    set it to 2 and ordinary 4-space bullet nesting breaks; set it to 4 and the
    2–3 space cases break. Instead this uses a *relative-step* model: every
    increase in a list marker's indentation opens one deeper level (re-emitted
    at ``level * 4`` spaces), every decrease closes levels. That handles 2-, 3-
    and 4-space styles uniformly and is a no-op on lists already on the 4-space
    grid (so it can't regress them).

    Only list-*marker* lines are rewritten; everything else passes through
    untouched. Runs after ``fenced_code`` (priority 25) so fenced blocks are
    already stashed to single placeholder lines and never seen here. Indented
    (4-space) code is left alone because it carries no marker. A flush-left,
    non-list, non-blank line ends any open list and resets the level stack."""

    def run(self, lines):
        out = []
        # Each stack entry is the *original* indent width of an open list level,
        # smallest (outermost) first. len(stack)-1 is the current depth.
        stack = []
        for line in lines:
            match = LIST_ITEM_RE.match(line)
            if match is None:
                stripped = line.strip()
                # A flush-left, non-list, non-blank line (heading, paragraph,
                # hr…) closes any open list. Stash placeholders (\x02…) and
                # indented continuation/code keep the list open.
                if stripped and not line[:1].isspace() and not line.startswith("\x02"):
                    stack = []
                out.append(line)
                continue

            indent = match.group(1).expandtabs(4)
            width = len(indent)
            while stack and width < stack[-1]:
                stack.pop()
            if not stack or width > stack[-1]:
                stack.append(width)
            level = len(stack) - 1
            out.append(
                " " * (level * 4) + match.group(2) + match.group(3) + match.group(4)
            )
        return out


class ListIndentNormalizeExtension(Extension):
    def extendMarkdown(self, md):
        # Priority 24: just below fenced_code (25) so code fences are already
        # stashed, above the other GFM raw-text preprocessors.
        md.preprocessors.register(
            ListIndentNormalizePreprocessor(md), "list_indent_normalize", 24
        )


# A standalone line that forces a page break in the PDF export.
PAGE_BREAK_RE = re.compile(
    r"^[ ]{0,3}(?:\\newpage|\\pagebreak|<!--[ \t]*pagebreak[ \t]*-->)[ \t]*$",
    re.IGNORECASE,
)


class PageBreakPreprocessor(Preprocessor):
    """Turn a standalone ``\\newpage`` / ``\\pagebreak`` / ``<!-- pagebreak -->``
    line into a stashed ``<div class="page-break">``. Registered *below*
    ``fenced_code_block`` (priority 25) so a marker inside a code fence is left
    untouched; the regex's ``[ ]{0,3}`` lead also ignores 4-space/tab-indented
    code. The break only matters in print — on screen it shows as a faint
    divider (see CSS)."""

    def run(self, lines):
        out = []
        for line in lines:
            if PAGE_BREAK_RE.match(line):
                placeholder = self.md.htmlStash.store('<div class="page-break"></div>')
                out.extend(["", placeholder, ""])
            else:
                out.append(line)
        return out


class PageBreakExtension(Extension):
    def extendMarkdown(self, md):
        md.preprocessors.register(PageBreakPreprocessor(md), "page_break", 21)


HTML_BLOCK_TAG_MODES = {
    # Block-level processing: tags that typically wrap paragraphs/lists.
    "details": "1", "summary": "1", "section": "1", "article": "1",
    "aside": "1", "blockquote": "1",
    # Span-only processing: README-style wrappers around inline content
    # (badges, bold). Using block mode here would turn 4-space-indented
    # inline HTML into code blocks.
    "div": "span", "header": "span", "footer": "span", "nav": "span",
    "main": "span", "figure": "span", "figcaption": "span",
    "center": "span", "address": "span", "p": "span",
}
HTML_BLOCK_OPEN_RE = re.compile(
    r"<(?P<tag>[a-zA-Z][a-zA-Z0-9-]*)(?P<attrs>(?:\s[^<>]*)?)(?P<close>/?>)"
)


class MarkdownInHtmlAutoAttrPreprocessor(Preprocessor):
    # Adds a markdown attribute to block-level HTML opening tags so
    # README-style files with badges or content inside <div>/<details>
    # still have their inner markdown parsed. Skips indented lines to
    # avoid touching <tag> occurrences inside indented code blocks.
    #
    # Span-mode wrappers (div/center/header/...) are *upgraded* to block
    # mode when the opening tag sits alone on its line and is followed by a
    # blank line. This mirrors GitHub: `<div align="center">\n\n# Title`
    # parses the inner markdown as blocks (so the heading renders), while
    # `<div>\n    <img>` (no blank line, content hugging the tag) stays span
    # so 4-space-indented inline HTML isn't turned into a code block.

    def run(self, lines):
        out = []
        for i, line in enumerate(lines):
            if line.startswith("    ") or line.startswith("\t"):
                out.append(line)
                continue
            next_blank = i + 1 >= len(lines) or not lines[i + 1].strip()
            out.append(
                HTML_BLOCK_OPEN_RE.sub(
                    lambda match: self._inject(match, line, next_blank), line
                )
            )
        return out

    @staticmethod
    def _inject(match, line, next_blank):
        mode = HTML_BLOCK_TAG_MODES.get(match.group("tag").lower())
        if mode is None:
            return match.group(0)
        attrs = match.group("attrs")
        if re.search(r"\bmarkdown\s*=", attrs):
            return match.group(0)
        if mode == "span" and next_blank and line.strip() == match.group(0):
            mode = "1"
        return f"<{match.group('tag')}{attrs} markdown=\"{mode}\"{match.group('close')}"


class MarkdownInHtmlAutoAttrExtension(Extension):
    def extendMarkdown(self, md):
        md.preprocessors.register(
            MarkdownInHtmlAutoAttrPreprocessor(md),
            "md_in_html_auto_attr",
            24,
        )


GFM_HARD_BREAK_RE = re.compile(r"\\\s*$")


class GFMHardBreakPreprocessor(Preprocessor):
    # GFM treats a trailing backslash at end of line as a hard linebreak.
    # Convert it to two trailing spaces (Python-Markdown's native hard-break).
    # Runs after fenced_code (priority 25) so stashed fenced blocks are untouched.

    def run(self, lines):
        out = []
        for line in lines:
            if line.startswith("    ") or line.startswith("\t"):
                out.append(line)
                continue
            if GFM_HARD_BREAK_RE.search(line):
                out.append(GFM_HARD_BREAK_RE.sub("  ", line))
            else:
                out.append(line)
        return out


class GFMHardBreakExtension(Extension):
    def extendMarkdown(self, md):
        md.preprocessors.register(GFMHardBreakPreprocessor(md), "gfm_hard_break", 23)


GFM_TABLE_SEPARATOR_RE = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$"
)


class GFMTableBreakPreprocessor(Preprocessor):
    # Python-Markdown's tables extension requires a blank line above the table
    # header; GFM allows a table to follow prose directly. Detect a separator
    # row (`| --- | --- |`) and insert a blank line above the header line if
    # the preceding line is non-blank. Runs after fenced_code (25) so stashed
    # code blocks are skipped.

    def run(self, lines):
        out = []
        for line in lines:
            if line.startswith("    ") or line.startswith("\t"):
                out.append(line)
                continue
            if GFM_TABLE_SEPARATOR_RE.match(line) and len(out) >= 2 and out[-2].strip():
                out.insert(-1, "")
            out.append(line)
        return out


class GFMTableBreakExtension(Extension):
    def extendMarkdown(self, md):
        md.preprocessors.register(GFMTableBreakPreprocessor(md), "gfm_table_break", 22)


GITHUB_ALERT_RE = re.compile(
    r"^\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(?:\n|$)",
    re.IGNORECASE,
)


class GitHubAlertTreeprocessor(Treeprocessor):
    # GFM alert syntax: a blockquote whose first line is "[!TYPE]" renders as
    # a styled callout. Detect the marker on the first paragraph and rewrite
    # the blockquote: strip the marker, add `markdown-alert markdown-alert-<type>`
    # classes, and inject a title <p>.

    def run(self, root):
        from xml.etree.ElementTree import Element

        for blockquote in root.iter("blockquote"):
            first_p = next((c for c in blockquote if c.tag == "p"), None)
            if first_p is None or not first_p.text:
                continue
            match = GITHUB_ALERT_RE.match(first_p.text)
            if not match:
                continue

            alert_type = match.group(1).lower()
            remainder = first_p.text[match.end():]

            existing = blockquote.get("class", "")
            blockquote.set(
                "class",
                f"{existing} markdown-alert markdown-alert-{alert_type}".strip(),
            )
            first_p.text = remainder
            if not (first_p.text and first_p.text.strip()) and len(first_p) == 0:
                blockquote.remove(first_p)

            title = Element("p")
            title.set("class", "markdown-alert-title")
            title.text = alert_type.capitalize()
            blockquote.insert(0, title)
        return root


class GitHubAlertExtension(Extension):
    def extendMarkdown(self, md):
        # After inline (priority 20) so the marker text is still at the start
        # of first_p.text and not split across elements.
        md.treeprocessors.register(GitHubAlertTreeprocessor(md), "github_alert", 19)


class StrikethroughInlineProcessor(InlineProcessor):
    def handleMatch(self, m, data):
        el = etree.Element("del")
        el.text = m.group(1)
        return el, m.start(0), m.end(0)


class StrikethroughExtension(Extension):
    def extendMarkdown(self, md):
        md.inlinePatterns.register(
            StrikethroughInlineProcessor(r"~~(.+?)~~", md),
            "strikethrough", 175,
        )


SKIP_EMOJI_TAGS = {"code", "pre"}


class EmojiTreeprocessor(Treeprocessor):
    # Walks the tree and replaces GitHub-style :shortcode: aliases with their
    # unicode glyphs. Skips <code> and <pre> subtrees so code samples that
    # happen to contain :tokens: aren't rewritten.

    def run(self, root):
        self._walk(root)
        return root

    def _walk(self, element):
        if element.tag in SKIP_EMOJI_TAGS:
            return
        if element.text:
            element.text = _emoji_lib.emojize(element.text, language="alias")
        for child in element:
            self._walk(child)
            if child.tail:
                child.tail = _emoji_lib.emojize(child.tail, language="alias")


class EmojiExtension(Extension):
    def extendMarkdown(self, md):
        if _emoji_lib is None:
            return
        # Run after inline (priority 20) so <code> spans exist as elements
        # and can be skipped.
        md.treeprocessors.register(EmojiTreeprocessor(md), "emoji", 11)


# The `[ ]`/`[x]` checkbox marker at the start of a list item's text. The
# lookahead (not consumed) keeps the trailing space as the item's text, and lets
# an empty `- [ ]` (marker at end of line) still count as a task.
TASK_MARKER_TEXT_RE = re.compile(r"^\s*\[([ xX])\](?=\s|$)")


class TaskListTreeprocessor(Treeprocessor):
    """Render GFM task-list items (``- [ ]`` / ``- [x]``) as checkbox inputs.

    Each ``<li>`` whose text begins with a ``[ ]``/``[x]`` marker has the marker
    stripped and an ``<input type="checkbox">`` injected at its front, plus a
    document-order ``data-task-index`` so the client can map a clicked box back
    to the Nth task marker in the *source* (see ``/api/toggle-task`` and
    ``markwright.tasks.toggle_task_marker``). ``root.iter("li")`` yields items in
    document order, matching the source line order the toggle helper scans."""

    def run(self, root):
        index = 0
        for li in root.iter("li"):
            holder, text = self._marker_holder(li)
            if holder is None:
                continue
            match = TASK_MARKER_TEXT_RE.match(text)
            if not match:
                continue
            checked = match.group(1).lower() == "x"

            box = etree.Element("input")
            box.set("type", "checkbox")
            box.set("class", "task-list-item-checkbox")
            box.set("data-task-index", str(index))
            if checked:
                box.set("checked", "checked")
            box.tail = text[match.end():]
            index += 1

            li.set("class", (li.get("class", "") + " task-list-item").strip())
            holder.text = ""
            holder.insert(0, box)
        return root

    @staticmethod
    def _marker_holder(li):
        """The element carrying the leading marker text: the ``<li>`` itself for
        a tight list, or its first ``<p>`` child for a loose list."""
        if li.text and li.text.strip():
            return li, li.text
        first = next(iter(li), None)
        if first is not None and first.tag == "p" and first.text and first.text.strip():
            return first, first.text
        return None, ""


class TaskListExtension(Extension):
    def extendMarkdown(self, md):
        # After inline (priority 20) so the `[ ]` marker is still plain text at
        # the start of the item (it's not a link, so inline leaves it intact).
        md.treeprocessors.register(TaskListTreeprocessor(md), "task_list", 18)


class LocalPathTreeprocessor(Treeprocessor):
    def __init__(self, md, current_file):
        super().__init__(md)
        self.current_file = current_file

    def run(self, root):
        current_dir = self.current_file.parent

        for element in root.iter():
            if element.tag == "img":
                src = element.get("src", "")
                if src and is_local_reference(src):
                    element.set("src", url_for("asset", filename=resolve_reference(current_dir, src)))

            if element.tag == "a":
                href = element.get("href", "")
                if href and is_local_reference(href):
                    target = resolve_reference(current_dir, href)
                    if target.split("#", 1)[0].lower().endswith((".md", ".rst")):
                        element.set("href", url_for("index", file=target))
                    else:
                        element.set("href", url_for("asset", filename=target))

        return root


class LocalPathExtension(Extension):
    def __init__(self, current_file):
        super().__init__()
        self.current_file = current_file

    def extendMarkdown(self, md):
        md.treeprocessors.register(LocalPathTreeprocessor(md, self.current_file), "local_paths", 15)
