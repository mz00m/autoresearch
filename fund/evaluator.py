"""Backtest evaluator — the overfitting-resistant scorer (the ``val_bpb`` analog).

In ML, ``val_bpb`` is honest: a lower number is genuinely a better model. In
markets, a great backtest is mostly noise, and an autonomous loop that tries
~100 hypotheses a night is a *machine for manufacturing overfit strategies*.
So this scorer is hardened against multiple-testing in three ways:

  1. OOS vault     — strategy code only ever sees in-sample data; the locked
                     out-of-sample slice is scored here, once.
  2. Walk-forward  — a strategy must work across rolling regimes, not one window.
  3. Deflated SR   — the score *knows how many hypotheses were tried* and
                     discounts the best one accordingly (Bailey & Lopez de Prado).

Plus the house tiebreaker: simpler beats complex unless complex clears a much
higher bar — because simpler == fewer parameters == less overfit.

Like ``risk_engine.py`` this module is sacred: agents read it, never edit it.
Pure stdlib so it runs without the ML deps.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

_PHI = NormalDist()
_GAMMA = 0.5772156649015329  # Euler-Mascheroni constant


# --- basic stats (pure stdlib) ---------------------------------------------

def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def _std(xs: list[float], ddof: int = 1) -> float:
    n = len(xs)
    if n - ddof <= 0:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - ddof))


def _skew(xs: list[float]) -> float:
    n = len(xs)
    s = _std(xs, ddof=0)
    if s == 0 or n == 0:
        return 0.0
    m = _mean(xs)
    return sum((x - m) ** 3 for x in xs) / (n * s ** 3)


def _kurtosis(xs: list[float]) -> float:
    """Non-excess kurtosis (normal == 3.0)."""
    n = len(xs)
    s = _std(xs, ddof=0)
    if s == 0 or n == 0:
        return 3.0
    m = _mean(xs)
    return sum((x - m) ** 4 for x in xs) / (n * s ** 4)


def sharpe_per_period(returns: list[float]) -> float:
    s = _std(returns)
    return _mean(returns) / s if s > 0 else 0.0


def sharpe_annualized(returns: list[float], periods_per_year: int = 252) -> float:
    return sharpe_per_period(returns) * math.sqrt(periods_per_year)


def sortino_annualized(returns: list[float], target: float = 0.0,
                       periods_per_year: int = 252) -> float:
    downside = [min(0.0, r - target) for r in returns]
    dd = math.sqrt(sum(d * d for d in downside) / len(downside)) if returns else 0.0
    if dd == 0:
        return 0.0
    return (_mean(returns) - target) / dd * math.sqrt(periods_per_year)


def max_drawdown(returns: list[float]) -> float:
    """Max peak-to-trough drawdown of the compounded equity curve, in [0, 1]."""
    equity, peak, mdd = 1.0, 1.0, 0.0
    for r in returns:
        equity *= (1.0 + r)
        peak = max(peak, equity)
        mdd = max(mdd, (peak - equity) / peak if peak > 0 else 0.0)
    return mdd


# --- overfitting defenses ---------------------------------------------------

def oos_vault_split(n: int, oos_frac: float = 0.3) -> tuple[range, range]:
    """Return (in_sample_idx, oos_idx). The OOS tail is never shown to agents."""
    cut = int(n * (1.0 - oos_frac))
    return range(0, cut), range(cut, n)


def walk_forward_splits(n: int, n_splits: int = 5, min_train: int = 50):
    """Yield (train_idx, test_idx) anchored, expanding-window splits."""
    if n_splits < 1 or n <= min_train:
        return
    fold = max(1, (n - min_train) // n_splits)
    start_test = min_train
    while start_test < n:
        end_test = min(start_test + fold, n)
        yield range(0, start_test), range(start_test, end_test)
        start_test = end_test


def expected_max_sharpe(trial_sharpes: list[float]) -> float:
    """Benchmark SR* you'd expect as the *max* over N independent trials,
    purely from selection (Bailey & Lopez de Prado). Per-period units."""
    n = len(trial_sharpes)
    if n <= 1:
        return 0.0
    var = _std(trial_sharpes, ddof=1) ** 2
    sigma = math.sqrt(var)
    if sigma == 0:
        return 0.0
    z1 = _PHI.inv_cdf(1.0 - 1.0 / n)
    z2 = _PHI.inv_cdf(1.0 - 1.0 / (n * math.e))
    return sigma * ((1.0 - _GAMMA) * z1 + _GAMMA * z2)


def deflated_sharpe_ratio(returns: list[float], trial_sharpes: list[float]) -> float:
    """Probability the strategy's true (per-period) SR exceeds the selection
    benchmark SR*, correcting for non-normality and multiple testing.
    Returns a value in [0, 1]; higher is better (want >= 0.95)."""
    t = len(returns)
    if t < 3:
        return 0.0
    sr = sharpe_per_period(returns)
    sr_star = expected_max_sharpe(trial_sharpes)
    sk = _skew(returns)
    ku = _kurtosis(returns)
    denom = 1.0 - sk * sr + ((ku - 1.0) / 4.0) * sr * sr
    if denom <= 0:
        return 0.0
    z = (sr - sr_star) * math.sqrt(t - 1) / math.sqrt(denom)
    return _PHI.cdf(z)


# --- the scorecard ----------------------------------------------------------

@dataclass(frozen=True)
class Constraints:
    max_drawdown: float = 0.50          # hard cap; mandate allows down to -100% but
    max_turnover: float = 12.0          #   we still refuse reckless paths
    min_trades: int = 30                # statistical floor; a win streak proves nothing
    min_deflated_sharpe: float = 0.95   # must clear the multiple-testing benchmark
    complexity_penalty: float = 0.0     # subtract n_params * this from the objective


@dataclass(frozen=True)
class Score:
    passed: bool
    objective: float            # deflated, downside-focused; higher is better
    sortino: float
    sharpe_annualized: float
    deflated_sharpe: float
    max_drawdown: float
    n_obs: int
    reasons: list[str]


def evaluate(oos_returns: list[float], trial_sharpes: list[float], *,
             turnover: float, n_trades: int, n_params: int = 0,
             constraints: Constraints = Constraints()) -> Score:
    """Score a candidate on its LOCKED out-of-sample returns. Hard constraints
    first (any violation => not passed, regardless of return), then objective."""
    reasons: list[str] = []
    mdd = max_drawdown(oos_returns)
    dsr = deflated_sharpe_ratio(oos_returns, trial_sharpes)
    sortino = sortino_annualized(oos_returns)
    sharpe = sharpe_annualized(oos_returns)

    if len(oos_returns) < 3:
        reasons.append("REJECT: not enough OOS observations to score")
    if n_trades < constraints.min_trades:
        reasons.append(f"REJECT: {n_trades} trades < min {constraints.min_trades}")
    if mdd > constraints.max_drawdown:
        reasons.append(f"REJECT: max drawdown {mdd:.1%} > cap {constraints.max_drawdown:.1%}")
    if turnover > constraints.max_turnover:
        reasons.append(f"REJECT: turnover {turnover:.1f} > cap {constraints.max_turnover:.1f}")
    if dsr < constraints.min_deflated_sharpe:
        reasons.append(
            f"REJECT: deflated Sharpe {dsr:.3f} < {constraints.min_deflated_sharpe:.2f} "
            f"(likely overfit / multiple-testing artifact)"
        )

    passed = len(reasons) == 0
    objective = sortino * dsr - n_params * constraints.complexity_penalty
    if passed:
        reasons.append(f"KEEP: deflated Sharpe {dsr:.3f}, OOS Sortino {sortino:.2f}")
    return Score(
        passed=passed,
        objective=objective,
        sortino=sortino,
        sharpe_annualized=sharpe,
        deflated_sharpe=dsr,
        max_drawdown=mdd,
        n_obs=len(oos_returns),
        reasons=reasons,
    )
