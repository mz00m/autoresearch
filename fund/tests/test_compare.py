"""Strategy comparison — runs in isolation, renders comparison HTML."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fund.compare import _metrics, _run_one, render
from fund.portfolio import EquityPoint, Portfolio


def _stub_pf(equities: list[tuple[str, float]]) -> Portfolio:
    pf = Portfolio.fresh(equities[0][1], date.fromisoformat(equities[0][0]))
    pf.history = [EquityPoint(date=d, cash=e, position_value=0.0, equity=e)
                  for d, e in equities]
    return pf


def test_metrics_zero_for_empty_history():
    pf = Portfolio.fresh(10_000, date(2024, 1, 1))
    m = _metrics(pf, [])
    assert m["cum"] == 0.0
    assert m["n_days"] == 0


def test_metrics_cum_from_history():
    pf = _stub_pf([("2024-01-01", 10_000), ("2024-01-02", 10_500)])
    m = _metrics(pf, [{"date": "2024-01-02", "day_return": "0.05",
                       "benchmark_cum_return": "0.02"}])
    assert abs(m["cum"] - 0.05) < 1e-6
    assert abs(m["bench_cum"] - 0.02) < 1e-6
    assert abs(m["excess"] - 0.03) < 1e-6


def test_metrics_max_dd_tracks_peak_to_trough():
    pf = _stub_pf([("2024-01-01", 10_000),
                   ("2024-01-02", 11_000),   # peak
                   ("2024-01-03", 9_900)])   # -10% from peak
    m = _metrics(pf, [])
    assert abs(m["max_dd"] - 0.10) < 1e-6


def test_metrics_best_and_worst_day_from_log():
    pf = _stub_pf([("2024-01-01", 10_000), ("2024-01-04", 10_100)])
    rows = [
        {"date": "2024-01-02", "day_return": "0.01", "benchmark_cum_return": ""},
        {"date": "2024-01-03", "day_return": "-0.03", "benchmark_cum_return": ""},
        {"date": "2024-01-04", "day_return": "0.02", "benchmark_cum_return": ""},
    ]
    m = _metrics(pf, rows)
    assert abs(m["best_day"] - 0.02) < 1e-6
    assert abs(m["worst_day"] + 0.03) < 1e-6


def test_render_marks_winner_row():
    a_pf = _stub_pf([("2024-01-01", 10_000), ("2024-01-04", 10_500)])
    b_pf = _stub_pf([("2024-01-01", 10_000), ("2024-01-04", 9_800)])
    html = render(
        [("alpha", a_pf, [], "#1f4f8b"), ("beta", b_pf, [], "#a83232")],
        days=3, end=date(2024, 1, 4), principal=10_000, active="beta")
    assert "winner" in html
    assert "alpha" in html and "beta" in html
    # active != winner -> "trails the bench leader" hint should appear
    assert "trails" in html


def test_render_when_active_is_winner_says_led():
    a_pf = _stub_pf([("2024-01-01", 10_000), ("2024-01-04", 10_500)])
    b_pf = _stub_pf([("2024-01-01", 10_000), ("2024-01-04", 9_800)])
    html = render(
        [("alpha", a_pf, [], "#1f4f8b"), ("beta", b_pf, [], "#a83232")],
        days=3, end=date(2024, 1, 4), principal=10_000, active="alpha")
    assert "would have led" in html


def test_run_one_isolation_does_not_touch_live_state():
    """compare._run_one creates an isolated state file; the canonical
    portfolio_state.json must not be touched."""
    from fund.portfolio import STATE_PATH
    canonical = STATE_PATH
    sentinel = "__sentinel_unmodified__"
    # Write a sentinel into canonical so we can confirm it's unchanged.
    backup = None
    try:
        if os.path.exists(canonical):
            with open(canonical) as f:
                backup = f.read()
        with open(canonical, "w") as f:
            f.write(sentinel)
        # Run a 1-strategy compare on synthetic so the test is fast + offline
        pf, rows = _run_one("sixty_forty", days=5, end=date(2020, 12, 1),
                            principal=10_000, source="synthetic")
        # Canonical state must be untouched
        with open(canonical) as f:
            assert f.read() == sentinel
        assert pf.cash >= 0
    finally:
        if backup is not None:
            with open(canonical, "w") as f:
                f.write(backup)
        else:
            os.unlink(canonical)


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
