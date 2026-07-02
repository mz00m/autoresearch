"""Portfolio state arithmetic — cash, positions, fills, mark-to-market."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fund.portfolio import (Portfolio, Ticket, cumulative_return, daily_returns,
                            drawdown)

PASS, FAIL = "PASS", "FAIL"


def _t(side: str, sym: str, qty: int, ref_price: float, status: str = "pending") -> Ticket:
    return Ticket(ticket_id="x", created="2024-01-01", symbol=sym, side=side,
                  qty=qty, ref_price=ref_price, rationale="test",
                  risk_max_loss=qty * ref_price, status=status)


def test_fresh_portfolio_has_principal_as_cash():
    pf = Portfolio.fresh(25_000.0, date(2024, 1, 1))
    assert pf.cash == 25_000.0
    assert pf.equity({}) == 25_000.0
    assert pf.position_value({}) == 0.0


def test_apply_fill_buy_credits_position_and_debits_cash():
    pf = Portfolio.fresh(10_000.0, date(2024, 1, 1))
    pf.apply_fill(_t("BUY", "SPY", 10, 400.0), fill_price=400.0,
                  on=date(2024, 1, 2), slippage_bps=0)
    assert pf.cash == 6_000.0
    assert pf.positions["SPY"].qty == 10
    assert pf.positions["SPY"].avg_cost == 400.0


def test_apply_fill_buy_with_slippage_pays_more_per_share():
    pf = Portfolio.fresh(10_000.0, date(2024, 1, 1))
    pf.apply_fill(_t("BUY", "SPY", 10, 400.0), fill_price=400.0,
                  on=date(2024, 1, 2), slippage_bps=10)
    # 10bps drag on 400 -> 0.40 extra per share; 10 sh * 400.40 = 4004
    assert abs(pf.cash - (10_000 - 4_004.0)) < 1e-6
    assert abs(pf.positions["SPY"].avg_cost - 400.40) < 1e-6


def test_apply_fill_sell_credits_cash_and_decrements_position():
    pf = Portfolio.fresh(10_000.0, date(2024, 1, 1))
    pf.apply_fill(_t("BUY", "SPY", 10, 400.0), fill_price=400.0,
                  on=date(2024, 1, 2), slippage_bps=0)
    pf.apply_fill(_t("SELL", "SPY", 4, 410.0), fill_price=410.0,
                  on=date(2024, 1, 3), slippage_bps=0)
    assert pf.positions["SPY"].qty == 6
    assert abs(pf.cash - (6_000 + 4 * 410.0)) < 1e-6


def test_apply_fill_sell_more_than_owned_rejected():
    pf = Portfolio.fresh(10_000.0, date(2024, 1, 1))
    pf.apply_fill(_t("BUY", "SPY", 10, 400.0), fill_price=400.0,
                  on=date(2024, 1, 2), slippage_bps=0)
    t = _t("SELL", "SPY", 20, 400.0)
    pf.apply_fill(t, fill_price=400.0, on=date(2024, 1, 3))
    assert t.status == "rejected"
    assert pf.positions["SPY"].qty == 10  # unchanged


def test_apply_fill_buy_oversized_rejected():
    pf = Portfolio.fresh(100.0, date(2024, 1, 1))
    t = _t("BUY", "SPY", 10, 400.0)
    pf.apply_fill(t, fill_price=400.0, on=date(2024, 1, 2))
    assert t.status == "rejected"


def test_avg_cost_weighted_across_two_buys():
    pf = Portfolio.fresh(100_000.0, date(2024, 1, 1))
    pf.apply_fill(_t("BUY", "SPY", 10, 400.0), fill_price=400.0,
                  on=date(2024, 1, 2), slippage_bps=0)
    pf.apply_fill(_t("BUY", "SPY", 10, 500.0), fill_price=500.0,
                  on=date(2024, 1, 3), slippage_bps=0)
    assert pf.positions["SPY"].qty == 20
    assert pf.positions["SPY"].avg_cost == 450.0


def test_full_sell_zeroes_avg_cost():
    pf = Portfolio.fresh(10_000.0, date(2024, 1, 1))
    pf.apply_fill(_t("BUY", "SPY", 5, 400.0), fill_price=400.0,
                  on=date(2024, 1, 2), slippage_bps=0)
    pf.apply_fill(_t("SELL", "SPY", 5, 410.0), fill_price=410.0,
                  on=date(2024, 1, 3), slippage_bps=0)
    assert pf.positions["SPY"].qty == 0
    assert pf.positions["SPY"].avg_cost == 0.0


def test_mark_to_market_idempotent_per_date():
    pf = Portfolio.fresh(10_000.0, date(2024, 1, 1))
    pf.mark_to_market({}, date(2024, 1, 2))
    pf.mark_to_market({}, date(2024, 1, 2))   # same date again
    assert len(pf.history) == 1


def test_mark_to_market_uses_provided_prices():
    pf = Portfolio.fresh(10_000.0, date(2024, 1, 1))
    pf.apply_fill(_t("BUY", "SPY", 10, 400.0), fill_price=400.0,
                  on=date(2024, 1, 2), slippage_bps=0)
    pt = pf.mark_to_market({"SPY": 450.0}, date(2024, 1, 3))
    # cash 6000 + 10*450 = 10500
    assert pt.equity == 10_500.0


def test_drawdown_tracks_peak_to_trough():
    pf = Portfolio.fresh(10_000.0, date(2024, 1, 1))
    pf.mark_to_market({"SPY": 100.0}, date(2024, 1, 2))  # equity 10000
    pf.apply_fill(_t("BUY", "SPY", 50, 100.0), fill_price=100.0,
                  on=date(2024, 1, 2), slippage_bps=0)
    pf.mark_to_market({"SPY": 120.0}, date(2024, 1, 3))  # equity 5000 + 6000 = 11000
    pf.mark_to_market({"SPY": 90.0}, date(2024, 1, 4))   # equity 5000 + 4500 = 9500
    dd = drawdown(pf.history)
    assert abs(dd - (11_000 - 9_500) / 11_000) < 1e-6


def test_daily_returns_match_equity_history():
    pf = Portfolio.fresh(10_000.0, date(2024, 1, 1))
    pf.mark_to_market({}, date(2024, 1, 2))       # 10000
    pf.apply_fill(_t("BUY", "SPY", 50, 100.0), fill_price=100.0,
                  on=date(2024, 1, 2), slippage_bps=0)
    pf.mark_to_market({"SPY": 110.0}, date(2024, 1, 3))   # 5000 + 5500 = 10500
    rets = daily_returns(pf.history)
    assert rets[-1][0] == "2024-01-03"
    assert abs(rets[-1][1] - 0.05) < 1e-6


def test_save_and_load_roundtrip():
    pf = Portfolio.fresh(25_000.0, date(2024, 1, 1), strategy="risk_parity",
                         params={"vol_window": 42})
    pf.apply_fill(_t("BUY", "SPY", 5, 400.0), fill_price=400.0,
                  on=date(2024, 1, 2), slippage_bps=0)
    pf.mark_to_market({"SPY": 410.0}, date(2024, 1, 3))
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        pf.save(path)
        loaded = Portfolio.load(path)
        assert loaded.cash == pf.cash
        assert loaded.positions["SPY"].qty == 5
        assert loaded.active_strategy == "risk_parity"
        assert loaded.active_strategy_params == {"vol_window": 42}
        assert len(loaded.history) == 1
        assert len(loaded.filled) == 1
    finally:
        os.unlink(path)


def test_apply_fill_supports_fractional_buy():
    pf = Portfolio.fresh(10_000.0, date(2024, 1, 1))
    # Buy 2.5 SPY @ $400 = $1000 notional
    t = Ticket(ticket_id="frac", created="2024-01-02", symbol="SPY",
               side="BUY", qty=2.5, ref_price=400.0,
               rationale="fractional", risk_max_loss=1000.0)
    pf.apply_fill(t, fill_price=400.0, on=date(2024, 1, 2), slippage_bps=0)
    assert abs(pf.positions["SPY"].qty - 2.5) < 1e-9
    assert abs(pf.cash - 9_000.0) < 1e-9


def test_apply_fill_supports_fractional_sell_to_zero():
    pf = Portfolio.fresh(10_000.0, date(2024, 1, 1))
    pf.apply_fill(Ticket(ticket_id="b1", created="2024-01-02", symbol="SPY",
                          side="BUY", qty=2.5, ref_price=400.0,
                          rationale="", risk_max_loss=1000.0),
                  fill_price=400.0, on=date(2024, 1, 2), slippage_bps=0)
    # Sell exactly 2.5 — should leave qty=0, avg_cost=0
    pf.apply_fill(Ticket(ticket_id="s1", created="2024-01-03", symbol="SPY",
                          side="SELL", qty=2.5, ref_price=410.0,
                          rationale="", risk_max_loss=0.0),
                  fill_price=410.0, on=date(2024, 1, 3), slippage_bps=0)
    assert pf.positions["SPY"].qty == 0.0
    assert pf.positions["SPY"].avg_cost == 0.0


def test_fractional_position_partial_sell_keeps_avg_cost():
    pf = Portfolio.fresh(10_000.0, date(2024, 1, 1))
    pf.apply_fill(Ticket(ticket_id="b1", created="2024-01-02", symbol="SPY",
                          side="BUY", qty=10.0, ref_price=400.0,
                          rationale="", risk_max_loss=4000.0),
                  fill_price=400.0, on=date(2024, 1, 2), slippage_bps=0)
    pf.apply_fill(Ticket(ticket_id="s1", created="2024-01-03", symbol="SPY",
                          side="SELL", qty=3.75, ref_price=410.0,
                          rationale="", risk_max_loss=0.0),
                  fill_price=410.0, on=date(2024, 1, 3), slippage_bps=0)
    assert abs(pf.positions["SPY"].qty - 6.25) < 1e-9
    # avg_cost survives partial sells
    assert pf.positions["SPY"].avg_cost == 400.0


def test_expire_pending_clears_unfilled():
    pf = Portfolio.fresh(10_000.0, date(2024, 1, 1))
    pf.pending = [_t("BUY", "SPY", 10, 400.0), _t("SELL", "AGG", 5, 90.0)]
    n = pf.expire_pending()
    assert n == 2
    assert pf.pending == []


# --- runner -----------------------------------------------------------------

if __name__ == "__main__":
    tests = [(name, fn) for name, fn in globals().items()
             if name.startswith("test_") and callable(fn)]
    passed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  {PASS} {name}")
            passed += 1
        except AssertionError as e:
            print(f"  {FAIL} {name}: {e}")
        except Exception as e:
            print(f"  {FAIL} {name}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
    sys.exit(0 if passed == len(tests) else 1)
