from converters.shared import _safe_pct


def test_safe_pct_normal():
    assert _safe_pct(1000, 10000) == 10.0


def test_safe_pct_zero_context():
    assert _safe_pct(100, 0) == 0.0


def test_safe_pct_full():
    assert _safe_pct(10000, 10000) == 100.0


def test_safe_pct_rounds_to_2dp():
    assert _safe_pct(1, 3) == 33.33


def test_safe_pct_zero_used():
    assert _safe_pct(0, 10000) == 0.0
