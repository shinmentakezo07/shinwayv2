"""
Shin Proxy — Stateful streaming tool call parser.

Extracted from tools/parse.py. Imports parse_tool_calls_from_text from
tools.parse inside __init__ to avoid circular imports at module load time.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from config import settings
from tools.score import _find_marker_pos

if TYPE_CHECKING:
    from tools.registry import ToolRegistry


class StreamingToolCallParser:
    """Stateful incremental parser — O(n) total scan across all chunks.

    Maintains marker detection and JSON-complete detection incrementally.
    parse_tool_calls_from_text is called exactly once — when the outermost
    JSON object is complete — instead of on every chunk after marker confirmed.
    """

    _LOOKBACK = len("[assistant_tool_calls]")

    def __init__(self, tools: list[dict], registry: "ToolRegistry | None" = None) -> None:
        from tools.parse import parse_tool_calls_from_text as _ptcft
        self._parse = _ptcft
        self._tools = tools
        self._registry = registry
        self.buf = ""
        self._scan_pos = 0
        self._marker_confirmed = False
        self._marker_pos: int = -1
        # Incremental JSON-complete tracking (post-marker only)
        self._json_start: int = -1   # position of the opening { or [ after marker
        self._depth: int = 0         # current brace depth
        self._in_str: bool = False   # inside a JSON string
        self._esc: bool = False      # next char is escaped
        self._json_complete: bool = False  # True once outermost } or ] seen
        self._last_result: list[dict] | None = None  # cached parse result
        self._root_char: str = "{"   # '{' or '[' — set when opening char is found
        self._close_char: str = "}"  # '}' or ']' — matching close for _root_char
        self._json_abandoned: bool = False  # True when payload exceeds max_tool_payload_bytes

    def feed(self, chunk: str) -> list[dict] | None:
        """Append chunk and return parsed calls when JSON is complete, else None."""
        self.buf += chunk

        # Phase 1: marker detection
        if not self._marker_confirmed:
            rescan_start = max(0, self._scan_pos - self._LOOKBACK)
            relative_pos = _find_marker_pos(self.buf[rescan_start:])
            if relative_pos >= 0:
                self._marker_pos = rescan_start + relative_pos
                self._marker_confirmed = True
                # Find the start of the JSON payload — first { or [ after marker
                post = self.buf[self._marker_pos:]
                newline_pos_inner = post.find('\n')
                after_newline = (
                    post[newline_pos_inner + 1:]
                    if newline_pos_inner >= 0
                    else post[len('[assistant_tool_calls]'):]
                )
                brace = after_newline.find('{')
                bracket = after_newline.find('[')
                offset = self._marker_pos + (
                    newline_pos_inner + 1
                    if newline_pos_inner >= 0
                    else len('[assistant_tool_calls]')
                )
                if bracket >= 0 and (brace < 0 or bracket < brace):
                    self._root_char = '['
                    self._close_char = ']'
                    self._json_start = offset + bracket
                elif brace >= 0:
                    self._root_char = '{'
                    self._close_char = '}'
                    self._json_start = offset + brace
                self._scan_pos = self._json_start if self._json_start >= 0 else self._marker_pos
            else:
                self._scan_pos = max(0, len(self.buf) - self._LOOKBACK)
                return None

        # Phase 2: JSON-complete detection already done — return cached result
        if self._json_complete:
            return self._last_result

        # Phase 3: still looking for opening { or [ (marker confirmed but neither seen yet)
        if self._json_start < 0:
            newline_pos = self.buf.find('\n', self._marker_pos)
            after_marker = (
                newline_pos + 1
                if newline_pos >= 0
                else self._marker_pos + len('[assistant_tool_calls]')
            )
            brace = self.buf.find('{', after_marker)
            bracket = self.buf.find('[', after_marker)
            if bracket >= 0 and (brace < 0 or bracket < brace):
                self._root_char = '['
                self._close_char = ']'
                self._json_start = bracket
            elif brace >= 0:
                self._root_char = '{'
                self._close_char = '}'
                self._json_start = brace
            else:
                return None
            self._scan_pos = self._json_start

        # Phase 4: walk only NEW characters added by this chunk
        if self._json_start >= 0:
            if len(self.buf) - self._json_start > settings.max_tool_payload_bytes:
                import structlog as _sl
                _sl.get_logger().warning(
                    "tool_streaming_payload_too_large",
                    size=len(self.buf) - self._json_start,
                    limit=settings.max_tool_payload_bytes,
                )
                self._json_abandoned = True
                return None

        scan_from = max(self._json_start, self._scan_pos)
        i = scan_from
        buf = self.buf
        buf_len = len(buf)
        open_ch = self._root_char
        close_ch = self._close_char
        while i < buf_len:
            ch = buf[i]
            if self._esc:
                self._esc = False
            elif ch == '\\' and self._in_str:
                self._esc = True
            elif ch == '"':
                self._in_str = not self._in_str
            elif not self._in_str:
                if ch == open_ch:
                    self._depth += 1
                elif ch == close_ch:
                    self._depth -= 1
                    if self._depth == 0:
                        # Outermost } or ] found — JSON is complete; parse exactly once
                        self._json_complete = True
                        self._scan_pos = i + 1
                        self._last_result = self._parse(
                            buf[self._marker_pos:], self._tools, streaming=True,
                            registry=self._registry,
                        )
                        return self._last_result
            i += 1
        self._scan_pos = buf_len
        return None

    def finalize(self) -> list[dict] | None:
        """Non-streaming parse on the complete buffer — call once stream closes."""
        if self._json_abandoned or not self.buf:
            return None
        parse_slice = self.buf[self._marker_pos:] if self._marker_pos >= 0 else self.buf
        return self._parse(parse_slice, self._tools, streaming=False, registry=self._registry)
