"""plan.py — the one-command "what do I do this week" report.

Until the broker is wired up, you trade manually. This module gives you the
complete plan you need to execute at Schwab / Fidelity / wherever:

  1. BUY orders to place (with limit prices and notional amounts)
  2. SELL orders if rotating out of existing positions
  3. GTC stop-loss orders to set at the broker (exact prices)
  4. Strategy-exit conditions to watch between sessions

Output is copy-paste friendly. Optional ``--html`` writes a printable card.

Strategy defaults to ``top_n_momentum`` because the random-week analysis
(40 samples × 4 weeks × 10 years) put it at the top on mean return + practical
executability. Override with ``--strategy``.

Run:
  python3 -m fund.plan                                    # use active portfolio
  python3 -m fund.plan --principal 25000 --strategy top_n_momentum
  python3 -m fund.plan --as-of 2026-05-22 --html plan.html
"""

from __future__ import annotations

import argparse
import html as _html
import sys
from datetime import date, datetime, timedelta
from typing import Iterable

from fund.data.loader import load_panel
from fund.data.pit import Panel, PriceSeries
from fund.portfolio import Portfolio
from fund.strategy.dual_momentum import CASH
from fund.strategy.registry import build as build_strategy, universe_for

DEFAULT_STRATEGY = "top_n_momentum"
DEFAULT_STOP_PCT = 0.15


def _most_recent_close(panel: Panel, on: date) -> tuple[date, dict[str, float]]:
    cursor = on
    for _ in range(10):
        prices: dict[str, float] = {}
        for sym, ps in panel.series.items():
            sub = ps.as_of(cursor)
            if sub.dates and sub.dates[-1] == cursor:
                prices[sym] = sub.last  # type: ignore[assignment]
        if len(prices) >= max(1, len(panel.series) // 2):
            return cursor, prices
        cursor -= timedelta(days=1)
    return on, {sym: ps.last for sym, ps in panel.series.items() if ps.last}  # type: ignore


def _to_shares(weights: dict[str, float], equity: float,
               prices: dict[str, float]) -> dict[str, int]:
    out: dict[str, int] = {}
    for sym, w in weights.items():
        if sym == CASH:
            continue
        px = prices.get(sym)
        if not px or px <= 0 or w <= 0:
            continue
        out[sym] = int((equity * w) // px)
    return out


def _strategy_exit_text(strategy_name: str, params: dict, symbol: str,
                        panel: Panel, tbill: PriceSeries) -> str:
    if strategy_name == "sixty_forty":
        return "Fixed weights; SELL only at monthly rebalance if drifted."
    if strategy_name in ("dual_momentum", "top_n_momentum", "leveraged_momentum"):
        lookback = int(params.get("lookback_days", 126))
        n = int(params.get("n", 1)) if strategy_name != "dual_momentum" else 1
        ps = panel.series.get(symbol)
        if ps is None:
            return "Strategy can't see this symbol."
        cur_ret = ps.trailing_return(lookback)
        cur_ret_pct = f"{cur_ret * 100:+.1f}%" if cur_ret is not None else "n/a"
        uni = list(universe_for(strategy_name, params))
        ranks: list[tuple[float, str]] = []
        for sym in uni:
            other = panel.series.get(sym)
            if other is None:
                continue
            r = other.trailing_return(lookback)
            if r is not None:
                ranks.append((r, sym))
        ranks.sort(reverse=True)
        annual_rate = (tbill.last or 0.0) / 100.0
        tbill_floor = annual_rate * (lookback / 252.0)
        # next-best non-held challenger
        next_best = None
        for r, s in ranks:
            if s != symbol:
                next_best = (r, s)
                break
        bits = [
            f"trailing {lookback}d return now {cur_ret_pct} "
            f"(T-bill floor {tbill_floor * 100:+.1f}%)"
        ]
        if cur_ret is not None and cur_ret <= tbill_floor:
            bits.append("ALREADY below T-bill — exit at next rebalance")
        elif next_best:
            bits.append(f"exit if trailing return drops below {tbill_floor * 100:+.1f}% "
                        f"OR {next_best[1]} (now {next_best[0] * 100:+.1f}%) "
                        f"climbs above it")
        return "; ".join(bits)
    if strategy_name == "ma_crossover":
        fast = int(params.get("fast", 50))
        slow = int(params.get("slow", 200))
        return f"Exit when {fast}-day SMA crosses below {slow}-day SMA."
    if strategy_name == "risk_parity":
        return "Reduce when this symbol's realized vol rises vs the book."
    if strategy_name in ("adaptive", "stable_adaptive"):
        return "Exit whenever the selected underlying strategy loses the Sortino race."
    return "No explicit exit rule."


def build_plan(*, as_of: date, principal: float, strategy: str,
               strategy_params: dict, pf: Portfolio | None = None,
               stop_pct: float = DEFAULT_STOP_PCT,
               source: str = "auto") -> dict:
    """Compute the full plan — BUY orders, SELL orders, stops, exit notes."""
    strat = build_strategy(strategy, strategy_params)
    syms = sorted(set(universe_for(strategy, strategy_params)) | {"SPY"})
    if pf is not None:
        syms = sorted(set(syms) | set(pf.positions))
    panel, tbill = load_panel(syms, date(2005, 1, 1), as_of, source=source)
    asof_date, prices = _most_recent_close(panel, as_of)
    panel_pit = panel.as_of(asof_date)
    tbill_pit = tbill.as_of(asof_date)

    weights = strat.target_weights(panel_pit, tbill_pit)
    target_qty = _to_shares(weights, principal, prices)

    # Current positions from portfolio (if loaded)
    current_qty: dict[str, int] = {}
    if pf is not None:
        current_qty = {s: p.qty for s, p in pf.positions.items() if p.qty}

    all_syms = set(target_qty) | set(current_qty)
    buys: list[dict] = []
    sells: list[dict] = []
    holds: list[dict] = []
    for sym in sorted(all_syms):
        cur = current_qty.get(sym, 0)
        tgt = target_qty.get(sym, 0)
        delta = tgt - cur
        px = prices.get(sym, 0.0)
        stop_price = round(px * (1 - stop_pct), 2)
        if delta > 0:
            buys.append({
                "symbol": sym, "qty": delta, "price": px,
                "notional": delta * px, "stop": stop_price,
                "exit_when": _strategy_exit_text(strategy, strategy_params,
                                                  sym, panel_pit, tbill_pit),
                "tgt_weight": weights.get(sym, 0.0),
            })
        elif delta < 0:
            sells.append({"symbol": sym, "qty": -delta, "price": px,
                          "notional": -delta * px,
                          "reason": ("STRATEGY EXIT" if tgt == 0
                                     else "REDUCE WEIGHT")})
        elif cur > 0:
            holds.append({"symbol": sym, "qty": cur, "price": px,
                          "notional": cur * px, "stop": stop_price,
                          "exit_when": _strategy_exit_text(strategy, strategy_params,
                                                            sym, panel_pit, tbill_pit)})

    total_notional = sum(b["notional"] for b in buys) - sum(s["notional"] for s in sells)
    cash_pre = pf.cash if pf is not None else principal
    cash_post = cash_pre - total_notional

    return {
        "as_of": asof_date.isoformat(),
        "strategy": strategy, "strategy_params": strategy_params,
        "principal": principal, "stop_pct": stop_pct,
        "buys": buys, "sells": sells, "holds": holds,
        "cash_pre": cash_pre, "cash_post": cash_post,
        "weights": weights, "prices": prices,
    }


# --- console card ---------------------------------------------------------

def _print_card(plan: dict) -> None:
    s = plan["strategy"]
    p = plan["strategy_params"]
    p_label = (f"{s} ({', '.join(f'{k}={v}' for k, v in p.items())})"
               if p else s)
    print(f"\n{'═' * 78}")
    print(f"  WEEKLY TRADE PLAN — close of {plan['as_of']}")
    print(f"  strategy:  {p_label}")
    print(f"  principal: ${plan['principal']:,.2f}   "
          f"cash before: ${plan['cash_pre']:,.2f}   "
          f"after: ${plan['cash_post']:,.2f}")
    print(f"  stop loss: {int(plan['stop_pct'] * 100)}% below entry")
    print(f"{'═' * 78}")

    if plan["sells"]:
        print(f"\n▼ SELL — execute first to free up cash")
        for t in plan["sells"]:
            print(f"    SELL {t['qty']:>5d} {t['symbol']:<6s} "
                  f"~${t['price']:,.2f}  =  ${t['notional']:,.2f}    {t['reason']}")
    if plan["buys"]:
        print(f"\n▲ BUY — at market open, market or limit @ ref price")
        for t in plan["buys"]:
            print(f"    BUY  {t['qty']:>5d} {t['symbol']:<6s} "
                  f"~${t['price']:,.2f}  =  ${t['notional']:,.2f}   "
                  f"(target weight {t['tgt_weight'] * 100:.1f}%)")
        print(f"\n■ STOP-LOSS — set GTC after BUY fills (one per new position)")
        for t in plan["buys"]:
            print(f"    GTC SELL STOP  {t['qty']:>5d} {t['symbol']:<6s} "
                  f"trigger ≤ ${t['stop']:,.2f}  "
                  f"({(t['stop'] / t['price'] - 1) * 100:+.1f}% from here)")
        print(f"\n⏳ EXIT CONDITIONS — what would make the strategy SELL")
        for t in plan["buys"]:
            print(f"    {t['symbol']}: {t['exit_when']}")

    if plan["holds"]:
        print(f"\n● HOLD — keep these positions, current stops:")
        for h in plan["holds"]:
            print(f"    HOLD {h['qty']:>5d} {h['symbol']:<6s} "
                  f"= ${h['notional']:,.2f}   "
                  f"stop ≤ ${h['stop']:,.2f}")
            print(f"           {h['exit_when']}")

    if not (plan["buys"] or plan["sells"] or plan["holds"]):
        print(f"\n  (All cash — no positions to take or hold.)")
    print()


# --- HTML card -------------------------------------------------------------

_HTML_CSS = """
body { font-family: 'Iowan Old Style', Charter, Georgia, serif; background: #fbfaf6; color: #0f1115; max-width: 920px; margin: 0 auto; padding: 56px 32px 80px; line-height: 1.55; }
header { border-bottom: 2px solid #1a1a1a; padding-bottom: 18px; margin-bottom: 28px; }
.eyebrow { font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; color: #6b6f76; font-family: -apple-system, sans-serif; }
h1 { font-size: 30px; font-weight: 600; letter-spacing: -0.012em; margin: 6px 0 0; }
h2 { font-size: 17px; font-weight: 600; margin: 32px 0 12px; padding-bottom: 4px; border-bottom: 1px solid #e6e3da; font-family: -apple-system, sans-serif; letter-spacing: 0.02em; text-transform: uppercase; font-size: 12px; color: #6b6f76; }
.meta { color: #6b6f76; font-family: -apple-system, sans-serif; font-size: 13px; margin-top: 8px; }
.order { background: white; border-left: 3px solid #1c4f8e; padding: 12px 18px; margin: 8px 0; border-radius: 0 4px 4px 0; font-family: -apple-system, sans-serif; font-size: 14px; display: flex; gap: 16px; align-items: baseline; flex-wrap: wrap; }
.order.sell { border-left-color: #9b2226; }
.order.stop { border-left-color: #9a6b00; background: #fdfaf0; }
.order.hold { border-left-color: #137333; }
.action { font-weight: 600; letter-spacing: 0.04em; min-width: 90px; }
.action.BUY { color: #1c4f8e; }
.action.SELL { color: #9b2226; }
.action.STOP { color: #9a6b00; }
.action.HOLD { color: #137333; }
.qty { font-variant-numeric: tabular-nums; min-width: 60px; text-align: right; }
.symbol { font-weight: 600; letter-spacing: -0.01em; font-size: 16px; min-width: 56px; }
.price { font-variant-numeric: tabular-nums; color: #6b6f76; }
.notional { font-variant-numeric: tabular-nums; margin-left: auto; font-weight: 500; }
.exit { font-size: 12px; color: #6b6f76; margin-top: 6px; padding-left: 18px; border-left: 2px solid #e6e3da; font-style: italic; line-height: 1.5; }
.kpi-row { display: flex; gap: 28px; margin: 14px 0 0; flex-wrap: wrap; font-family: -apple-system, sans-serif; }
.kpi { min-width: 110px; }
.kpi-label { font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; color: #6b6f76; }
.kpi-value { font-size: 18px; font-weight: 500; margin-top: 2px; font-variant-numeric: tabular-nums; }
.empty { color: #6b6f76; font-style: italic; padding: 10px 0; font-family: -apple-system, sans-serif; }
"""


def render_html(plan: dict) -> str:
    s = plan["strategy"]
    p = plan["strategy_params"]
    p_label = (f"{s} ({', '.join(f'{k}={v}' for k, v in p.items())})"
               if p else s)

    def _order_html(action: str, t: dict, *, cls: str, show_exit: bool = False) -> str:
        exit_div = ""
        if show_exit and "exit_when" in t:
            exit_div = f'<div class="exit">{_html.escape(t["exit_when"])}</div>'
        return f"""
<div class="order {cls}">
  <span class="action {action.replace(' ', '')}">{_html.escape(action)}</span>
  <span class="qty">{t["qty"]}</span>
  <span class="symbol">{_html.escape(t["symbol"])}</span>
  <span class="price">@ ~${t["price"]:,.2f}</span>
  <span class="notional">${t.get("notional", t["qty"] * t["price"]):,.2f}</span>
</div>
{exit_div}
"""

    sections = []
    if plan["sells"]:
        body = "".join(_order_html("SELL", t, cls="sell") for t in plan["sells"])
        sections.append(f"<h2>1 · Sell first (frees cash)</h2>{body}")
    if plan["buys"]:
        body = "".join(_order_html("BUY", t, cls="") for t in plan["buys"])
        sections.append(f"<h2>2 · Buy at the open</h2>{body}")
        stops_body = "".join(
            _order_html(f"GTC STOP", {
                "symbol": t["symbol"], "qty": t["qty"], "price": t["stop"],
                "notional": t["qty"] * t["stop"],
            }, cls="stop") for t in plan["buys"]
        )
        sections.append(f"<h2>3 · Set GTC stop orders after fills</h2>{stops_body}")
        exits = "".join(
            f'<div class="order"><span class="symbol">{_html.escape(t["symbol"])}</span>'
            f'<div class="exit" style="border-left:none; padding-left:0">{_html.escape(t["exit_when"])}</div>'
            f'</div>'
            for t in plan["buys"]
        )
        sections.append(f"<h2>4 · Strategy exit conditions (watch between runs)</h2>{exits}")
    if plan["holds"]:
        body = "".join(_order_html("HOLD", h, cls="hold", show_exit=True)
                       for h in plan["holds"])
        sections.append(f"<h2>Hold</h2>{body}")
    if not sections:
        sections.append('<div class="empty">All cash — nothing to do.</div>')

    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Weekly trade plan — {plan["as_of"]}</title>
<style>{_HTML_CSS}</style></head><body>
<header>
  <div class="eyebrow">Weekly trade plan</div>
  <h1>{datetime.fromisoformat(plan["as_of"]).strftime("%A, %B %-d, %Y")}</h1>
  <div class="meta">
    Strategy: <strong>{_html.escape(p_label)}</strong> ·
    Principal ${plan["principal"]:,.0f} ·
    {int(plan["stop_pct"] * 100)}% stop-loss
  </div>
  <div class="kpi-row">
    <div class="kpi"><div class="kpi-label">Cash before</div><div class="kpi-value">${plan["cash_pre"]:,.0f}</div></div>
    <div class="kpi"><div class="kpi-label">Cash after</div><div class="kpi-value">${plan["cash_post"]:,.0f}</div></div>
    <div class="kpi"><div class="kpi-label">Orders</div><div class="kpi-value">{len(plan["buys"]) + len(plan["sells"])}</div></div>
  </div>
</header>
{"".join(sections)}
</body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description="One-shot weekly trade plan.")
    ap.add_argument("--strategy", default="",
                    help=f"override active strategy (default: {DEFAULT_STRATEGY} "
                         f"or active portfolio's)")
    ap.add_argument("--as-of", type=str, default="")
    ap.add_argument("--principal", type=float, default=0.0)
    ap.add_argument("--stop", type=float, default=DEFAULT_STOP_PCT)
    ap.add_argument("--source", default="auto")
    ap.add_argument("--html", default="",
                    help="also write a printable HTML card")
    args = ap.parse_args()
    as_of = (date.fromisoformat(args.as_of) if args.as_of else date.today())

    pf: Portfolio | None = None
    strategy = args.strategy
    strategy_params: dict = {}
    principal = args.principal
    try:
        pf = Portfolio.load()
        if not strategy:
            strategy = pf.active_strategy
            strategy_params = pf.active_strategy_params
        if principal <= 0:
            principal = pf.principal
    except FileNotFoundError:
        if not strategy:
            strategy = DEFAULT_STRATEGY
        if principal <= 0:
            principal = 25_000.0

    plan = build_plan(as_of=as_of, principal=principal, strategy=strategy,
                      strategy_params=strategy_params, pf=pf,
                      stop_pct=args.stop, source=args.source)
    _print_card(plan)
    if args.html:
        with open(args.html, "w") as f:
            f.write(render_html(plan))
        print(f"  printable card: {args.html}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
