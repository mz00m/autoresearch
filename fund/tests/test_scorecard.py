"""scorecard — the ranked candidate selection view."""

from __future__ import annotations

import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import fund.scorecard as sc
from fund.data.synthetic import synth_panel
from fund.portfolio import Portfolio, Position

ASOF = date(2023, 12, 29)


def _panel(symbols=("SPY", "QQQ", "AGG", "GLD")):
    return synth_panel(list(symbols), date(2018, 1, 1), date(2023, 12, 31), seed=7)


def _no_thesis(sym):
    return None


def test_universe_excludes_signals_and_cash():
    u = sc.scorecard_universe()
    assert "CASH" not in u
    assert not any(s.startswith("^") for s in u)
    assert "SPY" in u and "TQQQ" in u


def test_rows_ranked_by_score():
    sc.active_for = _no_thesis
    rows = sc.build_scorecard(_panel(), ASOF, symbols=("SPY", "QQQ", "AGG", "GLD"))
    assert len(rows) == 4
    scores = [r.score for r in rows]
    assert scores == sorted(scores, reverse=True)
    assert all(r.r63 is not None and r.worst_3d is not None for r in rows)


def test_thesis_conviction_lifts_score():
    panel = _panel()
    sc.active_for = _no_thesis
    base = {r.symbol: r.score
            for r in sc.build_scorecard(panel, ASOF, symbols=("SPY", "QQQ"))}
    sc.active_for = (lambda sym: {"confidence": 5, "catalyst": "x",
                                  "created_at": "2023-06-01T00:00:00"}
                     if sym == "SPY" else None)
    lifted = {r.symbol: r.score
              for r in sc.build_scorecard(panel, ASOF, symbols=("SPY", "QQQ"))}
    assert abs(lifted["SPY"] - (base["SPY"] + 15)) < 1e-9   # 5 conviction × 3
    assert abs(lifted["QQQ"] - base["QQQ"]) < 1e-9


def test_held_weight_and_unrealized():
    sc.active_for = _no_thesis
    pf = Portfolio.fresh(10_000.0, date(2023, 1, 1))
    pf.cash = 5_000.0
    pf.positions["SPY"] = Position(qty=10, avg_cost=100.0)
    rows = sc.build_scorecard(_panel(), ASOF, pf=pf, symbols=("SPY", "QQQ"))
    spy = next(r for r in rows if r.symbol == "SPY")
    qqq = next(r for r in rows if r.symbol == "QQQ")
    assert spy.held_weight > 0 and spy.unrealized_pct is not None
    assert qqq.held_weight == 0 and qqq.unrealized_pct is None


def test_missing_symbol_skipped():
    sc.active_for = _no_thesis
    rows = sc.build_scorecard(_panel(("SPY",)), ASOF, symbols=("SPY", "GHOST"))
    assert [r.symbol for r in rows] == ["SPY"]


def test_composite_penalizes_fragility():
    s_safe, _ = sc._composite(0.05, 0.10, 0.20, True, -0.05, 0.0, 0)
    s_frag, _ = sc._composite(0.05, 0.10, 0.20, True, -0.40, 0.0, 0)
    assert s_frag < s_safe


def test_regime_tilt_applied():
    s_flat, _ = sc._composite(0.1, 0.1, 0.1, False, -0.05, 0.0, 0)
    s_tilt, _ = sc._composite(0.1, 0.1, 0.1, False, -0.05, 10.0, 0)
    assert abs(s_tilt - (s_flat + 10.0)) < 1e-9


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
    print(f"\n{len(fns)}/{len(fns)} tests passed")


if __name__ == "__main__":
    _run_all()
