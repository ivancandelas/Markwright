# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
.venv/bin/python app.py                       # scan current directory, serve on 127.0.0.1:5000
.venv/bin/python app.py /path/to/folder       # scan another folder
.venv/bin/python app.py . --host 0.0.0.0 --port 8000
```

`app.run(host, port, debug=<env>, threaded=True)`. **`threaded=True` is required**: PDF export navigates a headless Chrome back to this same server, so it must handle a second request while the export request is still open (see PDF export). **`debug` defaults on** (auto-reload + interactive debugger) but follows `MARKWRIGHT_DEBUG` (`0`/`false` to disable); since the Werkzeug debugger allows RCE, `__main__` **force-disables it whenever `--host` is not loopback** (127.0.0.1/localhost/::1), so `--host 0.0.0.0` can't expose it. No lint config or build step.

Static assets are **cache-busted**: the `asset_url(filename)` helper (`inject_asset_helper` context processor) appends `?v=<mtime>` so a CSS/JS edit invalidates the browser cache. The `<link rel="icon">` and a `/favicon.ico` route both serve `static/favicon.svg` (no per-load favicon 404).

## Tests

Tests live in `tests/` (pytest, config in `pytest.ini`). Install with `uv pip install -r requirements-dev.txt`, run with `.venv/bin/python -m pytest`. Two files:

- **`tests/test_app.py`** — the **pure helpers**: frontmatter extraction, token resolvers (`_apply_datetime_tokens`, `_apply_frontmatter_tokens`, `_resolve_cover_tokens`, `_parse_fallback_values`, `_fm_scalar`), filename/Content-Disposition (`_resolve_export_filename`, `_content_disposition`), `safe_path` traversal guard, `sanitize_html`, `build_tree`/`scan_markdown_files`, margins, `_hf_markdown`, `_extract_doc_title`, and a `render_markdown` smoke test. These now live in `markwright/` but tests reference them as `appmod.<helper>` via `app.py`'s re-export surface, so they don't care which module a helper landed in.
- **`tests/test_routes.py`** — a broad/shallow **route oracle** (Flask test client): status codes, redirects, content markers for `/`, `/raw`, `/asset`, `/favicon.ico`, `/api/mtime`, `/api/sources`, `/api/pdf-presets`, runtime source-switch, and the docx-missing-pandoc 503 path. Exercises wiring without external binaries. The full Chrome/pandoc pipelines (`_render_pdf`/`_render_docx`) need a live server + binaries and are verified manually, not in CI.

The `content_dir` fixture (`tests/conftest.py`) swaps `markwright.state.CONTENT_DIR` to a `tmp_path` and restores it after.

Install deps with `uv pip install -r requirements.txt` (preferred). The repo uses a `uv`-managed venv with **no `pip` inside it** — use `uv pip ...`, not `.venv/bin/pip`. Runtime stack is pinned: Flask 3.0.3, Markdown 3.6, bleach 6.1.0, Pygments 2.18.0, docutils 0.21.2 (RST), PyYAML 6.0.2, emoji 2.15.0 (`:shortcode:` → glyph; soft-imported), Flask-Babel 4.0.0 (i18n), playwright 1.60.0 (PDF; drives system Chrome via `channel="chrome"`, no Chromium download — but a Chrome/Chromium install is required for export). DOCX export shells out to the system **`pandoc`** binary (not a pip dep; `/export/docx` → 503 if missing).

## Architecture

Flask app whose web layer (the `Flask` object, all `@app.route` handlers, Babel/i18n wiring, context processors, template filters, CLI `__main__`) lives in **`app.py`**; supporting logic is extracted into the **`markwright/` package**. Tests still `import app as appmod`; `app.py` re-imports the moved helpers so `appmod.<helper>` keeps resolving (a deliberate re-export surface).

`markwright/` modules:
- **`state.py`** — the single mutable global `CONTENT_DIR`. Read it **only** as `state.CONTENT_DIR` (attribute access) so the runtime source-swap is visible across modules; never `from state import CONTENT_DIR` (freezes a stale binding).
- **`config.py`** — static constants: cache/preset layout, asset/logo allowlists, git-URL prefixes, `IGNORED_DIRS`.
- **`links.py`** — `is_local_reference` / `resolve_reference` (local-ref gate + resolver, shared by both rewriters).
- **`frontmatter.py`** — `extract_frontmatter` + the GitHub-style nested-table panel.
- **`markdown_ext.py`** — all custom Python-Markdown extensions (priorities below) + `MERMAID_BLOCK_RE`.
- **`render.py`** — `sanitize_html` (the bleach allowlist), `render_markdown`, `render_rst`, `rewrite_local_links`.
- **`files.py`** — `safe_path` (traversal guard), `scan_markdown_files`, `build_tree`, `collect_tree_metadata`.
- **`tasks.py`** — `toggle_task_marker` (flips the Nth `[ ]`↔`[x]` task-list checkbox in *source* markdown, skipping fenced code; backs `/api/toggle-task`).
- **`sources.py`** — runtime source switching: `set_content_dir`, git clone/pull, the `sources.json` recents + last-file memory.
- **`presets.py`** — PDF-preset storage + logo/cover-image cleanup.
- **`export.py`** — the entire PDF + DOCX pipeline and its shared token/header/footer/cover helpers + preset serialization (no routes; the `/export/*` and `/api/pdf-presets*` handlers in `app.py` call into it).

Routes (all in `app.py`): `/` renders the viewer; `/asset/<path>` serves local images + non-markdown files; `/raw/<path>` returns raw markdown as `text/plain` (source-view toggle); `/api/source*` drive the source picker; `/api/save` + `/api/file/*` + `/api/upload-asset` + `/api/render` back the editor (local sources only); `/api/toggle-task` persists a single task-list checkbox toggle; `/export/pdf` and `/export/docx` (via pandoc); `/api/pdf-presets*` manage presets. Templates in `templates/index.html`; client behavior (theme/font/width/font-size selectors, sidebar collapse + floating re-open, bidirectional TOC↔content scroll sync, TOC filter box, tree collapse + sort, search filter, scroll persistence, mermaid overlay, copy buttons, export popover + preset manager modal) in `static/js/app.js`.

### Request flow for `/`

1. `scan_markdown_files()` walks `CONTENT_DIR` recursively, skipping `IGNORED_DIRS` (`.git`, `.venv`, `__pycache__`, etc.).
2. `build_tree()` turns the flat path list into a nested dict the Jinja `render_tree` macro recurses over.
3. `?file=` picks the current doc; `safe_path()` validates it stays under `CONTENT_DIR`.
4. `render_markdown()` runs Python-Markdown with `extra`, `tables`, `fenced_code`, `codehilite`, `sane_lists`, `toc`, plus custom `LocalPathExtension`.
5. Output is sanitized via `bleach.clean()` against an explicit allowlist before injection with `|safe`.

### Local link rewriting

`LocalPathTreeprocessor` rewrites relative `<img src>` and `<a href>` after parse but before sanitization:

- A reference is "local" iff `is_local_reference()` says so — i.e. not `http(s)://`, `mailto:`, `tel:`, `#`, `data:`, or absolute `/`.
- Relative paths resolve against the **current file's directory** (not `CONTENT_DIR`) via `resolve_reference()`, preserving any `#fragment`.
- `.md` targets become `url_for("index", file=...)` (open in-app); everything else routes to `/asset/...`.
- `/asset/` only serves suffixes in `ALLOWED_ASSET_EXTENSIONS` (images + `.pdf`).

### File discovery and per-format rendering

`scan_markdown_files()` globs `*.md`, `*.rst`, and `[Rr][Ee][Aa][Dd][Mm][Ee]*`, then dedupes via a set so extensionless `README` files surface. `index()` dispatches by suffix: `.rst` → `render_rst()` (docutils `publish_parts`, html5 writer, `doctitle_xform=False`, `raw_enabled=False`, `file_insertion_enabled=False`, `halt_level=5`); else → `render_markdown()`. Both sanitize through the shared `sanitize_html()` (single source of truth for allowed tags/attributes).

Markdown rewrites local refs via `LocalPathTreeprocessor`; RST does it post-hoc via `rewrite_local_links()` (a regex over `href=`/`src=` in the docutils HTML). Both recognise `.md` *and* `.rst` targets so cross-format navigation stays in-app.

### Mermaid blocks

` ```mermaid ` blocks are intercepted by `MermaidPreprocessor` before `fenced_code` and stashed as `<pre class="mermaid">…</pre>` via `md.htmlStash`. The client ES module in `templates/index.html` loads `mermaid@11` from CDN, captures `textContent` into `dataset.source`, then renders; `static/js/app.js` re-runs it with the matching theme on dark-mode toggle.

Priority gotcha: `MermaidPreprocessor` is at priority **27** — *above* `fenced_code_block` (25) so it isn't pygments-highlighted, but *below* `normalize_whitespace` (30), which strips the STX/ETX control chars wrapping every htmlStash placeholder. Any future preprocessor stashing raw HTML needs that same 25–30 window.

### Fenced code inside blockquotes

Python-Markdown's `fenced_code` is a **preprocessor** that only matches a fence flush-left (≤3 spaces); inside a blockquote every line carries a `> ` prefix, so the fence is never recognized and the ` ``` ` collapses into a multi-line **inline `<code>` span** (the code block silently vanishes). `BlockquoteFencePreprocessor` (priority **26**, in the 25–30 stash window) closes that gap: it finds a fence whose opener *and* closer are both blockquoted (`BLOCKQUOTE_PREFIX_RE` strips one-or-more `> ` levels, so nested `> >` quotes work too), strips the prefix, renders the inner block with a throwaway `Markdown(fenced_code+codehilite)` using the **same `_CODEHILITE_CONFIG`** (identical highlighting to a top-level fence), stashes the HTML, and re-emits the placeholder **still quoted** so it stays inside the `<blockquote>`. A `mermaid` info string is special-cased to the same `<pre class="mermaid">` stash as `MermaidPreprocessor`. It emits a blank quoted line *before* the placeholder (separates it from preceding prose) and one *after* only when quoted text follows directly — otherwise a stray empty `<p></p>` appears. Lazy continuation doesn't apply to code, so any block line lacking the `> ` prefix makes it bail (leaving the text untouched). Note: a fence with **no** `>` prefix sandwiched between quoted lines still splits the blockquote — that's standard GFM, not a bug.

### YAML frontmatter

`extract_frontmatter()` peels a leading `---\n…\n---` block off `.md` sources before the converter. The regex tolerates a doubled `---\n---\n` opener (the wired DESIGN.md ships with one).

YAML is parsed with `yaml.safe_load` and emitted as nested tables matching GitHub (`_yaml_value_to_html`):

- top-level dict → vertical 2-column `fm-vertical` table (`<th>key</th><td>value</td>` rows)
- nested dict of scalars → horizontal 2-row `fm-horizontal` table
- nested dict of dicts → stack of `<div class="fm-section">` blocks, each with a centered super-header (`fm-section-title`) above its inner table
- list of scalars → comma-joined; list with structured items → `<ul>`

On `safe_load` failure or non-dict, falls back to a Pygments-highlighted code block. The panel is `<details class="frontmatter-panel" open>`; `open` is in the bleach allowlist so the default-expanded state survives. RST has no equivalent (docutils handles its own field-list metadata).

### GFM extras (alerts, strikethrough, hard breaks, table-after-prose, list-after-prose, task lists, emoji)

Registered in `render_markdown()` alongside the standard extensions:

- `GitHubAlertExtension` — treeprocessor at priority **19** (after inline at 20 so the `[!TYPE]` marker is still in `first_p.text`). Rewrites blockquotes starting with `[!NOTE|TIP|IMPORTANT|WARNING|CAUTION]` into `<blockquote class="markdown-alert markdown-alert-<type>">` with an injected `<p class="markdown-alert-title">`.
- `StrikethroughExtension` — inline pattern `~~text~~` → `<del>` at priority 175.
- `GFMHardBreakExtension` — preprocessor at priority **23** (below `fenced_code_block` 25). Converts trailing backslashes to two trailing spaces. Skips indented lines.
- `GFMTableBreakExtension` — preprocessor at priority **22**. GFM allows no blank line above a table header; when a separator row (`| --- | --- |`) follows prose directly, inject a blank line above the header. Skips indented lines.
- `GFMListBreakExtension` — preprocessor at priority **21.5**. Python-Markdown never lets a list interrupt a paragraph, so a list written flush against the preceding prose (no blank line) is swallowed into that paragraph — and for an ordered list the first item vanishes, renumbering every visible item down by one. CommonMark/GFM *do* let a list interrupt a paragraph: any bullet, or an ordered list whose first marker is `1`. This injects a blank line above such a **flush-left** marker when it directly follows a non-blank, non-list prose line (`_can_interrupt` gates ordered lists to start-at-1; bullets always qualify). Skips indented lines and never splits a marker already following another list item (keeps contiguous lists intact).
- `ListIndentNormalizeExtension` — preprocessor at priority **24** (just below `fenced_code_block` 25 so fenced blocks are already stashed). Python-Markdown only nests a sublist indented a full 4 spaces; GitHub/CommonMark nest by the *parent marker's* width (2 spaces under `- `, 3 under `5. `), which plain Python-Markdown folds into the parent item's text. A fixed-width fix (e.g. `mdx_truly_sane_lists`) can't satisfy both 2/3-space and standard 4-space at once, so `ListIndentNormalizePreprocessor` uses a **relative-step** model: each increase in a list marker's indent opens one level (re-emitted at `level*4` spaces), each decrease closes levels — handling 2-/3-/4-space uniformly and **idempotent on already-4-space lists** (so it can't regress them). Only list-*marker* lines are rewritten; a flush-left non-list, non-blank line (heading/paragraph/`hr`, but not a `\x02…` stash placeholder) resets the level stack.
- `TaskListExtension` — treeprocessor at priority **18** (after inline at 20; the `[ ]` marker isn't a link so it stays plain text at the start of the item). Each `<li>` whose leading text is `[ ]`/`[x]`/`[X]` (tight list → on `li.text`; loose list → on the first `<p>` child's text) gets the marker stripped and an `<input type="checkbox" class="task-list-item-checkbox" data-task-index="N">` (`checked` when `[x]`) prepended; the `<li>` gains a `task-list-item` class (CSS drops its bullet). `data-task-index` is a **document-order counter** so the client can map a clicked box back to the Nth task marker in the *source* via `/api/toggle-task` — `root.iter("li")` visits items in the same order `markwright.tasks.toggle_task_marker` scans source lines (which skips fenced code, where `- [ ]` isn't a checkbox), so the indices align. `data-task-index` is in the bleach allowlist for `input`. (RST has no task-list rendering.)
- `EmojiExtension` — treeprocessor at priority **11** (after inline so `<code>` exists as elements and is skipped). Runs `emoji.emojize(..., language="alias")` on text/tail nodes outside `<code>`/`<pre>`. No-ops if `emoji` isn't importable.

Both indented-line skips matter: any preprocessor mutating raw text should bail on lines starting with 4 spaces or a tab, or it corrupts indented code blocks.

### Interactive task-list checkboxes

Rendered checkboxes (see `TaskListExtension`) are **interactive only on a writable source** (`editable` / `is_local_source()`; a git clone shows them `disabled`). `setupTaskCheckboxes()` in `static/js/app.js` wires the main `.markdown-body` (not the editor preview): clicking toggles the box and, with **auto-save on**, POSTs `{file, index, checked}` to `/api/toggle-task`; with auto-save **off** the toggle is visual-only (lost on reload). The preference lives in `localStorage` (`markwright-task-autosave`, default on) and surfaces as the header `#task-autosave-toggle` button, which is `hidden` until a doc actually has checkboxes.

`POST /api/toggle-task` (local-only, same scan-set + `safe_path` guards as `/api/save`; rejects `.rst`) calls `toggle_task_marker(source, index, checked)` to flip the Nth `[ ]`↔`[x]` in the on-disk source and rewrites the file — it does **not** re-render (the client already toggled optimistically). Bad `index`/`checked` → 400, out-of-range index → 409, non-local source → 403. On success it returns the new `mtime`, which the client feeds to `window.__mwSetMtimeBaseline()` so the live-reload poller doesn't reload the page on the write it just made. A failed save reverts the optimistic toggle.

### GitHub-style HTML+markdown mixing

`MarkdownInHtmlAutoAttrExtension` runs at priority **24** (after `fenced_code_block` 25 — fenced blocks already stashed — and before `html_block` 20). It auto-injects `markdown="…"` on block-level HTML opening tags so `md_in_html` (in `extra`) processes inner markdown. Mode is **tag-dependent** via `HTML_BLOCK_TAG_MODES`: `details`/`summary`/`section`/`article`/`aside`/`blockquote` get `"1"` (block); `div`/`header`/`footer`/`center`/etc. get `"span"` (inline only) so 4-space-indented inline HTML inside a centered `<div>` isn't reinterpreted as a code block. Lines starting with 4 spaces or a tab are skipped. The bleach allowlist includes `align` on `*` and `img` so `<div align="center">` survives.

### Runtime source switching

`CONTENT_DIR` can be swapped at runtime via `POST /api/source` (`{"source": "..."}`):

- A local path is resolved + validated by `set_content_dir()` (raises `ValueError`, not `SystemExit`, so the handler returns 400 cleanly).
- A git URL — detected by `is_git_url()` (scheme prefix or `.git` suffix) — is cloned/pulled into `CACHE_DIR/repos/<safe-name>` via `subprocess.run(["git", ...])` with depth=1 and a timeout, then used as the new `CONTENT_DIR`.
- Every successful swap is recorded in `CACHE_DIR/sources.json` (`record_recent()` dedupes by path, inserts at index 0, caps at `RECENTS_LIMIT`). The launch dir is seeded on startup so the picker is never empty.
- **Startup resumes the last source.** `resolve_startup_dir()` returns an explicit CLI `directory` when given; otherwise restores `load_recents()[0]` (most recent, since `record_recent` prepends), skipping paths that no longer exist, finally falling back to `.`. This is why `directory` defaults to `None`, not `"."` — a bare `python app.py` must be distinguishable from an explicit `.` so it resumes instead of snapping back to cwd (which would 404 the previously-open `?file=`).

`CACHE_DIR` defaults to `~/.cache/markwright/` but follows `XDG_CACHE_HOME`.

Cache cleanup: `prune_repo_cache()` runs at startup and deletes any `REPOS_DIR` subdir not referenced by `load_recents()` paths (and never `CONTENT_DIR`). `POST /api/source/remove {"path": "..."}` removes one recent; if the entry is `kind: git` *and* the resolved path is under `REPOS_DIR`, the clone is `shutil.rmtree`-d. Two guards: removing the active `CONTENT_DIR` → **400**, and `kind: local` entries never trigger filesystem deletion (so pointing at a working tree can't `rmtree` it via the UI).

### PDF export and presets

`GET /export/pdf?file=…&header=…&footer=…&preset=…` produces a real downloadable PDF. `_render_pdf()` launches **system Chrome** via Playwright (`channel="chrome"`), `goto`s the live in-app URL from `request.url_root` (so client JS incl. Mermaid runs) with **`wait_until="load"`**, then waits until every `pre.mermaid` has `data-processed="true"` (tolerant of timeout / no diagrams) as the **deterministic readiness signal**, then calls Chrome's `Page.printToPDF`. Output uses the print stylesheet — `@media print` hides sidebar/header/TOC, capturing only `.markdown-body`. (`wait_until` is **`load`, not `networkidle`** — the live-reload poll hits `/api/mtime` every second so the network rarely idles; the mermaid-processed wait is the real gate.)

**Error handling never leaks a traceback.** `export_pdf()` calls `_render_pdf` in a 2-attempt loop: a *retryable* failure (`_is_retryable_export_error` — timeouts/`ERR_`/navigation) gets one retry; a hard failure (no Chrome, `ERR_UNSAFE_PORT`) bails. On final failure the exception is `logging.exception`-logged and `_export_error_message(exc)` returns a clean, translated message + status (no Chrome → 503, unsafe port → 500, timeout → 504, else 500). `export_docx()` does the same.

Two non-obvious requirements:

- **`threaded=True`**: the export request makes Chrome fetch the page from this same server; single-threaded would deadlock.
- **`--explicitly-allowed-ports=<port>`** launch arg: Chrome refuses "unsafe" ports (e.g. 5060) with `ERR_UNSAFE_PORT`. The port is parsed from the URL and whitelisted so export works on any `--port`.

**Header/footer are 3-column bands** (left/center/right). The request sends `header_left`/`header_center`/`header_right` and `footer_*`; `_band_parts()` resolves each column via a fallback cascade (query param → preset's stored column → a legacy single `?header=`/`?footer=` mapped to center). `_hf_band()` builds a flex row where the **center column is wider (`flex:2` vs `flex:1`)** and, in headers, larger (`font-size:11px`, normal weight — *not* semibold, so inline `**bold**` stays heavier; the title slot's prominence comes from size, not weight). `_header_template()` wraps `_hf_band(..., header=True)` and stacks the preset logo above its column at `logoPosition`; `_footer_template()` wraps `_hf_band(..., header=False)` with no logo. Chrome renders header/footer at font-size 0 unless the template sets its own size, so the band always emits an explicit `font-size`.

Header/footer text supports `{page} {total} {url}` (Chrome live spans), `{title} {filename} {document_name}`, date/time tokens `{date} {time} {datetime}`, any `{frontmatter-key}` (e.g. `{author}`, `{version}`), and `{br}` (→ literal `<br>`, the only raw-HTML escape hatch — emitted right after `html.escape` so a typed `<br>` stays escaped but the token produces a real break; placed before token resolution so a frontmatter key named `br` can't shadow it). A tiny inline-markdown subset — `**bold**`, `*italic*`, `~~strike~~` (`_hf_markdown`, `_HF_MD_PATTERNS`) — is applied right after `{br}`, *before* token substitution, so only the user's literal text is styled and token-inserted values stay literal. `_hf_inner(text, literals, now, frontmatter)` resolves in order: HTML-escape literal → date/time from `now` (`_apply_datetime_tokens`) → server-side `literals` (`{title}`, `{filename}`, `{document_name}`) → `{frontmatter-key}` (`_apply_frontmatter_tokens(..., leave_unknown=True)`, so unmatched tokens stay for Chrome) → Chrome's live spans in `_PDF_HF_TOKENS`. **`{title}` is resolved server-side**: `_extract_doc_title()` returns frontmatter `title:`, else first ATX/setext heading, else filename stem. `index()` feeds this same value to the page `<title>` (as `doc_title`), so it doubles as the PDF's embedded document-title metadata. `{filename}`/`{document_name}` are the on-disk name.

**Date/time tokens are server-side and shared with the cover.** `{date}`/`{time}`/`{datetime}` take an optional inline `strftime` (`{date:%d/%m/%Y}`); without one they default to `%Y-%m-%d` / `%H:%M` / `%Y-%m-%d %H:%M` (`_DATETIME_DEFAULT_FMT`; an invalid format falls back rather than 500s). `export_pdf` builds **one** `datetime.now()` and **one** `_doc_frontmatter()` dict and threads both into header band, footer band *and* cover, so all three read identically. `{date}` was removed from `_PDF_HF_TOKENS` because Chrome rendered it locale-formatted while the cover rendered ISO; resolving server-side fixes the mismatch. (Only `{page}`/`{total}`/`{url}` remain Chrome-filled.)

**Fallback placeholder values (`useFallback` + `fallbackValues`).** A preset can supply defaults for `{frontmatter-key}` tokens when a doc lacks frontmatter (or a key). `fallbackValues` is a `key: value`-per-line block (`_parse_fallback_values()`); when `useFallback` is on, `export_pdf` merges it *under* the real frontmatter (`{**fallback, **frontmatter}`), so the doc's own values win and fallbacks only fill gaps (per-key, not all-or-nothing). Reserved tokens (`{date}`/`{time}`/`{datetime}`, `{page}`/`{total}`/`{url}`, `{title}`/`{filename}`/`{document_name}`) resolve on their own paths and are unaffected.

**Presets** (per-project/client letterheads) live in `CACHE_DIR/pdf_presets.json` (`load_presets()`/`save_presets()`); logos in `CACHE_DIR/pdf_logos/<preset-id>.<ext>`. Each holds name, the 6 column fields (`headerLeft`/`headerCenter`/`headerRight`, `footerLeft`/`footerCenter`/`footerRight`), logo + `logoPosition` (left/center/right), `pageSize` (validated against `ALLOWED_PAGE_SIZES` = keys of `_PAGE_PX`: A4/Letter/Legal/Tabloid — Tabloid landscape gives ledger), `orientation`, `margins` (mm), `fontScale` (body font %, clamped 50–200), `fontFamily` (one of `PDF_FONTS`' keys — a mirror of the screen `FONTS` list, `""` = system default; `_render_pdf` loads the matching Google webfont headless and applies the stack to `.markdown-body` so code/pre keep monospace), `includeToc` / `includeFrontmatter`, `useFallback` + `fallbackValues`, and cover fields (`coverEnabled`, `coverTitle`, `coverSubtitle`, `coverMeta`, `coverFooter`, `coverImageSource`, `coverImage`, `blankAfterCover`). Pre-3-column presets with a single `header`/`footer` string are migrated **on read** in `_serialize_preset()` (old value → center column); the save handler drops the legacy keys. When a preset is passed to `/export/pdf`, its logo is embedded as a base64 `data:` URI in the header band, and page size/orientation/margins drive the `Page.pdf` call.

`fontScale` scales the **body**, not header/footer. The print stylesheet sizes `.markdown-body` as `calc(11pt * var(--pdf-font-scale, 1))`; `_render_pdf` injects `:root{--pdf-font-scale:<fontScale/100>}` via `page.add_style_tag` before printing. Children size in em off `.markdown-body`, so one variable rescales the whole body. (The **screen** `A−/A+` control uses a *different* variable `--content-font-size`; the print rule hardcodes its own 11pt base, so PDF scaling must go through `--pdf-font-scale`.)

**Contents page (`includeToc`, default off).** Prepends a clickable "Contents" page (no printed page numbers — Chrome's `printToPDF` lacks `target-counter()`). Flag is per-preset *and* per-export: `export_pdf()` resolves it from the `include_toc` query param (popover checkbox always sends `0`/`1`, so it wins) else `preset["includeToc"]`. When on it appends `pdf_toc=1` to the in-app URL; `index()` renders a `<nav class="pdf-toc-page">` (the sidebar's `md.toc` HTML) at the top of `.markdown-body` *only* when `pdf_toc=1`. Hierarchical numbers (`1.1.2`) come from CSS `counters(pdftoc, ".")` on the nested `<ul>`; `@media print` gives `break-after: page`. RST has no `toc`, so the page is skipped.

**Cover page (`coverEnabled`, default off) — preset-only.** Unlike the contents page, the cover is built **server-side in `export_pdf()`** because its content lives in the preset and needs logo/image data URIs + token resolution. `_build_cover_html()` assembles a centered `<section class="pdf-cover">` from `coverTitle` (default `{title}`), `coverSubtitle`, `coverMeta` (one `Label: value` per line), `coverFooter`, plus one cover image — all optional; returns `""` when nothing is set. **Image source is a choice** (`coverImageSource`): `"custom"` uses uploaded `coverImage`, `"logo"` reuses the preset logo, `"none"`/missing shows nothing (`_cover_image_uri()`; pre-`coverImageSource` presets fall back to custom-if-uploaded, else legacy `coverLogo` → logo). **Tokens** via `_resolve_cover_tokens()`: `_apply_datetime_tokens`, then `{title}`/`{filename}`/`{document_name}` literals, then `_apply_frontmatter_tokens(..., leave_unknown=False)` for other `{key}` (case-insensitive) — unknown keys resolve to `""`, so a metadata row coming up empty is **dropped**. The cover (and an optional trailing `<div class="pdf-blank-page">` when `blankAfterCover`) is passed to `_render_pdf` as `prepend_html` and injected at the top of `.markdown-body` via `page.evaluate` *after* margins are final — `_render_pdf` injects `--pdf-page-content-height` (page height − final top/bottom margins, in CSS px) so cover/blank fill exactly one printable page and the footer pins to bottom. `@media print` gives both `break-after: page`. Cover images store as `<id>-cover.<ext>` in `LOGOS_DIR` (same validation/`MAX_LOGO_BYTES`), served by `GET /api/pdf-presets/<id>/cover-image`, removed by `delete_cover_files()`. Resolution: `include_cover` query param wins, else `preset["coverEnabled"]`; the popover checkbox is disabled without a selected preset.

**Author page breaks (`PageBreakExtension`).** A standalone `\newpage`, `\pagebreak`, or `<!-- pagebreak -->` becomes a stashed `<div class="page-break">`. Preprocessor at priority **21** — below `fenced_code_block` (25) so a marker in a code fence stays literal, and below `normalize_whitespace` (30) so the placeholder survives (the regex's `[ ]{0,3}` lead also ignores indented code). On screen it's a faint labeled "Page break" divider; `@media print` turns it into `break-after: page` and hides the label. `div`/`class` are already in the allowlist.

CRUD routes: `GET /api/pdf-presets` (lists via `_serialize_preset()` — exposes a `hasLogo` flag, never the filename), `POST /api/pdf-presets` (multipart create/update; validates non-empty name, logo extension against `ALLOWED_LOGO_EXTENSIONS`, `MAX_LOGO_BYTES`), `POST /api/pdf-presets/delete` (removes preset + logo + cover via `delete_logo_files()`/`delete_cover_files()`), `GET /api/pdf-presets/<id>/logo` and `.../cover-image` (serve thumbnails; both guard that the resolved parent is `LOGOS_DIR`). Client UI: the export popover's preset `<select>` + the `#preset-modal` manager in `static/js/app.js`.

**`@media print` overrides drive how the PDF looks.** Two non-obvious interactions:

- On screen `.markdown-body table` is `display:block; width:max-content; overflow:auto` (wide tables scroll). Print overrides to `display:table; width:100%; table-layout:auto` with `overflow-wrap:anywhere` on cells (wraps long URLs instead of clipping) + smaller `font-size` (~0.75em).
- The print color reset forces `--panel-alt` to white, flattening zebra striping and the `th` background. The print block re-asserts concrete grays (`th`, `tr:nth-child(even) td`) with `!important`; these render only because `_render_pdf` passes `print_background=True`. Any new background that must survive export needs the same treatment.

**Page margins: a CSS `@page { margin }` rule beats `page.pdf(margin=…)`.** The stylesheet ships a default `@page { margin: 18mm 14mm }` for Ctrl+P. Because that wins the cascade, `_render_pdf` *injects* its own `@page { margin: … }` style tag last (built from the computed per-export margins) — without it every export was pinned to 18/14mm and the `margin=` API arg was silently ignored. The band's horizontal inset (`_hf_band`'s `pad_left`/`pad_right`, from `margin["left"]`/`["right"]`) equals those page margins so the separator hairline and column text line up with the body edges; the outer div is full page width (Chrome renders header/footer across the whole sheet), and the hairline lives on an inner row inset by those paddings.

**Top/bottom margins auto-grow to clear the band.** Chrome anchors header/footer at the page edge and starts the body at the margin — it reserves *no* space for a tall band, so a logo or wrapped header collides with the body. `_render_pdf` *measures* each band before printing: injects the band HTML into a hidden full-page-width div (`page.evaluate`, width from `_PAGE_PX[format]`, swapped for landscape), reads `getBoundingClientRect().height`, converts px→mm (`* 25.4/96`), and sets `margin["top"]/["bottom"] = max(configured, band_mm + HF_GAP_MM)` (gap = 9mm). Never shrinks the configured margin — so the band must be measured at the *printed* width (wrapping must match). A no-content band is emitted as a blank `<div></div>` suppressor by `export_pdf`, because (a) an empty `_hf_band` would still draw its hairline and (b) an empty Chrome template falls back to Chrome's *default* date/title header.

### DOCX export

`GET /export/docx?file=…&preset=…&include_toc=…` converts via the system **`pandoc`** (`shutil.which("pandoc")`; missing → **503** with a hint). Unlike PDF it does **not** drive Chrome or use the render pipeline: `_render_docx()` feeds the source to pandoc on **stdin** (no temp file in the content dir) with `-t docx --standalone`, dispatching by suffix — `.rst` → `-f rst`, else `-f gfm`. For markdown it first strips YAML frontmatter with `extract_frontmatter()` (so it isn't dumped as a block), then surfaces frontmatter `title:`/`author:` as `--metadata` (→ docx core properties + standalone title block). Relative images embed via `--resource-path=<file dir><os.pathsep><CONTENT_DIR>`. `include_toc` (query param wins, else `preset["includeToc"]`) adds a real Word TOC field (`--toc --toc-depth=3`).

**Mermaid diagrams are pre-rendered to images.** Pandoc can't run the client mermaid step, so `_inline_mermaid_images()` finds ```mermaid blocks (via `MERMAID_BLOCK_RE`) and `_render_mermaid_pngs()` rasterizes each via headless Chrome — it `import()`s mermaid@11 from `_MERMAID_CDN`, renders each source, screenshots the element. Each block is swapped for `![](mermaid-N.png)`; PNGs go to a temp dir first on pandoc's `--resource-path`. To print the raster at natural size (capped to `_MERMAID_MAX_WIDTH_IN`), `_png_set_dpi()` rewrites each PNG's `pHYs` chunk to a computed DPI — pandoc reads that density, so no `link_attributes` (unsupported on `gfm`) is needed. Failure is graceful per-diagram: a diagram that won't render keeps its original fenced block.

**Post-processing patches the .docx** (`_style_docx()`, a zip rewrite) because pandoc's defaults don't match the viewer: (1) **font** — pandoc styles off the docx *theme* fonts, so the preset's `fontFamily` (its key *is* the family name) is written into `theme1.xml`'s major+minor `<a:latin typeface>`; (2) **tables** — pandoc's `Table` style is borderless, so it's replaced with `_DOCX_TABLE_STYLE` (grid borders + gray header + `band1Horz` zebra; pandoc sets `w:noHBand="0"` so banding renders) plus `autofit`, and each instance `tblW` in `document.xml` is rewritten to `pct 5000` so tables fill the body; (3) **TOC** — pandoc emits a TOC field with an **empty cached result**, so when `include_toc` is on the patch (a) injects `<w:updateFields w:val="true"/>` into `settings.xml` (Word recalcs on open) and (b) `_populate_toc()` fills the field with static clickable entries (`<w:hyperlink w:anchor>` to slug bookmarks pandoc places on headings, levels 1–3) so other viewers show contents immediately. So `fontFamily` *does* apply to DOCX (the only PDF preset field that also affects Word).

**Mermaid sizing in DOCX:** `_render_mermaid_pngs` rasterizes at `_MERMAID_DEVICE_SCALE`× (3); `_inline_mermaid_images` stamps DPI so it prints at `_MERMAID_SCALE`× (1.5) natural width, capped to `_MERMAID_MAX_WIDTH_IN`. Bump `_MERMAID_SCALE` to enlarge diagrams.

**Cover page in DOCX (preset-driven).** Resolved like the PDF cover (`include_cover` wins, else `preset["coverEnabled"]`), markdown only. `_build_cover_markdown()` reuses the *same* cover fields + `_resolve_cover_tokens` but emits a pandoc-markdown fragment of `custom-style` fenced divs (`Cover*`) mapping to centered paragraph styles injected by `_style_docx` (`_DOCX_COVER_STYLES`); resolved text is `_md_escape`-d. The cover image (`coverImageSource` → custom or logo, raster only — SVG skipped) embeds via the temp resource-path dir, DPI-capped to `_COVER_IMG_MAX_IN`. The fragment is prepended followed by a raw-OpenXML page break (`_DOCX_PAGE_BREAK`, ×2 for `blankAfterCover`); needs `gfm+fenced_divs+raw_attribute-implicit_figures`. When a cover is on, frontmatter title/author metadata is dropped so pandoc's title block doesn't duplicate it.

**Fidelity caveats (intentional):** the PDF-only fields — header/footer bands, margins, `fontScale`, frontmatter panel — do **not** apply (DOCX honors `file`, `preset` (font + TOC flag + cover fields), `include_toc`, `include_cover`). The popover's **Word (.docx)** button (`#export-run-docx`) shares `runExport(format)` with the PDF button; for Word it sends only `file`, `preset`, `include_toc`, `include_cover`.

### TOC filter

The `#toc-search` box (in the sticky `.toc-panel-top`, alongside "On this page") filters a long index client-side: each `.toc li` whose own link text matches gets `is-toc-match`, everything without a match in its own subtree gets `is-toc-filtered` (`display:none`) — so an ancestor stays visible whenever a descendant matches and the hierarchy still reads. Matching is accent-insensitive (`foldText` = lowercase + NFD + strip `̀-ͯ`, so "modulo" finds "Módulo") and the matched substring is wrapped in `<mark>`; a match also un-truncates (`white-space:normal`) since entries are ellipsized by default. Enter jumps to the first match, Escape clears, and clicking any entry clears the filter.

Non-obvious: filtering fights the **TOC↔content scroll sync**. Hidden entries have zero-height rects and the visible ones no longer follow reading order, so `syncContentFromToc()` bails while `tocFiltering`, `updateActiveToc()` skips its `scrollIntoView`, and `applyTocFilter()` sets `contentDriving` for 120ms so the scrollTop jump from collapsing/expanding entries doesn't yank the document — then re-centres on the active heading once cleared.

### Internationalization (i18n)

Translatable via **Flask-Babel** (gettext / `.po`+`.mo`). **English is the source language** — every msgid *is* its English string; **Spanish (`es`) is the only translated catalog**. `SUPPORTED_LOCALES = ["en", "es"]` in `app.py`.

**Locale selection** (`select_locale()`): a `lang` cookie wins (set by `#lang-select` in `app.js`, which writes the cookie and reloads), else `Accept-Language`, else English. No server session; the cookie is the only persistence.

Strings live in three places, all extracted into one catalog:
- **Python** (`app.py`): `from flask_babel import gettext as _`; messages wrapped `_("…")` with named placeholders (`_("…: %(error)s", error=exc)`). Only call `_()` inside request handlers — module-level constants need `lazy_gettext`.
- **Jinja** (`templates/index.html`): `{{ _('…') }}`. Gotchas: a literal `%` in a msgid breaks Jinja's gettext (reword, e.g. "(percent)" not "(%)"); msgids with HTML (`<code>…`) are rendered `|safe`. The `<code>`-heavy token-hint paragraphs are intentionally **left in English** (they reference literal token syntax like `{title}`).
- **JS** (`static/js/app.js`): the template injects the active catalog as `window.I18N` (`{{ js_i18n|tojson }}`, from `_js_catalog()`); a `t(str, vars)` helper mirrors gettext (English string is the key, missing → fall back to key, `%(name)s` interpolation). Wrap client strings `t("…")`.

**`current_locale` / `js_i18n`** are injected by the `inject_i18n` context processor; `<html lang="{{ current_locale }}">` reflects it.

**Workflow to add/update strings.** ⚠️ The `.venv/bin/pybabel` console script has a **broken shebang** in this venv and won't execute directly — invoke Babel as a module instead: `.venv/bin/python -m babel.messages.frontend <cmd> …`.
1. Wrap new strings (`_()` in Python/Jinja, `t()` in JS).
2. Extract: `.venv/bin/python -m babel.messages.frontend extract -F babel.cfg -k _ -k t -o messages.pot .`
3. Update: `.venv/bin/python -m babel.messages.frontend update -i messages.pot -d translations`
4. Add the Spanish string to the `ES` dict in `scripts/make_es_catalog.py` (source of truth for `es`), then run it (`.venv/bin/python scripts/make_es_catalog.py`) to write `translations/es/LC_MESSAGES/messages.po`.
5. Compile: `.venv/bin/python -m babel.messages.frontend compile -d translations`. **An edited `.po` does nothing until recompiled.**

The `en` catalog keeps empty `msgstr`s: gettext returns the (English) msgid when blank.

**Adding a new language** (e.g. French, `fr`):
1. Add the code to `SUPPORTED_LOCALES` in `app.py`. Nothing in `select_locale()` changes.
2. Add `<option value="fr">Français</option>` to `#lang-select` in `templates/index.html` (use the endonym).
3. `.venv/bin/python -m babel.messages.frontend init -i messages.pot -d translations -l fr` (regenerate `messages.pot` first if stale). (As above, `.venv/bin/pybabel` won't run directly — use the module form.)
4. Translate each `msgstr`. **Keep `%(name)s` and `<code>…</code>` byte-identical to the msgid**; a literal `%` stays. Optionally model a `scripts/make_<code>_catalog.py` on `make_es_catalog.py`.
5. `.venv/bin/python -m babel.messages.frontend compile -d translations`.
6. Verify: set the `lang` cookie (or `Accept-Language: fr`) and load `/`. Untranslated msgids fall back to English. No code beyond steps 1–2 is needed.

### Security boundaries to preserve when editing

- `safe_path()` must reject anything escaping `CONTENT_DIR` — keep the `target.relative_to(CONTENT_DIR)` check on any new file-serving route.
- Anything added to the bleach allowlists (`allowed_tags`, `allowed_attributes`, `protocols`) widens what user-authored markdown can render. Be deliberate.
- `is_local_reference()` is the gate deciding which URLs get rewritten; a new scheme exemption means it's no longer sanitized as a local path.

### State that lives in the browser

`static/js/app.js` persists theme (`markwright-theme`), sidebar collapsed (`markwright-sidebar-hidden`), sidebar scroll (`markwright-sidebar-scroll`), per-file content scroll (`markwright-content-scroll:<path>`), the last-used export preset id (`markwright-export-preset`), the task-checkbox auto-save preference (`markwright-task-autosave`), and per-file unsaved editor drafts (`markwright-draft:<root>:<file>`) in `localStorage`. PDF presets themselves live server-side in `CACHE_DIR`, not the browser (only the *selected* preset id is remembered client-side). There is no server-side session.
