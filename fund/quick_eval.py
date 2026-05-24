"""quick_eval — fast strategy backtests for multi-window / random-week studies.

The full ``simulate`` pipeline runs morning + closeout for every trading day,
which is faithful to production but pays a heavy I/O tax. For research-style
"run every strategy over many windows" workloads we don't need ticket I/O —
we just need the return series. This module calls ``fund.backtest.run_backtest``
directly and slices the returns by date range.

One backtest per strategy covers as many windows as you want — adaptive's
shadow backtests run ~once per rebalance against the full panel, not 7x
redundantly per calendar year.

Public API:
  panel_and_tbill(symbols, end, source)  -> (Panel, PriceSeries)
  full_backtest(name, params, panel, tbill) -> BacktestResult
  window_stats(result, start, end) -> {cum, max_dd, n_days}
  spy_window_return(panel, start, end)     -> float | None
"""

from __future__ import annotations

from datetime import date
from typing import Iterable

from fund.backtest import Costs, run_backtest, BacktestResult
from fund.data.loader import load_panel
from fund.data.pit import Panel, PriceSeries
from fund.strategy.registry import build as build_strategy, universe_for


def panel_and_tbill(symbols: list[str], end: date,
                    source: str = "auto") -> tuple[Panel, PriceSeries]:
    """Load enough history for any strategy to compute trailing returns."""
    return load_panel(symbols, date(2005, 1, 1), end, source=source)


def universe_union(strategy_specs: Iterable[tuple[str, dict]]) -> list[str]:
    syms: set[str] = set()
    for name, params in strategy_specs:
        syms.update(universe_for(name, params))
    return sorted(syms)


def full_backtest(name: str, params: dict, panel: Panel,
                  tbill: PriceSeries, *,
                  costs: Costs = Costs(slippage_bps=5.0)) -> BacktestResult:
    strat = build_strategy(name, params)
    return run_backtest(strat, panel, tbill, costs=costs)


def window_stats(result: BacktestResult, start: date, end: date) -> dict:
    """Cum return + max DD of `result.returns` over [start, end]."""
    rets = [r for d, r in zip(result.dates, result.returns)
            if start <= d <= end]
    if not rets:
        return {"cum": 0.0, "max_dd": 0.0, "n_days": 0}
    cum = 1.0
    peak = 1.0
    mdd = 0.0
    for r in rets:
        cum *= (1.0 + r)
        peak = max(peak, cum)
        if peak > 0:
            mdd = max(mdd, (peak - cum) / peak)
    return {"cum": cum - 1.0, "max_dd": mdd, "n_days": len(rets)}


def spy_window_return(panel: Panel, start: date, end: date) -> float | None:
    spy = panel.series.get("SPY")
    if spy is None:
        return None
    # Anchor at the close ON or before `start`, end at close ON or before `end`.
    start_slice = spy.as_of(start)
    end_slice = spy.as_of(end)
    if not start_slice.closes or not end_slice.closes:
        return None
    base = start_slice.closes[-1]
    if base <= 0:
        return None
    return end_slice.closes[-1] / base - 1.0
