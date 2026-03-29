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

    def test_input_text_block_extracted(self):
        content = [{"type": "input_text", "text": "user input"}]
        assert extract_text_with_placeholders(content) == "user input"

    def test_output_text_block_extracted(self):
        content = [{"type": "output_text", "text": "response"}]
        assert extract_text_with_placeholders(content) == "response"

    def test_mixed_text_and_image_blocks(self):
        content = [
            {"type": "text", "text": "before"},
            {"type": "image", "source": {}},
            {"type": "text", "text": "after"},
        ]
        result = extract_text_with_placeholders(content)
        assert result == f"before{UNSUPPORTED_BLOCK_PLACEHOLDER}after"

    def test_non_dict_blocks_skipped(self):
        content = ["bad", {"type": "text", "text": "ok"}]
        assert extract_text_with_placeholders(content) == "ok"

    def test_non_list_non_string_returns_empty(self):
        assert extract_text_with_placeholders(42) == ""
