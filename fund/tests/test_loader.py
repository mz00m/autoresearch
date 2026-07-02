"""Loader behavior — cache hits, staleness, fallback chain."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fund.data import loader
from fund.data.pit import PriceSeries


def test_is_stale_fresh_cache():
    """Cache ending yesterday with end=today should NOT be stale."""
    last = date(2024, 6, 4)  # Tuesday
    ps = PriceSeries("SPY", (last,), (100.0,))
    assert loader._is_stale(ps, date(2024, 6, 5), stale_days=3) is False


def test_is_stale_old_cache():
    """Cache ending a month ago must be marked stale."""
    last = date(2024, 5, 1)
    ps = PriceSeries("SPY", (last,), (100.0,))
    assert loader._is_stale(ps, date(2024, 6, 5), stale_days=3) is True


def test_is_stale_empty_cache():
    ps = PriceSeries("SPY", (), ())
    assert loader._is_stale(ps, date(2024, 6, 5), stale_days=3) is True


def test_is_stale_rolls_weekend():
    """If `end` is a Saturday, the requested floor is Friday — so a Friday cache
    is fresh, not stale, regardless of stale_days."""
    friday = date(2024, 6, 7)
    saturday = date(2024, 6, 8)
    ps = PriceSeries("SPY", (friday,), (100.0,))
    assert loader._is_stale(ps, saturday, stale_days=0) is False


def test_is_stale_threshold_boundary():
    """Cache exactly stale_days old is NOT stale (>, not >=)."""
    end = date(2024, 6, 5)  # Wed
    last = date(2024, 6, 2)  # Sunday -> 3 days back from Wed
    ps = PriceSeries("SPY", (last,), (100.0,))
    assert loader._is_stale(ps, end, stale_days=3) is False
    # one day older -> stale
    ps2 = PriceSeries("SPY", (date(2024, 6, 1),), (100.0,))
    assert loader._is_stale(ps2, end, stale_days=3) is True


if __name__ == "__main__":
    tests = [(n, fn) for n, fn in globals().items()
             if n.startswith("test_") and callable(fn)]
    passed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL {name}: {e}")
        except Exception as e:
            print(f"  FAIL {name}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
    sys.exit(0 if passed == len(tests) else 1)
