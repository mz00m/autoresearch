"""cache_for_ui.py — compute recommendations + sell-guide once, write JSON.

The Next.js dashboard is a viewer (no Python in process). This module is the
bridge: runs both `recommendations` and `sell_guide` for the current
portfolio + as-of date, writes the combined result to `fund/ui_cache.json`,
which the UI reads via server components.

Re-run whenever you want fresh numbers:

    python3 -m fund.cache_for_ui                 # uses today + active portfolio
    python3 -m fund.cache_for_ui --as-of 2026-05-22

You can also wire this into a cron / launchd plist that runs at market close.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import asdict
from datetime import date, datetime

from fund.portfolio import Portfolio
from fund.recommendations import compute_all
from fund.sell_guide import compute as compute_sell
from fund.tax import RealizedLot, summarize_realized

CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "ui_cache.json")
DAILY_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "daily_log.tsv")


def _ytd_tax_summary(pf: Portfolio, year: int) -> dict:
    """YTD realized PnL bucketed into ST/LT gains/losses."""
    lots: list[RealizedLot] = []
    for r in pf.realized:
        try:
            sold = date.fromisoformat(r["date_sold"])
        except Exception:
            continue
        if sold.year != year:
            continue
        lots.append(RealizedLot(
            date_acquired=r["date_acquired"], date_sold=r["date_sold"],
            qty=r["qty"], cost_per_share=r["cost_per_share"],
            sale_price=r["sale_price"], long_term=r["long_term"],
        ))
    s = summarize_realized(lots)
    return {
        "year": year,
        "st_gains": round(s.st_gains, 2), "st_losses": round(s.st_losses, 2),
        "lt_gains": round(s.lt_gains, 2), "lt_losses": round(s.lt_losses, 2),
        "net_short_term": round(s.net_short_term, 2),
        "net_long_term": round(s.net_long_term, 2),
        "net_total": round(s.net_total, 2),
        "lot_count": sum(len(p.lots) for p in pf.positions.values()),
        "wash_sale_warnings": dict(pf.last_loss_sales),
    }


def _regime_snapshot(pf: Portfolio, as_of: date, source: str) -> dict | None:
    """If the active strategy is regime_aware, classify and return signals."""
    if pf.active_strategy != "regime_aware":
        return None
    from fund.data.loader import load_panel
    from fund.strategy.regime_aware import RegimeAwareAllocator
    from fund.strategy.registry import universe_for
    syms = list(universe_for("regime_aware", {}))
    try:
        panel, _tbill = load_panel(syms, date(2005, 1, 1), as_of, source=source)
        allocator = RegimeAwareAllocator()
        regime, signals = allocator.classify(panel.as_of(as_of))
        return {"regime": regime,
                "vix": signals.get("vix"),
                "curve_slope": signals.get("curve_slope"),
                "spy_above_200d": signals.get("spy_above_200d"),
                "routed_to": allocator.routing.get(regime, ("?", {}))[0]}
    except Exception as e:
        return {"regime": "ERROR", "reason": str(e)}


def _drift_snapshot(pf: Portfolio, as_of: date, source: str) -> dict | None:
    """Run drift detector against the daily_log. Returns None if not enough
    live data (< 10 days) or computation fails."""
    if not os.path.exists(DAILY_LOG_PATH):
        return None
    with open(DAILY_LOG_PATH, newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    if len(rows) < 10:
        return None
    try:
        live = [float(r["day_return"]) for r in rows if r.get("day_return")]
    except (KeyError, ValueError):
        return None
    if len(live) < 10:
        return None
    try:
        from fund.drift import evaluate
        report = evaluate(pf.active_strategy, pf.active_strategy_params,
                          live, source=source, as_of=as_of)
        return {
            "n_live": report.n_live, "n_backtest": report.n_backtest,
            "live_mean_annualized": round(report.live_mean * 252, 4),
            "backtest_mean_annualized": round(report.backtest_mean * 252, 4),
            "t_statistic": round(report.t_statistic, 3),
            "p_value": round(report.p_value_approx, 4),
            "verdict": report.verdict,
            "reason": report.reason,
        }
    except Exception:
        return None


def build(as_of: date, *, source: str = "auto",
          pf: Portfolio | None = None) -> dict:
    if pf is None:
        try:
            pf = Portfolio.load()
        except FileNotFoundError:
            pf = None

    principal = pf.principal if pf else 25_000.0
    active = pf.active_strategy if pf else None
    active_params = pf.active_strategy_params if pf else {}

    recs = compute_all(as_of, principal=principal, source=source)

    sell_signals = []
    if pf is not None and any(p.qty for p in pf.positions.values()):
        signals, _ = compute_sell(pf, as_of, source=source)
        sell_signals = [asdict(s) for s in signals]

    tax = _ytd_tax_summary(pf, as_of.year) if pf is not None else None
    regime = _regime_snapshot(pf, as_of, source) if pf is not None else None
    drift = _drift_snapshot(pf, as_of, source) if pf is not None else None
    coach = _coach_report(pf, drift, tax) if pf is not None else None

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": recs["as_of"],
        "principal": principal,
        "active_strategy": active,
        "active_strategy_params": active_params,
        "recommendations": recs["by_strategy"],
        "prices": recs["prices"],
        "sell_signals": sell_signals,
        "tax_summary": tax,
        "regime_snapshot": regime,
        "drift_snapshot": drift,
        "coach": coach,
    }


def _coach_report(pf: Portfolio, drift: dict | None,
                  tax: dict | None) -> dict | None:
    """Synthesize verdict + drift + tax + wash + drawdown into one card."""
    from fund.coach import synthesize
    from fund.decision import evaluate as decision_eval

    # Pull verdict from daily_log
    rows: list[dict] = []
    if os.path.exists(DAILY_LOG_PATH):
        with open(DAILY_LOG_PATH, newline="") as f:
            rows = list(csv.DictReader(f, delimiter="\t"))
    decision = decision_eval(rows)
    dd = decision.current_drawdown if decision else 0.0
    excess_pp = decision.trailing_excess * 100 if decision else 0.0
    report = synthesize(
        decision_verdict=decision.verdict if decision else "ok",
        decision_excess_pp=excess_pp,
        drift_verdict=drift.get("verdict") if drift else None,
        drift_reason=drift.get("reason") if drift else None,
        tax_net_total=tax.get("net_total", 0.0) if tax else 0.0,
        tax_net_long_term=tax.get("net_long_term", 0.0) if tax else 0.0,
        wash_warnings=len(tax.get("wash_sale_warnings", {})) if tax else 0,
        has_pending_tickets=len(pf.pending) > 0,
        active_strategy=pf.active_strategy or "—",
        current_drawdown=dd,
    )
    return {
        "severity": report.severity,
        "headline": report.headline,
        "rationale": report.rationale,
        "next_action": report.next_action,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Cache rec+sell for the UI.")
    ap.add_argument("--as-of", type=str, default="")
    ap.add_argument("--source", default="auto")
    ap.add_argument("--out", default=CACHE_PATH)
    args = ap.parse_args()

    as_of = (date.fromisoformat(args.as_of) if args.as_of else date.today())
    cache = build(as_of, source=args.source)
    with open(args.out, "w") as f:
        json.dump(cache, f, indent=2, default=str)
    print(f"wrote {args.out}  (as_of={cache['as_of']}, "
          f"{len(cache['recommendations'])} strategies, "
          f"{len(cache['sell_signals'])} positions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
