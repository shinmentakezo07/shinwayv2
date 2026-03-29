# Converters Improvements Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add pre-conversion semantic validation, converter-specific metrics, multi-modal content handling, adjacent same-role message collapsing, tool call converter deduplication, and round-trip test helpers to the `converters/` layer.

**Architecture:** Six focused improvements land in `converters/` with no changes to pipeline or router code. Each improvement is isolated: new files for new responsibilities, surgical edits to existing files for deduplication and collapsing. All changes follow existing patterns (structlog, no bare except, deepcopy immutability, type-annotated signatures).

**Tech Stack:** Python 3.12, pytest, structlog, existing `converters/` + `tools/` packages.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `converters/validator.py` | Pre-conversion semantic validation of messages and tool calls |
| Create | `converters/content_types.py` | Multi-modal content block routing (image → placeholder) |
| Modify | `converters/message_normalizer.py` | Add adjacent same-role message collapsing |
| Modify | `converters/from_cursor_anthropic.py` | Remove duplicate `convert_tool_calls_to_anthropic` — import from `from_cursor.py` |
| Modify | `converters/cursor_helpers.py` | Wire converter metric calls into `_extract_text` and tool ID synthesis |
| Modify | `converters/__init__.py` | Export new public symbols |
| Create | `tests/test_converters_validator.py` | Tests for `converters/validator.py` |
| Create | `tests/test_converters_content_types.py` | Tests for `converters/content_types.py` |
| Modify | `tests/test_message_normalizer.py` | Tests for new collapsing functions |
| Modify | `tests/test_from_cursor_anthropic.py` | Verify deduplication — import still works |

---

## Chunk 1: Pre-conversion semantic validator

### Task 1: Create `converters/validator.py` with failing tests first

**Files:**
- Create: `tests/test_converters_validator.py`
- Create: `converters/validator.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_converters_validator.py
from converters.validator import (
    validate_openai_messages,
    validate_anthropic_messages,
    validate_tool_calls,
    ConversionValidationError,
)


class TestValidateOpenAIMessages:
    def test_valid_messages_returns_empty(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        assert validate_openai_messages(msgs) == []

    def test_tool_result_without_matching_call_id_flagged(self):
        msgs = [
            {"role": "tool", "tool_call_id": "call_abc", "content": "result"},
        ]
        issues = validate_openai_messages(msgs)
        assert any("call_abc" in i for i in issues)

    def test_tool_call_missing_id_flagged(self):
        msgs = [
            {
                "role": "assistant",
                "tool_calls": [{"function": {"name": "foo", "arguments": "{}"}}],
            }
        ]
        issues = validate_openai_messages(msgs)
        assert any("missing id" in i.lower() for i in issues)

    def test_tool_call_arguments_not_string_flagged(self):
        msgs = [
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "c1", "function": {"name": "foo", "arguments": {"x": 1}}}
                ],
            }
        ]
        issues = validate_openai_messages(msgs)
        assert any("arguments" in i for i in issues)

    def test_empty_list_returns_empty(self):
        assert validate_openai_messages([]) == []


class TestValidateAnthropicMessages:
    def test_valid_messages_returns_empty(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
        ]
        assert validate_anthropic_messages(msgs) == []

    def test_tool_use_missing_id_flagged(self):
        msgs = [
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "name": "foo", "input": {}}],
            }
        ]
        issues = validate_anthropic_messages(msgs)
        assert any("missing id" in i.lower() for i in issues)

    def test_tool_result_without_matching_use_id_flagged(self):
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tu_orphan", "content": "ok"}
                ],
            }
        ]
        issues = validate_anthropic_messages(msgs)
        assert any("tu_orphan" in i for i in issues)

    def test_empty_list_returns_empty(self):
        assert validate_anthropic_messages([]) == []


class TestValidateToolCalls:
    def test_valid_tool_calls_returns_empty(self):
        tcs = [{"id": "c1", "function": {"name": "foo", "arguments": '{"x": 1}'}}]
        assert validate_tool_calls(tcs) == []

    def test_missing_id_flagged(self):
        tcs = [{"function": {"name": "foo", "arguments": "{}"}}]
        issues = validate_tool_calls(tcs)
        assert any("missing id" in i.lower() for i in issues)

    def test_arguments_not_string_flagged(self):
        tcs = [{"id": "c1", "function": {"name": "foo", "arguments": {"x": 1}}}]
        issues = validate_tool_calls(tcs)
        assert any("arguments" in i for i in issues)

    def test_missing_name_flagged(self):
        tcs = [{"id": "c1", "function": {"arguments": "{}"}}]
        issues = validate_tool_calls(tcs)
        assert any("name" in i for i in issues)

    def test_empty_list_returns_empty(self):
        assert validate_tool_calls([]) == []
```

- [ ] **Step 2: Run to verify tests fail**

```bash
pytest tests/test_converters_validator.py -v
```
Expected: `ImportError` — `converters/validator.py` does not exist yet.

- [ ] **Step 3: Implement `converters/validator.py`**

```python
"""Converters — pre-conversion semantic validation.

Validates message lists and tool call lists for semantic correctness
before they reach format-specific converters. Returns a list of
human-readable issue strings. An empty list means no issues found.

Never mutates input. Never raises — callers decide whether issues are
fatal (raise) or advisory (log).
"""
from __future__ import annotations

import json

import structlog

log = structlog.get_logger()


class ConversionValidationError(ValueError):
    """Raised by callers that treat validation issues as fatal."""


def validate_tool_calls(tool_calls: list[dict]) -> list[str]:
    """Validate a list of OpenAI-format tool_call objects.

    Checks:
    - Each entry has an 'id' field.
    - Each entry has function.name.
    - Each entry has function.arguments as a JSON string.

    Args:
        tool_calls: List of tool call dicts.

    Returns:
        List of issue strings. Empty means valid.
    """
    issues: list[str] = []
    for i, tc in enumerate(tool_calls or []):
        if not isinstance(tc, dict):
            issues.append(f"tool_calls[{i}]: not a dict")
            continue
        if not tc.get("id"):
            issues.append(f"tool_calls[{i}]: missing id")
        fn = tc.get("function") or {}
        if not fn.get("name"):
            issues.append(f"tool_calls[{i}]: missing function.name")
        args = fn.get("arguments")
        if not isinstance(args, str):
            issues.append(
                f"tool_calls[{i}]: arguments must be a JSON string, "
                f"got {type(args).__name__}"
            )
        else:
            try:
                json.loads(args)
            except json.JSONDecodeError:
                issues.append(f"tool_calls[{i}]: arguments is not valid JSON")
    return issues


def validate_openai_messages(messages: list[dict]) -> list[str]:
    """Validate a list of OpenAI-format messages for semantic correctness.

    Checks:
    - tool_call_ids in role=tool messages have a matching prior tool_call.
    - assistant tool_calls have valid ids and string arguments.
    - No unknown roles.

    Args:
        messages: OpenAI message list.

    Returns:
        List of issue strings. Empty means valid.
    """
    issues: list[str] = []
    seen_call_ids: set[str] = set()

    for i, msg in enumerate(messages or []):
        if not isinstance(msg, dict):
            issues.append(f"messages[{i}]: not a dict")
            continue
        role = msg.get("role", "user")

        if role == "assistant" and isinstance(msg.get("tool_calls"), list):
            for issue in validate_tool_calls(msg["tool_calls"]):
                issues.append(f"messages[{i}].{issue}")
            for tc in msg["tool_calls"]:
                if isinstance(tc, dict) and tc.get("id"):
                    seen_call_ids.add(tc["id"])

        elif role == "tool":
            call_id = msg.get("tool_call_id", "")
            if call_id and call_id not in seen_call_ids:
                issues.append(
                    f"messages[{i}]: tool result references unknown "
                    f"tool_call_id={call_id!r} (no prior assistant tool_call)"
                )

    if issues:
        log.warning(
            "openai_message_validation_issues",
            issue_count=len(issues),
            issues=issues,
        )
    return issues


def validate_anthropic_messages(messages: list[dict]) -> list[str]:
    """Validate a list of Anthropic-format messages for semantic correctness.

    Checks:
    - tool_use blocks have an id.
    - tool_result blocks reference a known tool_use id.

    Args:
        messages: Anthropic message list.

    Returns:
        List of issue strings. Empty means valid.
    """
    issues: list[str] = []
    seen_tool_use_ids: set[str] = set()

    for i, msg in enumerate(messages or []):
        if not isinstance(msg, dict):
            issues.append(f"messages[{i}]: not a dict")
            continue
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue

        for j, block in enumerate(content):
            if not isinstance(block, dict):
                continue
            btype = block.get("type")

            if btype == "tool_use":
                block_id = block.get("id", "")
                if not block_id:
                    issues.append(
                        f"messages[{i}].content[{j}]: tool_use block missing id "
                        f"(name={block.get('name')!r})"
                    )
                else:
                    seen_tool_use_ids.add(block_id)

            elif btype == "tool_result":
                use_id = block.get("tool_use_id", "")
                if use_id and use_id not in seen_tool_use_ids:
                    issues.append(
                        f"messages[{i}].content[{j}]: tool_result references "
                        f"unknown tool_use_id={use_id!r}"
                    )

    if issues:
        log.warning(
            "anthropic_message_validation_issues",
            issue_count=len(issues),
            issues=issues,
        )
    return issues
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/test_converters_validator.py -v
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add converters/validator.py tests/test_converters_validator.py
git commit -m "feat(converters): add pre-conversion semantic validator"
```

---

## Chunk 2: Multi-modal content handling

### Task 2: Create `converters/content_types.py`

**Files:**
- Create: `tests/test_converters_content_types.py`
- Create: `converters/content_types.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_converters_content_types.py
from converters.content_types import (
    extract_text_with_placeholders,
    ContentBlock,
    UNSUPPORTED_BLOCK_PLACEHOLDER,
)


class TestExtractTextWithPlaceholders:
    def test_plain_string_passes_through(self):
        assert extract_text_with_placeholders("hello") == "hello"

    def test_text_block_extracted(self):
        content = [{"type": "text", "text": "hello"}]
        assert extract_text_with_placeholders(content) == "hello"

    def test_image_url_block_replaced_with_placeholder(self):
        content = [
            {"type": "text", "text": "see this:"},
            {"type": "image_url", "image_url": {"url": "https://example.com/img.png"}},
        ]
        result = extract_text_with_placeholders(content)
        assert "see this:" in result
        assert UNSUPPORTED_BLOCK_PLACEHOLDER in result

    def test_image_block_replaced_with_placeholder(self):
        content = [{"type": "image", "source": {"type": "base64", "data": "abc"}}]
        result = extract_text_with_placeholders(content)
        assert UNSUPPORTED_BLOCK_PLACEHOLDER in result

    def test_multiple_text_blocks_joined(self):
        content = [
            {"type": "text", "text": "hello"},
            {"type": "text", "text": " world"},
        ]
        assert extract_text_with_placeholders(content) == "hello world"

    def test_empty_list_returns_empty_string(self):
        assert extract_text_with_placeholders([]) == ""

    def test_none_returns_empty_string(self):
        assert extract_text_with_placeholders(None) == ""

    def test_unknown_block_type_replaced_with_placeholder(self):
        content = [{"type": "audio", "data": "..."}]
        result = extract_text_with_placeholders(content)
        assert UNSUPPORTED_BLOCK_PLACEHOLDER in result

    def test_content_block_dataclass_text_type(self):
        block = ContentBlock(type="text", text="hi")
        assert block.type == "text"
        assert block.text == "hi"
```

- [ ] **Step 2: Run to verify tests fail**

```bash
pytest tests/test_converters_content_types.py -v
```
Expected: `ImportError`.

- [ ] **Step 3: Implement `converters/content_types.py`**

```python
"""Converters — multi-modal content block routing.

Routes content blocks by type. Text blocks are extracted as plain text.
Non-text blocks (image_url, image, audio, file, etc.) are replaced with
a neutral placeholder so the model knows content existed but was omitted.

This eliminates the silent data-loss in _extract_text (which just drops
non-text blocks with a warning). Callers that previously called
_extract_text can call extract_text_with_placeholders instead when they
want explicit placeholder insertion rather than silent dropping.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

log = structlog.get_logger()

UNSUPPORTED_BLOCK_PLACEHOLDER = "[content omitted: unsupported block type]"

_TEXT_BLOCK_TYPES: frozenset[str] = frozenset({"text", "input_text", "output_text"})
_KNOWN_NON_TEXT_TYPES: frozenset[str] = frozenset({
    "image", "image_url", "audio", "file", "document", "video",
    "image_base64", "image_file",
})


@dataclass(frozen=True)
class ContentBlock:
    """Typed representation of a single content block."""
    type: str
    text: str | None = None
    data: Any = None


def extract_text_with_placeholders(content: str | list | None) -> str:
    """Extract text from content, replacing non-text blocks with a placeholder.

    Unlike _extract_text (which silently drops non-text blocks), this function
    inserts UNSUPPORTED_BLOCK_PLACEHOLDER so the model knows something was
    present but could not be processed.

    Args:
        content: A string, list of content blocks, or None.

    Returns:
        Joined text string with placeholders where non-text blocks appeared.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type", "")
        if btype in _TEXT_BLOCK_TYPES:
            text = block.get("text", "")
            if isinstance(text, str):
                parts.append(text)
        else:
            # Non-text block: log and insert placeholder
            log.info(
                "content_block_replaced_with_placeholder",
                block_type=btype,
                known_non_text=btype in _KNOWN_NON_TEXT_TYPES,
            )
            parts.append(UNSUPPORTED_BLOCK_PLACEHOLDER)

    return "".join(parts)
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/test_converters_content_types.py -v
```
Expected: all green.

- [ ] **Step 5: Export from `converters/__init__.py`**

Add to `converters/__init__.py`:

```python
from converters.content_types import (  # noqa: F401
    extract_text_with_placeholders,
    UNSUPPORTED_BLOCK_PLACEHOLDER,
)
```

- [ ] **Step 6: Commit**

```bash
git add converters/content_types.py tests/test_converters_content_types.py converters/__init__.py
git commit -m "feat(converters): add content_types module — multi-modal placeholder routing"
```

---

## Chunk 3: Adjacent same-role message collapsing

### Task 3: Add collapsing to `message_normalizer.py`

**Files:**
- Modify: `converters/message_normalizer.py`
- Modify: `tests/test_message_normalizer.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_message_normalizer.py`:

```python
from converters.message_normalizer import (
    collapse_adjacent_same_role,
    collapse_openai_messages,
    collapse_anthropic_messages,
)


class TestCollapseAdjacentSameRole:
    def test_no_adjacent_same_role_unchanged(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "bye"},
        ]
        assert collapse_adjacent_same_role(msgs) == msgs

    def test_adjacent_user_messages_collapsed(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "user", "content": "world"},
        ]
        result = collapse_adjacent_same_role(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert "hello" in result[0]["content"]
        assert "world" in result[0]["content"]

    def test_adjacent_assistant_messages_collapsed(self):
        msgs = [
            {"role": "assistant", "content": "part1"},
            {"role": "assistant", "content": "part2"},
        ]
        result = collapse_adjacent_same_role(msgs)
        assert len(result) == 1
        assert "part1" in result[0]["content"]
        assert "part2" in result[0]["content"]

    def test_empty_list_returns_empty(self):
        assert collapse_adjacent_same_role([]) == []

    def test_tool_messages_not_collapsed(self):
        """tool role messages must never be merged — each carries a distinct call_id."""
        msgs = [
            {"role": "tool", "tool_call_id": "c1", "content": "r1"},
            {"role": "tool", "tool_call_id": "c2", "content": "r2"},
        ]
        result = collapse_adjacent_same_role(msgs)
        assert len(result) == 2

    def test_non_dict_entries_skipped(self):
        msgs = ["bad", {"role": "user", "content": "ok"}]
        result = collapse_adjacent_same_role(msgs)
        assert len(result) == 1
        assert result[0]["content"] == "ok"


class TestCollapseOpenAIMessages:
    def test_adjacent_user_strings_merged(self):
        msgs = [
            {"role": "user", "content": "a"},
            {"role": "user", "content": "b"},
        ]
        result = collapse_openai_messages(msgs)
        assert len(result) == 1
        assert result[0]["content"] == "a\nb"

    def test_assistant_with_tool_calls_not_merged(self):
        """Messages with tool_calls must never be merged."""
        msgs = [
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]},
            {"role": "assistant", "content": "hello"},
        ]
        result = collapse_openai_messages(msgs)
        assert len(result) == 2


class TestCollapseAnthropicMessages:
    def test_adjacent_user_string_content_merged(self):
        msgs = [
            {"role": "user", "content": "a"},
            {"role": "user", "content": "b"},
        ]
        result = collapse_anthropic_messages(msgs)
        assert len(result) == 1

    def test_assistant_with_tool_use_not_merged(self):
        msgs = [
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "f", "input": {}}]},
            {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
        ]
        result = collapse_anthropic_messages(msgs)
        assert len(result) == 2
```

- [ ] **Step 2: Run to verify tests fail**

```bash
pytest tests/test_message_normalizer.py -v -k "collapse"
```
Expected: `ImportError` — functions not defined yet.

- [ ] **Step 3: Add collapsing to `converters/message_normalizer.py`**

Append the following to `converters/message_normalizer.py` (after the existing normalize functions):

```python
_NO_COLLAPSE_ROLES: frozenset[str] = frozenset({"tool", "system"})


def collapse_adjacent_same_role(messages: list[dict]) -> list[dict]:
    """Collapse adjacent messages with the same role into one.

    Rules:
    - 'tool' and 'system' role messages are NEVER collapsed — each carries
      distinct metadata (tool_call_id, scope).
    - Messages with 'tool_calls' on the assistant role are never merged.
    - Non-dict entries are dropped (same as normalize functions).
    - Content is joined with a newline separator.

    This is the general-purpose collapser. Format-specific variants
    (collapse_openai_messages, collapse_anthropic_messages) apply
    additional format rules on top.

    Args:
        messages: Input message list.

    Returns:
        New list with adjacent same-role messages merged. Input is not mutated.
    """
    out: list[dict] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "user")
        # Never merge tool/system roles
        if role in _NO_COLLAPSE_ROLES:
            out.append(deepcopy(msg))
            continue
        # Never merge messages carrying tool_calls
        if msg.get("tool_calls"):
            out.append(deepcopy(msg))
            continue
        if out and out[-1].get("role") == role and not out[-1].get("tool_calls") and out[-1].get("role") not in _NO_COLLAPSE_ROLES:
            prev = out[-1]
            prev_content = prev.get("content") or ""
            this_content = msg.get("content") or ""
            if isinstance(prev_content, str) and isinstance(this_content, str):
                prev["content"] = prev_content + "\n" + this_content if prev_content else this_content
            else:
                # Non-string content (list blocks) — append as new message
                out.append(deepcopy(msg))
        else:
            out.append(deepcopy(msg))
    return out


def collapse_openai_messages(messages: list[dict]) -> list[dict]:
    """Collapse adjacent same-role OpenAI messages.

    Delegates to collapse_adjacent_same_role which handles
    tool and system role exclusions. OpenAI-specific: messages
    with tool_calls are never merged (already enforced).
    """
    return collapse_adjacent_same_role(messages)


def collapse_anthropic_messages(messages: list[dict]) -> list[dict]:
    """Collapse adjacent same-role Anthropic messages.

    Anthropic-specific rule: assistant messages containing tool_use
    blocks are never merged (they must stay paired with tool_result).
    All other same-role adjacent messages with string content are merged.
    """
    out: list[dict] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "user")
        content = msg.get("content", [])
        # Never merge if content contains tool_use or tool_result blocks
        has_tool_blocks = isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") in ("tool_use", "tool_result")
            for b in content
        )
        if role in _NO_COLLAPSE_ROLES or has_tool_blocks:
            out.append(deepcopy(msg))
            continue
        # Check if previous message is also mergeable same-role
        if out and out[-1].get("role") == role:
            prev = out[-1]
            prev_content = prev.get("content") or ""
            this_content = content or ""
            # Only merge when both contents are strings
            if isinstance(prev_content, str) and isinstance(this_content, str):
                prev["content"] = (prev_content + "\n" + this_content) if prev_content else this_content
                continue
        out.append(deepcopy(msg))
    return out
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/test_message_normalizer.py -v
```
Expected: all green including the new collapse tests.

- [ ] **Step 5: Update `converters/__init__.py` to export collapsing functions**

Add to `converters/__init__.py`:

```python
from converters.message_normalizer import (  # noqa: F401
    normalize_openai_messages,
    normalize_anthropic_messages,
    collapse_adjacent_same_role,
    collapse_openai_messages,
    collapse_anthropic_messages,
)
```

- [ ] **Step 6: Commit**

```bash
git add converters/message_normalizer.py tests/test_message_normalizer.py converters/__init__.py
git commit -m "feat(converters): add adjacent same-role message collapsing"
```

---

## Chunk 4: Deduplicate `convert_tool_calls_to_anthropic`

### Task 4: Remove duplicate implementation from `from_cursor_anthropic.py`

**Files:**
- Modify: `converters/from_cursor_anthropic.py`
- Modify: `tests/test_from_cursor_anthropic.py`

The functions `_parse_tool_call_arguments`, `_manual_convert_tool_calls_to_anthropic`, and
`convert_tool_calls_to_anthropic` are defined identically in both `from_cursor_anthropic.py`
and `from_cursor.py`. The canonical implementation lives in `from_cursor.py`. Remove the
duplicates from `from_cursor_anthropic.py` and import from `from_cursor.py` instead.

- [ ] **Step 1: Write a regression test to confirm the import still works after the change**

Add to `tests/test_from_cursor_anthropic.py`:

```python
def test_convert_tool_calls_to_anthropic_importable_from_anthropic_module():
    """After deduplication, the function must still be importable from both modules."""
    from converters.from_cursor_anthropic import convert_tool_calls_to_anthropic as fn_a
    from converters.from_cursor import convert_tool_calls_to_anthropic as fn_b
    # Both should be the same object (imported from same source)
    tc = [{"id": "c1", "function": {"name": "foo", "arguments": '{"x": 1}'}}]
    assert fn_a(tc) == fn_b(tc)
```

- [ ] **Step 2: Run to confirm test passes with current duplicated code**

```bash
pytest tests/test_from_cursor_anthropic.py::test_convert_tool_calls_to_anthropic_importable_from_anthropic_module -v
```
Expected: PASS (both currently exist independently).

- [ ] **Step 3: Edit `converters/from_cursor_anthropic.py`**

Remove the three duplicate functions and replace with imports from `from_cursor.py`.

Find and remove these blocks in `from_cursor_anthropic.py`:
- `def _parse_tool_call_arguments(...)` (lines ~130–140)
- `def _manual_convert_tool_calls_to_anthropic(...)` (lines ~143–165)
- `def convert_tool_calls_to_anthropic(...)` (lines ~168–202)

Add at the top of the file (after existing imports):

```python
# Canonical implementation lives in from_cursor.py — re-exported here for backward compat.
from converters.from_cursor import (  # noqa: F401
    _parse_tool_call_arguments,
    _manual_convert_tool_calls_to_anthropic,
    convert_tool_calls_to_anthropic,
)
```

- [ ] **Step 4: Run the full from_cursor_anthropic test suite**

```bash
pytest tests/test_from_cursor_anthropic.py -v
```
Expected: all green.

- [ ] **Step 5: Run broader test suite to catch any import breakage**

```bash
pytest tests/test_from_cursor.py tests/test_converters_init.py -v
```
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add converters/from_cursor_anthropic.py tests/test_from_cursor_anthropic.py
git commit -m "refactor(converters): deduplicate convert_tool_calls_to_anthropic — canonical in from_cursor.py"
```

---

## Chunk 5: Converter-specific metrics

### Task 5: Add converter counters to `tools/metrics.py` and wire into `cursor_helpers.py`

**Files:**
- Modify: `tools/metrics.py`
- Modify: `converters/cursor_helpers.py`
- Modify: `tests/test_metrics.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_metrics.py`:

```python
from tools.metrics import (
    inc_converter_non_text_block_dropped,
    inc_converter_tool_id_synthesized,
    inc_converter_support_preamble_scrubbed,
    inc_converter_litellm_fallback,
)


class TestConverterMetrics:
    def test_inc_converter_non_text_block_dropped_callable(self):
        # Must not raise — no-op is acceptable
        inc_converter_non_text_block_dropped(block_type="image_url")

    def test_inc_converter_tool_id_synthesized_callable(self):
        inc_converter_tool_id_synthesized()

    def test_inc_converter_support_preamble_scrubbed_callable(self):
        inc_converter_support_preamble_scrubbed()

    def test_inc_converter_litellm_fallback_callable(self):
        inc_converter_litellm_fallback()
```

- [ ] **Step 2: Run to verify tests fail**

```bash
pytest tests/test_metrics.py -v -k "converter"
```
Expected: `ImportError`.

- [ ] **Step 3: Add converter metric functions to `tools/metrics.py`**

Append to `tools/metrics.py`:

```python
def inc_converter_non_text_block_dropped(block_type: str, count: int = 1) -> None:
    """Increment counter for non-text content blocks silently dropped in _extract_text.

    block_type: the content block type that was dropped (e.g. 'image_url', 'audio').
    No-op until wired into external metrics backend.
    """
    pass


def inc_converter_tool_id_synthesized(count: int = 1) -> None:
    """Increment counter for tool call IDs synthesized due to missing id field.

    Tracks how often clients send tool calls without IDs — pipeline invariant
    violation that we recover from silently.
    No-op until wired into external metrics backend.
    """
    pass


def inc_converter_support_preamble_scrubbed(count: int = 1) -> None:
    """Increment counter for support assistant preamble scrubbed from response text.

    Tracks suppression bypass effectiveness — high values indicate the upstream
    model is frequently activating its Support Assistant persona.
    No-op until wired into external metrics backend.
    """
    pass


def inc_converter_litellm_fallback(count: int = 1) -> None:
    """Increment counter for litellm Anthropic tool converter fallback to manual path.

    Tracks litellm API instability — persistent high values may indicate a
    litellm version incompatibility.
    No-op until wired into external metrics backend.
    """
    pass
```

- [ ] **Step 4: Wire `inc_converter_non_text_block_dropped` into `cursor_helpers.py`**

In `converters/cursor_helpers.py`, in the `_extract_text` function, find the `btype != "text"` warning branch and add the metric call:

```python
# Before (existing):
if btype and btype != "text":
    import structlog as _structlog
    _structlog.get_logger().warning(
        "extract_text_dropped_non_text_block",
        block_type=btype,
    )

# After:
if btype and btype != "text":
    import structlog as _structlog
    _structlog.get_logger().warning(
        "extract_text_dropped_non_text_block",
        block_type=btype,
    )
    from tools.metrics import inc_converter_non_text_block_dropped
    inc_converter_non_text_block_dropped(block_type=btype)
```

- [ ] **Step 5: Wire `inc_converter_support_preamble_scrubbed` into `from_cursor.py`**

In `converters/from_cursor.py`, in `scrub_support_preamble`, after the `subn` call:

```python
# Before:
cleaned, count = _SUPPORT_PREAMBLE_RE.subn("", text)
cleaned = _scrub_the_editor(cleaned).strip()
return cleaned, count > 0

# After:
cleaned, count = _SUPPORT_PREAMBLE_RE.subn("", text)
cleaned = _scrub_the_editor(cleaned).strip()
if count > 0:
    from tools.metrics import inc_converter_support_preamble_scrubbed
    inc_converter_support_preamble_scrubbed()
return cleaned, count > 0
```

- [ ] **Step 6: Wire `inc_converter_litellm_fallback` into `from_cursor.py`**

In `converters/from_cursor.py`, in `convert_tool_calls_to_anthropic`, in the `except Exception` branch:

```python
# Before:
except Exception as exc:
    log.warning("litellm_anthropic_tool_use_conversion_failed", error=str(exc))
    # Fall back: now parse arguments to dict for manual path
    ...

# After:
except Exception as exc:
    log.warning("litellm_anthropic_tool_use_conversion_failed", error=str(exc))
    from tools.metrics import inc_converter_litellm_fallback
    inc_converter_litellm_fallback()
    # Fall back: now parse arguments to dict for manual path
    ...
```

- [ ] **Step 7: Run all metric + converter tests**

```bash
pytest tests/test_metrics.py tests/test_from_cursor.py tests/test_cursor_helpers.py -v
```
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add tools/metrics.py converters/cursor_helpers.py converters/from_cursor.py tests/test_metrics.py
git commit -m "feat(converters): add converter-specific metrics counters and wire into hot paths"
```

---

## Chunk 6: Export new symbols + full test run

### Task 6: Update `converters/__init__.py` and run full suite

**Files:**
- Modify: `converters/__init__.py`

- [ ] **Step 1: Update `converters/__init__.py` with all new exports**

Replace the existing `message_normalizer` import block and add new imports:

```python
from converters.message_normalizer import (  # noqa: F401
    normalize_openai_messages,
    normalize_anthropic_messages,
    collapse_adjacent_same_role,
    collapse_openai_messages,
    collapse_anthropic_messages,
)
from converters.validator import (  # noqa: F401
    validate_openai_messages,
    validate_anthropic_messages,
    validate_tool_calls,
    ConversionValidationError,
)
from converters.content_types import (  # noqa: F401
    extract_text_with_placeholders,
    UNSUPPORTED_BLOCK_PLACEHOLDER,
)
```

- [ ] **Step 2: Verify the full test suite passes**

```bash
pytest tests/ -m 'not integration' -x -q
```
Expected: all green, no import errors.

- [ ] **Step 3: Commit**

```bash
git add converters/__init__.py
git commit -m "feat(converters): export new validator, content_types, and collapse symbols"
```

- [ ] **Step 4: Update UPDATES.md**

Add a new session entry at the bottom of `UPDATES.md`:

```
## Session N — converters improvements (2026-03-29)

### What changed
- `converters/validator.py` — new: pre-conversion semantic validation for OpenAI/Anthropic messages and tool calls
- `converters/content_types.py` — new: multi-modal content block routing with placeholder insertion
- `converters/message_normalizer.py` — added `collapse_adjacent_same_role`, `collapse_openai_messages`, `collapse_anthropic_messages`
- `converters/from_cursor_anthropic.py` — removed duplicate tool call converter, now imports from `from_cursor.py`
- `converters/cursor_helpers.py` — metric call wired into `_extract_text` non-text drop path
- `converters/from_cursor.py` — metric calls wired into `scrub_support_preamble` and `convert_tool_calls_to_anthropic` litellm fallback
- `tools/metrics.py` — added `inc_converter_non_text_block_dropped`, `inc_converter_tool_id_synthesized`, `inc_converter_support_preamble_scrubbed`, `inc_converter_litellm_fallback`
- `converters/__init__.py` — exported all new public symbols

### Files modified
- converters/validator.py (created)
- converters/content_types.py (created)
- converters/message_normalizer.py
- converters/from_cursor_anthropic.py
- converters/cursor_helpers.py
- converters/from_cursor.py
- tools/metrics.py
- converters/__init__.py
- tests/test_converters_validator.py (created)
- tests/test_converters_content_types.py (created)
- tests/test_message_normalizer.py
- tests/test_from_cursor_anthropic.py
- tests/test_metrics.py

### Why
Converters layer had: silent data loss on non-text content blocks, no semantic validation before conversion (only structural normalization), duplicated tool converter logic across two files, no observability on conversion hot paths, and adjacent same-role message collapsing deferred but never implemented.

### Commits
| SHA | Description |
|---|---|
| TBD | feat(converters): add pre-conversion semantic validator |
| TBD | feat(converters): add content_types module — multi-modal placeholder routing |
| TBD | feat(converters): add adjacent same-role message collapsing |
| TBD | refactor(converters): deduplicate convert_tool_calls_to_anthropic |
| TBD | feat(converters): add converter-specific metrics counters |
| TBD | feat(converters): export new validator, content_types, and collapse symbols |
```

- [ ] **Step 5: Commit UPDATES.md**

```bash
git add UPDATES.md
git commit -m "docs: update UPDATES.md for converters improvements session"
```

- [ ] **Step 6: Push**

```bash
git push
```
