# Markwright

A very small local Markdown viewer built with Flask. It scans this project directory for `.md` files, shows them in a collapsible sidebar, and renders the selected document with GitHub-like typography.

## Features

- Switch source at runtime from the sidebar — point at a local path or a git URL (cloned into `~/.cache/markwright/repos/`), with recent sources kept as quick links
- Recursive Markdown **and reStructuredText** (`.rst`) discovery
- Extensionless `README` files are picked up regardless of capitalisation
- Collapsible directory tree
- Search/filter for markdown files
- Current file highlighting
- Sanitized Markdown rendering
- Tables, fenced code blocks, blockquotes, links, images, and lists
- Syntax highlighting for code blocks
- Mermaid diagram rendering (```` ```mermaid ```` fenced blocks)
- **21 built-in themes** selectable from the sidebar — light, dark, sepia, Nord, Solarized (light/dark), Retro Sun, Monokai, Gruvbox, GitHub Light, Quiet Light, plus popular code-editor themes: Dracula, One Dark/Light, Tokyo Night, Catppuccin (Mocha/Latte), Night Owl, Material Palenight, Ayu Light, and Cobalt2 — with **automatic dark mode** following your OS until you pick one
- **Reading aids** — per-document **word count + reading-time** estimate, hover **¶ anchors** to copy a link to any heading, and a **back-to-top** button on long pages
- **Focus reading mode** — the **⤢** button (or press **F**) hides all chrome, centers the text at a comfortable reading width, goes true-fullscreen, and shows a scroll-progress bar, a **"~N min left"** estimate, and a current-paragraph spotlight; **Space/PageUp/PageDown** and **j/k** page through, the controls auto-hide, and **Esc** leaves
- **Edit mode** — edit a document's raw Markdown in the browser and save it back to disk (local sources only), with CodeMirror syntax highlighting; plus **create, rename, and delete** files from the header **⋮** menu (see below)
- Scroll position preservation
- Local asset support for relative images and links
- **PDF export** with reusable presets: 3-column header/footer bands, logo, page size/margins, a clickable contents page, and a configurable cover page (see below)
- **YAML frontmatter** rendered as a panel and usable as `{placeholders}` in PDF headers/footers and covers
- **Manual page breaks** in the PDF via a `\newpage` line
- Flask debug reload while developing
- File change live update

## Run Locally

### With uv

This is the setup used while creating the app:

```bash
cd /home/ivan/projects/markwright
uv venv
uv pip install -r requirements.txt
.venv/bin/python app.py
```

To scan another directory:

```bash
.venv/bin/python app.py /path/to/markdown-folder
```

### With pip

```bash
cd /home/ivan/projects/markwright
pip install -r requirements.txt
python app.py
```

To scan another directory:

```bash
python app.py /path/to/markdown-folder
```

### With Python venv and pip

Use this if you want an isolated virtual environment without `uv`:

```bash
cd /home/ivan/projects/markwright
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

To scan another directory:

```bash
python app.py /path/to/markdown-folder
```

If `python app.py` does not work on your system, use:

```bash
python3 app.py
```

Open:

```text
http://127.0.0.1:5000
```

Stop the server with `Ctrl+C` in the terminal running Flask.

## Usage

Place `.md` files anywhere inside the scanned folder. Refresh the browser and Markwright will rescan the directory and show the files in the sidebar.

By default, Markwright scans the current directory. You can pass a directory as the first argument:

```bash
python app.py ~/Documents/wiki
```

You can also choose a custom host or port:

```bash
python app.py ~/Documents/wiki --host 127.0.0.1 --port 8000
```

Relative links to other Markdown files open inside Markwright. Relative image paths are served locally from this project directory.

## Editing

When the current source is a **local folder** (not a cloned git repo), an **✎** button appears in the document header. Click it to edit the document's raw Markdown/RST in place, then **Save** (or **Ctrl/⌘+S**) to write it back to disk. The editor **stays open after saving** so you can keep working; the rendered view refreshes when you leave edit mode (or hit the **✎** button again to stop editing).

- A **● Unsaved changes** flag appears while the text differs from disk, **Save is disabled when there are no changes**, and a live **word/character count** is shown.
- **Live preview** — the **Preview** button opens a split view that renders your Markdown (Mermaid included) beside the source as you type.
- **Formatting & shortcuts** — toolbar buttons and keys for **bold (Ctrl/⌘+B)**, **italic (Ctrl/⌘+I)**, inline code, and **link (Ctrl/⌘+K)**; **Enter continues lists** (`-`, `1.`, `- [ ]`); **Ctrl/⌘+F / +H** find & replace; **Ctrl/⌘+S** save; **Esc** leaves edit mode.
- **Fullscreen** — the **⛶** button expands the editor (and preview) to fill the screen; **Esc** exits fullscreen.
- **Paste smarts** — paste a URL over selected text to make a link, and **paste or drag-and-drop an image** to save it next to the document and insert `![](…)` automatically.
- **Draft recovery** — unsaved edits are continuously backed up to your browser; if you close or crash mid-edit, you're offered to restore the draft next time you open that file.
- **Unsaved-changes guard** — you're warned before navigating away, closing the tab, or cancelling while there are unsaved edits.
- Editing is **text-only and local-only.** Git sources are read-only — a clone would just be overwritten on its next pull, so the edit button is hidden and the save endpoint refuses them.
- The editor upgrades to **CodeMirror** with Markdown syntax highlighting and line numbers, loaded on demand from a CDN the first time you open it. If the CDN is unreachable (e.g. offline) it falls back to a plain text box — editing still works.
- The editor theme follows the active page theme (dark themes get a dark editor).
- Auto-reload (the live "file changed on disk" refresh) is **paused while you're editing**, so it never discards your work mid-edit.

### Managing files

For local sources, the document header also has a **⋮** menu with:

- **New file…** — create a `.md`/`.rst` file (a name with no extension gets `.md`; nested paths like `docs/notes.md` create the folder). It then opens in the viewer.
- **Rename…** — rename or move the current file (keeps the original extension if you don't type one).
- **Delete…** — delete the current file, **after an inline confirmation**.

Each action opens a small inline form inside the menu (no browser pop-up dialogs); errors show inline. All three are local-only and refuse to overwrite an existing file; like editing, they're hidden and rejected for git sources.

## PDF export

Click the **⤓** button in the document header to open the export popover, then **Download PDF**. Export uses your system Chrome/Chromium under the hood (so Mermaid diagrams and styling are preserved), so a Chrome/Chromium install is required.

### Frontmatter and placeholders

Give a document a YAML **frontmatter** block as its very first lines (nothing — not even a blank line — may come before the opening `---`):

```markdown
---
title: Payment Gateway Specification
author: Ivan Candelas
version: 2.1
status: Draft
client: Baalbek
---

# Your heading…
```

Any key you put there becomes a `{placeholder}` you can use in the PDF header, footer, and cover — for example `{author}`, `{version}`, `{status}`, `{client}`. Matching is case-insensitive, and **you can add any key you like** (`{reviewer}`, `{project}`, …) — it's available immediately. If a placeholder has no matching key it renders empty (and on the cover, a metadata row that comes out empty is dropped).

Built-in placeholders, always available:

| Placeholder | Value |
|---|---|
| `{title}` | frontmatter `title:`, else the first heading, else the filename |
| `{filename}` / `{document_name}` | the file name on disk |
| `{date}` `{time}` `{datetime}` | the export moment — see formatting below |
| `{page}` `{total}` | current / total page number (header & footer only) |
| `{url}` | the document URL (header & footer only) |

**Date/time formatting.** `{date}`, `{time}`, and `{datetime}` accept an optional inline [strftime](https://strftime.org) format after a colon:

| Placeholder | Output |
|---|---|
| `{date}` | `2026-05-24` |
| `{time}` | `19:06` |
| `{datetime}` | `2026-05-24 19:06` |
| `{date:%d/%m/%Y}` | `24/05/2026` |
| `{time:%I:%M %p}` | `07:06 PM` |
| `{datetime:%d/%m/%Y %H:%M}` | `24/05/2026 19:06` |

These always reflect the export time (not a frontmatter `date:` field — name that key something else, e.g. `published:`, and use `{published}`).

The **frontmatter panel** shown at the top of the rendered document can be toggled on screen with the **ⓘ** button in the header (the toggle only appears when the document has frontmatter). It is **hidden in the PDF by default**; tick *Include frontmatter panel* in the export popover (or enable it in a preset) to keep it.

### Presets, cover page, and contents page

Open the export popover and click **⚙** to manage **presets** — reusable export profiles (per project or client). A preset stores:

- 3-column **header** and **footer** bands (left / center / right), with placeholder support
- a **logo** image and its position, **page size** (A4, Letter, Legal, or Tabloid/Ledger 11×17), **orientation**, **margins**, and **body font scale**
- **Default (fallback) values** — supply `key: value` defaults that fill placeholders when a document has no frontmatter, or is missing a key (the document's own frontmatter always wins)
- **Include contents page** — prepend a clickable, hierarchically-numbered table of contents
- a **cover page** — optional title, subtitle, metadata rows (one `Label: value` per line, placeholders welcome), a footer line, a **blank page after the cover**, and a cover image whose source you choose: *None*, *Use preset logo*, or *Upload an image*

The contents-page, cover-page, and frontmatter-panel options can also be toggled per-export in the popover, overriding the preset for that one download. (A cover needs a preset selected, since its content lives in the preset.)

### Manual page breaks

Put any of these on a line by itself in your Markdown to force a new page in the PDF:

```
\newpage
```

`\pagebreak` and `<!-- pagebreak -->` work the same way. On screen it shows as a faint "Page break" divider; markers inside fenced code blocks are left alone.

## Project Structure

```text
.
├── app.py                 # Flask app: routes, i18n wiring, CLI entry point
├── markwright/            # supporting package (rendering, files, sources, export, presets…)
├── requirements.txt
├── requirements-dev.txt   # test/dev deps (pytest)
├── README.md
├── tests/                 # pytest suite (pure helpers + route oracle)
├── translations/          # Flask-Babel catalogs (en source, es)
├── static
│   ├── css
│   │   └── style.css
│   └── js
│       └── app.js
└── templates
    └── index.html
```
