"""recommendations.py — what every strategy says to do TODAY.

Until the broker is wired up, you trade manually. This module runs every
registered strategy against the latest close, shows the target portfolio +
the dollar allocation + the integer share count for a given principal, side
by side. The active strategy's row is called out so you know which one your
paper portfolio is actually tracking.

It does *not* touch portfolio_state.json (no tickets created). It's a pure
read-only preview: "if I switched to X today, here's what X would buy."

Run:
  python3 -m fund.recommendations                # uses today + active principal
  python3 -m fund.recommendations --as-of 2026-05-22 --principal 25000
  python3 -m fund.recommendations --html recs.html   # also write a card
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
from fund.strategy.registry import (DEFAULT_UNIVERSE, build as build_strategy,
                                    list_strategies, universe_for)


def _all_symbols_needed() -> tuple[str, ...]:
    """Union of every symbol any registered strategy might pick. We fetch them
    once so each strategy can use whatever subset it wants."""
    syms: set[str] = set()
    for name in list_strategies():
        syms.update(universe_for(name, {}))
    return tuple(sorted(syms))


def _most_recent_close(panel: Panel, on: date) -> tuple[date | None,
                                                        dict[str, float]]:
    """Return (date_of_most_recent_close, {symbol: close}). Rolls back to last
    trading day if `on` is a weekend or holiday."""
    cursor = on
    for _ in range(10):  # at most a 10-day rollback
        prices: dict[str, float] = {}
        for sym, ps in panel.series.items():
            sub = ps.as_of(cursor)
            if sub.dates and sub.dates[-1] == cursor:
                prices[sym] = sub.last  # type: ignore[assignment]
        if len(prices) >= max(1, len(panel.series) // 2):
            return cursor, prices
        cursor -= timedelta(days=1)
    # fall back to whatever's available
    out = {sym: ps.last for sym, ps in panel.series.items() if ps.last}
    return None, out  # type: ignore[return-value]


def _to_shares(weights: dict[str, float], equity: float,
               prices: dict[str, float]) -> dict[str, dict]:
    """Return per-symbol {weight, dollars, shares, price}."""
    out: dict[str, dict] = {}
    for sym, w in weights.items():
        if sym == CASH:
            out[sym] = {"weight": w, "dollars": equity * w,
                        "shares": 0, "price": 0.0}
            continue
        px = prices.get(sym, 0.0)
        dollars = equity * w
        shares = int(dollars // px) if px > 0 else 0
        out[sym] = {"weight": w, "dollars": dollars,
                    "shares": shares, "price": px}
    # Residual = cash left after rounding
    deployed = sum(v["shares"] * v["price"] for v in out.values()
                   if v["price"] > 0)
    out["__cash_residual__"] = {"weight": 0.0,
                                "dollars": max(0.0, equity - deployed),
                                "shares": 0, "price": 0.0}
    return out


def compute_all(as_of: date, *, principal: float = 25_000.0,
                source: str = "auto") -> dict:
    syms = _all_symbols_needed()
    panel, tbill = load_panel(list(syms), date(2005, 1, 1), as_of, source=source)
    asof_date, prices = _most_recent_close(panel, as_of)
    if asof_date is None:
        raise RuntimeError(f"no prices available near {as_of}")
    panel_pit = panel.as_of(asof_date)
    tbill_pit = tbill.as_of(asof_date)

    out: dict[str, dict] = {}
    for name in list_strategies():
        strat = build_strategy(name, {})
        try:
            weights = strat.target_weights(panel_pit, tbill_pit)
        except Exception as e:
            out[name] = {"error": str(e), "weights": {}, "allocation": {}}
            continue
        out[name] = {
            "weights": weights,
            "allocation": _to_shares(weights, principal, prices),
        }
    return {"as_of": asof_date.isoformat(), "principal": principal,
            "prices": prices, "by_strategy": out}


def compute_one(strategy: str, params: dict, as_of: date, *,
                principal: float = 25_000.0, source: str = "auto") -> dict:
    """Fast single-strategy preview — only loads what THIS strategy needs."""
    from fund.strategy.registry import universe_for
    syms = sorted(set(universe_for(strategy, params)) | {"SPY"})
    panel, tbill = load_panel(list(syms), date(2005, 1, 1), as_of, source=source)
    asof_date, prices = _most_recent_close(panel, as_of)
    if asof_date is None:
        raise RuntimeError(f"no prices available near {as_of}")
    panel_pit = panel.as_of(asof_date)
    tbill_pit = tbill.as_of(asof_date)
    strat = build_strategy(strategy, params)
    weights = strat.target_weights(panel_pit, tbill_pit)
    allocation = _to_shares(weights, principal, prices)
    return {"as_of": asof_date.isoformat(), "principal": principal,
            "strategy": strategy, "params": params,
            "weights": weights, "allocation": allocation,
            "prices": prices}


# --- console card ----------------------------------------------------------

def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _fmt_money(x: float) -> str:
    return f"${x:,.2f}"


def _print_card(result: dict, active: str | None) -> None:
    print(f"\n{'=' * 78}")
    print(f" RECOMMENDATIONS — close of {result['as_of']}  "
          f"·  principal ${result['principal']:,.0f}")
    print(f"{'=' * 78}")
    for name, info in result["by_strategy"].items():
        marker = "  >>" if name == active else "    "
        active_tag = "  [ACTIVE]" if name == active else ""
        if "error" in info:
            print(f"{marker} {name}{active_tag}: ERROR {info['error']}")
            continue
        # Build single-line allocation summary
        pieces = []
        for sym, a in info["allocation"].items():
            if sym in ("__cash_residual__", CASH):
                continue
            if a["shares"] > 0:
                pieces.append(f"{a['shares']} {sym} @ ${a['price']:.2f}")
        cash_w = info["allocation"].get(CASH, {}).get("weight", 0.0)
        residual = info["allocation"].get("__cash_residual__", {}).get("dollars", 0.0)
        if cash_w > 0:
            pieces.append(f"CASH {_fmt_pct(cash_w)}")
        print(f"{marker} {name:<22}{active_tag}")
        if pieces:
            print(f"      {' · '.join(pieces)}")
            print(f"      cash residual ${residual:,.2f}")
        else:
            print(f"      ALL CASH (no signal cleared the T-bill gate)")
    print()


# --- HTML card -------------------------------------------------------------

_HTML_CSS = """
body { font-family: 'Iowan Old Style', Charter, Georgia, serif; background: #fbfaf6; color: #0f1115; max-width: 920px; margin: 0 auto; padding: 56px 32px 80px; line-height: 1.55; }
header { border-bottom: 1px solid #1a1a1a; padding-bottom: 18px; margin-bottom: 36px; }
.eyebrow { font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; color: #6b6f76; font-family: -apple-system, BlinkMacSystemFont, sans-serif; }
h1 { font-size: 30px; margin: 6px 0 0; font-weight: 600; letter-spacing: -0.012em; }
h2 { font-size: 17px; font-weight: 600; margin: 32px 0 10px; padding-bottom: 4px; border-bottom: 1px solid #e6e3da; }
table { width: 100%; border-collapse: collapse; font-size: 13px; font-family: -apple-system, BlinkMacSystemFont, sans-serif; }
th { text-align: left; padding: 8px 10px; font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; color: #6b6f76; border-bottom: 1px solid #1a1a1a; font-weight: 500; }
td { padding: 8px 10px; border-bottom: 1px solid #ececec; vertical-align: top; font-variant-numeric: tabular-nums; }
.num { text-align: right; }
.active { background: #fbf8ee; }
.tag-active { background: #1c4f8e; color: white; padding: 1px 6px; border-radius: 2px; font-size: 10px; letter-spacing: 0.04em; text-transform: uppercase; font-weight: 500; margin-left: 8px; font-family: -apple-system, sans-serif; }
.empty { color: #6b6f76; font-style: italic; padding: 12px 0; }
.muted { color: #6b6f76; }
.symbol { font-weight: 500; }
footer { margin-top: 56px; padding-top: 16px; border-top: 1px solid #e6e3da; color: #888; font-size: 11px; font-family: -apple-system, sans-serif; }
"""


def render_html(result: dict, active: str | None) -> str:
    body = []
    for name, info in result["by_strategy"].items():
        is_active = name == active
        title_tag = ' <span class="tag-active">Active</span>' if is_active else ""
        body.append(f'<h2>{_html.escape(name)}{title_tag}</h2>')
        if "error" in info:
            body.append(f'<div class="empty">ERROR: {_html.escape(info["error"])}</div>')
            continue
        rows = []
        cash_w = 0.0
        for sym, a in info["allocation"].items():
            if sym == "__cash_residual__":
                continue
            if sym == CASH:
                cash_w = a["weight"]
                continue
            if a["shares"] == 0 and a["weight"] == 0:
                continue
            rows.append(
                f'<tr><td><span class="symbol">{_html.escape(sym)}</span></td>'
                f'<td class="num">{_fmt_pct(a["weight"])}</td>'
                f'<td class="num">{_fmt_money(a["price"])}</td>'
                f'<td class="num">{a["shares"]}</td>'
                f'<td class="num">{_fmt_money(a["shares"] * a["price"])}</td>'
                f'</tr>'
            )
        residual = info["allocation"].get("__cash_residual__", {}).get("dollars", 0.0)
        if cash_w > 0:
            rows.append(
                f'<tr><td>CASH</td><td class="num">{_fmt_pct(cash_w)}</td>'
                f'<td class="num muted">—</td><td class="num muted">—</td>'
                f'<td class="num">{_fmt_money(result["principal"] * cash_w)}</td>'
                f'</tr>'
            )
        if not rows:
            body.append('<div class="empty">All cash — no signal cleared the T-bill gate.</div>')
        else:
            body.append(
                '<table><thead><tr><th>Symbol</th>'
                '<th class="num">Target weight</th><th class="num">Price</th>'
                '<th class="num">Shares</th><th class="num">Notional</th></tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table>'
            )
            if residual > 0.01:
                body.append(f'<div class="muted" style="font-size:11px;margin-top:6px;font-family:sans-serif">'
                            f'Cash residual after share rounding: {_fmt_money(residual)}</div>')

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Recommendations — {result["as_of"]}</title>
<style>{_HTML_CSS}</style></head><body>
<header>
  <div class="eyebrow">If you traded today</div>
  <h1>{datetime.fromisoformat(result["as_of"]).strftime("%A, %B %-d, %Y")}</h1>
  <div class="muted" style="margin-top:8px;font-family:sans-serif;font-size:13px">
    Side-by-side recommendations from every registered strategy.
    Principal <strong>${result["principal"]:,.0f}</strong>. Read-only — no tickets created.
  </div>
</header>
{"".join(body)}
<footer>Generated {datetime.now().strftime("%Y-%m-%d %H:%M")}. Whole-share counts only — IBKR/Alpaca cash-account semantics.</footer>
</body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only recommendation card.")
    ap.add_argument("--as-of", type=str, default="",
                    help="ISO date (default: today)")
    ap.add_argument("--principal", type=float, default=0.0,
                    help="Override principal (default: active portfolio's)")
    ap.add_argument("--source", default="auto")
    ap.add_argument("--html", default="",
                    help="Also write an HTML card to this path")
    args = ap.parse_args()

    as_of = (date.fromisoformat(args.as_of) if args.as_of else date.today())
    principal = args.principal
    active: str | None = None
    if principal <= 0:
        try:
            pf = Portfolio.load()
            principal = pf.principal
            active = pf.active_strategy
        except FileNotFoundError:
            principal = 25_000.0

    result = compute_all(as_of, principal=principal, source=args.source)
    _print_card(result, active=active)
    if args.html:
        with open(args.html, "w") as f:
            f.write(render_html(result, active=active))
        print(f"html card: {args.html}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
