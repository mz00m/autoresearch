"""MultiStrategy — weighted blend of underlying strategies."""

from __future__ import annotations

import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fund.data.synthetic import synth_panel, synth_tbill
from fund.strategy.dual_momentum import CASH
from fund.strategy.multi import MultiStrategy


UNIVERSE = ("SPY", "EFA", "AGG", "GLD", "QQQ")
START, END = date(2010, 1, 1), date(2020, 12, 31)


def _panel_and_tbill():
    return synth_panel(list(UNIVERSE), START, END), synth_tbill(START, END)


def test_weights_must_sum_to_one():
    try:
        MultiStrategy(allocations=(("sixty_forty", {}, 0.5),
                                    ("risk_parity", {}, 0.3)))
    except ValueError as e:
        assert "sum to 1.0" in str(e)
        return
    raise AssertionError("expected ValueError for non-unit weights")


def test_unit_weights_pass():
    m = MultiStrategy(allocations=(("sixty_forty", {}, 0.6),
                                    ("risk_parity", {"vol_window": 63}, 0.4)))
    assert m is not None


def test_blend_target_weights_sum_to_one():
    panel, tbill = _panel_and_tbill()
    m = MultiStrategy(allocations=(("sixty_forty", {}, 0.6),
                                    ("risk_parity", {"vol_window": 63}, 0.4)))
    w = m.target_weights(panel.as_of(date(2015, 6, 1)),
                          tbill.as_of(date(2015, 6, 1)))
    total = sum(w.values())
    assert abs(total - 1.0) < 1e-6, f"got {total}"


def test_blend_includes_components_of_each_strategy():
    panel, tbill = _panel_and_tbill()
    m = MultiStrategy(allocations=(("sixty_forty", {}, 0.5),
                                    ("risk_parity", {"vol_window": 63}, 0.5)))
    w = m.target_weights(panel.as_of(date(2015, 6, 1)),
                          tbill.as_of(date(2015, 6, 1)))
    # 60/40 contributes SPY and AGG; risk_parity contributes all 5 inverse-vol
    # so SPY should get 0.5 * 0.6 + 0.5 * (rp weight for SPY) > 0
    assert w.get("SPY", 0) > 0
    assert w.get("AGG", 0) > 0


def test_explicit_cash_slot_lands_in_cash_bucket():
    panel, tbill = _panel_and_tbill()
    m = MultiStrategy(allocations=(("sixty_forty", {}, 0.6),
                                    ("cash", {}, 0.4)))
    w = m.target_weights(panel.as_of(date(2015, 6, 1)),
                          tbill.as_of(date(2015, 6, 1)))
    assert abs(w.get(CASH, 0) - 0.4) < 1e-6


def test_broken_underlying_strategy_redirects_to_cash():
    """If a sub-strategy raises, we donate its slice to cash rather than
    silently overweighting the others (could be surprising in production)."""
    panel, tbill = _panel_and_tbill()
    # 'nonexistent' will fail build_strategy lookup
    m = MultiStrategy(allocations=(("sixty_forty", {}, 0.5),
                                    ("nonexistent", {}, 0.5)))
    w = m.target_weights(panel.as_of(date(2015, 6, 1)),
                          tbill.as_of(date(2015, 6, 1)))
    # Half goes to cash, half to 60/40 (SPY 0.3 + AGG 0.2)
    assert abs(w.get(CASH, 0) - 0.5) < 1e-6
    assert abs(w.get("SPY", 0) - 0.30) < 1e-6
    assert abs(w.get("AGG", 0) - 0.20) < 1e-6


def test_n_params_is_count_of_allocations():
    m = MultiStrategy(allocations=(("sixty_forty", {}, 0.5),
                                    ("risk_parity", {}, 0.5)))
    assert m.n_params == 2


def test_registry_builds_multi_from_params():
    from fund.strategy.registry import build, universe_for, list_strategies
    m = build("multi", {"allocations": [
        ["sixty_forty", {}, 0.6],
        ["risk_parity", {"vol_window": 63}, 0.4],
    ]})
    assert m.n_params == 2
    # universe should be the union of underlying universes
    u = universe_for("multi", {"allocations": [
        ["sixty_forty", {}, 0.6],
        ["risk_parity", {"vol_window": 63}, 0.4],
    ]})
    assert "SPY" in u and "AGG" in u
    assert "multi" in list_strategies()


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
