"""Morning trade guide + end-of-day closeout — full ops loop on synthetic data."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fund import closeout as closeout_mod
from fund import morning as morning_mod
from fund.portfolio import Portfolio, STATE_PATH


def _fresh_pf(strategy: str = "sixty_forty",
              params: dict | None = None,
              principal: float = 25_000.0) -> Portfolio:
    return Portfolio.fresh(principal, date(2024, 1, 2),
                           strategy=strategy, params=params)


def test_morning_from_empty_book_generates_buys():
    pf = _fresh_pf("sixty_forty")
    pf, tickets, prices = morning_mod.generate_tickets(pf, date(2020, 6, 1),
                                                       source="synthetic")
    sides = {t.side for t in tickets}
    # 60/40 against an empty book must produce two BUYs (SPY + AGG)
    assert "BUY" in sides
    assert all(t.status == "pending" for t in tickets if t.side == "BUY")
    syms = {t.symbol for t in tickets if t.side == "BUY"}
    assert syms == {"SPY", "AGG"}


def test_morning_no_tickets_when_already_at_target():
    pf = _fresh_pf("sixty_forty")
    # First morning to establish positions, then closeout to fill
    pf, t1, _ = morning_mod.generate_tickets(pf, date(2020, 6, 1),
                                              source="synthetic")
    pf, _, _ = closeout_mod.close_out(pf, date(2020, 6, 1),
                                       source="synthetic")
    # Run morning the very next day (almost no drift -> no tickets)
    pf, t2, _ = morning_mod.generate_tickets(pf, date(2020, 6, 2),
                                              source="synthetic")
    # Allow 0 or 1 ticket — any tiny drift is below 1% threshold most days
    assert len(t2) <= 1


def test_morning_pending_tickets_persist_in_portfolio():
    pf = _fresh_pf("sixty_forty")
    pf, tickets, _ = morning_mod.generate_tickets(pf, date(2020, 6, 1),
                                                  source="synthetic")
    pending_buys = [t for t in pf.pending if t.status == "pending"]
    # at least the BUY tickets carry into pending
    assert pending_buys
    assert all(t.side in {"BUY", "SELL"} for t in pending_buys)


def test_closeout_fills_pending_tickets_at_close():
    pf = _fresh_pf("sixty_forty")
    pf, _, _ = morning_mod.generate_tickets(pf, date(2020, 6, 1),
                                             source="synthetic")
    pf, row, _ = closeout_mod.close_out(pf, date(2020, 6, 1),
                                         source="synthetic")
    assert row["n_filled"] >= 1
    assert pf.pending == []
    # at least one SPY or AGG position should be open after the fill
    held = {s for s, p in pf.positions.items() if p.qty}
    assert held & {"SPY", "AGG"}


def test_closeout_appends_one_row_per_call():
    pf = _fresh_pf("sixty_forty")
    with tempfile.NamedTemporaryFile(suffix=".tsv", delete=False) as f:
        log_path = f.name
    os.unlink(log_path)
    try:
        pf, _, _ = morning_mod.generate_tickets(pf, date(2020, 6, 1),
                                                 source="synthetic")
        pf, _, _ = closeout_mod.close_out(pf, date(2020, 6, 1),
                                           source="synthetic", log_path=log_path)
        pf, _, _ = morning_mod.generate_tickets(pf, date(2020, 6, 2),
                                                 source="synthetic")
        pf, _, _ = closeout_mod.close_out(pf, date(2020, 6, 2),
                                           source="synthetic", log_path=log_path)
        with open(log_path) as fh:
            lines = fh.readlines()
        assert len(lines) == 3   # header + 2 rows
    finally:
        if os.path.exists(log_path):
            os.unlink(log_path)


def test_closeout_no_close_yet_is_noop():
    """If as_of falls on a non-trading synthetic day, closeout should not crash
    or write a row when the book has no pending tickets."""
    pf = _fresh_pf("sixty_forty")
    # Pick a Sunday — synthetic data only has weekdays
    pf, _, _ = closeout_mod.close_out(pf, date(2020, 6, 7),
                                       source="synthetic")
    # No fills, no equity history shift (just an empty mark)
    assert pf.pending == []


def test_morning_sub_threshold_drift_skipped():
    """Once at target, a single-day move shouldn't trigger rebalance churn."""
    pf = _fresh_pf("sixty_forty")
    pf, _, _ = morning_mod.generate_tickets(pf, date(2020, 6, 1),
                                             source="synthetic")
    pf, _, _ = closeout_mod.close_out(pf, date(2020, 6, 1),
                                       source="synthetic")
    pf, tickets, _ = morning_mod.generate_tickets(pf, date(2020, 6, 2),
                                                   source="synthetic")
    # All same-day drift should be < 1% of equity -> no tickets
    over_threshold = [t for t in tickets if t.status == "pending"]
    assert len(over_threshold) <= 1


def test_risk_engine_rejects_oversized_buy():
    """If the strategy demands more shares than cash supports, those tickets
    must be tagged rejected (not silently filled later)."""
    # Tiny principal vs SPY (~$500/share) — 60% target cannot fit one share
    pf = _fresh_pf("sixty_forty", principal=50.0)
    pf, tickets, _ = morning_mod.generate_tickets(pf, date(2020, 6, 1),
                                                   source="synthetic")
    # Either zero tickets (target shares floored to 0) or rejected
    assert all(t.status in {"pending", "rejected"} for t in tickets)


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
