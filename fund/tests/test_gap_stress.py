"""gap_stress — stops are triggers, not floors; verify the worst-case math."""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fund.data.pit import Panel, PriceSeries
from fund.gap_stress import stress_portfolio, stress_symbol


def _series(symbol, rets):
    """Build a PriceSeries from a list of daily returns starting at 100."""
    closes, p = [100.0], 100.0
    for r in rets:
        p *= (1.0 + r)
        closes.append(p)
    start = date(2024, 1, 1)
    dates = tuple(start + timedelta(days=i) for i in range(len(closes)))
    return PriceSeries(symbol, dates, tuple(closes))


def _crash_series(symbol="LEV"):
    # 40 quiet days with one -20% gap and a -10%/-10%/-5% three-day slide
    rets = [0.001] * 15 + [-0.20] + [0.001] * 10 + [-0.10, -0.10, -0.05] + [0.001] * 11
    return _series(symbol, rets)


def test_worst_1d_and_3d():
    f = stress_symbol("LEV", Panel({"LEV": _crash_series()}), weight=1.0,
                      stop_pct=0.10)
    assert abs(f.worst_1d - (-0.20)) < 1e-9
    expected_3d = 0.90 * 0.90 * 0.95 - 1.0     # the slide beats the single gap
    assert abs(f.worst_3d - expected_3d) < 1e-9


def test_days_past_stop_counted():
    f = stress_symbol("LEV", Panel({"LEV": _crash_series()}), weight=1.0,
                      stop_pct=0.10)
    assert f.days_past_stop == 1                # only the -20% day exceeds 10%
    assert abs(f.stop_slippage - (-0.10)) < 1e-9  # gapped 10% past the trail


def test_short_history_returns_none():
    short = _series("NEW", [0.01] * 10)         # < 30 closes
    assert stress_symbol("NEW", Panel({"NEW": short}), weight=1.0) is None


def test_portfolio_aggregation():
    panel = Panel({"LEV": _crash_series("LEV"),
                   "CALM": _series("CALM", [0.001] * 40 + [-0.02] + [0.001] * 5)})
    rep = stress_portfolio({"LEV": 0.5, "CALM": 0.5, "CASH": 0.0}, panel,
                           stop_pct=0.10)
    assert len(rep.findings) == 2
    assert abs(rep.naive_stop_loss - (-0.10)) < 1e-9   # -10% × total weight 1.0
    expected_1d = 0.5 * -0.20 + 0.5 * -0.02
    assert abs(rep.gap_loss_1d - expected_1d) < 1e-9
    assert rep.gap_loss_3d <= rep.gap_loss_1d          # 3-day is never kinder


def test_missing_symbol_skipped():
    rep = stress_portfolio({"GHOST": 1.0}, Panel({}), stop_pct=0.10)
    assert rep.findings == []


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
    print(f"\n{len(fns)}/{len(fns)} tests passed")


if __name__ == "__main__":
    _run_all()
