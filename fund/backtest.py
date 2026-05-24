"""The fixed backtest protocol — every hypothesis is evaluated identically.

Produces a DAILY portfolio return series (so the evaluator's 252/yr annualization
is correct), strictly point-in-time: weights chosen at the close of a rebalance
day using data <= that day apply to the *following* days. Frictions (slippage,
commission) are modeled as a one-day drag on each rebalance so the winners are
optimal for a real account, not a frictionless fantasy.

The harness is strategy-agnostic: any object with ``target_weights(panel_asof,
tbill_asof) -> {symbol: weight}`` and an ``n_params`` works.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from fund.data.pit import Panel, PriceSeries
from fund.strategy.dual_momentum import CASH


@dataclass(frozen=True)
class Costs:
    slippage_bps: float = 5.0       # per unit of one-way turnover
    commission_per_leg: float = 0.0  # IBKR ETFs ~ $0; in bps-of-trade terms here


@dataclass
class BacktestResult:
    dates: list[date]                       # day each return is realized
    returns: list[float]                    # daily portfolio return, net of costs
    rebal_dates: list[date] = field(default_factory=list)
    rebal_turnover: dict = field(default_factory=dict)  # date -> one-way turnover

    def partition(self, cutoff: date):
        """Split into (in_sample, oos) by date <= cutoff. Returns two dicts with
        keys: returns, n_rebal, turnover_annualized."""
        ins_r = [r for d, r in zip(self.dates, self.returns) if d <= cutoff]
        oos_r = [r for d, r in zip(self.dates, self.returns) if d > cutoff]
        ins_rb = [d for d in self.rebal_dates if d <= cutoff]
        oos_rb = [d for d in self.rebal_dates if d > cutoff]
        return (_window_stats(ins_r, ins_rb, self.rebal_turnover, self.dates),
                _window_stats(oos_r, oos_rb, self.rebal_turnover, self.dates,
                              after=cutoff))


def _years(dates: list[date], lo: date | None = None) -> float:
    pts = [d for d in dates if (lo is None or d > lo)]
    if len(pts) < 2:
        return 0.0
    return (pts[-1] - pts[0]).days / 365.25


def _window_stats(returns, rebal_dates, turnover_map, all_dates, after=None):
    yrs = _years([d for d in all_dates if (after is None or d > after)])
    tot_turn = sum(turnover_map.get(d, 0.0) for d in rebal_dates)
    return {
        "returns": returns,
        "n_rebal": len(rebal_dates),
        "turnover_annualized": (tot_turn / yrs) if yrs > 0 else 0.0,
    }


def _month_starts(dates: list[date]) -> set[date]:
    """First trading day of each month."""
    seen, starts = set(), set()
    for d in dates:
        key = (d.year, d.month)
        if key not in seen:
            seen.add(key)
            starts.add(d)
    return starts


def _daily_cash_rate(tbill: PriceSeries, on: date) -> float:
    annual_pct = tbill.as_of(on).last
    return (annual_pct / 100.0 / 252.0) if annual_pct is not None else 0.0


def run_backtest(strategy, panel: Panel, tbill: PriceSeries,
                 costs: Costs = Costs()) -> BacktestResult:
    dates = panel.common_dates()
    if len(dates) < 2:
        return BacktestResult([], [])
    rebal = _month_starts(dates)
    closes = {s: dict(zip(ps.dates, ps.closes)) for s, ps in panel.series.items()}

    weights: dict[str, float] = {CASH: 1.0}
    out_dates, out_rets, rebal_dates = [], [], []
    turnover_map: dict[date, float] = {}

    for i in range(1, len(dates)):
        prev, today = dates[i - 1], dates[i]

        # realize return prev->today using weights held since the last rebalance
        r = 0.0
        for sym, w in weights.items():
            if w == 0.0:
                continue
            if sym == CASH:
                r += w * _daily_cash_rate(tbill, prev)
            else:
                c0 = closes[sym].get(prev)
                c1 = closes[sym].get(today)
                if c0 and c1:
                    r += w * (c1 / c0 - 1.0)

        # decide new weights at today's close (data <= today), apply going forward
        if today in rebal:
            new_w = strategy.target_weights(panel.as_of(today), tbill.as_of(today))
            keys = set(new_w) | set(weights)
            turnover = sum(abs(new_w.get(k, 0.0) - weights.get(k, 0.0)) for k in keys)
            drag = (costs.slippage_bps / 1e4) * turnover
            r -= drag
            if turnover > 1e-9:
                rebal_dates.append(today)
                turnover_map[today] = turnover
            weights = new_w

        out_dates.append(today)
        out_rets.append(r)

    return BacktestResult(out_dates, out_rets, rebal_dates, turnover_map)
