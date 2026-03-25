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


def test_ua_chrome_version_matches_sec_ch_ua():
    """UA Chrome version must match sec-ch-ua version — no contradiction."""
    import re
    headers = _build_headers(cred=None)
    ua = headers.get("User-Agent", "")
    sec_ch_ua = headers.get("sec-ch-ua", "")
    ua_match = re.search(r"Chrome/(\d+)", ua)
    sec_match = re.search(r'Chromium";v="(\d+)', sec_ch_ua)
    assert ua_match and sec_match, "Could not parse versions from UA or sec-ch-ua"
    assert ua_match.group(1) == sec_match.group(1), (
        f"UA Chrome/{ua_match.group(1)} != sec-ch-ua Chromium/{sec_match.group(1)}"
    )


def test_ua_is_windows_not_linux():
    """UA must say Windows — sec-ch-ua-platform says Windows."""
    headers = _build_headers(cred=None)
    ua = headers.get("User-Agent", "")
    assert "Linux" not in ua, f"Linux leaked in UA: {ua}"
    assert "Windows" in ua, f"Expected Windows in UA: {ua}"


def test_connection_keep_alive():
    """Browsers send Connection: keep-alive on persistent connections."""
    headers = _build_headers(cred=None)
    assert headers.get("Connection") == "keep-alive"


def test_dnt_header_present():
    """Brave sends DNT: 1 by default."""
    headers = _build_headers(cred=None)
    assert headers.get("DNT") == "1"
