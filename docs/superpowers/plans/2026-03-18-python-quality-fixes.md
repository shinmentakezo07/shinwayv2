# Python Quality Fixes Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply all Python code quality fixes identified in the static analysis review: unused imports, f-string fixes, nosec annotations, pytest/mypy config, integration test fixture refactor, variable rename, and pipeline `__init__` noqa additions.

**Architecture:** Pure cleanup pass — no behaviour changes. All fixes are mechanical: ruff auto-fix for F401/F541, targeted manual edits for the rest. Tests must stay green throughout.

**Tech Stack:** Python 3.12, pytest, ruff, bandit, mypy

---

## Chunk 1: Auto-fixable ruff issues (F401 unused imports, F541 f-strings)

### Task 1: Apply ruff --fix to source files

**Files:**
- Modify: `analytics.py` (remove `OrderedDict`, `Any`)
- Modify: `cursor/client.py` (remove `json`)
- Modify: `cursor/sse.py` (remove `settings`)
- Modify: `converters/to_cursor.py` (strip f-prefix from 3 plain strings)
- Modify: `multirun.py` (strip f-prefix from 1 plain string)

- [ ] **Step 1: Run ruff auto-fix on source files only**

```bash
ruff check analytics.py cursor/client.py cursor/sse.py converters/to_cursor.py multirun.py --fix
```

Expected: each file reports fixes applied, exit 0.

- [ ] **Step 2: Verify ruff is clean on those files**

```bash
ruff check analytics.py cursor/client.py cursor/sse.py converters/to_cursor.py multirun.py
```

Expected: no output, exit 0.

- [ ] **Step 3: Run unit tests to confirm nothing broke**

```bash
PYTHONPATH=. pytest tests/ -m 'not integration' --ignore=tests/integration --tb=short -q
```

Expected: 210 passed.

- [ ] **Step 4: Commit**

```bash
git add analytics.py cursor/client.py cursor/sse.py converters/to_cursor.py multirun.py
git commit -m "chore: remove unused imports and bare f-strings (ruff auto-fix)"
```

---

## Chunk 2: Manual source fixes — variable rename + pipeline noqa

### Task 2: Rename ambiguous variable `l` → `line` in cursor/credentials.py

**Files:**
- Modify: `cursor/credentials.py:175`

- [ ] **Step 1: Apply rename**

In `cursor/credentials.py` line 175, change:
```python
# Before
lines = [l.strip() for l in raw.splitlines() if l.strip()]
# After
lines = [line.strip() for line in raw.splitlines() if line.strip()]
```

- [ ] **Step 2: Verify ruff clean**

```bash
ruff check cursor/credentials.py
```

Expected: no output.

- [ ] **Step 3: Run tests**

```bash
PYTHONPATH=. pytest tests/test_credentials.py -v --tb=short
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add cursor/credentials.py
git commit -m "chore: rename ambiguous loop var l -> line (E741)"
```

### Task 3: Add `# noqa: F401` to unsuppressed re-exports in pipeline/__init__.py

**Files:**
- Modify: `pipeline/__init__.py:16-24`

Lines 16–24 import private names purely for test monkey-patching re-export. Lines 7–14 already have `# noqa: F401`. Lines 16–24 are missing it.

- [ ] **Step 1: Add noqa comments to unsuppressed lines**

In `pipeline/__init__.py`, add `# noqa: F401` to the end of each import that ruff flags:
- line 16: `from pipeline.record import _provider_from_model, _record  # noqa: F401`
- line 18: `    _SUPPRESSION_SIGNALS,  # noqa: F401`
- line 19: `    _SUPPRESSION_PERSONA_SIGNALS,  # noqa: F401`
- line 20: `    _SUPPRESSION_KNOCKOUTS,  # noqa: F401`

- [ ] **Step 2: Verify ruff clean**

```bash
ruff check pipeline/__init__.py
```

Expected: no output.

- [ ] **Step 3: Run tests**

```bash
PYTHONPATH=. pytest tests/test_pipeline.py -v --tb=short
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add pipeline/__init__.py
git commit -m "chore: add noqa F401 to pipeline re-export imports"
```

---

## Chunk 3: Bandit nosec annotations

### Task 4: Add `# nosec` annotations to intentional bandit findings

**Files:**
- Modify: `config.py:24`
- Modify: `cursor/client.py:234,243,252`
- Modify: `pipeline/suppress.py:116`
- Modify: `multirun.py:137`
- Modify: `run.py:18`
- Modify: `pipeline/tools.py:32`
- Modify: `tools/parse.py:251,260,275,902,922`
- Modify: `storage/keys.py:151`

Each annotation includes a brief explanation so future readers know the finding is deliberate.

- [ ] **Step 1: Annotate config.py — B104 bind all interfaces**

`config.py:24`:
```python
    host: str = Field(default="0.0.0.0", alias="HOST")  # nosec B104 — intentional: proxy listens on all interfaces in Docker
```

- [ ] **Step 2: Annotate cursor/client.py — B311 random jitter (3 sites)**

`cursor/client.py:234`:
```python
                    jitter = random.uniform(0, base * 0.3)  # nosec B311 — jitter for backoff, not crypto
```
`cursor/client.py:243`:
```python
                    jitter = random.uniform(0, base * 0.3)  # nosec B311 — jitter for backoff, not crypto
```
`cursor/client.py:252`:
```python
                    jitter = random.uniform(0, min(wait * 0.1, 5.0))  # nosec B311 — jitter for backoff, not crypto
```

- [ ] **Step 3: Annotate pipeline/suppress.py — B311 random jitter**

`pipeline/suppress.py:116`:
```python
                jitter = random.uniform(0, base * 0.3)  # nosec B311 — jitter for backoff, not crypto
```

- [ ] **Step 4: Annotate multirun.py — B603 subprocess with controlled input**

`multirun.py:137` (the `subprocess.Popen` call):
```python
        proc = subprocess.Popen(  # nosec B603 — input is [sys.executable, "run.py"], fully controlled
```

- [ ] **Step 5: Annotate run.py — B110 try/except pass (stderr reconfigure)**

`run.py:18`:
```python
    except Exception:  # nosec B110 — best-effort stderr reconfigure; failure is harmless
        pass
```

- [ ] **Step 6: Annotate pipeline/tools.py — B110 try/except pass (JSON decode fallback)**

`pipeline/tools.py:32`:
```python
        except Exception:  # nosec B110 — intentional: args may not be JSON; fallback is by design
            pass
```

- [ ] **Step 7: Annotate tools/parse.py — B110 try/except pass (5 sites in 4-strategy parse cascade)**

Each of lines 251, 260, 275, 902, 922 is a fallthrough step in the parse strategy cascade:
```python
    except Exception:  # nosec B110 — parse strategy fallthrough; next strategy follows
        pass
```

- [ ] **Step 8: Annotate storage/keys.py — B608 false-positive SQL injection**

`storage/keys.py:151`:
```python
            f"UPDATE api_keys SET {', '.join(fields)} WHERE key = ?", values  # nosec B608 — fields are hardcoded string literals validated against _ALLOWED_UPDATE_FIELDS whitelist
```

- [ ] **Step 9: Verify bandit is clean (medium+high only)**

```bash
bandit -r . --exclude ./.venv,./admin-ui,./tests,./.claude -ll -q 2>&1
```

Expected: 0 issues at medium/high severity.

- [ ] **Step 10: Run tests**

```bash
PYTHONPATH=. pytest tests/ -m 'not integration' --ignore=tests/integration --tb=short -q
```

Expected: 210 passed.

- [ ] **Step 11: Commit**

```bash
git add config.py cursor/client.py pipeline/suppress.py multirun.py run.py pipeline/tools.py tools/parse.py storage/keys.py
git commit -m "chore: add nosec annotations to intentional bandit findings"
```

---

## Chunk 4: pytest and mypy config

### Task 5: Add `pythonpath = .` to pytest.ini

**Files:**
- Modify: `pytest.ini`

This eliminates the need for `PYTHONPATH=.` prefix on every test run.

- [ ] **Step 1: Add pythonpath setting**

In `pytest.ini`, add `pythonpath = .` after `asyncio_mode = auto`:
```ini
[pytest]
pythonpath = .
asyncio_mode = auto
asyncio_default_fixture_loop_scope = function
markers =
    integration: marks tests as requiring a live server (deselect with -m 'not integration')
```

- [ ] **Step 2: Verify tests run without PYTHONPATH prefix**

```bash
pytest tests/ -m 'not integration' --ignore=tests/integration --tb=short -q
```

Expected: 210 passed.

- [ ] **Step 3: Commit**

```bash
git add pytest.ini
git commit -m "chore: add pythonpath = . to pytest.ini so tests run without PYTHONPATH prefix"
```

### Task 6: Add mypy.ini for clean type checking

**Files:**
- Create: `mypy.ini`

- [ ] **Step 1: Create mypy.ini**

```ini
[mypy]
python_version = 3.12
explicit_package_bases = True
ignore_missing_imports = True
exclude = (?x)(
    admin-ui/|
    \.venv/|
    \.claude/
  )
```

- [ ] **Step 2: Verify mypy runs without the duplicate-module error**

```bash
python3 -m mypy . --no-error-summary 2>&1 | head -20
```

Expected: no "Source file found twice" error. Type errors may still appear — that's acceptable for now.

- [ ] **Step 3: Commit**

```bash
git add mypy.ini
git commit -m "chore: add mypy.ini with explicit_package_bases to fix duplicate-module error"
```

---

## Chunk 5: Integration test fixture refactor

### Task 7: Move module-level create_app() into fixtures in integration tests

**Files:**
- Modify: `tests/integration/test_all_tools.py`
- Modify: `tests/integration/test_tool_call.py`

The module-level `app = create_app()` call causes pytest collection to fail when env vars are absent, because FastAPI app startup reads env vars immediately.

- [ ] **Step 1: Read both files in full before editing**

```bash
cat tests/integration/test_all_tools.py
cat tests/integration/test_tool_call.py
```

- [ ] **Step 2: Refactor test_all_tools.py**

Remove `app = create_app()` from module level. Add a module-scoped fixture:
```python
@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())
```
Update all test functions that use `client` to accept it as a parameter instead of referencing the module-level variable.

- [ ] **Step 3: Refactor test_tool_call.py** (same pattern)

- [ ] **Step 4: Verify collection succeeds without env vars**

```bash
pytest tests/integration/ --collect-only 2>&1 | head -20
```

Expected: items collected, no ImportError or collection errors.

- [ ] **Step 5: Run all unit tests to confirm nothing regressed**

```bash
pytest tests/ -m 'not integration' --ignore=tests/integration --tb=short -q
```

Expected: 210 passed.

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_all_tools.py tests/integration/test_tool_call.py
git commit -m "fix(tests): move create_app() from module level into module-scoped fixtures"
```

---

## Chunk 6: Final verification

### Task 8: Full verification pass

- [ ] **Step 1: ruff clean across all project files**

```bash
ruff check . --exclude admin-ui --exclude .claude
```

Expected: 0 errors in project source (test files may have residual F401 from test-only unused imports — acceptable).

- [ ] **Step 2: bandit medium/high clean**

```bash
bandit -r . --exclude ./.venv,./admin-ui,./tests,./.claude -ll -q
```

Expected: 0 issues at medium or high severity.

- [ ] **Step 3: Full unit test suite**

```bash
pytest tests/ -m 'not integration' --ignore=tests/integration --tb=short