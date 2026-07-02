"""Tests for the sacred risk engine. Run: python3 -m pytest fund/tests -q
(also runnable plain: python3 fund/tests/test_risk_engine.py)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk_engine import (  # noqa: E402
    AccountMode,
    Kind,
    Order,
    RiskEngine,
    worst_case_loss,
)


def engine(**kw):
    base = dict(principal=25_000.0, equity=25_000.0, mode=AccountMode.CASH)
    base.update(kw)
    return RiskEngine(**base)


# --- bounded-liability instruments are accepted within limits --------------

def test_long_equity_within_cash_ok():
    v = engine().check(Order(Kind.LONG_EQUITY, "SPY", qty=10, price=500))
    assert v.approved
    assert v.max_loss == 5_000
    assert v.cash_required == 5_000


def test_long_call_max_loss_is_premium():
    v = engine().check(Order(Kind.LONG_CALL, "AAPL", contracts=2, premium=3.0))
    assert v.approved
    assert v.max_loss == 2 * 100 * 3.0  # 600
    assert v.cash_required == 600


def test_debit_spread_max_loss_is_net_debit():
    v = engine().check(Order(Kind.DEBIT_SPREAD, "QQQ", contracts=5, net_debit=1.2))
    assert v.approved
    assert v.max_loss == 5 * 100 * 1.2  # 600


def test_cash_secured_put_is_bounded():
    ml, cash = worst_case_loss(
        Order(Kind.CASH_SECURED_PUT, "T", contracts=1, strike=20, premium=1)
    )
    assert ml == 100 * (20 - 1)  # 1900
    assert cash == 1900


# --- THE rule: never lose more than principal ------------------------------

def test_rejects_when_worst_case_exceeds_equity():
    e = engine(equity=5_000.0, settled_cash=5_000.0)
    v = e.check(Order(Kind.LONG_EQUITY, "SPY", qty=20, price=500))  # needs 10k
    assert not v.approved
    assert any("exceed equity" in r or "settled cash" in r for r in v.reasons)


def test_portfolio_aggregate_loss_capped_at_equity():
    e = engine(equity=10_000.0, settled_cash=10_000.0)
    e.apply(Order(Kind.LONG_EQUITY, "SPY", qty=12, price=500))  # 6k committed
    v = e.check(Order(Kind.LONG_EQUITY, "QQQ", qty=12, price=500))  # +6k -> 12k > 10k
    assert not v.approved


# --- deny-by-default for forbidden / unknown shapes ------------------------

def test_unknown_kind_is_denied():
    bad = Order.__new__(Order)  # bypass dataclass to inject a rogue kind
    object.__setattr__(bad, "kind", "naked_call")
    object.__setattr__(bad, "symbol", "TSLA")
    for fld in ("qty", "contracts", "price", "entry_price", "strike",
                "premium", "net_debit", "note"):
        object.__setattr__(bad, fld, 0.0 if fld != "note" else "")
    v = engine().check(bad)
    assert not v.approved
    assert v.max_loss == float("inf")


def test_invalid_params_rejected_not_crashed():
    v = engine().check(Order(Kind.LONG_EQUITY, "SPY", qty=-5, price=500))
    assert not v.approved


# --- cash vs margin & circuit breaker --------------------------------------

def test_cash_mode_limited_by_settled_cash():
    e = engine(equity=25_000.0, settled_cash=1_000.0)
    v = e.check(Order(Kind.LONG_EQUITY, "SPY", qty=10, price=500))  # 5k > 1k settled
    assert not v.approved


def test_apply_decrements_settled_cash():
    e = engine(equity=25_000.0, settled_cash=25_000.0)
    e.apply(Order(Kind.LONG_EQUITY, "SPY", qty=10, price=500))
    assert abs(e.settled_cash - 20_000.0) < 1e-6


def test_drawdown_kill_switch_trips_and_halts():
    e = engine(equity=10_000.0, settled_cash=10_000.0, drawdown_halt_frac=0.5)
    # floor = 25k * 0.5 = 12.5k; equity 10k is below -> trip
    v = e.check(Order(Kind.LONG_EQUITY, "SPY", qty=1, price=100))
    assert not v.approved
    assert e.halted
    # once halted, even a tiny order is refused
    v2 = e.check(Order(Kind.LONG_EQUITY, "SPY", qty=1, price=1))
    assert not v2.approved


def test_cannot_apply_rejected_order():
    e = engine(equity=100.0, settled_cash=100.0)
    try:
        e.apply(Order(Kind.LONG_EQUITY, "SPY", qty=10, price=500))
        raised = False
    except PermissionError:
        raised = True
    assert raised


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} tests passed")


if __name__ == "__main__":
    _run_all()
