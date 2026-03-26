"""Tests for Files API router."""
from __future__ import annotations
import os
import pytest
os.environ.setdefault("LITELLM_MASTER_KEY", "sk-test")
os.environ.setdefault("CURSOR_COOKIE", "WorkosCursorSessionToken=test")

import config
import middleware.auth as _auth
from fastapi.testclient import TestClient

_TEST_KEY = "sk-test-files"


@pytest.fixture(autouse=True)
def clear_files():
    """Reset the in-memory file stores between tests."""
    import routers.files as _f
    _f._files.clear()
    _f._file_content.clear()
    yield
    _f._files.clear()
    _f._file_content.clear()


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(config.settings, "master_key", _TEST_KEY)
    _auth._env_keys.cache_clear()
    from app import create_app
    with TestClient(create_app()) as c:
        yield c
    _auth._env_keys.cache_clear()


def test_upload_file_returns_object(client):
    resp = client.post(
        "/v1/files",
        data={"purpose": "assistants"},
        files={"file": ("data.jsonl", b'{"a":1}\n', "application/jsonl")},
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "file"
    assert body["id"].startswith("file-")
    assert body["purpose"] == "assistants"
    assert body["filename"] == "data.jsonl"
    assert body["bytes"] == len(b'{"a":1}\n')
    assert body["status"] == "processed"


def test_list_files_returns_uploaded(client):
    client.post(
        "/v1/files",
        data={"purpose": "batch"},
        files={"file": ("x.jsonl", b'{"x":1}\n', "application/jsonl")},
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    resp = client.get("/v1/files", headers={"Authorization": f"Bearer {_TEST_KEY}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "list"
    assert len(body["data"]) == 1


def test_get_file_by_id(client):
    up = client.post(
        "/v1/files",
        data={"purpose": "assistants"},
        files={"file": ("y.jsonl", b'{"y":1}\n', "application/jsonl")},
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    file_id = up.json()["id"]
    resp = client.get(f"/v1/files/{file_id}", headers={"Authorization": f"Bearer {_TEST_KEY}"})
    assert resp.status_code == 200
    assert resp.json()["id"] == file_id


def test_get_missing_file_returns_404(client):
    resp = client.get("/v1/files/file-notexist", headers={"Authorization": f"Bearer {_TEST_KEY}"})
    assert resp.status_code == 404


def test_delete_file(client):
    up = client.post(
        "/v1/files",
        data={"purpose": "batch"},
        files={"file": ("z.jsonl", b'{"z":1}\n', "application/jsonl")},
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    file_id = up.json()["id"]
    resp = client.delete(f"/v1/files/{file_id}", headers={"Authorization": f"Bearer {_TEST_KEY}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] is True
    assert body["id"] == file_id


def test_delete_missing_file_returns_404(client):
    resp = client.delete("/v1/files/file-gone", headers={"Authorization": f"Bearer {_TEST_KEY}"})
    assert resp.status_code == 404


def test_files_requires_auth(client):
    resp = client.get("/v1/files")
    assert resp.status_code == 401


def test_get_file_content_returns_bytes(client):
    up = client.post(
        "/v1/files",
        data={"purpose": "assistants"},
        files={"file": ("data.jsonl", b'{"a":1}\n', "application/jsonl")},
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    file_id = up.json()["id"]
    resp = client.get(f"/v1/files/{file_id}/content", headers={"Authorization": f"Bearer {_TEST_KEY}"})
    assert resp.status_code == 200
    assert resp.content == b'{"a":1}\n'
    assert "attachment" in resp.headers.get("content-disposition", "")


def test_get_content_missing_file_returns_404(client):
    resp = client.get("/v1/files/file-notexist/content", headers={"Authorization": f"Bearer {_TEST_KEY}"})
    assert resp.status_code == 404


def test_delete_removes_content_too(client):
    up = client.post(
        "/v1/files",
        data={"purpose": "batch"},
        files={"file": ("del.jsonl", b'{}\n', "application/jsonl")},
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    file_id = up.json()["id"]
    client.delete(f"/v1/files/{file_id}", headers={"Authorization": f"Bearer {_TEST_KEY}"})
    resp = client.get(f"/v1/files/{file_id}/content", headers={"Authorization": f"Bearer {_TEST_KEY}"})
    assert resp.status_code == 404
