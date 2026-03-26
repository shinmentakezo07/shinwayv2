"""Tests for fine-tuning stub router."""
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


def test_create_job_returns_501(client):
    resp = client.post(
        "/v1/fine_tuning/jobs",
        json={"model": "gpt-4o", "training_file": "file-abc"},
        headers={"Authorization": "Bearer sk-test"},
    )
    assert resp.status_code == 501
    body = resp.json()
    assert body["error"]["code"] == "fine_tuning_not_supported"
    assert body["error"]["type"] == "not_implemented_error"


def test_list_jobs_returns_501(client):
    resp = client.get(
        "/v1/fine_tuning/jobs",
        headers={"Authorization": "Bearer sk-test"},
    )
    assert resp.status_code == 501


def test_get_job_returns_501(client):
    resp = client.get(
        "/v1/fine_tuning/jobs/ftjob-abc",
        headers={"Authorization": "Bearer sk-test"},
    )
    assert resp.status_code == 501


def test_cancel_job_returns_501(client):
    resp = client.post(
        "/v1/fine_tuning/jobs/ftjob-abc/cancel",
        headers={"Authorization": "Bearer sk-test"},
    )
    assert resp.status_code == 501


def test_fine_tuning_requires_auth(client):
    resp = client.post("/v1/fine_tuning/jobs", json={})
    assert resp.status_code == 401
