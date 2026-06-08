"""Route smoke tests — a behavioral oracle for the modularization refactor.

These exercise the Flask routes end-to-end (no Chrome / pandoc / git) so the
package split that follows can't silently change observable behavior. They are
deliberately broad and shallow: status codes, redirects, and a few content
markers, not deep rendering assertions (those live in test_app.py).

The `client` fixture rides on the `content_dir` fixture (conftest.py), which
points the module-global CONTENT_DIR at an isolated tmp dir and restores it
afterward — so none of these touch the user's real content or cache state
except through monkeypatched seams.
"""
from pathlib import Path

import pytest

import app as appmod


@pytest.fixture
def client(content_dir):
    (content_dir / "hello.md").write_text(
        "---\ntitle: Hello Doc\n---\n# Hello\n\nA paragraph.\n", encoding="utf-8"
    )
    (content_dir / "doc.rst").write_text("Title\n=====\n\nBody.\n", encoding="utf-8")
    sub = content_dir / "sub"
    sub.mkdir()
    (sub / "nested.md").write_text("# Nested\n", encoding="utf-8")
    appmod.app.config.update(TESTING=True)
    return appmod.app.test_client()


class TestIndex:
    def test_root_renders_and_lists_tree(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert b"hello.md" in r.data
        assert b"nested.md" in r.data

    def test_file_param_renders_markdown(self, client):
        r = client.get("/?file=hello.md")
        assert r.status_code == 200
        assert b"Hello" in r.data
        # frontmatter title flows into the page <title>
        assert b"Hello Doc" in r.data

    def test_rst_renders(self, client):
        r = client.get("/?file=doc.rst")
        assert r.status_code == 200
        assert b"Body" in r.data

    def test_stale_file_param_redirects_instead_of_404(self, client):
        r = client.get("/?file=does-not-exist.md")
        assert r.status_code == 302

    def test_pdf_toc_flag_renders_contents_page(self, client):
        r = client.get("/?file=hello.md&pdf_toc=1")
        assert r.status_code == 200
        assert b"pdf-toc-page" in r.data


class TestRaw:
    def test_raw_returns_source_text(self, client):
        r = client.get("/raw/hello.md")
        assert r.status_code == 200
        assert r.mimetype == "text/plain"
        assert b"# Hello" in r.data

    def test_raw_missing_is_404(self, client):
        assert client.get("/raw/nope.md").status_code == 404


class TestAsset:
    def test_asset_disallowed_extension_is_404(self, client):
        # .md is not in ALLOWED_ASSET_EXTENSIONS
        assert client.get("/asset/hello.md").status_code == 404

    def test_asset_missing_is_404(self, client):
        assert client.get("/asset/nope.png").status_code == 404

    def test_asset_traversal_is_blocked(self, client):
        assert client.get("/asset/../../etc/passwd").status_code == 404


class TestFavicon:
    def test_favicon_served(self, client):
        r = client.get("/favicon.ico")
        assert r.status_code == 200


class TestMtime:
    def test_mtime_returns_float(self, client):
        r = client.get("/api/mtime?file=hello.md")
        assert r.status_code == 200
        assert isinstance(r.get_json()["mtime"], float)

    def test_mtime_requires_file(self, client):
        assert client.get("/api/mtime").status_code == 400

    def test_mtime_unknown_file_is_404(self, client):
        assert client.get("/api/mtime?file=nope.md").status_code == 404


class TestSources:
    def test_sources_lists_active_dir(self, client, content_dir):
        r = client.get("/api/sources")
        assert r.status_code == 200
        assert r.get_json()["content_dir"] == str(content_dir)

    def test_source_switch_is_observed_by_index(self, client, tmp_path):
        """The crux of the CONTENT_DIR refactor: swapping the dir must be seen by
        a subsequent request. The content_dir fixture restores it afterward."""
        other = tmp_path / "other_root"
        other.mkdir()
        (other / "only-here.md").write_text("# Only Here\n", encoding="utf-8")
        appmod.set_content_dir(other)
        r = client.get("/")
        assert b"only-here.md" in r.data
        assert b"hello.md" not in r.data


class TestPresets:
    def test_presets_list_ok(self, client):
        r = client.get("/api/pdf-presets")
        assert r.status_code == 200
        assert isinstance(r.get_json()["presets"], list)


class TestDocxExport:
    def test_docx_missing_pandoc_returns_503(self, client, monkeypatch):
        monkeypatch.setattr(appmod.shutil, "which", lambda name: None)
        r = client.get("/export/docx?file=hello.md")
        assert r.status_code == 503
        assert "Pandoc" in r.get_json()["error"]

    def test_docx_unknown_file_is_404(self, client):
        assert client.get("/export/docx?file=nope.md").status_code == 404
