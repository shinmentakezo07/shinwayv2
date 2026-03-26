# New Router Modules Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 4 new router modules to the Shinway proxy: `embeddings`, `usage`, `completions` (already exists in openai.py — promote to proper 501 stub), `files`, `audio`, `fine_tuning`, and `webhooks` — completing the OpenAI API surface and adding a proper usage/reporting API.

**Architecture:** Each new router is a self-contained `APIRouter` in `routers/`. Unsupported endpoints return a clean 501 with a machine-readable error code. The `usage` router reads from the existing `AnalyticsStore` singleton and adds a per-day breakdown by querying the rolling log. All routers are registered in `app.py`. Storage-backed routers (`files`, `webhooks`) use the aiosqlite pattern from `storage/batch.py`. No new dependencies introduced.

**Tech Stack:** Python 3.12, FastAPI, aiosqlite, structlog, pydantic-settings — all already present.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `routers/embeddings.py` | CREATE | `POST /v1/embeddings` — 501 stub with machine-readable error |
| `routers/audio.py` | CREATE | `POST /v1/audio/transcriptions`, `POST /v1/audio/speech` — 501 stubs |
| `routers/files.py` | CREATE | `POST /v1/files`, `GET /v1/files`, `GET /v1/files/{id}`, `DELETE /v1/files/{id}` — in-memory store |
| `routers/fine_tuning.py` | CREATE | `POST /v1/fine_tuning/jobs`, `GET /v1/fine_tuning/jobs`, `GET /v1/fine_tuning/jobs/{id}` — 501 stubs |
| `routers/webhooks.py` | CREATE | `POST /v1/internal/webhooks`, `GET /v1/internal/webhooks`, `DELETE /v1/internal/webhooks/{id}` — SQLite-backed |
| `routers/usage.py` | CREATE | `GET /v1/usage/daily`, `GET /v1/usage/keys/{key}` — reads from analytics singleton |
| `storage/webhooks.py` | CREATE | `WebhookStore` — aiosqlite store for webhook registrations |
| `app.py` | MODIFY | Register all 6 new routers in `create_app()` and init `webhook_store` in lifespan |
| `tests/test_embeddings_router.py` | CREATE | Unit tests for embeddings stub |
| `tests/test_audio_router.py` | CREATE | Unit tests for audio stubs |
| `tests/test_files_router.py` | CREATE | Unit tests for files CRUD |
| `tests/test_fine_tuning_router.py` | CREATE | Unit tests for fine_tuning stubs |
| `tests/test_webhooks_router.py` | CREATE | Unit tests for webhooks CRUD |
| `tests/test_usage_router.py` | CREATE | Unit tests for usage reporting |

---

## Chunk 1: Stub routers — embeddings, audio, fine_tuning

These three routers have no storage. They auth the request, return 501, and are fully tested.

### Task 1: `routers/embeddings.py`

**Files:**
- Create: `routers/embeddings.py`
- Create: `tests/test_embeddings_router.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_embeddings_router.py
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


def test_embeddings_returns_501(client):
    resp = client.post(
        "/v1/embeddings",
        json={"model": "text-embedding-3-small", "input": "hello"},
        headers={"Authorization": "Bearer sk-test"},
    )
    assert resp.status_code == 501
    body = resp.json()
    assert body["error"]["code"] == "embeddings_not_supported"


def test_embeddings_requires_auth(client):
    resp = client.post("/v1/embeddings", json={"input": "hi"})
    assert resp.status_code == 401
```

- [ ] **Step 2: Run test — expect FAIL (route not yet registered)**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_embeddings_router.py -v
```
Expected: ImportError or 404

- [ ] **Step 3: Create `routers/embeddings.py`**

```python
"""
Shin Proxy — Embeddings stub.

Embeddings are not supported by the Cursor upstream.
Returns a clean 501 so clients that probe capabilities don't hang.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from middleware.auth import verify_bearer
from middleware.rate_limit import enforce_rate_limit

router = APIRouter()
log = structlog.get_logger()

_NOT_SUPPORTED = JSONResponse(
    status_code=501,
    content={
        "error": {
            "message": (
                "Embeddings are not supported by this proxy. "
                "Use a dedicated embeddings provider (OpenAI, Cohere, etc.)."
            ),
            "type": "not_implemented_error",
            "code": "embeddings_not_supported",
        }
    },
)


@router.post("/v1/embeddings")
async def embeddings(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Embeddings — not supported by this proxy."""
    await verify_bearer(authorization)
    enforce_rate_limit(await verify_bearer(authorization), request=request)
    log.info("embeddings_stub_called")
    return _NOT_SUPPORTED
```

- [ ] **Step 4: Register router in `app.py`**

In `create_app()`, after `from routers.batch import router as batch_router`:
```python
from routers.embeddings import router as embeddings_router
```
And after `app.include_router(batch_router)`:
```python
app.include_router(embeddings_router)
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_embeddings_router.py -v
```
Expected: 2 passed

- [ ] **Step 6: Remove duplicate stub from `routers/openai.py`**

Delete the `/v1/embeddings` stub endpoint (lines ~288-298) from `routers/openai.py` since `routers/embeddings.py` now owns it.

- [ ] **Step 7: Run full test suite to confirm no regression**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/ -m 'not integration' -q
```
Expected: all passing

- [ ] **Step 8: Commit**

```bash
git add routers/embeddings.py tests/test_embeddings_router.py routers/openai.py app.py
git commit -m "feat(routers): add embeddings router — clean 501, remove stub from openai.py"
```

---

### Task 2: `routers/audio.py`

**Files:**
- Create: `routers/audio.py`
- Create: `tests/test_audio_router.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_audio_router.py
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
    assert resp.json()["error"]["code"] == "audio_not_supported"


def test_speech_returns_501(client):
    resp = client.post(
        "/v1/audio/speech",
        json={"model": "tts-1", "input": "Hello", "voice": "alloy"},
        headers={"Authorization": "Bearer sk-test"},
    )
    assert resp.status_code == 501
    assert resp.json()["error"]["code"] == "audio_not_supported"


def test_audio_requires_auth(client):
    resp = client.post("/v1/audio/speech", json={"input": "hi"})
    assert resp.status_code == 401
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_audio_router.py -v
```

- [ ] **Step 3: Create `routers/audio.py`**

```python
"""
Shin Proxy — Audio API stubs.

Audio (speech synthesis, transcription) is not supported by the Cursor upstream.
Returns clean 501 responses so clients that enumerate capabilities don't hang.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from middleware.auth import verify_bearer
from middleware.rate_limit import enforce_rate_limit

router = APIRouter()
log = structlog.get_logger()

_NOT_SUPPORTED = {
    "error": {
        "message": (
            "Audio endpoints are not supported by this proxy. "
            "Use the OpenAI API directly for speech and transcription."
        ),
        "type": "not_implemented_error",
        "code": "audio_not_supported",
    }
}


@router.post("/v1/audio/transcriptions")
async def audio_transcriptions(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Audio transcription — not supported."""
    await verify_bearer(authorization)
    log.info("audio_transcriptions_stub_called")
    return JSONResponse(status_code=501, content=_NOT_SUPPORTED)


@router.post("/v1/audio/speech")
async def audio_speech(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Text-to-speech — not supported."""
    await verify_bearer(authorization)
    log.info("audio_speech_stub_called")
    return JSONResponse(status_code=501, content=_NOT_SUPPORTED)


@router.post("/v1/audio/translations")
async def audio_translations(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Audio translation — not supported."""
    await verify_bearer(authorization)
    return JSONResponse(status_code=501, content=_NOT_SUPPORTED)
```

- [ ] **Step 4: Register in `app.py`**

```python
from routers.audio import router as audio_router
# ...
app.include_router(audio_router)
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_audio_router.py -v
```

- [ ] **Step 6: Commit**

```bash
git add routers/audio.py tests/test_audio_router.py app.py
git commit -m "feat(routers): add audio router — clean 501 for transcription, speech, translation"
```

---

### Task 3: `routers/fine_tuning.py`

**Files:**
- Create: `routers/fine_tuning.py`
- Create: `tests/test_fine_tuning_router.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_fine_tuning_router.py
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
    assert resp.json()["error"]["code"] == "fine_tuning_not_supported"


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


def test_fine_tuning_requires_auth(client):
    resp = client.post("/v1/fine_tuning/jobs", json={})
    assert resp.status_code == 401
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_fine_tuning_router.py -v
```

- [ ] **Step 3: Create `routers/fine_tuning.py`**

```python
"""
Shin Proxy — Fine-tuning API stubs.

Fine-tuning is not supported by the Cursor upstream.
Stubs complete the OpenAI API surface so clients that enumerate
capabilities don't receive connection errors.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from middleware.auth import verify_bearer

router = APIRouter()
log = structlog.get_logger()

_NOT_SUPPORTED = {
    "error": {
        "message": (
            "Fine-tuning is not supported by this proxy. "
            "Use the OpenAI API directly for fine-tuning."
        ),
        "type": "not_implemented_error",
        "code": "fine_tuning_not_supported",
    }
}


@router.post("/v1/fine_tuning/jobs")
async def create_fine_tuning_job(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Create fine-tuning job — not supported."""
    await verify_bearer(authorization)
    return JSONResponse(status_code=501, content=_NOT_SUPPORTED)


@router.get("/v1/fine_tuning/jobs")
async def list_fine_tuning_jobs(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """List fine-tuning jobs — not supported."""
    await verify_bearer(authorization)
    return JSONResponse(status_code=501, content=_NOT_SUPPORTED)


@router.get("/v1/fine_tuning/jobs/{job_id}")
async def get_fine_tuning_job(
    job_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Get fine-tuning job status — not supported."""
    await verify_bearer(authorization)
    return JSONResponse(status_code=501, content=_NOT_SUPPORTED)


@router.post("/v1/fine_tuning/jobs/{job_id}/cancel")
async def cancel_fine_tuning_job(
    job_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Cancel fine-tuning job — not supported."""
    await verify_bearer(authorization)
    return JSONResponse(status_code=501, content=_NOT_SUPPORTED)
```

- [ ] **Step 4: Register in `app.py`**

```python
from routers.fine_tuning import router as fine_tuning_router
# ...
app.include_router(fine_tuning_router)
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_fine_tuning_router.py -v
```

- [ ] **Step 6: Commit**

```bash
git add routers/fine_tuning.py tests/test_fine_tuning_router.py app.py
git commit -m "feat(routers): add fine_tuning router — 501 stubs for job create/list/get/cancel"
```

---

## Chunk 2: Files router (in-memory store)

The Files API is needed by clients that upload training data or batch inputs before submitting jobs. Since Cursor doesn't use files, we store metadata in-memory and return file IDs. No actual file content is processed — upload is accepted, metadata is stored in a dict keyed by `file-<uuid>`, and DELETE removes it.

### Task 4: `routers/files.py`

**Files:**
- Create: `routers/files.py`
- Create: `tests/test_files_router.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_files_router.py
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


def test_upload_file_returns_object(client):
    resp = client.post(
        "/v1/files",
        data={"purpose": "assistants"},
        files={"file": ("data.jsonl", b'{"a":1}\n', "application/jsonl")},
        headers={"Authorization": "Bearer sk-test"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "file"
    assert body["id"].startswith("file-")
    assert body["purpose"] == "assistants"
    assert body["filename"] == "data.jsonl"


def test_list_files_returns_uploaded(client):
    client.post(
        "/v1/files",
        data={"purpose": "batch"},
        files={"file": ("x.jsonl", b'{"x":1}\n', "application/jsonl")},
        headers={"Authorization": "Bearer sk-test"},
    )
    resp = client.get("/v1/files", headers={"Authorization": "Bearer sk-test"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "list"
    assert len(body["data"]) >= 1


def test_get_file_by_id(client):
    up = client.post(
        "/v1/files",
        data={"purpose": "assistants"},
        files={"file": ("y.jsonl", b'{"y":1}\n', "application/jsonl")},
        headers={"Authorization": "Bearer sk-test"},
    )
    file_id = up.json()["id"]
    resp = client.get(f"/v1/files/{file_id}", headers={"Authorization": "Bearer sk-test"})
    assert resp.status_code == 200
    assert resp.json()["id"] == file_id


def test_get_missing_file_returns_404(client):
    resp = client.get("/v1/files/file-notexist", headers={"Authorization": "Bearer sk-test"})
    assert resp.status_code == 404


def test_delete_file(client):
    up = client.post(
        "/v1/files",
        data={"purpose": "batch"},
        files={"file": ("z.jsonl", b'{"z":1}\n', "application/jsonl")},
        headers={"Authorization": "Bearer sk-test"},
    )
    file_id = up.json()["id"]
    resp = client.delete(f"/v1/files/{file_id}", headers={"Authorization": "Bearer sk-test"})
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


def test_delete_missing_file_returns_404(client):
    resp = client.delete("/v1/files/file-gone", headers={"Authorization": "Bearer sk-test"})
    assert resp.status_code == 404


def test_files_requires_auth(client):
    resp = client.get("/v1/files")
    assert resp.status_code == 401
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_files_router.py -v
```

- [ ] **Step 3: Create `routers/files.py`**

```python
"""
Shin Proxy — OpenAI-compatible Files API.

Files are stored in-memory (metadata only — no actual file content is kept).
This satisfies clients that call /v1/files before submitting batch jobs.
File IDs are stable within a single server process lifetime.

Endpoints:
    POST   /v1/files
    GET    /v1/files
    GET    /v1/files/{file_id}
    DELETE /v1/files/{file_id}
"""
from __future__ import annotations

import time
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Form, Header, Request, UploadFile
from fastapi.responses import JSONResponse

from middleware.auth import verify_bearer
from middleware.rate_limit import enforce_rate_limit

router = APIRouter()
log = structlog.get_logger()

# In-memory store: file_id -> file metadata dict
# Key is scoped to process lifetime — no persistence needed for this use case.
_files: dict[str, dict[str, Any]] = {}


def _file_object(file_id: str, filename: str, purpose: str, size: int) -> dict[str, Any]:
    return {
        "id": file_id,
        "object": "file",
        "bytes": size,
        "created_at": int(time.time()),
        "filename": filename,
        "purpose": purpose,
        "status": "processed",
        "status_details": None,
    }


@router.post("/v1/files")
async def upload_file(
    request: Request,
    file: UploadFile,
    purpose: str = Form(...),
    authorization: str | None = Header(default=None),
):
    """Upload a file — stores metadata in-memory."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)
    content = await file.read()
    file_id = f"file-{uuid.uuid4().hex[:24]}"
    obj = _file_object(file_id, file.filename or "upload", purpose, len(content))
    _files[file_id] = obj
    log.info("file_uploaded", file_id=file_id, purpose=purpose, bytes=len(content))
    return JSONResponse(obj)


@router.get("/v1/files")
async def list_files(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """List all uploaded files."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)
    return JSONResponse({
        "object": "list",
        "data": list(_files.values()),
    })


@router.get("/v1/files/{file_id}")
async def get_file(
    file_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Retrieve file metadata by ID."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)
    obj = _files.get(file_id)
    if obj is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"File '{file_id}' not found", "type": "not_found_error", "code": "404"}},
        )
    return JSONResponse(obj)


@router.delete("/v1/files/{file_id}")
async def delete_file(
    file_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Delete a file record."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)
    if file_id not in _files:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"File '{file_id}' not found", "type": "not_found_error", "code": "404"}},
        )
    del _files[file_id]
    log.info("file_deleted", file_id=file_id)
    return JSONResponse({"id": file_id, "object": "file", "deleted": True})
```

- [ ] **Step 4: Register in `app.py`**

```python
from routers.files import router as files_router
# ...
app.include_router(files_router)
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_files_router.py -v
```
Expected: 7 passed

- [ ] **Step 6: Commit**

```bash
git add routers/files.py tests/test_files_router.py app.py
git commit -m "feat(routers): add files router — in-memory upload/list/get/delete"
```

---

## Chunk 3: Usage router

Reads from the existing `AnalyticsStore` singleton. No new storage. Adds per-day breakdown by scanning the rolling log and grouping by `int(ts / 86400) * 86400`.

### Task 5: `routers/usage.py`

**Files:**
- Create: `routers/usage.py`
- Create: `tests/test_usage_router.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_usage_router.py
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


def test_daily_usage_returns_list(client):
    resp = client.get("/v1/usage/daily", headers={"Authorization": "Bearer sk-test"})
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert isinstance(body["data"], list)


def test_daily_usage_accepts_limit_param(client):
    resp = client.get("/v1/usage/daily?limit=7", headers={"Authorization": "Bearer sk-test"})
    assert resp.status_code == 200


def test_key_usage_returns_stats(client):
    resp = client.get("/v1/usage/keys/sk-test", headers={"Authorization": "Bearer sk-test"})
    assert resp.status_code == 200
    body = resp.json()
    assert "requests" in body
    assert "estimated_cost_usd" in body


def test_usage_requires_auth(client):
    resp = client.get("/v1/usage/daily")
    assert resp.status_code == 401
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_usage_router.py -v
```

- [ ] **Step 3: Create `routers/usage.py`**

```python
"""
Shin Proxy — Usage / billing reporting API.

Endpoints:
    GET /v1/usage/daily                  — per-day aggregates from rolling log
    GET /v1/usage/keys/{key}             — per-key lifetime stats
    GET /v1/usage/summary                — total spend + request counts across all keys
"""
from __future__ import annotations

import time
from collections import defaultdict

import structlog
from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse

from analytics import analytics
from middleware.auth import verify_bearer
from middleware.rate_limit import enforce_rate_limit

router = APIRouter()
log = structlog.get_logger()

_SECONDS_PER_DAY = 86_400


def _day_bucket(ts: int) -> int:
    """Return the start-of-day unix timestamp for a given ts."""
    return (ts // _SECONDS_PER_DAY) * _SECONDS_PER_DAY


@router.get("/v1/usage/daily")
async def daily_usage(
    request: Request,
    limit: int = Query(default=30, ge=1, le=90),
    authorization: str | None = Header(default=None),
):
    """Return per-day usage aggregates from the rolling request log.

    Groups the in-memory rolling log by UTC calendar day.
    Days are returned newest-first. Limited to the last `limit` days.
    """
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)

    logs = await analytics.snapshot_log(limit=200)

    # Aggregate by day bucket
    by_day: dict[int, dict] = defaultdict(lambda: {
        "requests": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
    })
    for entry in logs:
        bucket = _day_bucket(entry["ts"])
        by_day[bucket]["requests"] += 1
        by_day[bucket]["input_tokens"] += entry.get("input_tokens", 0)
        by_day[bucket]["output_tokens"] += entry.get("output_tokens", 0)
        by_day[bucket]["cost_usd"] += entry.get("cost_usd", 0.0)

    data = [
        {
            "date": bucket,
            "requests": v["requests"],
            "input_tokens": v["input_tokens"],
            "output_tokens": v["output_tokens"],
            "cost_usd": round(v["cost_usd"], 6),
        }
        for bucket, v in sorted(by_day.items(), reverse=True)
    ][:limit]

    return JSONResponse({
        "object": "list",
        "data": data,
        "retrieved_at": int(time.time()),
    })


@router.get("/v1/usage/keys/{key_prefix:path}")
async def key_usage(
    key_prefix: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Return lifetime usage stats for a specific API key."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)

    snapshot = await analytics.snapshot()
    key_data = snapshot["keys"].get(key_prefix, {
        "requests": 0,
        "cache_hits": 0,
        "fallbacks": 0,
        "estimated_input_tokens": 0,
        "estimated_output_tokens": 0,
        "estimated_cost_usd": 0.0,
        "latency_ms_total": 0.0,
        "last_request_ts": 0,
        "providers": {},
    })
    return JSONResponse({"key": key_prefix, **key_data})


@router.get("/v1/usage/summary")
async def usage_summary(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Return aggregate totals across all API keys."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)

    snapshot = await analytics.snapshot()
    total_requests = 0
    total_input = 0
    total_output = 0
    total_cost = 0.0
    for rec in snapshot["keys"].values():
        total_requests += rec.get("requests", 0)
        total_input += rec.get("estimated_input_tokens", 0)
        total_output += rec.get("estimated_output_tokens", 0)
        total_cost += rec.get("estimated_cost_usd", 0.0)

    return JSONResponse({
        "total_requests": total_requests,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cost_usd": round(total_cost, 6),
        "key_count": len(snapshot["keys"]),
        "retrieved_at": int(time.time()),
    })
```

- [ ] **Step 4: Register in `app.py`**

```python
from routers.usage import router as usage_router
# ...
app.include_router(usage_router)
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_usage_router.py -v
```
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add routers/usage.py tests/test_usage_router.py app.py
git commit -m "feat(routers): add usage router — daily breakdown and per-key stats from analytics store"
```

---

## Chunk 4: Webhooks router + storage

Webhooks allow clients to register a callback URL for async notifications (batch completions, etc.). Uses the aiosqlite pattern from `storage/batch.py`.

### Task 6: `storage/webhooks.py`

**Files:**
- Create: `storage/webhooks.py`

- [ ] **Step 1: Create `storage/webhooks.py`**

```python
"""
Shin Proxy — SQLite store for webhook registrations.

Schema:
    id         TEXT PRIMARY KEY  — webhook_<hex24>
    api_key    TEXT NOT NULL     — owning bearer token
    url        TEXT NOT NULL     — HTTPS callback URL
    events     TEXT NOT NULL     — JSON array of event names
    is_active  INTEGER NOT NULL  — 1 active / 0 disabled
    created_at INTEGER NOT NULL  — unix timestamp
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

import aiosqlite
import structlog

log = structlog.get_logger()

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS webhooks (
    id         TEXT    PRIMARY KEY,
    api_key    TEXT    NOT NULL,
    url        TEXT    NOT NULL,
    events     TEXT    NOT NULL DEFAULT '[]',
    is_active  INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
)
"""


def _to_record(row: aiosqlite.Row) -> dict[str, Any]:
    d = dict(row)
    d["events"] = json.loads(d["events"] or "[]")
    d["is_active"] = bool(d["is_active"])
    return d


class WebhookStore:
    def __init__(self, db_path: str = "webhooks.db") -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute(_CREATE_TABLE)
        await self._db.commit()
        log.info("webhook_store_ready", path=self._db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    def _assert_init(self) -> None:
        if self._db is None:
            raise RuntimeError("WebhookStore not initialised — call init() first")

    async def create(self, api_key: str, url: str, events: list[str]) -> dict[str, Any]:
        self._assert_init()
        webhook_id = f"webhook_{uuid.uuid4().hex[:24]}"
        now = int(time.time())
        await self._db.execute(  # type: ignore[union-attr]
            "INSERT INTO webhooks (id, api_key, url, events, is_active, created_at) VALUES (?, ?, ?, ?, 1, ?)",
            (webhook_id, api_key, url, json.dumps(events), now),
        )
        await self._db.commit()  # type: ignore[union-attr]
        log.info("webhook_created", webhook_id=webhook_id, url=url)
        return {"id": webhook_id, "object": "webhook", "api_key": api_key,
                "url": url, "events": events, "is_active": True, "created_at": now}

    async def list_by_key(self, api_key: str) -> list[dict[str, Any]]:
        self._assert_init()
        async with self._db.execute(  # type: ignore[union-attr]
            "SELECT * FROM webhooks WHERE api_key = ? ORDER BY created_at DESC", (api_key,)
        ) as cur:
            rows = await cur.fetchall()
        return [_to_record(r) for r in rows]

    async def get(self, webhook_id: str, api_key: str) -> dict[str, Any] | None:
        self._assert_init()
        async with self._db.execute(  # type: ignore[union-attr]
            "SELECT * FROM webhooks WHERE id = ? AND api_key = ?", (webhook_id, api_key)
        ) as cur:
            row = await cur.fetchone()
        return _to_record(row) if row else None

    async def delete(self, webhook_id: str, api_key: str) -> bool:
        self._assert_init()
        cur = await self._db.execute(  # type: ignore[union-attr]
            "DELETE FROM webhooks WHERE id = ? AND api_key = ?", (webhook_id, api_key)
        )
        await self._db.commit()  # type: ignore[union-attr]
        return (cur.rowcount or 0) > 0


webhook_store: WebhookStore = WebhookStore()
```

- [ ] **Step 2: Commit storage layer**

```bash
git add storage/webhooks.py
git commit -m "feat(storage): add WebhookStore — aiosqlite CRUD for webhook registrations"
```

---

### Task 7: `routers/webhooks.py`

**Files:**
- Create: `routers/webhooks.py`
- Create: `tests/test_webhooks_router.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_webhooks_router.py
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


def test_create_webhook(client):
    resp = client.post(
        "/v1/internal/webhooks",
        json={"url": "https://example.com/hook", "events": ["batch.completed"]},
        headers={"Authorization": "Bearer sk-test"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "webhook"
    assert body["id"].startswith("webhook_")
    assert body["url"] == "https://example.com/hook"
    assert body["events"] == ["batch.completed"]


def test_create_webhook_rejects_non_https(client):
    resp = client.post(
        "/v1/internal/webhooks",
        json={"url": "http://example.com/hook", "events": []},
        headers={"Authorization": "Bearer sk-test"},
    )
    assert resp.status_code == 422


def test_list_webhooks(client):
    client.post(
        "/v1/internal/webhooks",
        json={"url": "https://example.com/h1", "events": []},
        headers={"Authorization": "Bearer sk-test"},
    )
    resp = client.get("/v1/internal/webhooks", headers={"Authorization": "Bearer sk-test"})
    assert resp.status_code == 200
    assert "data" in resp.json()


def test_delete_webhook(client):
    create = client.post(
        "/v1/internal/webhooks",
        json={"url": "https://example.com/h2", "events": []},
        headers={"Authorization": "Bearer sk-test"},
    )
    wid = create.json()["id"]
    resp = client.delete(f"/v1/internal/webhooks/{wid}", headers={"Authorization": "Bearer sk-test"})
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


def test_delete_missing_webhook_returns_404(client):
    resp = client.delete("/v1/internal/webhooks/webhook_notexist", headers={"Authorization": "Bearer sk-test"})
    assert resp.status_code == 404


def test_webhooks_requires_auth(client):
    resp = client.get("/v1/internal/webhooks")
    assert resp.status_code == 401
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_webhooks_router.py -v
```

- [ ] **Step 3: Create `routers/webhooks.py`**

```python
"""
Shin Proxy — Webhook registration API.

Allows clients to register HTTPS callback URLs for async event delivery.
Event delivery is fire-and-forget — this router only manages registrations.

Endpoints:
    POST   /v1/internal/webhooks
    GET    /v1/internal/webhooks
    GET    /v1/internal/webhooks/{webhook_id}
    DELETE /v1/internal/webhooks/{webhook_id}
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from middleware.auth import verify_bearer
from middleware.rate_limit import enforce_rate_limit
from storage.webhooks import webhook_store

router = APIRouter()
log = structlog.get_logger()

_VALID_EVENTS = frozenset({
    "batch.completed",
    "batch.failed",
    "batch.cancelled",
    "response.completed",
})


class CreateWebhookBody(BaseModel):
    url: str
    events: list[str] = []


@router.post("/v1/internal/webhooks")
async def create_webhook(
    body: CreateWebhookBody,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Register a new webhook endpoint."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)

    if not body.url.startswith("https://"):
        return JSONResponse(
            status_code=422,
            content={"error": {"message": "Webhook URL must use HTTPS.", "type": "invalid_request_error", "code": "422"}},
        )

    unknown = [e for e in body.events if e not in _VALID_EVENTS]
    if unknown:
        log.warning("webhook_unknown_events", unknown=unknown)

    record = await webhook_store.create(api_key=api_key, url=body.url, events=body.events)
    return JSONResponse(record)


@router.get("/v1/internal/webhooks")
async def list_webhooks(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """List all webhook registrations for the authenticated key."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)
    data = await webhook_store.list_by_key(api_key)
    return JSONResponse({"object": "list", "data": data})


@router.get("/v1/internal/webhooks/{webhook_id}")
async def get_webhook(
    webhook_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Get a specific webhook registration."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)
    record = await webhook_store.get(webhook_id, api_key)
    if record is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Webhook '{webhook_id}' not found", "type": "not_found_error", "code": "404"}},
        )
    return JSONResponse(record)


@router.delete("/v1/internal/webhooks/{webhook_id}")
async def delete_webhook(
    webhook_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Delete a webhook registration."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)
    deleted = await webhook_store.delete(webhook_id, api_key)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Webhook '{webhook_id}' not found", "type": "not_found_error", "code": "404"}},
        )
    log.info("webhook_deleted", webhook_id=webhook_id)
    return JSONResponse({"id": webhook_id, "object": "webhook", "deleted": True})
```

- [ ] **Step 4: Register in `app.py` and init store in lifespan**

In `_lifespan`, after `await quota_store.init()`:
```python
from storage.webhooks import webhook_store
await webhook_store.init()
log.info("webhook_store_started")
```

In the `finally` block, after `await quota_store.close()`:
```python
from storage.webhooks import webhook_store
await webhook_store.close()
log.info("webhook_store_closed")
```

In `create_app()`, register the router:
```python
from routers.webhooks import router as webhooks_router
# ...
app.include_router(webhooks_router)
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_webhooks_router.py -v
```
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add routers/webhooks.py storage/webhooks.py tests/test_webhooks_router.py app.py
git commit -m "feat(routers): add webhooks router + WebhookStore — HTTPS-only registration with SQLite persistence"
```

---

## Chunk 5: Wire everything + final verification

### Task 8: Final `app.py` wiring and full test run

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Verify all 6 routers are registered in `app.py`**

The import block in `create_app()` must include:
```python
from routers.internal import router as internal_router
from routers.openai import router as openai_router
from routers.anthropic import router as anthropic_router
from routers.responses import router as responses_router
from routers.batch import router as batch_router
from routers.embeddings import router as embeddings_router
from routers.audio import router as audio_router
from routers.fine_tuning import router as fine_tuning_router
from routers.files import router as files_router
from routers.usage import router as usage_router
from routers.webhooks import router as webhooks_router
```

And `app.include_router()` calls for each.

- [ ] **Step 2: Verify lifespan initialises `webhook_store`**

Confirm `_lifespan` has:
```python
from storage.webhooks import webhook_store
await webhook_store.init()
```
and the corresponding `close()` in the `finally` block.

- [ ] **Step 3: Run full unit test suite**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/ -m 'not integration' -q
```
Expected: all passing (no regressions)

- [ ] **Step 4: Verify route registration**

```bash
cd /teamspace/studios/this_studio/dikders && python -c "
import os; os.environ.setdefault('LITELLM_MASTER_KEY','sk-test'); os.environ.setdefault('CURSOR_COOKIE','WorkosCursorSessionToken=test')
from app import create_app
app = create_app()
routes = [r.path for r in app.routes]
expected = ['/v1/embeddings', '/v1/audio/speech', '/v1/audio/transcriptions', '/v1/fine_tuning/jobs', '/v1/files', '/v1/usage/daily', '/v1/internal/webhooks']
for p in expected:
    assert any(p in r for r in routes), f'MISSING: {p}'
print('All routes registered OK')
"
```

- [ ] **Step 5: Commit final wiring**

```bash
git add app.py
git commit -m "feat(app): register all new router modules — embeddings, audio, fine_tuning, files, usage, webhooks"
```

- [ ] **Step 6: Update UPDATES.md**

Add a new session entry documenting:
- Files created: `routers/embeddings.py`, `routers/audio.py`, `routers/fine_tuning.py`, `routers/files.py`, `routers/usage.py`, `routers/webhooks.py`, `storage/webhooks.py`
- Files modified: `app.py`, `routers/openai.py` (removed duplicate embeddings stub)
- Tests created: 6 new test files
- Why: complete OpenAI API surface, add usage reporting, add webhook registration

```bash
git add UPDATES.md
git commit -m "docs: update UPDATES.md for Session 150 — new router modules"
git push
```

---

## Summary of new endpoints

| Method | Path | Status | Notes |
|--------|------|--------|-------|
| POST | `/v1/embeddings` | 501 | Moved from openai.py stub |
| POST | `/v1/audio/transcriptions` | 501 | New |
| POST | `/v1/audio/speech` | 501 | New |
| POST | `/v1/audio/translations` | 501 | New |
| POST | `/v1/fine_tuning/jobs` | 501 | New |
| GET | `/v1/fine_tuning/jobs` | 501 | New |
| GET | `/v1/fine_tuning/jobs/{id}` | 501 | New |
| POST | `/v1/fine_tuning/jobs/{id}/cancel` | 501 | New |
| POST | `/v1/files` | 200 | In-memory |
| GET | `/v1/files` | 200 | In-memory |
| GET | `/v1/files/{id}` | 200 | In-memory |
| DELETE | `/v1/files/{id}` | 200 | In-memory |
| GET | `/v1/usage/daily` | 200 | From analytics store |
| GET | `/v1/usage/keys/{key}` | 200 | From analytics store |
| GET | `/v1/usage/summary` | 200 | From analytics store |
| POST | `/v1/internal/webhooks` | 200 | SQLite-backed |
| GET | `/v1/internal/webhooks` | 200 | SQLite-backed |
| GET | `/v1/internal/webhooks/{id}` | 200 | SQLite-backed |
| DELETE | `/v1/internal/webhooks/{id}` | 200 | SQLite-backed |
