# tests/test_pipeline_context.py
import pytest
import time
from pipeline.context import PipelineContext

def test_default_state():
    ctx = PipelineContext(request_id="req-1")
    assert ctx.request_id == "req-1"
    assert ctx.suppression_attempts == 0
    assert ctx.fallback_model_used is None
    assert ctx.ttft_ms is None
    assert ctx.bytes_streamed == 0
    assert ctx.tool_calls_parsed == 0
    assert ctx.started_at > 0

def test_record_ttft():
    ctx = PipelineContext(request_id="req-2")
    ctx.record_ttft()
    assert ctx.ttft_ms is not None
    assert ctx.ttft_ms >= 0

def test_record_ttft_only_once():
    ctx = PipelineContext(request_id="req-3")
    ctx.record_ttft()
    first = ctx.ttft_ms
    ctx.record_ttft()  # second call must be a no-op
    assert ctx.ttft_ms == first

def test_latency_ms():
    ctx = PipelineContext(request_id="req-4")
    ms = ctx.latency_ms()
    assert ms >= 0

def test_increment_suppression():
    ctx = PipelineContext(request_id="req-5")
    ctx.suppression_attempts += 1
    assert ctx.suppression_attempts == 1
