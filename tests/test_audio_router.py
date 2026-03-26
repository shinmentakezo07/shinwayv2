"""Tests for audio stub router."""
from __future__ import annotations
import os
import pytest
os.environ.setdefault("LITELLM_MASTER_KEY", "sk-test")
os.environ.setdefault("CURSOR_COOKIE", "WorkosCursorSessionToken=test")

from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from app import create_app
    return TestClient(create_app())


def test_transcriptions_returns_501(client):
    resp = client.post(
        "/v1/audio/transcriptions",
        data={"model": "whisper-1"},
        files={"file": ("audio.mp3", b"fake", "audio/mpeg")},
        headers={"Authorization": "Bearer sk-test"},
    )
    assert resp.status_code == 501
    body = resp.json()
    assert body["error"]["code"] == "audio_not_supported"


def test_speech_returns_501(client):
    resp = client.post(
        "/v1/audio/speech",
        json={"model": "tts-1", "input": "Hello", "voice": "alloy"},
        headers={"Authorization": "Bearer sk-test"},
    )
    assert resp.status_code == 501
    assert resp.json()["error"]["code"] == "audio_not_supported"


def test_translations_returns_501(client):
    resp = client.post(
        "/v1/audio/translations",
        data={"model": "whisper-1"},
        files={"file": ("audio.mp3", b"fake", "audio/mpeg")},
        headers={"Authorization": "Bearer sk-test"},
    )
    assert resp.status_code == 501


def test_audio_requires_auth(client):
    resp = client.post("/v1/audio/speech", json={"input": "hi"})
    assert resp.status_code == 401
