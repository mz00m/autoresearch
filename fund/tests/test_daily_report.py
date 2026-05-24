"""Daily HTML report — renders, has the right structural pieces."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fund.daily_report import render, write
from fund.portfolio import Portfolio, Ticket


def _seed_pf() -> Portfolio:
    pf = Portfolio.fresh(25_000.0, date(2024, 6, 1), strategy="sixty_forty")
    # Two days of history with a small move
    pf.mark_to_market({}, date(2024, 6, 3))           # 25000 cash
    t = Ticket(ticket_id="abc12345", created="2024-06-03",
               symbol="SPY", side="BUY", qty=10, ref_price=400.0,
               rationale="60/40: take SPY to 60%",
               risk_max_loss=4000.0)
    pf.apply_fill(t, fill_price=400.0, on=date(2024, 6, 3), slippage_bps=0)
    pf.mark_to_market({"SPY": 410.0}, date(2024, 6, 4))   # 21000 + 4100 = 25100
    return pf


def test_render_returns_html_with_doctype():
    html = render(_seed_pf(), today_tickets=[], prices={"SPY": 410.0},
                  as_of=date(2024, 6, 4))
    assert html.startswith("<!doctype html>")
    assert "</html>" in html


def test_render_includes_strategy_name():
    html = render(_seed_pf(), today_tickets=[], prices={"SPY": 410.0},
                  as_of=date(2024, 6, 4))
    assert "sixty_forty" in html


def test_render_includes_equity_chart_svg():
    html = render(_seed_pf(), today_tickets=[], prices={"SPY": 410.0},
                  as_of=date(2024, 6, 4))
    assert "<svg" in html
    assert "Cumulative return since inception" in html


def test_render_shows_pending_ticket_rows():
    pf = _seed_pf()
    tickets = [Ticket(ticket_id="t1", created="2024-06-04", symbol="AGG",
                      side="BUY", qty=20, ref_price=88.0,
                      rationale="60/40: add AGG", risk_max_loss=1760.0)]
    html = render(pf, today_tickets=tickets, prices={"SPY": 410.0, "AGG": 88.0},
                  as_of=date(2024, 6, 4))
    assert "AGG" in html
    assert "60/40: add AGG" in html


def test_render_shows_empty_state_when_no_tickets():
    html = render(_seed_pf(), today_tickets=[], prices={"SPY": 410.0},
                  as_of=date(2024, 6, 4))
    assert "No tickets" in html or "already at target" in html


def test_render_shows_today_fills_when_present():
    pf = _seed_pf()  # already has one fill on 2024-06-03; render for that date
    html = render(pf, today_tickets=[], prices={"SPY": 400.0},
                  as_of=date(2024, 6, 3))
    assert "SPY" in html
    # filled ticket appears in the fills section
    assert "Today&#x27;s fills" in html or "Today's fills" in html


def test_render_shows_drawdown_when_history_dips():
    pf = _seed_pf()
    pf.mark_to_market({"SPY": 380.0}, date(2024, 6, 5))  # drop -> equity 21000 + 3800 = 24800
    html = render(pf, today_tickets=[], prices={"SPY": 380.0},
                  as_of=date(2024, 6, 5))
    assert "Drawdown" in html


def test_write_creates_file():
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        path = f.name
    try:
        out = write(_seed_pf(), today_tickets=[], prices={"SPY": 410.0},
                    as_of=date(2024, 6, 4), path=path)
        assert out == path
        assert os.path.exists(path)
        with open(path) as fh:
            content = fh.read()
        assert "<!doctype html>" in content
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
