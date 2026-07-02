"""sell_guide.py — explicit sell triggers per held position.

The morning command already produces SELL tickets implicitly when target
weights change; this module makes the *conditions for selling* explicit so
you know what to watch between morning runs.

For each open position we surface four sell signals:

  1. STOP_LOSS      — price below cost * (1 - stop_pct). Hard floor.
  2. TRAILING_STOP  — price below peak * (1 - trailing_pct). Locks in gains.
  3. STRATEGY_EXIT  — what the active strategy itself would have to see to
                      drop this position (e.g., "USO trailing 252d return
                      falls below T-bill OR another asset overtakes it").
  4. ACTION         — the consolidated verdict: HOLD / WATCH / SELL.

The output is meant for a human eye between morning runs — you set
broker-side stop orders at the prices we calculate; the strategy_exit
condition is what to glance at if you want to front-run a rebalance.

Run:
  python3 -m fund.sell_guide                  # uses today + active portfolio
  python3 -m fund.sell_guide --as-of 2026-05-22 --principal 25000
"""

from __future__ import annotations

import argparse
import html as _html
import sys
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from typing import Iterable

from fund.data.loader import load_panel
from fund.data.pit import Panel, PriceSeries
from fund.portfolio import Portfolio
from fund.strategy.dual_momentum import CASH
from fund.strategy.registry import (DEFAULT_UNIVERSE, build as build_strategy,
                                    universe_for)


# Defaults; aggressive strategies should use tighter stops
DEFAULT_STOP_PCT = 0.15           # 15% below cost
DEFAULT_TRAILING_PCT = 0.15       # 15% off peak-since-purchase


@dataclass
class SellSignal:
    symbol: str
    qty: int
    cost: float
    last: float
    pnl_pct: float
    stop_loss_price: float
    trailing_stop_price: float
    strategy_exit: str               # human-readable condition
    action: str                      # HOLD | WATCH | SELL
    reasons: list[str]


def _peak_since(prices: PriceSeries, since: date | None) -> float | None:
    """Highest close in `prices` >= `since`. Falls back to overall max if since
    is None or before the series."""
    if not prices.closes:
        return None
    if since is None:
        return max(prices.closes)
    peak = None
    for d, c in zip(prices.dates, prices.closes):
        if d >= since:
            peak = c if peak is None else max(peak, c)
    return peak if peak is not None else prices.closes[-1]


def _strategy_exit_text(strategy_name: str, params: dict, symbol: str,
                        panel: Panel, tbill: PriceSeries,
                        active_weights: dict[str, float]) -> str:
    """Plain-English description of what would make the active strategy drop
    this symbol from the book. Conservative wording — never a price level."""
    if strategy_name == "sixty_forty":
        return (f"60/40 is fixed-weight; SELL only when {symbol} drifts above "
                f"its target band on the next rebalance (~1st of month).")
    if strategy_name in ("dual_momentum", "top_n_momentum", "leveraged_momentum"):
        n = int(params.get("n", 1)) if strategy_name != "dual_momentum" else 1
        lookback = int(params.get("lookback_days", 252))
        ps = panel.series.get(symbol)
        if ps is None:
            return "Strategy can't see this symbol — likely manual position."
        cur_ret = ps.trailing_return(lookback)
        cur_ret_pct = f"{(cur_ret * 100):+.1f}%" if cur_ret is not None else "n/a"
        # what's the universe + their trailing returns?
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
        # find next-best non-held competitor
        held_set = set(active_weights) - {CASH}
        next_best = next(((r, s) for r, s in ranks if s not in held_set), None)
        bits = [
            f"{symbol} trailing {lookback}d return: {cur_ret_pct} "
            f"(T-bill floor: {tbill_floor * 100:+.1f}%)",
        ]
        if cur_ret is not None and cur_ret <= tbill_floor:
            bits.append("ALREADY below T-bill gate — strategy would exit at next rebalance.")
        elif next_best:
            bits.append(f"Strategy will SELL when: trailing {lookback}d return "
                        f"drops below {tbill_floor * 100:+.1f}% OR is overtaken by "
                        f"{next_best[1]} (currently {next_best[0] * 100:+.1f}%) — "
                        f"top-{n} cutoff.")
        else:
            bits.append(f"Strategy will SELL when: trailing {lookback}d return "
                        f"drops below {tbill_floor * 100:+.1f}%.")
        return "  ".join(bits)
    if strategy_name == "ma_crossover":
        fast = int(params.get("fast", 50))
        slow = int(params.get("slow", 200))
        ps = panel.series.get(symbol)
        if ps is None or len(ps.closes) < slow:
            return f"MA crossover will SELL when fast SMA ({fast}d) drops below slow SMA ({slow}d)."
        fast_sma = sum(ps.closes[-fast:]) / fast
        slow_sma = sum(ps.closes[-slow:]) / slow
        gap = (fast_sma / slow_sma - 1) * 100
        return (f"Fast SMA ${fast_sma:,.2f} is {gap:+.2f}% above slow SMA ${slow_sma:,.2f}. "
                f"Strategy SELLS when fast crosses below slow.")
    if strategy_name == "risk_parity":
        return ("Inverse-vol weights — strategy will REDUCE this position when "
                f"{symbol}'s realized vol rises vs the rest of the book.")
    if strategy_name == "adaptive":
        return ("Adaptive picks the trailing-90d-Sortino winner each rebalance. "
                "Will SELL this position whenever its currently-winning underlying "
                "strategy loses the Sortino ranking.")
    return "No explicit exit rule documented for this strategy."


def compute(pf: Portfolio, as_of: date, *,
            stop_pct: float = DEFAULT_STOP_PCT,
            trailing_pct: float = DEFAULT_TRAILING_PCT,
            source: str = "auto") -> tuple[list[SellSignal], dict[str, float]]:
    """Return (signals, latest_prices). Pure read — touches no state."""
    if not pf.positions or not any(p.qty for p in pf.positions.values()):
        return [], {}

    # Load history for all relevant symbols. We need a long lookback for the
    # strategy_exit text (252d trailing returns).
    syms_held = sorted(s for s, p in pf.positions.items() if p.qty)
    syms_for_strategy = list(universe_for(pf.active_strategy,
                                          pf.active_strategy_params))
    syms = sorted(set(syms_held) | set(syms_for_strategy) | {"SPY"})
    panel, tbill = load_panel(syms, date(2005, 1, 1), as_of, source=source)
    # roll back to most recent close
    cursor = as_of
    prices: dict[str, float] = {}
    for _ in range(10):
        prices = {}
        for s in syms_held:
            ps = panel.series.get(s)
            if ps is not None:
                sub = ps.as_of(cursor)
                if sub.last is not None:
                    prices[s] = sub.last
        if len(prices) == len(syms_held):
            break
        cursor -= timedelta(days=1)

    panel_pit = panel.as_of(cursor)
    tbill_pit = tbill.as_of(cursor)
    strat = build_strategy(pf.active_strategy, pf.active_strategy_params)
    try:
        target_w = strat.target_weights(panel_pit, tbill_pit)
    except Exception:
        target_w = {}

    out: list[SellSignal] = []
    # Determine "since" date for trailing peak: latest BUY fill date per symbol.
    last_buy: dict[str, date] = {}
    for t in pf.filled:
        if t.side == "BUY" and t.fill_date:
            d = date.fromisoformat(t.fill_date)
            last_buy[t.symbol] = max(last_buy.get(t.symbol, d), d)

    for sym in syms_held:
        pos = pf.positions[sym]
        last = prices.get(sym, pos.avg_cost)
        cost = pos.avg_cost
        pnl_pct = (last / cost - 1) if cost > 0 else 0.0
        stop = cost * (1 - stop_pct)
        ps = panel_pit.series.get(sym)
        peak = _peak_since(ps, last_buy.get(sym)) if ps else last
        trailing = (peak or last) * (1 - trailing_pct)

        exit_text = _strategy_exit_text(pf.active_strategy,
                                        pf.active_strategy_params,
                                        sym, panel_pit, tbill_pit, target_w)

        # consolidated action
        reasons: list[str] = []
        action = "HOLD"
        if last <= stop + 1e-6:
            reasons.append(f"price ${last:,.2f} hit stop-loss ${stop:,.2f}")
            action = "SELL"
        if last <= trailing + 1e-6:
            reasons.append(f"price ${last:,.2f} below trailing stop ${trailing:,.2f}")
            action = "SELL"
        target_for_sym = target_w.get(sym, 0.0)
        if action == "HOLD" and target_for_sym == 0:
            reasons.append(f"strategy no longer targets {sym} "
                           f"(target weight 0.0%)")
            action = "SELL"
        elif action == "HOLD":
            # how close to thresholds?
            stop_margin = (last - stop) / stop * 100 if stop > 0 else 0
            trail_margin = (last - trailing) / trailing * 100 if trailing > 0 else 0
            if min(stop_margin, trail_margin) < 5:
                action = "WATCH"
                reasons.append(f"within 5% of nearest stop (stop +{stop_margin:.1f}%, "
                               f"trail +{trail_margin:.1f}%)")
            else:
                reasons.append("all sell triggers comfortably clear")

        out.append(SellSignal(
            symbol=sym, qty=pos.qty, cost=cost, last=last,
            pnl_pct=pnl_pct, stop_loss_price=round(stop, 2),
            trailing_stop_price=round(trailing, 2),
            strategy_exit=exit_text, action=action, reasons=reasons,
        ))
    return out, prices


# --- console card ----------------------------------------------------------

def _print_card(signals: list[SellSignal], pf: Portfolio, as_of: date) -> None:
    print(f"\n{'=' * 84}")
    print(f" SELL GUIDE — held positions as of {as_of}  ·  strategy: {pf.active_strategy}")
    print(f"{'=' * 84}")
    if not signals:
        print("  No positions — nothing to manage.\n")
        return
    for s in signals:
        flag = {"HOLD": " HOLD ", "WATCH": " WATCH", "SELL": " SELL "}[s.action]
        col = {"HOLD": "", "WATCH": "  *", "SELL": "  !!"}[s.action]
        pnl_arrow = "▲" if s.pnl_pct > 0 else ("▼" if s.pnl_pct < 0 else "·")
        print(f"\n  [{flag}]{col}  {s.symbol}  qty {s.qty}")
        print(f"    cost ${s.cost:,.2f}  last ${s.last:,.2f}  "
              f"{pnl_arrow} {s.pnl_pct * 100:+.2f}%  "
              f"position value ${s.qty * s.last:,.2f}")
        print(f"    stop-loss      below ${s.stop_loss_price:,.2f}  "
              f"({(s.stop_loss_price / s.last - 1) * 100:+.1f}% from here)")
        print(f"    trailing stop  below ${s.trailing_stop_price:,.2f}  "
              f"({(s.trailing_stop_price / s.last - 1) * 100:+.1f}% from here)")
        print(f"    strategy exit  {s.strategy_exit}")
        for r in s.reasons:
            print(f"                   - {r}")
    print()


# --- HTML card -------------------------------------------------------------

_HTML_CSS = """
body { font-family: 'Iowan Old Style', Charter, Georgia, serif; background: #fbfaf6; color: #0f1115; max-width: 920px; margin: 0 auto; padding: 56px 32px 80px; line-height: 1.55; }
header { border-bottom: 1px solid #1a1a1a; padding-bottom: 18px; margin-bottom: 28px; }
.eyebrow { font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; color: #6b6f76; font-family: -apple-system, sans-serif; }
h1 { font-size: 28px; font-weight: 600; letter-spacing: -0.012em; margin: 6px 0 0; }
.muted { color: #6b6f76; font-family: -apple-system, sans-serif; font-size: 13px; }
.card { background: white; border: 1px solid #e6e3da; border-radius: 4px; padding: 18px 22px; margin-bottom: 18px; }
.card.action-SELL { border-left: 4px solid #9b2226; }
.card.action-WATCH { border-left: 4px solid #9a6b00; }
.card.action-HOLD { border-left: 4px solid #137333; }
.row { display: flex; gap: 28px; align-items: baseline; }
.symbol { font-family: -apple-system, sans-serif; font-size: 22px; font-weight: 600; letter-spacing: -0.005em; }
.qty { color: #6b6f76; font-family: -apple-system, sans-serif; font-size: 13px; margin-left: 8px; }
.action-tag { display: inline-block; padding: 2px 10px; border-radius: 3px; font-family: -apple-system, sans-serif; font-size: 11px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; margin-left: auto; }
.action-tag.SELL { background: #9b2226; color: white; }
.action-tag.WATCH { background: #9a6b00; color: white; }
.action-tag.HOLD { background: #137333; color: white; }
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-top: 14px; padding-top: 14px; border-top: 1px solid #ececec; font-family: -apple-system, sans-serif; }
.kpi-label { font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase; color: #6b6f76; }
.kpi-value { font-size: 16px; font-variant-numeric: tabular-nums; margin-top: 2px; font-weight: 500; }
.kpi-value.pos { color: #137333; } .kpi-value.neg { color: #9b2226; }
.exit { margin-top: 12px; font-size: 13px; color: #333; font-family: -apple-system, sans-serif; padding: 10px 12px; background: #faf8f0; border-radius: 3px; }
.reasons { margin-top: 8px; font-size: 12px; color: #6b6f76; font-family: -apple-system, sans-serif; }
.reasons li { margin-left: 18px; }
"""


def render_html(signals: list[SellSignal], pf: Portfolio, as_of: date) -> str:
    cards = []
    for s in signals:
        pnl_class = "pos" if s.pnl_pct > 0 else ("neg" if s.pnl_pct < 0 else "")
        stop_pct = (s.stop_loss_price / s.last - 1) * 100 if s.last > 0 else 0
        trail_pct = (s.trailing_stop_price / s.last - 1) * 100 if s.last > 0 else 0
        reasons_html = "".join(f'<li>{_html.escape(r)}</li>' for r in s.reasons)
        cards.append(f"""
<div class="card action-{s.action}">
  <div class="row">
    <div class="symbol">{_html.escape(s.symbol)}
      <span class="qty">{s.qty} shares · ${(s.qty * s.last):,.2f}</span>
    </div>
    <span class="action-tag {s.action}">{s.action}</span>
  </div>
  <div class="kpis">
    <div><div class="kpi-label">Cost</div><div class="kpi-value">${s.cost:,.2f}</div></div>
    <div><div class="kpi-label">Last</div><div class="kpi-value">${s.last:,.2f}</div></div>
    <div><div class="kpi-label">P&amp;L</div><div class="kpi-value {pnl_class}">{s.pnl_pct * 100:+.2f}%</div></div>
    <div><div class="kpi-label">Stop / Trail</div><div class="kpi-value">${s.stop_loss_price:,.2f} / ${s.trailing_stop_price:,.2f}</div></div>
  </div>
  <div class="exit"><strong>Strategy exit:</strong> {_html.escape(s.strategy_exit)}</div>
  <ul class="reasons">{reasons_html}</ul>
</div>
""")

    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Sell guide — {as_of}</title>
<style>{_HTML_CSS}</style></head><body>
<header>
  <div class="eyebrow">When to sell</div>
  <h1>Sell guide — {datetime.fromisoformat(as_of.isoformat()).strftime("%A, %B %-d, %Y")}</h1>
  <div class="muted" style="margin-top:6px">
    Strategy: <strong>{_html.escape(pf.active_strategy)}</strong> ·
    {len(signals)} open position{"s" if len(signals) != 1 else ""}.
    Set broker-side stops at the prices shown; check the strategy-exit
    condition between morning runs.
  </div>
</header>
{"".join(cards) if cards else '<div class="muted">No open positions.</div>'}
</body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Explicit sell triggers per position.")
    ap.add_argument("--as-of", type=str, default="")
    ap.add_argument("--source", default="auto")
    ap.add_argument("--stop", type=float, default=DEFAULT_STOP_PCT,
                    help=f"stop-loss as fraction (default {DEFAULT_STOP_PCT})")
    ap.add_argument("--trailing", type=float, default=DEFAULT_TRAILING_PCT,
                    help=f"trailing-stop as fraction (default {DEFAULT_TRAILING_PCT})")
    ap.add_argument("--html", default="")
    args = ap.parse_args()
    as_of = (date.fromisoformat(args.as_of) if args.as_of else date.today())
    try:
        pf = Portfolio.load()
    except FileNotFoundError as e:
        print(e)
        return 1
    signals, _prices = compute(pf, as_of,
                                stop_pct=args.stop,
                                trailing_pct=args.trailing,
                                source=args.source)
    _print_card(signals, pf, as_of)
    if args.html:
        with open(args.html, "w") as f:
            f.write(render_html(signals, pf, as_of))
        print(f"html: {args.html}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
