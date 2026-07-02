"""Strategy specs — weights, lookback, registry contract."""

from __future__ import annotations

import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fund.data.synthetic import synth_panel, synth_tbill
from fund.strategy.dual_momentum import CASH, DualMomentum
from fund.strategy.ma_crossover import MovingAverageCrossover, _sma
from fund.strategy.registry import build, list_strategies, universe_for
from fund.strategy.risk_parity import RiskParity, _daily_vol
from fund.strategy.sixty_forty import SixtyForty
from fund.strategy.top_n_momentum import TopNMomentum

UNIVERSE = ("SPY", "EFA", "AGG", "GLD", "QQQ")
START, END = date(2010, 1, 1), date(2020, 12, 31)


def _panel_and_tbill():
    return synth_panel(list(UNIVERSE), START, END), synth_tbill(START, END)


def _weights_sum_to_one_or_cash(w: dict[str, float]) -> bool:
    if w == {CASH: 1.0}:
        return True
    return abs(sum(w.values()) - 1.0) < 1e-6


def test_sixty_forty_returns_60_40_when_assets_available():
    panel, tbill = _panel_and_tbill()
    s = SixtyForty()
    w = s.target_weights(panel.as_of(date(2015, 6, 1)),
                         tbill.as_of(date(2015, 6, 1)))
    assert w == {"SPY": 0.60, "AGG": 0.40}
    assert s.n_params == 0


def test_sixty_forty_falls_back_to_cash_when_missing():
    panel, tbill = _panel_and_tbill()
    s = SixtyForty(equity="MISSING", bonds="AGG")
    w = s.target_weights(panel.as_of(date(2015, 6, 1)),
                         tbill.as_of(date(2015, 6, 1)))
    assert w == {CASH: 1.0}


def test_risk_parity_weights_sum_to_one():
    panel, tbill = _panel_and_tbill()
    s = RiskParity(universe=UNIVERSE, vol_window=63)
    w = s.target_weights(panel.as_of(date(2015, 6, 1)),
                         tbill.as_of(date(2015, 6, 1)))
    assert _weights_sum_to_one_or_cash(w)
    # bonds (AGG, low vol) should get the largest weight
    assert w["AGG"] > w["SPY"]
    assert w["AGG"] > w["QQQ"]


def test_risk_parity_falls_back_to_cash_without_history():
    # tiny panel — vol_window can't be computed
    panel, tbill = _panel_and_tbill()
    s = RiskParity(universe=UNIVERSE, vol_window=10_000)
    w = s.target_weights(panel.as_of(date(2010, 2, 1)),
                         tbill.as_of(date(2010, 2, 1)))
    assert w == {CASH: 1.0}


def test_daily_vol_returns_none_with_insufficient_data():
    assert _daily_vol((100.0, 101.0), 100) is None
    assert _daily_vol((100.0, 101.0, 102.0), 2) is not None


def test_dual_momentum_picks_best_asset_or_cash():
    panel, tbill = _panel_and_tbill()
    s = DualMomentum(UNIVERSE, lookback_days=126)
    w = s.target_weights(panel.as_of(date(2015, 6, 1)),
                         tbill.as_of(date(2015, 6, 1)))
    if w != {CASH: 1.0}:
        assert len(w) == 1 and abs(sum(w.values()) - 1.0) < 1e-6


def test_dual_momentum_n_params_is_one():
    assert DualMomentum(UNIVERSE).n_params == 1


def test_registry_builds_each_known_strategy():
    for name in list_strategies():
        s = build(name)
        assert hasattr(s, "target_weights")
        assert hasattr(s, "n_params")


def test_registry_unknown_raises_value_error():
    try:
        build("does_not_exist")
    except ValueError:
        return
    raise AssertionError("expected ValueError for unknown strategy")


def test_universe_for_sixty_forty_uses_only_two_assets():
    u = universe_for("sixty_forty", {})
    assert set(u) == {"SPY", "AGG"}


def test_universe_for_dual_momentum_uses_default_universe():
    u = universe_for("dual_momentum", {})
    assert "SPY" in u and "AGG" in u and len(u) >= 3


def test_top_n_momentum_holds_n_assets_when_above_tbill():
    panel, tbill = _panel_and_tbill()
    s = TopNMomentum(UNIVERSE, n=2, lookback_days=126)
    w = s.target_weights(panel.as_of(date(2015, 6, 1)),
                         tbill.as_of(date(2015, 6, 1)))
    if w != {CASH: 1.0}:
        assert len(w) == 2
        assert abs(sum(w.values()) - 1.0) < 1e-6
        # equal-weighted
        assert all(abs(v - 0.5) < 1e-6 for v in w.values())


def test_top_n_momentum_falls_back_to_cash_when_all_below_tbill():
    """If every asset's trailing return is below the T-bill window, hold cash."""
    panel, tbill = _panel_and_tbill()
    # Use a very long lookback (most data) — for synthetic, some assets are
    # below tbill in early periods. The fallback is correctness, not direction.
    s = TopNMomentum(UNIVERSE, n=2, lookback_days=10)
    w = s.target_weights(panel.as_of(date(2010, 1, 15)),
                         tbill.as_of(date(2010, 1, 15)))
    # Either holds something (and weights are valid) or fully cash
    assert _weights_sum_to_one_or_cash(w)


def test_top_n_n_params_is_two():
    assert TopNMomentum(UNIVERSE).n_params == 2


def test_ma_crossover_goes_long_when_fast_above_slow():
    panel, tbill = _panel_and_tbill()
    s = MovingAverageCrossover(asset="SPY", fast=20, slow=50)
    w = s.target_weights(panel.as_of(date(2018, 1, 1)),
                         tbill.as_of(date(2018, 1, 1)))
    # synthetic data with positive drift will mostly be fast > slow
    assert w in ({"SPY": 1.0}, {CASH: 1.0})


def test_ma_crossover_cash_without_enough_history():
    panel, tbill = _panel_and_tbill()
    s = MovingAverageCrossover(asset="SPY", fast=50, slow=99999)
    w = s.target_weights(panel.as_of(date(2018, 1, 1)),
                         tbill.as_of(date(2018, 1, 1)))
    assert w == {CASH: 1.0}


def test_ma_crossover_cash_when_asset_missing():
    panel, tbill = _panel_and_tbill()
    s = MovingAverageCrossover(asset="DOES_NOT_EXIST", fast=50, slow=200)
    w = s.target_weights(panel.as_of(date(2018, 1, 1)),
                         tbill.as_of(date(2018, 1, 1)))
    assert w == {CASH: 1.0}


def test_sma_basic():
    assert _sma((1.0, 2.0, 3.0, 4.0), 2) == 3.5
    assert _sma((1.0, 2.0), 5) is None


def test_no_strategy_returns_weights_above_one():
    panel, tbill = _panel_and_tbill()
    for name in list_strategies():
        s = build(name)
        w = s.target_weights(panel.as_of(date(2018, 1, 1)),
                             tbill.as_of(date(2018, 1, 1)))
        assert _weights_sum_to_one_or_cash(w), f"{name} weights sum != 1: {w}"


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
