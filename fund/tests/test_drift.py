"""Drift-from-backtest detector — Welch t-test on live vs backtest."""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fund.drift import _normal_two_sided_p, _welch_t


def test_welch_t_zero_when_means_equal():
    # Two distributions with same mean should produce t ~ 0
    t = _welch_t(0.001, 0.01, 100, 0.001, 0.01, 1000)
    assert abs(t) < 0.01


def test_welch_t_negative_when_first_mean_lower():
    t = _welch_t(0.0001, 0.01, 30, 0.005, 0.01, 1000)
    assert t < -2


def test_welch_t_handles_tiny_sample():
    # n1 < 2 should return 0 instead of crashing
    assert _welch_t(0.001, 0.01, 1, 0.001, 0.01, 1000) == 0.0


def test_normal_two_sided_p_at_zero_is_one():
    assert abs(_normal_two_sided_p(0.0) - 1.0) < 1e-6


def test_normal_two_sided_p_at_two_approx_5pct():
    # Standard normal: ±2σ corresponds to p ≈ 0.0455
    p = _normal_two_sided_p(2.0)
    assert 0.04 < p < 0.05


def test_normal_two_sided_p_at_three_very_small():
    p = _normal_two_sided_p(3.0)
    assert p < 0.005


def test_evaluate_returns_in_band_when_no_live():
    """No live data → unmeasurable, returns in_band sentinel."""
    from fund.drift import evaluate
    # We can't run a real backtest in unit test (no network in CI),
    # so call with empty live returns — it should short-circuit before
    # the backtest.
    r = evaluate("sixty_forty", {}, [], source="synthetic")
    assert r.n_live == 0
    assert r.verdict == "in_band"


def test_evaluate_in_band_with_consistent_live(monkeypatch=None):
    """Mock the backtest to avoid network. Live mean equal to backtest mean
    should produce in_band verdict."""
    from fund.drift import evaluate, _welch_t
    from datetime import date
    import fund.drift as drift_mod

    class FakeBT:
        returns = [0.0004] * 2000   # 2000 days, mean 0.0004

    def fake_load_panel(*a, **k):
        return None, None
    def fake_build(*a, **k):
        return None
    def fake_run_backtest(*a, **k):
        return FakeBT()

    orig_load = drift_mod.load_panel
    orig_build = drift_mod.build_strategy
    orig_run = drift_mod.run_backtest
    drift_mod.load_panel = fake_load_panel
    drift_mod.build_strategy = fake_build
    drift_mod.run_backtest = fake_run_backtest
    try:
        live_returns = [0.0004 + (0.01 if i % 2 == 0 else -0.01)
                        for i in range(30)]   # mean ~ 0.0004
        r = evaluate("sixty_forty", {}, live_returns, source="synthetic")
        assert r.verdict == "in_band"
        assert r.n_live == 30
        assert r.n_backtest == 2000
    finally:
        drift_mod.load_panel = orig_load
        drift_mod.build_strategy = orig_build
        drift_mod.run_backtest = orig_run


def test_evaluate_drifted_when_live_way_off_backtest():
    """Mock backtest mean = 0.0005/day; live mean = -0.005/day (huge drift)."""
    from fund.drift import evaluate
    import fund.drift as drift_mod

    # backtest needs variance for t to be defined
    class FakeBT:
        returns = [0.0005 + (0.008 if i % 2 == 0 else -0.008)
                   for i in range(2000)]

    def fake_load(*a, **k): return None, None
    def fake_build(*a, **k): return None
    def fake_run(*a, **k): return FakeBT()
    orig = (drift_mod.load_panel, drift_mod.build_strategy, drift_mod.run_backtest)
    drift_mod.load_panel = fake_load
    drift_mod.build_strategy = fake_build
    drift_mod.run_backtest = fake_run
    try:
        # Need non-zero variance for Welch t to be defined; alternate signs
        live = [-0.005 + (0.001 if i % 2 == 0 else -0.001) for i in range(30)]
        r = evaluate("sixty_forty", {}, live, source="synthetic")
        assert r.verdict in ("drifted", "drifting"), f"got {r.verdict}: {r.reason}"
        assert r.t_statistic < -2, f"t={r.t_statistic}"
    finally:
        drift_mod.load_panel = orig[0]
        drift_mod.build_strategy = orig[1]
        drift_mod.run_backtest = orig[2]


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
