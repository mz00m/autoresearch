"""gap_stress.py — what trailing stops do NOT protect against.

The adversarial review's key finding on the leveraged sleeve: a 10-15% trailing
stop reads like a floor, but stops are *triggers*, not guarantees. In a real
crash the market gaps at the open and a market-on-trigger stop fills 20-30%
below the trail price. This tool makes that concrete per held symbol using its
own price history:

  * worst 1-day and worst 3-day drop the symbol has actually printed
  * how often it moved past the stop distance in a single session
  * the portfolio-level hit if every position gap-filled at its historical
    worst instead of at the stop

Read the output as: "the stop is my *intent*; this is my *exposure*."
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, timedelta

from fund.data.pit import Panel
from fund.data.loader import load_panel
from fund.portfolio import Portfolio


@dataclass(frozen=True)
class GapFinding:
    symbol: str
    weight: float               # fraction of book
    worst_1d: float             # most negative 1-day return, e.g. -0.35
    worst_3d: float             # most negative 3-day compounded return
    days_past_stop: int         # sessions that fell further than the stop alone
    n_days: int                 # history length the stats are drawn from
    stop_pct: float

    @property
    def stop_slippage(self) -> float:
        """How far past the stop the worst single day went (0 if never)."""
        return min(0.0, self.worst_1d + self.stop_pct)


@dataclass(frozen=True)
class GapReport:
    findings: list[GapFinding]
    stop_pct: float

    @property
    def naive_stop_loss(self) -> float:
        """Portfolio loss if every stop filled exactly at trail (the belief)."""
        return -self.stop_pct * sum(f.weight for f in self.findings)

    @property
    def gap_loss_1d(self) -> float:
        """Portfolio loss if every position gap-filled at its historical worst
        single day (the exposure)."""
        return sum(f.weight * min(f.worst_1d, -0.0) for f in self.findings)

    @property
    def gap_loss_3d(self) -> float:
        """Same, over the worst historical 3-day window per symbol — closer to
        how crashes actually unfold before a human reacts."""
        return sum(f.weight * min(f.worst_3d, -0.0) for f in self.findings)


def _daily_returns(closes: tuple[float, ...]) -> list[float]:
    return [closes[i] / closes[i - 1] - 1.0
            for i in range(1, len(closes)) if closes[i - 1] > 0]


def stress_symbol(symbol: str, panel: Panel, weight: float,
                  stop_pct: float = 0.10) -> GapFinding | None:
    ps = panel.series.get(symbol)
    if ps is None or len(ps) < 30:
        return None
    rets = _daily_returns(ps.closes)
    worst_1d = min(rets)
    worst_3d = 0.0
    for i in range(len(rets) - 2):
        w = (1 + rets[i]) * (1 + rets[i + 1]) * (1 + rets[i + 2]) - 1.0
        worst_3d = min(worst_3d, w)
    past_stop = sum(1 for r in rets if r < -stop_pct)
    return GapFinding(symbol=symbol, weight=weight, worst_1d=worst_1d,
                      worst_3d=worst_3d, days_past_stop=past_stop,
                      n_days=len(rets), stop_pct=stop_pct)


def stress_portfolio(weights: dict[str, float], panel: Panel,
                     stop_pct: float = 0.10) -> GapReport:
    findings = []
    for sym, w in sorted(weights.items(), key=lambda kv: -kv[1]):
        if sym == "CASH" or w <= 0:
            continue
        f = stress_symbol(sym, panel, w, stop_pct)
        if f is not None:
            findings.append(f)
    return GapReport(findings=findings, stop_pct=stop_pct)


def _print_report(rep: GapReport, book: float) -> None:
    print(f"\n{'=' * 78}")
    print(f" GAP STRESS — stops are triggers, not floors (stop = {rep.stop_pct:.0%} trail)")
    print(f"{'=' * 78}")
    if not rep.findings:
        print("  no priced positions to stress.")
        return
    print(f"  {'sym':<6} {'weight':>7} {'worst 1d':>9} {'worst 3d':>9} "
          f"{'past-stop days':>14}  {'history':>8}")
    for f in rep.findings:
        print(f"  {f.symbol:<6} {f.weight:>6.0%} {f.worst_1d:>8.1%} "
              f"{f.worst_3d:>8.1%} {f.days_past_stop:>14d}  {f.n_days:>7d}d")
    print()
    print(f"  If stops fill at trail (the belief):     "
          f"{rep.naive_stop_loss:>7.1%}  (${rep.naive_stop_loss * book:>+10,.0f})")
    print(f"  If gaps fill at worst historical 1-day:  "
          f"{rep.gap_loss_1d:>7.1%}  (${rep.gap_loss_1d * book:>+10,.0f})")
    print(f"  If crash unfolds over worst 3 days:      "
          f"{rep.gap_loss_3d:>7.1%}  (${rep.gap_loss_3d * book:>+10,.0f})")
    slippers = [f for f in rep.findings if f.days_past_stop > 0]
    if slippers:
        worst = min(slippers, key=lambda f: f.stop_slippage)
        print(f"\n  ⚠ {worst.symbol} has printed {worst.days_past_stop} sessions "
              f"beyond the stop distance — worst gap-through "
              f"{worst.stop_slippage:.1%} past the trail.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Stress held positions for gap-through-stop risk.")
    ap.add_argument("--stop-pct", type=float, default=0.10,
                    help="trailing stop distance (default 10%%)")
    ap.add_argument("--years", type=int, default=8,
                    help="history window for worst-case stats (default 8y)")
    ap.add_argument("--source", default="auto")
    args = ap.parse_args()

    try:
        pf = Portfolio.load()
    except FileNotFoundError:
        print("no portfolio — run fund.portfolio init first")
        return 1
    held = {s: p for s, p in pf.positions.items() if p.qty > 0}
    if not held:
        print("no held positions.")
        return 0

    end = date.today()
    panel, _ = load_panel(list(held), end - timedelta(days=args.years * 365),
                          end, source=args.source)
    prices = {s: (panel.series[s].last if panel.series.get(s) and panel.series[s].last
                  else p.avg_cost) for s, p in held.items()}
    book = pf.cash + sum(p.qty * prices[s] for s, p in held.items())
    weights = {s: p.qty * prices[s] / book for s, p in held.items() if book > 0}

    rep = stress_portfolio(weights, panel, stop_pct=args.stop_pct)
    _print_report(rep, book)
    return 0


if __name__ == "__main__":
    sys.exit(main())
