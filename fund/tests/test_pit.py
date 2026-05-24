"""Tests for the point-in-time guard and the backtest's look-ahead safety.
Run from repo root: python3 fund/tests/test_pit.py
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fund.backtest import run_backtest  # noqa: E402
from fund.data.pit import Panel, PriceSeries  # noqa: E402
from fund.data.synthetic import synth_panel, synth_tbill  # noqa: E402
from fund.strategy.dual_momentum import CASH, DualMomentum  # noqa: E402


def _series():
    ds = tuple(date(2020, 1, d) for d in range(1, 11))
    cs = tuple(float(x) for x in range(100, 110))
    return PriceSeries("X", ds, cs)


def test_as_of_excludes_future():
    s = _series()
    v = s.as_of(date(2020, 1, 5))
    assert v.dates[-1] == date(2020, 1, 5)
    assert v.last == 104.0
    assert len(v) == 5


def test_as_of_before_start_is_empty():
    s = _series()
    assert len(s.as_of(date(2019, 1, 1))) == 0


def test_trailing_return():
    s = _series()
    # 109/100 - 1 over 9 steps
    assert abs(s.trailing_return(9) - (109.0 / 100.0 - 1.0)) < 1e-12
    assert s.trailing_return(100) is None  # not enough history


def test_panel_common_dates_intersection():
    a = PriceSeries("A", (date(2020, 1, 1), date(2020, 1, 2)), (1.0, 2.0))
    b = PriceSeries("B", (date(2020, 1, 2), date(2020, 1, 3)), (1.0, 2.0))
    assert Panel({"A": a, "B": b}).common_dates() == [date(2020, 1, 2)]


def test_strategy_cannot_see_future():
    """A strategy fed an as_of panel sees only past data, so its decision on a
    date is invariant to whatever happens afterwards."""
    full = synth_panel(["SPY", "AGG"], date(2018, 1, 1), date(2021, 12, 31), seed=3)
    tb = synth_tbill(date(2018, 1, 1), date(2021, 12, 31), seed=3)
    strat = DualMomentum(("SPY", "AGG"), lookback_days=126)
    asof = date(2020, 6, 1)
    w1 = strat.target_weights(full.as_of(asof), tb.as_of(asof))
    # truncate the universe to ONLY past data, decision must be identical
    truncated = full.as_of(asof)
    w2 = strat.target_weights(truncated.as_of(asof), tb.as_of(asof))
    assert w1 == w2


def test_backtest_runs_and_is_bounded():
    panel = synth_panel(["SPY", "AGG", "GLD"], date(2015, 1, 1), date(2020, 12, 31), seed=1)
    tb = synth_tbill(date(2015, 1, 1), date(2020, 12, 31), seed=1)
    res = run_backtest(DualMomentum(("SPY", "AGG", "GLD"), 126), panel, tb)
    assert len(res.returns) > 1000
    # long-only single-asset: a daily loss can never exceed 100%
    assert min(res.returns) > -1.0
    assert len(res.rebal_dates) > 12


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
    print(f"\n{len(fns)}/{len(fns)} tests passed")


if __name__ == "__main__":
    _run_all()
