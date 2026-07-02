"""Drift-from-backtest detector — the §5 graduation signal.

A strategy that worked in a backtest should produce live returns whose
distribution looks like the backtest's. When it doesn't — when the live mean
drifts off the backtest mean by more than noise can explain — something is
wrong: a regime change, a data error, a hidden cost the model missed, or the
scorer being gamed.

This module compares the trailing N live days to the same strategy's full
backtest distribution using Welch's two-sample t-statistic. If |t| > 2,
that's roughly p < 0.05 — the live distribution is statistically different
from the backtest. That's the moment to investigate, not necessarily to act
(could just be a small-sample artifact); but it's the *trigger* the
fund.md §5 graduation gate asks for.

Pure stdlib, idempotent, reads from daily_log + a single backtest pass.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import pickle
from dataclasses import dataclass
from datetime import date as _date, datetime as _datetime

from fund.backtest import Costs, run_backtest
from fund.data.loader import load_panel
from fund.strategy.registry import build as build_strategy, universe_for

# Cache backtest return-series so refresh-cache doesn't re-run a multi-year
# backtest every time. Key = (strategy, params, panel-last-date). Files live
# in ~/.fund/cache/ and are individually <1MB each.
_CACHE_DIR = os.path.expanduser("~/.fund/cache/drift")


def _cache_key(strategy: str, params: dict, panel_last_date: _date) -> str:
    payload = json.dumps({"s": strategy, "p": params,
                          "d": panel_last_date.isoformat()},
                         sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()[:24]


def _cache_path(key: str) -> str:
    return os.path.join(_CACHE_DIR, f"{key}.pkl")


def _cache_get(strategy: str, params: dict,
               panel_last_date: _date) -> list[float] | None:
    path = _cache_path(_cache_key(strategy, params, panel_last_date))
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def _cache_put(strategy: str, params: dict, panel_last_date: _date,
               returns: list[float]) -> None:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    path = _cache_path(_cache_key(strategy, params, panel_last_date))
    try:
        with open(path, "wb") as f:
            pickle.dump(returns, f)
    except Exception:
        pass   # cache is best-effort; never block on a write failure


@dataclass(frozen=True)
class DriftReport:
    n_live: int
    n_backtest: int
    live_mean: float           # per-day live return
    backtest_mean: float       # per-day backtest return (full history)
    live_std: float
    backtest_std: float
    t_statistic: float
    p_value_approx: float      # two-tailed Normal approximation (large n)
    verdict: str               # in_band | drifting | drifted
    reason: str


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: list[float], ddof: int = 1) -> float:
    n = len(xs)
    if n - ddof <= 0:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - ddof))


def _welch_t(mean1: float, std1: float, n1: int,
             mean2: float, std2: float, n2: int) -> float:
    """Two-sample Welch t-statistic. Returns 0 when stds are 0."""
    if n1 < 2 or n2 < 2:
        return 0.0
    var1 = (std1 ** 2) / n1
    var2 = (std2 ** 2) / n2
    denom = math.sqrt(var1 + var2)
    if denom <= 0:
        return 0.0
    return (mean1 - mean2) / denom


def _normal_two_sided_p(t: float) -> float:
    """Normal approximation to the two-tailed p-value. For our daily windows
    (n_live in dozens, n_backtest in thousands) it's tight enough."""
    return math.erfc(abs(t) / math.sqrt(2.0))


def evaluate(strategy: str, strategy_params: dict,
             live_daily_returns: list[float], *,
             source: str = "auto", as_of=None) -> DriftReport:
    """Compute drift between live returns and the strategy's full-history
    backtest. ``live_daily_returns`` is just the list of day-returns from
    the daily_log (already parsed). `as_of` is the date the panel loads
    through (defaults to today)."""
    from datetime import date
    as_of = as_of or date.today()
    if not live_daily_returns:
        return DriftReport(
            n_live=0, n_backtest=0, live_mean=0, backtest_mean=0,
            live_std=0, backtest_std=0, t_statistic=0, p_value_approx=1.0,
            verdict="in_band",
            reason="no live track record yet — drift unmeasurable",
        )

    syms = sorted(set(universe_for(strategy, strategy_params)) | {"SPY"})
    panel, tbill = load_panel(syms, date(2005, 1, 1), as_of, source=source)
    panel_last = as_of
    if panel is not None and getattr(panel, "series", None):
        cands = [d for ps in panel.series.values() for d in ps.dates]
        if cands:
            panel_last = max(cands)
    cached = _cache_get(strategy, strategy_params, panel_last)
    if cached is not None:
        bt_rets = cached
    else:
        strat = build_strategy(strategy, strategy_params)
        bt = run_backtest(strat, panel, tbill, costs=Costs(slippage_bps=5.0))
        bt_rets = bt.returns
        _cache_put(strategy, strategy_params, panel_last, bt_rets)
    if len(bt_rets) < 50:
        return DriftReport(
            n_live=len(live_daily_returns), n_backtest=len(bt_rets),
            live_mean=_mean(live_daily_returns), backtest_mean=_mean(bt_rets),
            live_std=_std(live_daily_returns), backtest_std=_std(bt_rets),
            t_statistic=0, p_value_approx=1.0, verdict="in_band",
            reason=f"backtest too short ({len(bt_rets)} days) to compare",
        )

    live_mean = _mean(live_daily_returns)
    live_std = _std(live_daily_returns)
    bt_mean = _mean(bt_rets)
    bt_std = _std(bt_rets)

    t = _welch_t(live_mean, live_std, len(live_daily_returns),
                 bt_mean, bt_std, len(bt_rets))
    p_approx = _normal_two_sided_p(t)

    if abs(t) >= 2.5:
        verdict = "drifted"
        reason = (f"|t|={abs(t):.2f} (p≈{p_approx:.3f}) — live mean "
                  f"{live_mean * 252 * 100:+.1f}%/yr is significantly "
                  f"{'below' if t < 0 else 'above'} backtest "
                  f"{bt_mean * 252 * 100:+.1f}%/yr. "
                  f"Investigate before adding capital.")
    elif abs(t) >= 1.5:
        verdict = "drifting"
        reason = (f"|t|={abs(t):.2f} (p≈{p_approx:.3f}) — early-warning "
                  f"signal; live mean {live_mean * 252 * 100:+.1f}%/yr vs "
                  f"backtest {bt_mean * 252 * 100:+.1f}%/yr. Watch the "
                  f"next 10-20 days.")
    else:
        verdict = "in_band"
        reason = (f"|t|={abs(t):.2f} — live behavior consistent with "
                  f"backtest distribution ({len(live_daily_returns)} "
                  f"live days vs {len(bt_rets)} backtest days).")

    return DriftReport(
        n_live=len(live_daily_returns), n_backtest=len(bt_rets),
        live_mean=live_mean, backtest_mean=bt_mean,
        live_std=live_std, backtest_std=bt_std,
        t_statistic=t, p_value_approx=p_approx,
        verdict=verdict, reason=reason,
    )
