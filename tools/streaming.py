"""
Shin Proxy — Stateful streaming tool call parser.

Extracted from tools/parse.py. Imports parse_tool_calls_from_text from
tools.parse inside __init__ to avoid circular imports at module load time.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

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
        self._json_start: int = -1   # position of the opening { after marker
        self._depth: int = 0         # current brace depth
        self._in_str: bool = False   # inside a JSON string
        self._esc: bool = False      # next char is escaped
        self._json_complete: bool = False  # True once outermost } seen
        self._last_result: list[dict] | None = None  # cached parse result

    def feed(self, chunk: str) -> list[dict] | None:
        """Append chunk and return parsed calls when JSON is complete, else None."""
        self.buf += chunk

        # Phase 1: marker detection (same as before)
        if not self._marker_confirmed:
            rescan_start = max(0, self._scan_pos - self._LOOKBACK)
            relative_pos = _find_marker_pos(self.buf[rescan_start:])
            if relative_pos >= 0:
                self._marker_pos = rescan_start + relative_pos
                self._marker_confirmed = True
                # Find the start of the JSON payload (first { after marker)
                newline_pos = self.buf.find('\n', self._marker_pos)
                after_marker = (
                    newline_pos + 1
                    if newline_pos >= 0
                    else self._marker_pos + len('[assistant_tool_calls]')
                )
                brace_pos = self.buf.find('{', after_marker)
                if brace_pos >= 0:
                    self._json_start = brace_pos
                    self._scan_pos = brace_pos  # start incremental scan from here
            else:
                self._scan_pos = max(0, len(self.buf) - self._LOOKBACK)
                return None

        # Phase 2: JSON-complete detection already done — return cached result
        if self._json_complete:
            return self._last_result

        # Phase 3: still looking for opening { (marker confirmed but { not yet seen)
        if self._json_start < 0:
            newline_pos = self.buf.find('\n', self._marker_pos)
            after_marker = (
                newline_pos + 1
                if newline_pos >= 0
                else self._marker_pos + len('[assistant_tool_calls]')
            )
            brace_pos = self.buf.find('{', after_marker)
            if brace_pos < 0:
                return None
            self._json_start = brace_pos
            self._scan_pos = brace_pos

        # Phase 4: walk only NEW characters added by this chunk
        scan_from = max(self._json_start, self._scan_pos)
        i = scan_from
        buf = self.buf
        buf_len = len(buf)
        while i < buf_len:
            ch = buf[i]
            if self._esc:
                self._esc = False
            elif ch == '\\' and self._in_str:
                self._esc = True
            elif ch == '"':
                self._in_str = not self._in_str
            elif not self._in_str:
                if ch == '{':
                    self._depth += 1
                elif ch == '}':
                    self._depth -= 1
                    if self._depth == 0:
                        # Outermost } found — JSON is complete; parse exactly once
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
        if not self.buf:
            return None
        parse_slice = self.buf[self._marker_pos:] if self._marker_pos >= 0 else self.buf
        return self._parse(parse_slice, self._tools, streaming=False, registry=self._registry)
