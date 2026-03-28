# tests/test_stream_state.py
from pipeline.stream_state import StreamPhase, StreamStateTracker


def test_initial_phase_is_init():
    tracker = StreamStateTracker()
    assert tracker.phase == StreamPhase.INIT


def test_transition_to_streaming_text():
    tracker = StreamStateTracker()
    tracker.transition(StreamPhase.STREAMING_TEXT)
    assert tracker.phase == StreamPhase.STREAMING_TEXT


def test_transition_to_marker_detected():
    tracker = StreamStateTracker()
    tracker.transition(StreamPhase.STREAMING_TEXT)
    tracker.transition(StreamPhase.MARKER_DETECTED)
    assert tracker.phase == StreamPhase.MARKER_DETECTED


def test_transition_records_history():
    tracker = StreamStateTracker()
    tracker.transition(StreamPhase.STREAMING_TEXT)
    tracker.transition(StreamPhase.TOOL_COMPLETE)
    assert StreamPhase.STREAMING_TEXT in tracker.history
    assert StreamPhase.TOOL_COMPLETE in tracker.history


def test_is_terminal_finished():
    tracker = StreamStateTracker()
    tracker.transition(StreamPhase.FINISHED)
    assert tracker.is_terminal()


def test_is_terminal_abandoned():
    tracker = StreamStateTracker()
    tracker.transition(StreamPhase.ABANDONED)
    assert tracker.is_terminal()


def test_is_not_terminal_streaming_text():
    tracker = StreamStateTracker()
    tracker.transition(StreamPhase.STREAMING_TEXT)
    assert not tracker.is_terminal()


def test_all_phases_are_string_comparable():
    for phase in StreamPhase:
        assert isinstance(phase.value, str)
