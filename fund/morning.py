"""Morning trade guide — produce today's tickets, never fire them.

This is the operational lever the research loop has been earning the right to
pull. It runs against the active strategy stored in ``portfolio_state.json``,
turns target weights into concrete BUY/SELL diffs against the current paper
positions, and writes each one as a *pending ticket* — a human-approvable
instruction with the risk_engine verdict already attached.

Convention: the guide runs *before* the market opens, so the as-of price is
the most recent close (yesterday by default). Tickets are sized using that
close as the reference; the closeout fills them at the actual close.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from dataclasses import asdict
from datetime import date, timedelta

from fund.data.loader import load_panel
from fund.portfolio import Portfolio, Ticket
from fund.risk_concentration import ConcentrationLimits
from fund.risk_engine import AccountMode, Kind, Order, RiskEngine
from fund.strategy.registry import build as build_strategy, universe_for
from fund.tax import wash_sale_check

REBALANCE_THRESHOLD = 0.01  # don't churn for sub-1% drift; spend bps elsewhere
# Default: integer shares (IBKR cash-account semantics). Set to False to permit
# fractional via Alpaca / Schwab. Set in env via FUND_WHOLE_SHARES_ONLY=0
import os as _os
WHOLE_SHARES_ONLY = _os.environ.get("FUND_WHOLE_SHARES_ONLY", "1") != "0"


def _most_recent_prices(panel, on: date) -> dict[str, float]:
    """Last close at or before `on` for each symbol. None if no data."""
    out: dict[str, float] = {}
    for sym, ps in panel.series.items():
        sub = ps.as_of(on)
        if sub.last is not None:
            out[sym] = sub.last
    return out


def _target_shares(target_weights: dict[str, float], equity: float,
                   prices: dict[str, float],
                   whole_shares_only: bool = WHOLE_SHARES_ONLY,
                   ) -> dict[str, float]:
    """Convert {symbol: weight} -> {symbol: share count}. CASH gets dropped
    (residual). If whole_shares_only, floor to integers (IBKR cash semantics);
    otherwise round to 4 decimal places (Alpaca / Schwab fractional support)."""
    out: dict[str, float] = {}
    for sym, w in target_weights.items():
        if sym == "CASH":
            continue
        px = prices.get(sym)
        if not px or px <= 0 or w <= 0:
            out[sym] = 0.0
            continue
        raw_qty = (equity * w) / px
        if whole_shares_only:
            out[sym] = float(int(raw_qty))
        else:
            out[sym] = round(raw_qty, 4)
    return out


def generate_tickets(pf: Portfolio, as_of: date, *,
                     source: str = "auto",
                     rebalance_threshold: float = REBALANCE_THRESHOLD,
                     ) -> tuple[Portfolio, list[Ticket], dict[str, float]]:
    """Produce pending tickets for `as_of`. Mutates pf (marks to market, writes
    pending list). Returns (pf, tickets, reference_prices)."""
    strat = build_strategy(pf.active_strategy, pf.active_strategy_params)
    symbols = list(universe_for(pf.active_strategy, pf.active_strategy_params))

    # Load price history up to as_of so the strategy + risk check both see real.
    # FRED tbill is needed by dual_momentum's absolute-momentum gate.
    panel, tbill = load_panel(symbols, date(2005, 1, 1), as_of, source=source)
    prices = _most_recent_prices(panel, as_of)
    if not prices:
        raise RuntimeError(f"no prices available at {as_of} for {symbols}")

    # Mark current book before deciding new targets so equity is current.
    pt = pf.mark_to_market(prices, as_of)
    equity = pt.equity

    # Compute target weights as of today, then convert to share counts.
    target_w = strat.target_weights(panel.as_of(as_of), tbill.as_of(as_of))
    target_q = _target_shares(target_w, equity, prices)

    # Diff current -> target.
    current_q = {s: p.qty for s, p in pf.positions.items() if p.qty}
    all_syms = set(target_q) | set(current_q)

    pf.expire_pending()  # any leftover unfilled tickets from yesterday die
    tickets: list[Ticket] = []
    # Concentration limits are OPT-IN via FUND_CONCENTRATION_MANDATE=1. The
    # bench includes deliberately-concentrated strategies (dual_momentum
    # picks one asset, top_n_momentum can pick two in the same sector) and
    # defaulting on breaks them. Turn it on when running a diversification
    # mandate where overconcentration is the bigger risk than missing trends.
    open_exposure = {sym: pos.qty * prices.get(sym, pos.avg_cost)
                     for sym, pos in pf.positions.items() if pos.qty}
    limits = ConcentrationLimits() if _os.environ.get(
        "FUND_CONCENTRATION_MANDATE") == "1" else None
    engine = RiskEngine(principal=pf.principal, equity=equity,
                        mode=AccountMode.CASH, settled_cash=pf.cash,
                        open_exposure=open_exposure,
                        concentration_limits=limits)

    # Process SELLs first so cash frees up for BUYs (we won't actually fill
    # until closeout, but the ticket ordering matters for the human).
    sells, buys = [], []
    for sym in sorted(all_syms):
        cur = current_q.get(sym, 0.0)
        tgt = target_q.get(sym, 0.0)
        delta = tgt - cur
        px = prices.get(sym)
        if not px or abs(delta) < 1e-6:
            continue
        notional = abs(delta) * px
        # threshold: skip tiny rebalances that just bleed costs
        if notional / max(equity, 1.0) < rebalance_threshold:
            continue
        if delta < 0:
            sells.append((sym, -delta, px))
        else:
            buys.append((sym, delta, px))

    # SELLs: no risk_engine check needed (reduces risk); just verify owned.
    # Net the freed exposure out of the engine's open_exposure dict so the
    # subsequent BUY checks see the post-rotation book, not the pre-rotation
    # one. Without this, rotating from 60/40 → top_n_momentum would have the
    # engine reject the new BUYs because it thinks SPY+AGG is still on book.
    for sym, qty, px in sells:
        cur = pf.positions.get(sym)
        if cur is None or cur.qty + 1e-9 < qty:
            continue
        rationale = (f"{pf.active_strategy}: trim {sym} from {cur.qty:g} to "
                     f"{cur.qty - qty:g} (target weight {target_w.get(sym, 0):.2%})")
        t = Ticket(ticket_id=uuid.uuid4().hex[:8], created=as_of.isoformat(),
                   symbol=sym, side="SELL", qty=qty, ref_price=round(px, 4),
                   rationale=rationale, risk_max_loss=0.0)
        tickets.append(t)
        # Free the exposure for downstream BUY checks
        freed = qty * px
        existing = engine.open_exposure.get(sym, 0.0)
        engine.open_exposure[sym] = max(0.0, existing - freed)
        # Also free the cash so the cash-availability check passes
        engine.settled_cash = (engine.settled_cash or 0.0) + freed

    # BUYs: each must clear risk_engine.check() AND not breach wash-sale.
    # Process largest first so we don't accidentally approve small ones that
    # starve a primary position.
    buys.sort(key=lambda b: -b[1] * b[2])
    for sym, qty, px in buys:
        # Wash-sale check: bought-back-too-soon after a loss sale voids the loss
        wash = wash_sale_check(sym, as_of, pf.last_loss_sales)
        if wash.blocked:
            tickets.append(Ticket(
                ticket_id=uuid.uuid4().hex[:8], created=as_of.isoformat(),
                symbol=sym, side="BUY", qty=qty, ref_price=round(px, 4),
                rationale=f"WASH-SALE DEFERRED: {wash.reason}",
                risk_max_loss=0.0, status="rejected"))
            continue
        order = Order(kind=Kind.LONG_EQUITY, symbol=sym, qty=float(qty), price=px)
        verdict = engine.check(order)
        if not verdict.approved:
            tickets.append(Ticket(
                ticket_id=uuid.uuid4().hex[:8], created=as_of.isoformat(),
                symbol=sym, side="BUY", qty=qty, ref_price=round(px, 4),
                rationale=f"REJECTED by risk engine: {'; '.join(verdict.reasons)}",
                risk_max_loss=verdict.max_loss, status="rejected"))
            continue
        engine.apply(order)
        rationale = (f"{pf.active_strategy}: take {sym} to target weight "
                     f"{target_w.get(sym, 0):.2%} ({qty:g} sh @ ~${px:,.2f})")
        tickets.append(Ticket(
            ticket_id=uuid.uuid4().hex[:8], created=as_of.isoformat(),
            symbol=sym, side="BUY", qty=qty, ref_price=round(px, 4),
            rationale=rationale, risk_max_loss=verdict.max_loss))

    pf.pending = [t for t in tickets if t.status == "pending"]
    # rejected/expired tickets are kept in the return list for the report but
    # we don't carry them in pf.pending — closeout shouldn't try to fill them.
    return pf, tickets, prices


def _print_card(pf: Portfolio, tickets: list[Ticket], prices: dict[str, float],
                as_of: date) -> None:
    equity = pf.equity(prices)
    print(f"\n=== MORNING GUIDE  {as_of}  ===")
    print(f"strategy:  {pf.active_strategy}  {pf.active_strategy_params or ''}")
    print(f"equity:    ${equity:,.2f}  (cash ${pf.cash:,.2f}, "
          f"positions ${pf.position_value(prices):,.2f})")
    if pf.positions:
        print(f"holdings:  " + ", ".join(
            f"{s} {p.qty} @ ${p.avg_cost:,.2f}"
            for s, p in pf.positions.items() if p.qty))
    if not tickets:
        print("tickets:   (none — portfolio is already at target)")
        return
    print(f"tickets:   {len(tickets)}")
    for t in tickets:
        flag = {"pending": "  ", "rejected": "X ", "expired": ". "}[t.status]
        qty_str = f"{t.qty:>8.4f}" if t.qty != int(t.qty) else f"{int(t.qty):>8d}"
        print(f"  {flag}{t.side:4s} {qty_str} {t.symbol:<5s} "
              f"@ ~${t.ref_price:,.2f}   {t.rationale}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate today's trade tickets.")
    ap.add_argument("--as-of", type=str, default="",
                    help="ISO date (default: today)")
    ap.add_argument("--source", default="auto",
                    help="data source: auto | real | synthetic")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--no-report", action="store_true",
                    help="skip regenerating fund/daily.html")
    args = ap.parse_args()
    as_of = (date.fromisoformat(args.as_of) if args.as_of else date.today())

    pf = Portfolio.load()
    pf, tickets, prices = generate_tickets(pf, as_of, source=args.source)
    if not args.quiet:
        _print_card(pf, tickets, prices, as_of)
    pf.save()
    if not args.no_report:
        from fund.closeout import DAILY_LOG
        from fund.daily_report import write as write_report
        path = write_report(pf, today_tickets=tickets, prices=prices,
                            daily_log_path=DAILY_LOG, as_of=as_of)
        if not args.quiet:
            print(f"\nreport: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
