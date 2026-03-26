"""
Shin Proxy — Tool call confidence scoring.

Extracted from tools/parse.py. No imports from other tools/ modules.
"""
from __future__ import annotations

import re


# Matches [assistant_tool_calls] anchored to the start of a line (not inside prose).
# re.MULTILINE so ^ matches any line start, not just start-of-string.
# No re.IGNORECASE — the-editor always emits lowercase; flag risks false positives.
_TOOL_CALL_MARKER_RE = re.compile(
    r"^[ \t]*\[assistant_tool_calls\]",
    re.MULTILINE,
)


def _find_marker_pos(text: str) -> int:
    """Return the character position of a "real" [assistant_tool_calls] marker.

    A real marker must appear at the start of a line and must NOT be inside a
    backtick code fence (e.g. a mermaid diagram or markdown example).
    Returns -1 if no such marker exists.
    """
    # Collect all (start, end) ranges for complete code-fence blocks.
    fence_ranges = [
        (m.start(), m.end())
        for m in re.finditer(r"```.*?```", text, flags=re.DOTALL)
    ]

    def _in_fence(pos: int) -> bool:
        return any(s <= pos < e for s, e in fence_ranges)

    # Return the first marker position that is NOT inside a fence.
    for m in _TOOL_CALL_MARKER_RE.finditer(text):
        if not _in_fence(m.start()):
            return m.start()
    return -1


def score_tool_call_confidence(text: str, calls: list[dict]) -> float:
    """Score how confident we are the model intentionally made a tool call.

    Returns 0.0 (accidental) to 1.0 (definitely intentional).
    """
    if not calls:
        return 0.0

    score = 0.0
    lower = text.lower()

    # Strong positive signals
    real_marker_pos = _find_marker_pos(text)
    if real_marker_pos >= 0:
        score += 0.5
        if real_marker_pos <= 1:  # marker is at start of response (pos 0) or after single leading newline (pos 1)
            score += 0.2

    # Weak positive signals
    if "tool_calls" in lower:
        score += 0.1
    if '"name"' in text and '"arguments"' in text:
        score += 0.1

    # Negative signals — model was illustrating, not calling
    if real_marker_pos < 0 and len(text) > 1500:
        score -= 0.3
    if "for example" in lower or "such as" in lower:
        score -= 0.2
    if "```" in text and _find_marker_pos(text) < 0:
        score -= 0.1

    return max(0.0, min(1.0, score))
