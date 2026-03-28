# tests/test_pipeline_tracer.py
import time
from pipeline.tracer import PipelineTracer, Span


def test_span_records_duration():
    tracer = PipelineTracer(request_id="r1")
    with tracer.span("upstream_call"):
        time.sleep(0.01)
    spans = tracer.spans()
    assert "upstream_call" in spans
    assert spans["upstream_call"] >= 10  # at least 10 ms


def test_multiple_spans():
    tracer = PipelineTracer(request_id="r1")
    with tracer.span("a"):
        pass
    with tracer.span("b"):
        pass
    spans = tracer.spans()
    assert "a" in spans and "b" in spans


def test_record_event():
    tracer = PipelineTracer(request_id="r1")
    tracer.record_event("tool_parse", calls=3, outcome="success")
    events = tracer.events()
    assert len(events) == 1
    assert events[0]["name"] == "tool_parse"
    assert events[0]["calls"] == 3


def test_flush_returns_dict():
    tracer = PipelineTracer(request_id="r1")
    with tracer.span("s1"):
        pass
    result = tracer.flush()
    assert result["request_id"] == "r1"
    assert "spans_ms" in result
    assert "s1" in result["spans_ms"]


def test_nested_span_names_do_not_conflict():
    tracer = PipelineTracer(request_id="r1")
    with tracer.span("outer"):
        with tracer.span("inner"):
            pass
    spans = tracer.spans()
    assert "outer" in spans
    assert "inner" in spans
