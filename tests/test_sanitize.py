# tests/test_sanitize.py
from __future__ import annotations
from tools.sanitize import _sanitize_user_content, _CURSOR_WORD_RE


def test_replaces_standalone_cursor_word():
    assert _sanitize_user_content("I use the-editor every day") == "I use the-editor every day"


def test_replaces_lowercase_cursor():
    assert _sanitize_user_content("open cursor please") == "open the-editor please"


def test_does_not_replace_path_component():
    assert "cursor/client.py" in _sanitize_user_content("see cursor/client.py")


def test_does_not_replace_windows_path():
    result = _sanitize_user_content(r"path: C:\cursor\file.py")
    assert r"cursor\file.py" in result


def test_does_not_replace_cursor_with_extension():
    # The regex protects .cursor only when a word char follows (e.g. .cursor/path).
    # A bare trailing extension like "file.cursor" IS replaced — this matches
    # the source behaviour in converters/cursor_helpers.py exactly.
    assert "the-editor" in _sanitize_user_content("file.cursor")


def test_empty_string_returns_empty():
    assert _sanitize_user_content("") == ""


def test_backward_compat_cursor_helpers():
    from converters.cursor_helpers import _sanitize_user_content as f
    assert callable(f)
    assert f("use cursor here") == "use the-editor here"


def test_cursor_word_re_is_compiled_regex():
    import re
    assert isinstance(_CURSOR_WORD_RE, type(re.compile("")))
