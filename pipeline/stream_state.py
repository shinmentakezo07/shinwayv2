"""Streaming phase state machine.

Defines the phases a streaming pipeline generator can be in.
The `StreamStateTracker` tracks the current phase and history,
making valid transitions explicit and unit-testable independent
of the HTTP layer.

The streaming generators (stream_openai.py, stream_anthropic.py)
use StreamPhase to name their current phase via `tracker.transition()`
instead of relying on a flat collection of boolean locals.
"""
from __future__ import annotations

from enum import Enum


class StreamPhase(str, Enum):
    """All phases of a streaming pipeline run."""

    INIT = "init"                             # Before any stream data received
    STREAMING_TEXT = "streaming_text"         # Model emitting text content
    MARKER_DETECTED = "marker_detected"       # [assistant_tool_calls] marker seen
    PARSING_TOOL_JSON = "parsing_tool_json"   # Accumulating tool call JSON
    TOOL_COMPLETE = "tool_complete"           # Tool call JSON fully parsed
    FINISHED = "finished"                     # Stream closed cleanly
    SUPPRESSED = "suppressed"                 # Suppression signal detected
    ABANDONED = "abandoned"                   # Stream abandoned (payload too large, timeout)


_TERMINAL_PHASES = {StreamPhase.FINISHED, StreamPhase.SUPPRESSED, StreamPhase.ABANDONED}


class StreamStateTracker:
    """Tracks streaming generator phase transitions.

    Maintains current phase and full transition history.
    Does not enforce valid transitions — the generator is authoritative
    on what transitions are legal. This class names and records them.
    """

    def __init__(self) -> None:
        self._phase: StreamPhase = StreamPhase.INIT
        self._history: list[StreamPhase] = [StreamPhase.INIT]

    @property
    def phase(self) -> StreamPhase:
        """Current streaming phase."""
        return self._phase

    @property
    def history(self) -> list[StreamPhase]:
        """Ordered list of all phases visited (including current)."""
        return list(self._history)

    def transition(self, new_phase: StreamPhase) -> None:
        """Move to a new phase and record it in history.

        Args:
            new_phase: The phase to transition to.
        """
        self._phase = new_phase
        self._history.append(new_phase)

    def is_terminal(self) -> bool:
        """Return True if the current phase is a terminal (end) state."""
        return self._phase in _TERMINAL_PHASES
