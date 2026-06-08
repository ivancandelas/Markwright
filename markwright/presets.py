"""PDF export preset storage (``pdf_presets.json``) and on-disk logo / cover
image cleanup. Logos live in ``LOGOS_DIR`` as ``<id>.<ext>`` and cover images as
``<id>-cover.<ext>``.
"""
import json

from markwright.config import (
    ALLOWED_LOGO_EXTENSIONS,
    CACHE_DIR,
    LOGOS_DIR,
    PRESETS_FILE,
)


def load_presets():
    if not PRESETS_FILE.is_file():
        return []
    try:
        data = json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data.get("presets", []) if isinstance(data, dict) else []


def save_presets(presets):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    PRESETS_FILE.write_text(
        json.dumps({"presets": presets}, indent=2),
        encoding="utf-8",
    )


def find_preset(preset_id):
    return next((p for p in load_presets() if p.get("id") == preset_id), None)


def delete_logo_files(preset_id):
    """Remove any stored logo for a preset id, regardless of extension."""
    if not LOGOS_DIR.is_dir():
        return
    for ext in ALLOWED_LOGO_EXTENSIONS:
        candidate = LOGOS_DIR / f"{preset_id}{ext}"
        if candidate.exists():
            candidate.unlink()


def delete_cover_files(preset_id):
    """Remove any stored cover image for a preset id (stored as
    ``<id>-cover.<ext>`` alongside logos), regardless of extension."""
    if not LOGOS_DIR.is_dir():
        return
    for ext in ALLOWED_LOGO_EXTENSIONS:
        candidate = LOGOS_DIR / f"{preset_id}-cover{ext}"
        if candidate.exists():
            candidate.unlink()
