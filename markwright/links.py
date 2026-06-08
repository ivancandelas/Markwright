"""Local-reference classification + resolution.

Shared by both rewriters: the markdown ``LocalPathTreeprocessor`` and the RST
``rewrite_local_links`` regex pass. ``is_local_reference`` is the security gate
that decides which URLs get rewritten (and thus treated as on-disk paths rather
than sanitized links) — adding a scheme exemption here widens that surface.
"""
from pathlib import PurePosixPath


def is_local_reference(value):
    lowered = value.lower()
    return not (
        lowered.startswith("http://")
        or lowered.startswith("https://")
        or lowered.startswith("mailto:")
        or lowered.startswith("tel:")
        or lowered.startswith("#")
        or lowered.startswith("data:")
        or lowered.startswith("/")
    )


def resolve_reference(current_dir, value):
    path_part, separator, suffix = value.partition("#")
    relative = (current_dir / path_part).as_posix()
    normalized = PurePosixPath(relative).as_posix()
    return f"{normalized}{separator}{suffix}" if separator else normalized
