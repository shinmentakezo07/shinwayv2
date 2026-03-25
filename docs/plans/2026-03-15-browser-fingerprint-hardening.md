# Browser Fingerprint Hardening — A through D

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the proxy's outgoing requests to cursor.com indistinguishable from a real Brave browser on Windows by fixing four specific impersonation gaps.

**Architecture:** All changes are confined to two files — `cursor/client.py` (header assembly) and `config.py` (default UA string). No logic changes, no new dependencies. Each fix is a targeted string/header edit.

**Tech Stack:** Python, httpx, pydantic-settings

---

## Background — What is broken today

| Problem | Location | Effect |
|---|---|---|
| A | `x-stainless-*` headers in `client.py:57-63` | Explicitly identifies client as Anthropic Python SDK — real browsers never send these |
| B | UA says `Chrome/137 Linux` but `sec-ch-ua` says `Brave/146 Windows` | 3-way version+platform contradiction |
| C | `config.py:47` default `USER_AGENT` is `Chrome/137 Linux` | Mismatches the Windows/146 sec-ch-ua hints |
| D | No `Connection: keep-alive` or `DNT: 1` | Brave sends both; absence is a fingerprint signal |

---

## Task 1: Remove `x-stainless-*` headers (Fix A)

**Files:**
- Modify: `cursor/client.py:57-63`
- Test: `tests/test_client_headers.py` (new file)

**What to do:**

Remove these 6 lines from the `headers` dict in `_build_headers`:
```python
# DELETE these lines:
"x-stainless-retry-count": "0",
"x-stainless-lang": "python",
"x-stainless-package-version": "1.0.0",
"x-stainless-os": platform.system() or "Windows",
"x-stainless-arch": platform.machine().replace("AMD64", "x64") or "x64",
"x-stainless-runtime": "python",
"x-stainless-runtime-version": platform.python_version(),
```

Also remove `import platform` from the top of `client.py` — it is only used for the stainless headers. Verify with grep first.

**Step 1: Write failing test**

Create `tests/test_client_headers.py`:
```python
from unittest.mock import MagicMock
from cursor.client import _build_headers

def test_no_stainless_headers():
    """Real browsers never send x-stainless-* headers."""
    headers = _build_headers(cred=None)
    stainless = [k for k in headers if k.startswith("x-stainless")]
    assert stainless == [], f"Found stainless headers: {stainless}"

def test_no_platform_leak():
    """No Python platform info should leak into headers."""
    import platform as _platform
    headers = _build_headers(cred=None)
    python_version = _platform.python_version()
    for v in headers.values():
        assert python_version not in v, f"Python version leaked in header value: {v}"
```

**Step 2: Run to verify it FAILS**
```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_client_headers.py -v 2>&1 | tail -20
```
Expected: FAIL — `x-stainless-lang` found

**Step 3: Apply the fix**

In `cursor/client.py`:
- Remove the 7 `x-stainless-*` lines from `headers` dict
- Check if `import platform` is still needed: `grep -n 'platform\.' cursor/client.py` — if no remaining uses, remove the import

**Step 4: Run test to verify PASS**
```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_client_headers.py::test_no_stainless_headers tests/test_client_headers.py::test_no_platform_leak -v 2>&1 | tail -10
```
Expected: PASS

**Step 5: Run full suite**
```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/ -q --ignore=tests/integration -k 'not test_is_suppressed' 2>&1 | tail -10
```
Expected: all pass

**Step 6: Commit**
```bash
git add cursor/client.py tests/test_client_headers.py
git commit -m "fix: remove x-stainless-* headers — real browsers never send SDK identity headers"
```

---

## Task 2: Fix UA / sec-ch-ua / platform version consistency (Fixes B + C)

**Files:**
- Modify: `cursor/client.py:43-51` (header values)
- Modify: `config.py:47-48` (default USER_AGENT)
- Test: `tests/test_client_headers.py` (add tests)

**Target consistent identity:**
- Browser: Brave 146 on Windows 11
- UA: `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36`
- `sec-ch-ua`: `"Chromium";v="146", "Not-A.Brand";v="24", "Brave";v="146"`  ← already correct
- `sec-ch-ua-platform`: `"Windows"` ← already correct
- `sec-ch-ua-platform-version`: `"19.0.0"` ← Windows 11 22H2 build, keep as-is

The only changes needed:
1. `config.py` default `user_agent`: change `Chrome/137.0.0.0` + `Linux x86_64` → `Chrome/146.0.0.0` + `Windows NT 10.0; Win64; x64`
2. `client.py` fallback UA (line 43): already says `Chrome/146.0.0.0 Windows` ← already correct, no change needed

**Step 1: Add failing test**

Add to `tests/test_client_headers.py`:
```python
from config import settings

def test_ua_chrome_version_matches_sec_ch_ua():
    """UA Chrome version must match sec-ch-ua version — no 3-way contradiction."""
    headers = _build_headers(cred=None)
    ua = headers.get("User-Agent", "")
    sec_ch_ua = headers.get("sec-ch-ua", "")
    # Extract Chrome version from UA: Chrome/NNN
    import re
    ua_version_match = re.search(r"Chrome/(\d+)", ua)
    sec_version_match = re.search(r'Chromium";v="(\d+)', sec_ch_ua)
    assert ua_version_match and sec_version_match, "Could not parse versions"
    assert ua_version_match.group(1) == sec_version_match.group(1), (
        f"UA Chrome/{ua_version_match.group(1)} != sec-ch-ua Chromium/{sec_version_match.group(1)}"
    )

def test_ua_is_windows_not_linux():
    """UA must not leak Linux — sec-ch-ua-platform says Windows."""
    headers = _build_headers(cred=None)
    ua = headers.get("User-Agent", "")
    assert "Linux" not in ua, f"Linux leaked in UA: {ua}"
    assert "Windows" in ua, f"Expected Windows in UA: {ua}"
```

**Step 2: Run to verify FAIL**
```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_client_headers.py::test_ua_chrome_version_matches_sec_ch_ua tests/test_client_headers.py::test_ua_is_windows_not_linux -v 2>&1 | tail -15
```
Expected: FAIL — Chrome/137 != 146, Linux in UA

**Step 3: Fix `config.py` default user_agent**

In `config.py` change:
```python
# FROM:
default="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
"(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",

# TO:
default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
"(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
```

**Step 4: Run tests to verify PASS**
```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_client_headers.py -v 2>&1 | tail -15
```
Expected: all PASS

**Step 5: Run full suite**
```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/ -q --ignore=tests/integration -k 'not test_is_suppressed' 2>&1 | tail -10
```

**Step 6: Commit**
```bash
git add config.py tests/test_client_headers.py
git commit -m "fix: align default UA to Chrome/146 Windows — matches sec-ch-ua version and platform"
```

---

## Task 3: Add `Connection: keep-alive` and `DNT: 1` (Fix D)

**Files:**
- Modify: `cursor/client.py` (add 2 headers to `_build_headers`)
- Test: `tests/test_client_headers.py` (add tests)

**Why:**
- `Connection: keep-alive` — standard on all persistent browser connections (httpx uses HTTP/1.1 keep-alive by default anyway, but the header should be explicit)
- `DNT: 1` — Brave sends Do Not Track by default; its absence is a fingerprint signal for a Brave impersonation

**Step 1: Add failing tests**

Add to `tests/test_client_headers.py`:
```python
def test_connection_keep_alive():
    """Browsers send Connection: keep-alive on persistent connections."""
    headers = _build_headers(cred=None)
    assert headers.get("Connection") == "keep-alive"

def test_dnt_header_present():
    """Brave sends DNT: 1 by default."""
    headers = _build_headers(cred=None)
    assert headers.get("DNT") == "1"
```

**Step 2: Run to verify FAIL**
```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_client_headers.py::test_connection_keep_alive tests/test_client_headers.py::test_dnt_header_present -v 2>&1 | tail -10
```
Expected: FAIL — headers not present

**Step 3: Add headers to `_build_headers` in `cursor/client.py`**

Add these two lines to the `headers` dict (after `sec-gpc`):
```python
"Connection": "keep-alive",
"DNT": "1",
```

**Step 4: Run tests to verify PASS**
```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_client_headers.py -v 2>&1 | tail -15
```
Expected: all PASS

**Step 5: Run full suite**
```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/ -q --ignore=tests/integration -k 'not test_is_suppressed' 2>&1 | tail -10
```

**Step 6: Commit**
```bash
git add cursor/client.py tests/test_client_headers.py
git commit -m "fix: add Connection keep-alive and DNT headers — Brave sends both by default"
```

---

## Final verification

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/ -q --ignore=tests/integration -k 'not test_is_suppressed' 2>&1 | tail -10
```
Expected: all pass including new `test_client_headers.py` tests

---

## Summary of all changes

| File | Change |
|---|---|
| `cursor/client.py` | Remove 7 `x-stainless-*` lines, remove `import platform`, add `Connection` + `DNT` |
| `config.py` | Update default `user_agent` from Chrome/137 Linux → Chrome/146 Windows |
| `tests/test_client_headers.py` | New file — 6 tests covering all four fixes |
