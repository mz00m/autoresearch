"""options_suggester + options_budget — the rails around the asymmetric layer."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import fund.options_suggester as osug
from fund import options_budget
from fund.portfolio import Portfolio, Position

ASOF = date(2026, 5, 25)


def _tmp_budget_path():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)  # start absent — load_spends treats missing as empty
    return path


def _thesis(confidence=4):
    return {"confidence": confidence, "catalyst": "test catalyst",
            "kill_switch": "test", "horizon": "6mo", "status": "active"}


def _pf(cash=25_000.0, positions=None):
    pf = Portfolio.fresh(cash, date(2026, 1, 1))
    for sym, (qty, cost) in (positions or {}).items():
        pf.positions[sym] = Position(qty=qty, avg_cost=cost)
    return pf


# --- budget math -------------------------------------------------------------

def test_budget_record_and_trailing():
    p = _tmp_budget_path()
    options_budget.record("QQQ", 500.0, date(2026, 5, 1), path=p)
    options_budget.record("SPY", 250.0, date(2025, 1, 1), path=p)  # >12mo old
    assert options_budget.spent_trailing(ASOF, path=p) == 500.0


def test_budget_remaining_never_negative():
    p = _tmp_budget_path()
    options_budget.record("QQQ", 99_999.0, date(2026, 5, 1), path=p)
    assert options_budget.remaining(25_000.0, ASOF, path=p) == 0.0


def test_budget_rejects_nonpositive_cost():
    p = _tmp_budget_path()
    try:
        options_budget.record("QQQ", 0.0, ASOF, path=p)
        raised = False
    except ValueError:
        raised = True
    assert raised


# --- single suggestion sizing ------------------------------------------------

def test_suggest_basic_shape():
    osug.active_for = lambda sym: _thesis(4)
    s = osug.suggest_for("QQQ", 500.0, book_value=35_000.0, asof=ASOF)
    assert s is not None
    assert s.strike > 500.0                       # OTM
    assert s.breakeven_price > s.strike           # strike + premium
    assert date.fromisoformat(s.expiry).weekday() == 4   # a real Friday expiry
    assert s.days_to_expiry >= 30
    assert s.est_total_cost <= 35_000.0 * 0.05 * osug.OVERSIZE_TOLERANCE


def test_oversize_contract_is_skipped_not_forced():
    osug.active_for = lambda sym: _thesis(4)
    # one ASML contract costs far more than 5% of a small book
    s = osug.suggest_for("ASML", 900.0, book_value=10_000.0, asof=ASOF)
    assert s is None


def test_budget_cap_below_one_contract_returns_none():
    osug.active_for = lambda sym: _thesis(4)
    s = osug.suggest_for("QQQ", 500.0, book_value=35_000.0, asof=ASOF,
                         max_premium=5.0)
    assert s is None


# --- portfolio batch: budget trimming + engine verdict ------------------------

def test_batch_respects_premium_budget():
    p = _tmp_budget_path()
    osug.active_for = lambda sym: _thesis(5)
    pf = _pf(cash=25_000.0, positions={"QQQ": (20, 500.0), "SPY": (20, 500.0)})
    prices = {"QQQ": 500.0, "SPY": 500.0}
    # tiny annual budget: fits roughly one contract, not two positions
    suggs, before = osug.suggest_for_portfolio(
        pf, prices, asof=ASOF, annual_budget_pct=0.005, budget_path=p)
    total = sum(s.est_total_cost for s in suggs)
    assert total <= before + 1e-9
    assert len(suggs) <= 1


def test_budget_goes_to_highest_conviction_first():
    p = _tmp_budget_path()
    conv = {"QQQ": 5, "SPY": 3}
    osug.active_for = lambda sym: _thesis(conv.get(sym, 3))
    pf = _pf(cash=25_000.0, positions={"SPY": (20, 500.0), "QQQ": (20, 500.0)})
    prices = {"QQQ": 500.0, "SPY": 500.0}
    suggs, _ = osug.suggest_for_portfolio(
        pf, prices, asof=ASOF, annual_budget_pct=0.005, budget_path=p)
    assert suggs and suggs[0].symbol == "QQQ"


def test_exhausted_budget_yields_no_suggestions():
    p = _tmp_budget_path()
    options_budget.record("QQQ", 99_999.0, date(2026, 5, 1), path=p)
    osug.active_for = lambda sym: _thesis(5)
    pf = _pf(cash=25_000.0, positions={"QQQ": (20, 500.0)})
    suggs, before = osug.suggest_for_portfolio(
        pf, {"QQQ": 500.0}, asof=ASOF, budget_path=p)
    assert before == 0.0 and suggs == []


def test_engine_approves_when_cash_covers():
    p = _tmp_budget_path()
    osug.active_for = lambda sym: _thesis(4)
    pf = _pf(cash=25_000.0, positions={"QQQ": (20, 500.0)})
    suggs, _ = osug.suggest_for_portfolio(pf, {"QQQ": 500.0}, asof=ASOF,
                                          budget_path=p)
    assert suggs and suggs[0].engine_approved
    assert "OK" in suggs[0].engine_reason


def test_engine_rejects_when_settled_cash_short():
    p = _tmp_budget_path()
    osug.active_for = lambda sym: _thesis(4)
    pf = _pf(cash=0.50, positions={"QQQ": (20, 500.0)})   # no settled cash
    suggs, _ = osug.suggest_for_portfolio(pf, {"QQQ": 500.0}, asof=ASOF,
                                          budget_path=p)
    assert suggs and not suggs[0].engine_approved
    assert "settled cash" in suggs[0].engine_reason


def test_below_conviction_positions_skipped():
    p = _tmp_budget_path()
    osug.active_for = lambda sym: _thesis(2)
    pf = _pf(cash=25_000.0, positions={"QQQ": (20, 500.0)})
    suggs, _ = osug.suggest_for_portfolio(pf, {"QQQ": 500.0}, asof=ASOF,
                                          budget_path=p)
    assert suggs == []


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
    print(f"\n{len(fns)}/{len(fns)} tests passed")


if __name__ == "__main__":
    _run_all()
