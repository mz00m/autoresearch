"""Sector + correlation concentration caps in the risk engine."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fund.risk_concentration import ConcentrationLimits, evaluate
from fund.risk_engine import AccountMode, Kind, Order, RiskEngine


def test_no_book_under_caps_passes():
    reasons = evaluate({}, {"SPY": 5_000}, equity=25_000)
    assert reasons == []


def test_sector_cap_rejects_overconcentration():
    # XLE + USO both energy; together would be 12000 = 48% of 25k > 40% cap
    book = {"XLE": 6_000}
    reasons = evaluate(book, {"USO": 6_000}, equity=25_000)
    assert any("energy" in r for r in reasons)


def test_single_symbol_cap_rejects():
    reasons = evaluate({}, {"SPY": 15_000}, equity=25_000)
    assert any("SPY" in r and "single-symbol" in r for r in reasons)


def test_correlated_cluster_cap_rejects():
    # SPY + QQQ + UPRO are all in the us_equity cluster
    book = {"SPY": 8_000, "QQQ": 5_000}
    reasons = evaluate(book, {"UPRO": 5_000}, equity=25_000)
    assert any("correlated-cluster" in r for r in reasons)


def test_uncategorized_symbol_does_not_trigger_sector_cap():
    """A symbol with no SECTOR mapping is 'uncategorized' and shouldn't be capped."""
    reasons = evaluate({}, {"XYZWEIRD": 24_000}, equity=25_000)
    # single-symbol cap will catch it but no sector reason
    assert not any("sector" in r and "uncategorized" in r for r in reasons)


def test_engine_integration_rejects_sector_breach():
    limits = ConcentrationLimits(max_sector_frac=0.40,
                                  max_cluster_frac=0.60,
                                  max_single_symbol_frac=0.50)
    eng = RiskEngine(principal=25_000, equity=25_000,
                     mode=AccountMode.CASH, settled_cash=25_000,
                     concentration_limits=limits)
    # First energy order: 30% — under sector cap
    o1 = Order(kind=Kind.LONG_EQUITY, symbol="XLE", qty=126, price=59.49)
    v1 = eng.check(o1)
    assert v1.approved
    eng.apply(o1)
    # Second energy order would push to ~80% — must be rejected
    o2 = Order(kind=Kind.LONG_EQUITY, symbol="USO", qty=88, price=140.92)
    v2 = eng.check(o2)
    assert not v2.approved
    assert any("energy" in r for r in v2.reasons)


def test_engine_without_limits_does_not_check_concentration():
    """Backwards compat: an engine without concentration_limits behaves as before."""
    eng = RiskEngine(principal=25_000, equity=25_000,
                     mode=AccountMode.CASH, settled_cash=25_000)
    o = Order(kind=Kind.LONG_EQUITY, symbol="SPY", qty=33, price=745.64)
    v = eng.check(o)
    assert v.approved
    # No concentration-related reasons in the message stream
    assert not any("sector" in r or "cluster" in r for r in v.reasons)


def test_apply_updates_open_exposure_for_future_checks():
    limits = ConcentrationLimits(max_sector_frac=0.40)
    eng = RiskEngine(principal=25_000, equity=25_000,
                     mode=AccountMode.CASH, settled_cash=25_000,
                     concentration_limits=limits)
    eng.apply(Order(kind=Kind.LONG_EQUITY, symbol="XLE", qty=100, price=59.49))
    assert "XLE" in eng.open_exposure
    assert abs(eng.open_exposure["XLE"] - 5949.0) < 0.01


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
