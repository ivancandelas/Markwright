"""Toggle a single task-list checkbox in *source* markdown.

The viewer renders ``- [ ]`` items as interactive checkboxes
(``TaskListTreeprocessor``); clicking one with auto-save on calls
``/api/toggle-task``, which uses ``toggle_task_marker`` to flip the matching
``[ ]``↔``[x]`` in the on-disk file. The client sends the *document-order index*
of the checkbox (its ``data-task-index``), and this scan must visit task markers
in the same order the renderer does — so it skips fenced code blocks, whose
``- [ ]`` lines never become checkboxes.
"""
import re

# A task-list marker line in source markdown: a list marker (bullet or ordered)
# followed by a `[ ]`/`[x]` checkbox. The lookahead mirrors the renderer's
# (an empty `- [ ]` counts; `[ ]x` does not).
TASK_MARKER_RE = re.compile(
    r"^(?P<lead>[ \t]*(?:[-*+]|\d{1,9}[.)])[ \t]+)\[(?P<state>[ xX])\](?=\s|$)"
)

# A fenced-code delimiter line (``` or ~~~, optionally indented).
FENCE_RE = re.compile(r"^[ \t]*(?P<fence>`{3,}|~{3,})")


def toggle_task_marker(source, index, checked):
    """Return ``source`` with its ``index``-th task-list checkbox set to
    ``checked``. Raises ``IndexError`` if there is no such marker.

    Lines inside fenced code blocks are skipped so their ``- [ ]`` text — which
    the renderer leaves as literal code, not a checkbox — doesn't shift the count.
    """
    lines = source.split("\n")
    fence = None  # the open fence's delimiter char while inside a code block
    count = 0
    for i, line in enumerate(lines):
        fence_match = FENCE_RE.match(line)
        if fence is None:
            if fence_match:
                fence = fence_match.group("fence")[0]
                continue
        else:
            # Inside a fence: a same-char delimiter closes it; nothing else counts.
            if fence_match and fence_match.group("fence")[0] == fence:
                fence = None
            continue

        marker = TASK_MARKER_RE.match(line)
        if marker is None:
            continue
        if count == index:
            box = "x" if checked else " "
            lines[i] = f"{marker.group('lead')}[{box}]{line[marker.end():]}"
            return "\n".join(lines)
        count += 1

    raise IndexError(index)
