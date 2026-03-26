'''
Shin Proxy — User content sanitization.

Replaces the standalone word 'cursor' (any case) in user-supplied content
with a neutral placeholder to prevent the upstream model from activating
its Support Assistant identity.

Extracted from converters/cursor_helpers.py. converters/ keeps a backward-
compat re-export. tools/ has zero dependency on converters/.
'''
from __future__ import annotations

import re

# ── Cursor word blocker ────────────────────────────────────────────
# Replaces the word "cursor" (any case) in USER-SUPPLIED content only.
# Prevents the model from seeing the word and activating its "Cursor Support
# Assistant" identity when users mention the editor by name.

_CURSOR_REPLACEMENT = "the-editor"

# Match the word "cursor" (any case) BUT NOT when it is:
#   - Part of a file path:  cursor/client.py   C:\cursor\file.py
#   - Inside a JSON string next to a slash or backslash
#   - Immediately followed or preceded by a path separator (/ or \)
# Negative lookbehind: not preceded by  /  \  or alphanumeric (already in a word)
# Negative lookahead:  not followed by  /  \.  (path component or extension)
_CURSOR_WORD_RE = re.compile(
    r"(?<![/\\a-zA-Z0-9])"      # not preceded by path sep or word char
    r"[Cc][Uu][Rr][Ss][Oo][Rr]" # the word itself
    r"(?![/\\.]\w)"              # not followed by path sep, dot, or word char
)


def _sanitize_user_content(text: str) -> str:
    """Replace the standalone word 'cursor' (any case) with a neutral placeholder.

    Only applied to user/assistant message content — NOT to proxy-injected
    system prompts or tool instructions (those intentionally reference Cursor
    by name to cancel its hidden prompt rules).

    IMPORTANT: does NOT replace 'cursor' when it appears as a path component
    (e.g. cursor/client.py, C:\\cursor\\file.py) — those are real file paths
    that coding agents like Roo Code and Kilo Code need to read correctly.
    """
    if not text:
        return text or ""
    return _CURSOR_WORD_RE.sub(_CURSOR_REPLACEMENT, text)
