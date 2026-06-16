"""Unit tests for the pure helpers in app.py.

These cover the parsing / token-resolution / sanitisation / path-safety logic
that has no Flask request context or external process (Chrome, pandoc, git)
behind it. Route handlers and the PDF/DOCX export pipelines are intentionally
out of scope here.
"""
from datetime import datetime

import pytest
from werkzeug.exceptions import NotFound

import app as appmod


# --------------------------------------------------------------------------- #
# Frontmatter extraction
# --------------------------------------------------------------------------- #
class TestExtractFrontmatter:
    def test_basic_block_is_split_from_body(self):
        block, rest = appmod.extract_frontmatter("---\ntitle: Hi\n---\n# Body\n")
        assert block == "title: Hi\n"
        assert rest == "# Body\n"

    def test_no_frontmatter_returns_empty_block_and_original(self):
        src = "# Just a heading\n\ntext\n"
        block, rest = appmod.extract_frontmatter(src)
        assert block == ""
        assert rest == src

    def test_doubled_dash_opener_is_tolerated(self):
        # Some files (wired DESIGN.md) ship with a doubled "---\n---" opener.
        block, rest = appmod.extract_frontmatter("---\n---\ntitle: Hi\n---\nBody\n")
        assert block == "title: Hi\n"
        assert rest == "Body\n"

    def test_closing_fence_at_eof_without_trailing_newline(self):
        block, rest = appmod.extract_frontmatter("---\na: 1\n---")
        assert block == "a: 1\n"
        assert rest == ""

    def test_dashes_not_at_start_are_not_frontmatter(self):
        src = "intro\n---\ntitle: Hi\n---\n"
        block, rest = appmod.extract_frontmatter(src)
        assert block == ""
        assert rest == src


# --------------------------------------------------------------------------- #
# is_local_reference / is_git_url
# --------------------------------------------------------------------------- #
class TestIsLocalReference:
    @pytest.mark.parametrize("value", [
        "doc.md", "images/pic.png", "../sibling/readme.md", "deep/path.rst",
        "FILE.MD",
    ])
    def test_local_paths(self, value):
        assert appmod.is_local_reference(value) is True

    @pytest.mark.parametrize("value", [
        "http://example.com", "https://example.com", "HTTPS://EXAMPLE.COM",
        "mailto:a@b.c", "tel:+123", "#anchor", "data:image/png;base64,AAAA",
        "/absolute/root.md",
    ])
    def test_non_local_references(self, value):
        assert appmod.is_local_reference(value) is False


class TestIsGitUrl:
    @pytest.mark.parametrize("value", [
        "https://github.com/a/b", "http://host/repo", "git://host/r",
        "ssh://git@host/r", "git@github.com:a/b.git", "/local/repo.git",
    ])
    def test_git_urls(self, value):
        assert appmod.is_git_url(value) is True

    @pytest.mark.parametrize("value", ["/home/user/docs", "./relative", "plain"])
    def test_non_git(self, value):
        assert appmod.is_git_url(value) is False


# --------------------------------------------------------------------------- #
# resolve_reference
# --------------------------------------------------------------------------- #
class TestResolveReference:
    def test_resolves_relative_to_current_dir(self):
        from pathlib import PurePosixPath
        out = appmod.resolve_reference(PurePosixPath("a/b"), "c/d.md")
        assert out == "a/b/c/d.md"

    def test_preserves_fragment(self):
        from pathlib import PurePosixPath
        out = appmod.resolve_reference(PurePosixPath("a"), "doc.md#section")
        assert out == "a/doc.md#section"

    def test_joins_without_collapsing_dotdot(self):
        # resolve_reference joins lexically (PurePosixPath.as_posix) and does NOT
        # collapse `..`; the final consumer resolves it. Documenting that here.
        from pathlib import PurePosixPath
        out = appmod.resolve_reference(PurePosixPath("a/b"), "../x.md")
        assert out == "a/b/../x.md"


# --------------------------------------------------------------------------- #
# safe_path (path-traversal guard) + scan / build_tree
# --------------------------------------------------------------------------- #
class TestSafePath:
    def test_valid_path_stays_under_content_dir(self, content_dir):
        (content_dir / "doc.md").write_text("x")
        resolved = appmod.safe_path("doc.md")
        assert resolved == (content_dir / "doc.md").resolve()

    def test_empty_path_aborts_404(self, content_dir):
        with pytest.raises(NotFound):
            appmod.safe_path("")

    def test_traversal_aborts_404(self, content_dir):
        with pytest.raises(NotFound):
            appmod.safe_path("../../etc/passwd")


class TestScanAndTree:
    def test_scan_finds_md_rst_readme_and_skips_ignored(self, content_dir):
        (content_dir / "a.md").write_text("x")
        (content_dir / "b.rst").write_text("x")
        (content_dir / "README").write_text("x")
        sub = content_dir / "sub"
        sub.mkdir()
        (sub / "c.md").write_text("x")
        ignored = content_dir / ".git"
        ignored.mkdir()
        (ignored / "hidden.md").write_text("x")

        found = appmod.scan_markdown_files()
        assert "a.md" in found
        assert "b.rst" in found
        assert "README" in found
        assert "sub/c.md" in found
        assert ".git/hidden.md" not in found

    def test_build_tree_nests_by_path(self):
        tree = appmod.build_tree(["a.md", "sub/b.md", "sub/deep/c.md"])
        assert tree["a.md"] == "a.md"
        assert tree["sub"]["b.md"] == "sub/b.md"
        assert tree["sub"]["deep"]["c.md"] == "sub/deep/c.md"


# --------------------------------------------------------------------------- #
# sanitize_html
# --------------------------------------------------------------------------- #
class TestSanitizeHtml:
    def test_strips_script(self):
        # bleach strip=True removes the *tags* (so nothing executes); the inert
        # text content may remain, which is the documented behaviour.
        out = appmod.sanitize_html("<p>ok</p><script>alert(1)</script>")
        assert "<script>" not in out
        assert "<p>ok</p>" in out

    def test_keeps_allowed_tags(self):
        out = appmod.sanitize_html("<h1>Title</h1><strong>b</strong>")
        assert "<h1>Title</h1>" in out
        assert "<strong>b</strong>" in out

    def test_drops_javascript_protocol_link(self):
        out = appmod.sanitize_html('<a href="javascript:alert(1)">x</a>')
        assert "javascript:" not in out


# --------------------------------------------------------------------------- #
# Margin parsing
# --------------------------------------------------------------------------- #
class TestMargins:
    @pytest.mark.parametrize("value,expected", [
        (10, "10mm"), ("12.5", "12.5mm"), (0, "0mm"),
        (-5, "0mm"), (500, "100mm"),
    ])
    def test_margin_mm_clamps(self, value, expected):
        assert appmod._margin_mm(value, 18) == expected

    def test_margin_mm_garbage_uses_fallback(self):
        assert appmod._margin_mm("abc", 14) == "14mm"
        assert appmod._margin_mm(None, 18) == "18mm"

    @pytest.mark.parametrize("value,expected", [
        ("18mm", 18.0), ("14", 14.0), (" 12MM ", 12.0), ("junk", 0.0), (None, 0.0),
    ])
    def test_parse_mm(self, value, expected):
        assert appmod._parse_mm(value) == expected


# --------------------------------------------------------------------------- #
# Token resolvers
# --------------------------------------------------------------------------- #
NOW = datetime(2026, 6, 2, 14, 30, 0)


class TestDatetimeTokens:
    def test_defaults(self):
        assert appmod._apply_datetime_tokens("{date}", NOW) == "2026-06-02"
        assert appmod._apply_datetime_tokens("{time}", NOW) == "14:30"
        assert appmod._apply_datetime_tokens("{datetime}", NOW) == "2026-06-02 14:30"

    def test_custom_format(self):
        assert appmod._apply_datetime_tokens("{date:%d/%m/%Y}", NOW) == "02/06/2026"

    def test_invalid_format_falls_back_to_default(self):
        # An unparseable strftime must not raise; it falls back to the default fmt.
        out = appmod._apply_datetime_tokens("{date:%Q}", NOW)
        assert out  # produces something
        assert "{date" not in out

    def test_case_insensitive_token(self):
        assert appmod._apply_datetime_tokens("{DATE}", NOW) == "2026-06-02"


class TestFrontmatterTokens:
    def test_exact_key(self):
        out = appmod._apply_frontmatter_tokens(
            "{author}", {"author": "Iván"}, escape=False, leave_unknown=True)
        assert out == "Iván"

    def test_case_insensitive_key(self):
        out = appmod._apply_frontmatter_tokens(
            "{Author}", {"author": "Iván"}, escape=False, leave_unknown=True)
        assert out == "Iván"

    def test_unknown_left_intact_when_requested(self):
        out = appmod._apply_frontmatter_tokens(
            "{missing}", {}, escape=False, leave_unknown=True)
        assert out == "{missing}"

    def test_unknown_dropped_when_not_left(self):
        out = appmod._apply_frontmatter_tokens(
            "{missing}", {}, escape=False, leave_unknown=False)
        assert out == ""

    def test_escape_applies(self):
        out = appmod._apply_frontmatter_tokens(
            "{x}", {"x": "a<b>&c"}, escape=True, leave_unknown=False)
        assert out == "a&lt;b&gt;&amp;c"

    def test_list_value_is_comma_joined(self):
        out = appmod._apply_frontmatter_tokens(
            "{tags}", {"tags": ["a", "b"]}, escape=False, leave_unknown=True)
        assert out == "a, b"


class TestFmScalar:
    def test_list(self):
        assert appmod._fm_scalar([1, 2, 3]) == "1, 2, 3"

    def test_dict_is_empty(self):
        assert appmod._fm_scalar({"a": 1}) == ""

    def test_scalar_stringified(self):
        assert appmod._fm_scalar(42) == "42"


class TestParseFallbackValues:
    def test_basic(self):
        out = appmod._parse_fallback_values("author: Me\nversion: 1.0")
        assert out == {"author": "Me", "version": "1.0"}

    def test_ignores_blank_and_keyless(self):
        out = appmod._parse_fallback_values("\n  \nno-colon-here\nk: v")
        assert out == {"k": "v"}

    def test_value_with_colon(self):
        out = appmod._parse_fallback_values("url: http://x:80/y")
        assert out == {"url": "http://x:80/y"}

    def test_empty(self):
        assert appmod._parse_fallback_values("") == {}
        assert appmod._parse_fallback_values(None) == {}


class TestResolveCoverTokens:
    def test_combines_datetime_literals_frontmatter(self):
        out = appmod._resolve_cover_tokens(
            "{title} {date} {author}",
            {"{title}": "My Doc"},
            {"author": "Iván"},
            NOW,
        )
        assert out == "My Doc 2026-06-02 Iván"

    def test_unknown_frontmatter_drops(self):
        out = appmod._resolve_cover_tokens("{missing}", {}, {}, NOW)
        assert out == ""

    def test_empty_input(self):
        assert appmod._resolve_cover_tokens("", {}, {}, NOW) == ""


# --------------------------------------------------------------------------- #
# Header/footer inline markdown
# --------------------------------------------------------------------------- #
class TestHfMarkdown:
    def test_bold(self):
        assert "<strong" in appmod._hf_markdown("**x**")

    def test_italic(self):
        assert appmod._hf_markdown("*x*") == "<em>x</em>"

    def test_strike(self):
        assert appmod._hf_markdown("~~x~~") == "<del>x</del>"

    def test_unbalanced_left_literal(self):
        assert appmod._hf_markdown("a * b") == "a * b"


# --------------------------------------------------------------------------- #
# Filename resolution + Content-Disposition
# --------------------------------------------------------------------------- #
class TestResolveExportFilename:
    def test_default_template_uses_title(self):
        out = appmod._resolve_export_filename(
            "", {"{title}": "My Doc"}, {}, NOW, "fallback", ".pdf")
        assert out == "My Doc.pdf"

    def test_tokens_compose(self):
        out = appmod._resolve_export_filename(
            "{title} - {version}", {"{title}": "API"}, {"version": "2.0"},
            NOW, "fallback", ".pdf")
        assert out == "API - 2.0.pdf"

    def test_strips_typed_extension(self):
        out = appmod._resolve_export_filename(
            "report.pdf", {"{title}": "x"}, {}, NOW, "fb", ".pdf")
        assert out == "report.pdf"
        assert out.count(".pdf") == 1

    def test_illegal_chars_replaced(self):
        out = appmod._resolve_export_filename(
            "a/b:c?d", {"{title}": "x"}, {}, NOW, "fb", ".pdf")
        assert "/" not in out[:-4]
        assert ":" not in out
        assert "?" not in out

    def test_falls_back_when_empty_after_resolution(self):
        out = appmod._resolve_export_filename(
            "{missing}", {}, {}, NOW, "fallback-stem", ".docx")
        assert out == "fallback-stem.docx"

    def test_truncates_long_names(self):
        out = appmod._resolve_export_filename(
            "x" * 300, {"{title}": "x"}, {}, NOW, "fb", ".pdf")
        assert len(out) <= 150 + len(".pdf")

    def test_accented_name_preserved(self):
        out = appmod._resolve_export_filename(
            "{title}", {"{title}": "Iván Candelas"}, {}, NOW, "fb", ".pdf")
        assert out == "Iván Candelas.pdf"


class TestContentDisposition:
    def test_ascii_name(self):
        out = appmod._content_disposition("report.pdf")
        assert 'filename="report.pdf"' in out
        assert "filename*=UTF-8''report.pdf" in out

    def test_accented_name_has_ascii_fallback_and_utf8(self):
        out = appmod._content_disposition("Iván.pdf")
        # ASCII fallback strips the accent…
        assert 'filename="Ivan.pdf"' in out
        # …and the RFC 5987 form percent-encodes the original.
        assert "filename*=UTF-8''" in out
        assert "%C3%A1" in out  # á

    def test_empty_ascii_falls_back_to_document(self):
        # A name with no ASCII-representable characters yields the "document"
        # fallback for the plain filename= form.
        out = appmod._content_disposition("世界")
        assert 'filename="document"' in out
        assert "filename*=UTF-8''%E4%B8%96%E7%95%8C" in out


# --------------------------------------------------------------------------- #
# Env / asset helpers
# --------------------------------------------------------------------------- #
class TestEnvBool:
    def test_missing_uses_default(self, monkeypatch):
        monkeypatch.delenv("MDV_TEST_FLAG", raising=False)
        assert appmod._env_bool("MDV_TEST_FLAG", default=True) is True
        assert appmod._env_bool("MDV_TEST_FLAG", default=False) is False

    @pytest.mark.parametrize("raw,expected", [
        ("1", True), ("true", True), ("YES", True), ("on", True),
        ("0", False), ("false", False), ("no", False), ("", False),
    ])
    def test_parses(self, raw, expected, monkeypatch):
        monkeypatch.setenv("MDV_TEST_FLAG", raw)
        assert appmod._env_bool("MDV_TEST_FLAG", default=True) is expected


class TestAssetVersion:
    def test_existing_file_is_mtime_int(self):
        # The app's own CSS exists; its token must be a positive integer string.
        token = appmod._asset_version("css/style.css")
        assert token.isdigit() and int(token) > 0

    def test_missing_file_is_zero(self):
        assert appmod._asset_version("does/not/exist.css") == "0"


# --------------------------------------------------------------------------- #
# Export error classification (no raw traceback leaks to the client)
# --------------------------------------------------------------------------- #
class TestExportErrorMessage:
    def _msg(self, exc):
        # _() needs an app/request context for the active locale.
        with appmod.app.test_request_context("/"):
            return appmod._export_error_message(exc)

    def test_missing_chrome_is_503(self):
        msg, status = self._msg(Exception("Executable doesn't exist at /usr/bin/chrome"))
        assert status == 503
        assert "Chrome" in msg

    def test_unsafe_port_is_500(self):
        msg, status = self._msg(Exception("net::ERR_UNSAFE_PORT"))
        assert status == 500

    def test_timeout_is_504(self):
        msg, status = self._msg(Exception("Timeout 30000ms exceeded"))
        assert status == 504

    def test_generic_is_500_and_hides_detail(self):
        msg, status = self._msg(Exception("some internal traceback detail xyz"))
        assert status == 500
        # The raw exception text must NOT be surfaced to the client.
        assert "xyz" not in msg


class TestRetryableExportError:
    @pytest.mark.parametrize("text", [
        "Timeout 30000ms exceeded", "net::ERR_CONNECTION_RESET",
        "navigation failed", "timed out waiting",
    ])
    def test_retryable(self, text):
        assert appmod._is_retryable_export_error(Exception(text)) is True

    @pytest.mark.parametrize("text", [
        "Executable doesn't exist", "net::ERR_UNSAFE_PORT",
    ])
    def test_not_retryable(self, text):
        assert appmod._is_retryable_export_error(Exception(text)) is False


# --------------------------------------------------------------------------- #
# _extract_doc_title (reads from disk via tmp tree)
# --------------------------------------------------------------------------- #
class TestExtractDocTitle:
    def test_frontmatter_title_wins(self, content_dir):
        p = content_dir / "doc.md"
        p.write_text("---\ntitle: From Frontmatter\n---\n# Heading\n")
        assert appmod._extract_doc_title(p, "doc.md") == "From Frontmatter"

    def test_first_heading_when_no_frontmatter(self, content_dir):
        p = content_dir / "doc.md"
        p.write_text("# The Heading\n\nbody\n")
        assert appmod._extract_doc_title(p, "doc.md") == "The Heading"

    def test_filename_stem_when_no_title_or_heading(self, content_dir):
        p = content_dir / "plain.md"
        p.write_text("just text, no heading\n")
        assert appmod._extract_doc_title(p, "plain.md") == "plain"

    def test_missing_file_returns_stem(self, content_dir):
        p = content_dir / "nope.md"
        assert appmod._extract_doc_title(p, "nope.md") == "nope"


# --------------------------------------------------------------------------- #
# render_markdown smoke test (under CONTENT_DIR)
# --------------------------------------------------------------------------- #
class TestRenderMarkdown:
    def test_returns_html_and_toc(self, content_dir):
        p = content_dir / "doc.md"
        p.write_text("# Title\n\nSome **bold** text.\n")
        html_out, toc = appmod.render_markdown(p)
        assert "<h1" in html_out
        assert "<strong>bold</strong>" in html_out
        assert isinstance(toc, str)

    def test_script_is_sanitized_out(self, content_dir):
        p = content_dir / "doc.md"
        p.write_text("# T\n\n<script>alert(1)</script>\n")
        html_out, _ = appmod.render_markdown(p)
        assert "<script>" not in html_out

    def test_github_style_sublist_indentation_nests(self, content_dir):
        # GitHub/CommonMark nest sublists by the parent marker's width (2-3
        # spaces); the ListIndentNormalize preprocessor maps that onto the
        # 4-space grid Python-Markdown needs. See ListIndentNormalizePreprocessor.
        p = content_dir / "doc.md"
        p.write_text(
            "5. Parent A\n"
            "   - 5.1 three-space child\n"
            "8. Parent B\n"
            "  - 8.1 two-space child\n"
        )
        html_out, _ = appmod.render_markdown(p)
        # Both under-indented sublists become real nested <ul>s, not folded text.
        assert html_out.count("<ul>") == 2
        assert "5.1 three-space child" in html_out
        assert "8.1 two-space child" in html_out

    def test_standard_four_space_nesting_preserved(self, content_dir):
        # The normalizer is a no-op on lists already on the 4-space grid.
        p = content_dir / "doc.md"
        p.write_text("- a\n    - b\n        - c\n")
        html_out, _ = appmod.render_markdown(p)
        assert html_out.count("<ul>") == 3  # three nesting levels

    def test_fenced_code_inside_blockquote(self, content_dir):
        # Python-Markdown's fenced_code never matches a `> `-prefixed fence, so
        # without BlockquoteFencePreprocessor the block collapses into an inline
        # <code> span. It should render as a highlighted block *inside* the quote.
        p = content_dir / "doc.md"
        p.write_text(
            "> antes\n"
            ">\n"
            "> ```bash\n"
            "> echo hola\n"
            "> ```\n"
            ">\n"
            "> despues\n"
        )
        html_out, _ = appmod.render_markdown(p)
        assert '<div class="codehilite">' in html_out
        # The fence must not have leaked out as a multi-line inline code span.
        assert "<code>bash" not in html_out
        # Block stays nested in the blockquote (no stray closing tag before it).
        body = html_out[html_out.index("<blockquote") : html_out.index("</blockquote>")]
        assert '<div class="codehilite">' in body
        assert "<p></p>" not in body  # no stray empty paragraph artifact

    def test_fenced_code_in_blockquote_after_prose_renders_block(self, content_dir):
        # The fence is the last block in the quote (no trailing blank line).
        p = content_dir / "doc.md"
        p.write_text("> Solución:\n>\n> ```sh\n> ls -la\n> ```\n")
        html_out, _ = appmod.render_markdown(p)
        assert '<div class="codehilite">' in html_out
        assert "<p></p>" not in html_out
