"""Tax-lot accounting + wash-sale logic."""

from __future__ import annotations

import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fund.portfolio import Portfolio, Ticket
from fund.tax import (LotPolicy, TaxLot, realize_sale, select_lots_for_sale,
                      summarize_realized, wash_sale_check)


def test_lot_long_term_classification():
    lot = TaxLot(date_acquired="2023-01-01", qty=10, cost_per_share=100.0)
    assert lot.is_long_term(date(2024, 1, 1)) is False    # exactly 1 year
    assert lot.is_long_term(date(2024, 1, 2)) is True     # 366 days


def test_fifo_picks_oldest_first():
    lots = [
        TaxLot("2024-03-01", 5, 100.0),
        TaxLot("2024-01-01", 5, 80.0),    # oldest
    ]
    picks = select_lots_for_sale(lots, 5, date(2025, 1, 1), 110.0, LotPolicy.FIFO)
    assert picks[0][0].date_acquired == "2024-01-01"


def test_lifo_picks_newest_first():
    lots = [
        TaxLot("2024-01-01", 5, 80.0),
        TaxLot("2024-03-01", 5, 100.0),   # newest
    ]
    picks = select_lots_for_sale(lots, 5, date(2025, 1, 1), 110.0, LotPolicy.LIFO)
    assert picks[0][0].date_acquired == "2024-03-01"


def test_hifo_picks_highest_cost_first():
    lots = [
        TaxLot("2024-01-01", 5, 80.0),
        TaxLot("2024-03-01", 5, 120.0),   # highest cost
    ]
    picks = select_lots_for_sale(lots, 5, date(2025, 1, 1), 100.0, LotPolicy.HIFO)
    assert picks[0][0].cost_per_share == 120.0


def test_tax_optimal_picks_lt_loss_before_st_gain():
    lots = [
        # ST gain: bought 2 months ago at $80, now $100 -> +$100 gain
        TaxLot("2025-09-01", 5, 80.0),
        # LT loss: bought 2 years ago at $150, now $100 -> -$250 loss
        TaxLot("2023-09-01", 5, 150.0),
    ]
    picks = select_lots_for_sale(lots, 5, date(2025, 11, 1), 100.0,
                                  LotPolicy.TAX_OPTIMAL)
    # Should pick the LT loss first
    assert picks[0][0].cost_per_share == 150.0


def test_realize_sale_returns_new_lots_and_pnl():
    lots = [
        TaxLot("2024-01-01", 10, 100.0),
    ]
    new_lots, realized = realize_sale(lots, 4, 120.0, date(2024, 6, 1),
                                       policy=LotPolicy.FIFO)
    assert len(new_lots) == 1
    assert abs(new_lots[0].qty - 6) < 1e-9
    assert len(realized) == 1
    assert abs(realized[0].realized_pnl - (4 * 20)) < 1e-9  # 4 sh * $20 gain


def test_summarize_realized_buckets_st_lt():
    lots_sold_st = [
        TaxLot("2024-01-01", 5, 100.0),
    ]
    lots_sold_lt = [
        TaxLot("2022-01-01", 5, 100.0),
    ]
    _, st = realize_sale(lots_sold_st, 5, 120.0, date(2024, 6, 1))
    _, lt = realize_sale(lots_sold_lt, 5, 90.0, date(2024, 6, 1))
    summary = summarize_realized(st + lt)
    assert summary.st_gains == 5 * 20    # 100 ST gain
    assert summary.lt_losses == 5 * -10  # -50 LT loss


def test_portfolio_apply_fill_creates_lot():
    pf = Portfolio.fresh(10_000.0, date(2024, 1, 1))
    pf.apply_fill(Ticket(ticket_id="b1", created="2024-01-02", symbol="SPY",
                          side="BUY", qty=10, ref_price=400.0,
                          rationale="", risk_max_loss=4000.0),
                  fill_price=400.0, on=date(2024, 1, 2), slippage_bps=0)
    pos = pf.positions["SPY"]
    assert len(pos.lots) == 1
    assert pos.lots[0].date_acquired == "2024-01-02"
    assert pos.lots[0].qty == 10
    assert pos.lots[0].cost_per_share == 400.0


def test_portfolio_sell_realizes_pnl_and_logs():
    pf = Portfolio.fresh(10_000.0, date(2024, 1, 1))
    pf.apply_fill(Ticket(ticket_id="b1", created="2024-01-02", symbol="SPY",
                          side="BUY", qty=10, ref_price=100.0,
                          rationale="", risk_max_loss=1000.0),
                  fill_price=100.0, on=date(2024, 1, 2), slippage_bps=0)
    pf.apply_fill(Ticket(ticket_id="s1", created="2024-06-01", symbol="SPY",
                          side="SELL", qty=4, ref_price=110.0,
                          rationale="", risk_max_loss=0.0),
                  fill_price=110.0, on=date(2024, 6, 1), slippage_bps=0)
    # 4 shares sold at $10 gain each = $40 realized
    assert len(pf.realized) == 1
    assert pf.realized[0]["realized_pnl"] == 40.0
    assert pf.realized[0]["long_term"] is False   # < 1 year
    # Remaining lot has 6 shares
    assert pf.positions["SPY"].lots[0].qty == 6


def test_loss_sale_updates_wash_tracking():
    pf = Portfolio.fresh(10_000.0, date(2024, 1, 1))
    pf.apply_fill(Ticket(ticket_id="b1", created="2024-01-02", symbol="SPY",
                          side="BUY", qty=10, ref_price=100.0,
                          rationale="", risk_max_loss=1000.0),
                  fill_price=100.0, on=date(2024, 1, 2), slippage_bps=0)
    # Sell at a loss
    pf.apply_fill(Ticket(ticket_id="s1", created="2024-03-01", symbol="SPY",
                          side="SELL", qty=10, ref_price=80.0,
                          rationale="", risk_max_loss=0.0),
                  fill_price=80.0, on=date(2024, 3, 1), slippage_bps=0)
    assert pf.last_loss_sales.get("SPY") == "2024-03-01"


def test_wash_sale_check_blocks_within_window():
    check = wash_sale_check("SPY", date(2024, 3, 15),
                             {"SPY": "2024-03-01"})
    assert check.blocked is True
    assert "wash-sale" in check.reason
    assert check.days_until_clear > 0


def test_wash_sale_check_clears_after_window():
    check = wash_sale_check("SPY", date(2024, 4, 5),
                             {"SPY": "2024-03-01"})
    assert check.blocked is False


def test_wash_sale_check_no_history_passes():
    check = wash_sale_check("SPY", date(2024, 3, 15), {})
    assert check.blocked is False


def test_save_load_preserves_lots_and_realized():
    import tempfile
    pf = Portfolio.fresh(10_000.0, date(2024, 1, 1))
    pf.apply_fill(Ticket(ticket_id="b1", created="2024-01-02", symbol="SPY",
                          side="BUY", qty=5, ref_price=100.0,
                          rationale="", risk_max_loss=500.0),
                  fill_price=100.0, on=date(2024, 1, 2), slippage_bps=0)
    pf.apply_fill(Ticket(ticket_id="s1", created="2024-06-01", symbol="SPY",
                          side="SELL", qty=2, ref_price=110.0,
                          rationale="", risk_max_loss=0.0),
                  fill_price=110.0, on=date(2024, 6, 1), slippage_bps=0)
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        pf.save(path)
        loaded = Portfolio.load(path)
        assert loaded.positions["SPY"].qty == 3
        assert len(loaded.positions["SPY"].lots) == 1
        assert loaded.positions["SPY"].lots[0].qty == 3
        assert len(loaded.realized) == 1
        assert loaded.realized[0]["realized_pnl"] == 20.0
    finally:
        os.unlink(path)


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
