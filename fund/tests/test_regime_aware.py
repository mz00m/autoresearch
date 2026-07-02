"""Regime classifier — decision tree on VIX, yield curve, and SPY trend."""

from __future__ import annotations

import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fund.data.pit import Panel, PriceSeries
from fund.strategy.regime_aware import RegimeAwareAllocator, _classify


def _make_panel(*, vix=None, tnx=None, irx=None, spy_above_sma=None):
    """Build a synthetic panel with the given macro readings."""
    series = {}
    if vix is not None:
        series["^VIX"] = PriceSeries("^VIX", (date(2024, 1, 1),), (vix,))
    if tnx is not None:
        series["^TNX"] = PriceSeries("^TNX", (date(2024, 1, 1),), (tnx,))
    if irx is not None:
        series["^IRX"] = PriceSeries("^IRX", (date(2024, 1, 1),), (irx,))
    if spy_above_sma is not None:
        # Synthesize 200 closes whose SMA is below or above the last
        if spy_above_sma:
            closes = tuple([100.0] * 199 + [150.0])  # last > sma
        else:
            closes = tuple([100.0] * 199 + [50.0])   # last < sma
        dates = tuple(date(2023, 1, i % 28 + 1) for i in range(200))
        series["SPY"] = PriceSeries("SPY", dates, closes)
    return Panel(series)


def test_panic_when_vix_above_35():
    regime, _ = _classify(_make_panel(vix=40.0))
    assert regime == "PANIC"


def test_stressed_when_vix_above_25():
    regime, _ = _classify(_make_panel(vix=30.0))
    assert regime == "STRESSED"


def test_stressed_when_curve_deeply_inverted():
    regime, _ = _classify(_make_panel(vix=15.0, tnx=3.0, irx=5.0,
                                       spy_above_sma=True))
    # curve = 3 - 5 = -2 < -0.5
    assert regime == "STRESSED"


def test_stressed_when_spy_below_200d():
    regime, _ = _classify(_make_panel(vix=15.0, tnx=4.0, irx=3.0,
                                       spy_above_sma=False))
    assert regime == "STRESSED"


def test_calm_when_all_three_benign():
    regime, signals = _classify(_make_panel(vix=14.0, tnx=4.5, irx=3.5,
                                             spy_above_sma=True))
    assert regime == "CALM"
    assert signals["vix"] == 14.0
    assert abs(signals["curve_slope"] - 1.0) < 1e-6


def test_normal_when_vix_in_middle_band():
    regime, _ = _classify(_make_panel(vix=20.0, tnx=4.5, irx=3.5,
                                       spy_above_sma=True))
    assert regime == "NORMAL"


def test_falls_back_to_normal_when_no_signals():
    """If VIX/curve/trend data isn't loaded, default to NORMAL (not crash)."""
    regime, _ = _classify(_make_panel())
    assert regime == "NORMAL"


def test_allocator_routes_panic_to_sixty_forty():
    """Direct test of the routing dict."""
    a = RegimeAwareAllocator()
    assert a.routing["PANIC"][0] == "sixty_forty"
    assert a.routing["CALM"][0] == "top_n_momentum"
    assert a.routing["STRESSED"][0] == "risk_parity"


def test_allocator_n_params_zero():
    """No tunable knobs — the thresholds are design constants."""
    assert RegimeAwareAllocator().n_params == 0


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
