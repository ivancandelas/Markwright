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
import json
from pathlib import Path

import pytest

import app as appmod
from markwright import sources, state


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


class TestSearch:
    def test_search_finds_content_across_files(self, client):
        # "paragraph" only appears in hello.md's body.
        r = client.get("/api/search?q=paragraph")
        assert r.status_code == 200
        data = r.get_json()
        assert data["query"] == "paragraph"
        paths = [hit["path"] for hit in data["results"]]
        assert "hello.md" in paths
        hit = next(h for h in data["results"] if h["path"] == "hello.md")
        assert hit["count"] >= 1
        assert hit["matches"][0]["match_len"] == len("paragraph")

    def test_search_is_case_insensitive(self, client):
        r = client.get("/api/search?q=NESTED")
        paths = [hit["path"] for hit in r.get_json()["results"]]
        assert "sub/nested.md" in paths

    def test_search_short_query_returns_empty(self, client):
        r = client.get("/api/search?q=a")
        assert r.status_code == 200
        assert r.get_json()["results"] == []

    def test_search_missing_query_returns_empty(self, client):
        assert client.get("/api/search").get_json()["results"] == []


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


class TestSessionScopedSource:
    """The multi-client bug: CONTENT_DIR used to be one process global, so the
    last browser to switch sources switched them for *everyone* — browser A
    pressing F5 would suddenly be served browser B's tree. The active source now
    rides the signed session cookie; these pin that down.

    ``record_recent`` is stubbed out throughout: the recents list still lives in
    the real user cache, and switching sources for real would write to it.
    """

    @pytest.fixture
    def other_root(self, tmp_path_factory):
        # A *sibling* of the content_dir fixture's tree, not a child: nested under
        # it, its files would show up in the other session's scan and the
        # isolation assertions would pass or fail for the wrong reason.
        other = tmp_path_factory.mktemp("source_b")
        (other / "only-in-b.md").write_text("# Only In B\n", encoding="utf-8")
        return other

    @pytest.fixture(autouse=True)
    def _no_recents_writes(self, monkeypatch):
        monkeypatch.setattr(appmod, "record_recent", lambda entry: [])

    def switch(self, cli, path):
        r = cli.post("/api/source", json={"source": str(path)})
        assert r.status_code == 200, r.get_json()
        return r

    def test_switch_does_not_leak_to_another_session(self, client, content_dir, other_root):
        """The reported bug, verbatim: two browsers, two sources, one server."""
        browser_a = client
        browser_b = appmod.app.test_client()

        assert b"hello.md" in browser_a.get("/").data          # A starts on the default
        self.switch(browser_b, other_root)                     # B switches away

        reloaded = browser_a.get("/").data                     # A presses F5
        assert b"hello.md" in reloaded
        assert b"only-in-b.md" not in reloaded

    def test_switched_session_keeps_its_source_across_requests(self, client, other_root):
        self.switch(client, other_root)
        for _ in range(2):  # the override must persist, not just apply once
            body = client.get("/").data
            assert b"only-in-b.md" in body
            assert b"hello.md" not in body

    def test_switch_leaves_the_process_default_alone(self, client, content_dir, other_root):
        """A session override must not write through to the process default —
        that's what a fresh client (and the next server start) is served."""
        self.switch(client, other_root)
        assert state.CONTENT_DIR == Path(content_dir)
        assert b"hello.md" in appmod.app.test_client().get("/").data

    def test_api_sources_reports_the_callers_dir(self, client, other_root):
        self.switch(client, other_root)
        assert client.get("/api/sources").get_json()["content_dir"] == str(other_root)
        fresh = appmod.app.test_client()
        assert fresh.get("/api/sources").get_json()["content_dir"] == str(state.CONTENT_DIR)

    def test_session_survives_a_vanished_dir(self, client, other_root):
        """A remembered source can be deleted between requests; fall back to the
        process default rather than serving a directory that no longer exists."""
        self.switch(client, other_root)
        (other_root / "only-in-b.md").unlink()
        other_root.rmdir()
        r = client.get("/")
        assert r.status_code == 200
        assert b"hello.md" in r.data

    def test_asset_route_is_session_scoped(self, client, content_dir, other_root):
        """Subresources resolve through the session too — this is why the PDF
        exporter has to replay cookies rather than pass a URL token."""
        (content_dir / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (other_root / "b.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        assert client.get("/asset/a.png").status_code == 200
        assert client.get("/asset/b.png").status_code == 404
        self.switch(client, other_root)
        assert client.get("/asset/b.png").status_code == 200
        assert client.get("/asset/a.png").status_code == 404

    def test_principal_is_minted_once_and_reused(self, client):
        with client.session_transaction() as sess:
            sess.clear()
        client.get("/")
        with client.session_transaction() as sess:
            first = sess.get("sid")
        assert first
        client.get("/")
        with client.session_transaction() as sess:
            assert sess.get("sid") == first


class TestPerPrincipalRecents:
    """Recents used to be one shared list, so one client's source history (and
    its per-path last_file) was everyone's. Buckets are now keyed by principal,
    with a shared list kept as the boot-time and new-client fallback.

    These write recents for real (into conftest's isolated store), unlike
    TestSessionScopedSource which stubs record_recent out.
    """

    @pytest.fixture
    def store(self, isolated_sources_store):
        return isolated_sources_store

    @pytest.fixture
    def roots(self, tmp_path_factory):
        made = []
        for name in ("source_x", "source_y"):
            root = tmp_path_factory.mktemp(name)
            (root / f"{name}.md").write_text(f"# {name}\n", encoding="utf-8")
            made.append(root)
        return made

    def switch(self, cli, path):
        r = cli.post("/api/source", json={"source": str(path)})
        assert r.status_code == 200, r.get_json()
        return r.get_json()["recents"]

    def paths(self, cli):
        return [r["path"] for r in cli.get("/api/sources").get_json()["recents"]]

    def sid(self, cli):
        with cli.session_transaction() as sess:
            return sess["sid"]

    def test_history_does_not_leak_between_clients(self, client, roots):
        """Once two clients have diverged, neither sees the other's later moves."""
        x, y = roots
        browser_b = appmod.app.test_client()
        self.switch(client, x)
        self.switch(browser_b, y)
        assert self.paths(client) == [str(x)]        # B's switch is invisible to A
        assert self.paths(browser_b)[0] == str(y)    # B's own move leads its list

    def test_a_new_client_inherits_history_once_then_diverges(self, client, roots):
        """Deliberate, not incidental: a client with no bucket is seeded from the
        shared list, so B's first switch lands on top of A's history rather than
        wiping the picker. Inheritance happens exactly once — after that the
        buckets are independent (see the divergence tests). This is the seam to
        revisit at login: an authenticated user should not inherit another's
        history, whereas one person's second browser should."""
        x, y = roots
        self.switch(client, x)
        browser_b = appmod.app.test_client()
        assert self.switch(browser_b, y) == [
            {"label": y.name, "path": str(y), "kind": "local"},
            {"label": x.name, "path": str(x), "kind": "local"},
        ]

    def test_new_client_is_seeded_from_the_shared_list(self, client, roots):
        """A first-time browser opens on a populated picker, not an empty one —
        which is what the shared list exists for."""
        x, _ = roots
        self.switch(client, x)
        assert str(x) in self.paths(appmod.app.test_client())

    def test_seeding_is_a_copy_not_an_alias(self, client, roots):
        """A seeded client must not be writing into the shared list by reference."""
        x, y = roots
        self.switch(client, x)
        fresh = appmod.app.test_client()
        self.paths(fresh)          # seed it
        self.switch(fresh, y)      # then diverge
        assert self.paths(client) == [str(x)]

    def test_removal_is_per_client(self, client, roots):
        x, y = roots
        browser_b = appmod.app.test_client()
        self.switch(client, x)
        self.switch(browser_b, y)
        self.switch(browser_b, x)  # B now knows both
        client.post("/api/source/remove", json={"path": str(x)})
        assert str(x) in self.paths(browser_b)

    def test_last_file_is_per_client(self, client, content_dir, roots):
        """Two clients on the same source, reading different docs, must not
        overwrite each other's resume point."""
        (content_dir / "second.md").write_text("# Second\n", encoding="utf-8")
        browser_b = appmod.app.test_client()
        for cli in (client, browser_b):
            self.switch(cli, content_dir)
        client.get("/?file=hello.md")
        browser_b.get("/?file=second.md")
        assert b"<h1 id=\"hello\">Hello</h1>" in client.get("/").data
        assert b"<h1 id=\"second\">Second</h1>" in browser_b.get("/").data

    def test_a_passive_client_is_not_dragged_by_an_active_one(self, client, content_dir, store):
        """Regression, found in a live two-browser run. Seeding used to happen
        lazily on first write, so a client that only ever *read* never
        materialized a bucket and kept resolving through the shared list — its
        resume point silently followed whatever the other client last opened.
        The passive client below writes *nothing*: its whole state comes from the
        seed, which is precisely the case lazy seeding never materialized."""
        (content_dir / "second.md").write_text("# Second\n", encoding="utf-8")
        active = client
        self.switch(active, content_dir)
        active.get("/?file=hello.md")          # shared list now resumes at hello.md

        passive = appmod.app.test_client()     # minted from exactly that state
        assert b"<h1 id=\"hello\">Hello</h1>" in passive.get("/").data

        active.get("/?file=second.md")         # the active client moves on
        assert b"<h1 id=\"hello\">Hello</h1>" in passive.get("/").data

    def test_every_client_owns_a_bucket_from_its_first_request(self, client, store):
        client.get("/")
        buckets = json.loads(store.read_text(encoding="utf-8"))["principals"]
        assert self.sid(client) in buckets

    def test_startup_resume_reads_the_shared_list(self, client, roots):
        """resolve_startup_dir runs with no request and no principal, so it must
        still find something — the shared list mirrors the latest writer."""
        x, _ = roots
        self.switch(client, x)
        assert sources.resolve_startup_dir(None) == str(x)

    def test_all_referenced_paths_unions_every_bucket(self, client, roots):
        x, y = roots
        browser_b = appmod.app.test_client()
        self.switch(client, x)
        self.switch(browser_b, y)
        assert {str(x), str(y)} <= sources.all_referenced_paths()

    def test_principal_buckets_are_capped(self, client, roots, monkeypatch):
        monkeypatch.setattr(sources, "PRINCIPALS_LIMIT", 3)
        x, _ = roots
        for _ in range(6):
            self.switch(appmod.app.test_client(), x)
        saved = json.loads((sources.SOURCES_FILE).read_text(encoding="utf-8"))
        assert len(saved["principals"]) <= 3
        assert saved["recents"], "the shared list must survive eviction"

    def test_legacy_file_without_principals_still_loads(self, store, client):
        store.write_text(json.dumps({"recents": [{"path": "/old", "label": "old"}]}),
                         encoding="utf-8")
        assert "/old" in self.paths(client)  # seeded from the pre-buckets shape


class TestCloneDeletionGuard:
    """Removing a git source deletes its checkout. With per-client recents that
    became a cross-client hazard: one client's removal would rmtree a clone
    another client still has listed (or is reading right now)."""

    @pytest.fixture
    def repos(self, monkeypatch, tmp_path_factory):
        cache = tmp_path_factory.mktemp("cache")
        repos_dir = cache / "repos"
        (repos_dir / "shared-repo").mkdir(parents=True)
        (repos_dir / "shared-repo" / "readme.md").write_text("# Repo\n", encoding="utf-8")
        monkeypatch.setattr(sources, "CACHE_DIR", cache)
        monkeypatch.setattr(sources, "SOURCES_FILE", cache / "sources.json")
        monkeypatch.setattr(sources, "REPOS_DIR", repos_dir)
        monkeypatch.setattr(appmod, "REPOS_DIR", repos_dir)
        return repos_dir / "shared-repo"

    def seed(self, clients, clone):
        """Give each client a recents bucket holding the same git clone."""
        entry = {"label": "shared-repo", "path": str(clone), "kind": "git",
                 "url": "https://example.invalid/shared-repo.git"}
        buckets = {}
        for cli in clients:
            cli.get("/")  # mint the principal
            with cli.session_transaction() as sess:
                buckets[sess["sid"]] = {"recents": [dict(entry)], "updated": 1.0}
        sources.SOURCES_FILE.write_text(
            json.dumps({"recents": [dict(entry)], "principals": buckets}), encoding="utf-8")
        return entry

    def test_clone_survives_while_another_client_references_it(self, client, repos):
        browser_b = appmod.app.test_client()
        entry = self.seed([client, browser_b], repos)
        r = client.post("/api/source/remove", json={"path": entry["path"]})
        assert r.status_code == 200
        assert repos.is_dir(), "B still lists this clone — it must not be deleted"

    def test_clone_is_deleted_once_nobody_references_it(self, client, repos):
        entry = self.seed([client], repos)
        r = client.post("/api/source/remove", json={"path": entry["path"]})
        assert r.status_code == 200
        assert not repos.exists()


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
