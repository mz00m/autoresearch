"""Decision signal — "are we on the right path, or should we iterate?"

A compact, opinionated read of the operational track record so the daily card
doesn't just *show* numbers but *interprets* them. Pure functions over the
daily_log rows + portfolio history; no extra network/data needed.

Signals it surfaces:

  * trailing N-day return (portfolio + benchmark + excess)
  * hit rate vs benchmark (fraction of days the portfolio beats SPY)
  * worst-day drag (the single ugliest day, in case anomalies dominate)
  * current vs peak drawdown
  * a single verdict in {ok, watch, iterate} with a one-line reason

Verdict rules are deliberately simple — they're meant to *trigger a human
review*, not to overrule one:

  iterate  — trailing excess <= -3pp AND hit rate < 40% over >=20 days
  watch    — trailing excess <= -1pp OR drawdown > 8% AND drawdown is current
  ok       — otherwise

The thresholds are tunable knobs in DecisionConfig; defaults are conservative.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class DecisionConfig:
    window_days: int = 20
    iterate_excess_pp: float = -3.0     # excess in percentage points
    iterate_hit_rate: float = 0.40
    watch_excess_pp: float = -1.0
    watch_drawdown: float = 0.08
    min_days_for_iterate: int = 20      # don't fire "iterate" off thin data


@dataclass
class DecisionReport:
    n_days: int
    trailing_return: float          # portfolio cum over window
    trailing_benchmark: float       # benchmark (SPY) cum over window
    trailing_excess: float          # portfolio - benchmark, in raw return units
    hit_rate: float                 # fraction of days portfolio beats benchmark
    worst_day: float                # most-negative day return
    current_drawdown: float
    verdict: str                    # ok | watch | iterate
    reason: str                     # one-line human-readable rationale


def _to_float(s, default: float = 0.0) -> float:
    try:
        return float(s) if s not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _trailing(rows: list[dict], n: int) -> list[dict]:
    return rows[-n:] if len(rows) >= n else rows[:]


def _compound(rets: Iterable[float]) -> float:
    acc = 1.0
    for r in rets:
        acc *= (1.0 + r)
    return acc - 1.0


def evaluate(daily_log_rows: list[dict],
             config: DecisionConfig = DecisionConfig()) -> DecisionReport:
    """Read daily_log.tsv (already-parsed dicts) and produce a verdict.

    daily_log fields used: date, day_return, drawdown, benchmark_cum_return.
    Benchmark daily returns are reconstructed by differencing successive
    cum_return values — no extra data fetch."""
    rows = list(daily_log_rows)
    if not rows:
        return DecisionReport(
            n_days=0, trailing_return=0.0, trailing_benchmark=0.0,
            trailing_excess=0.0, hit_rate=0.0, worst_day=0.0,
            current_drawdown=0.0, verdict="ok",
            reason="no track record yet — run the loop for a few days first",
        )

    window = _trailing(rows, config.window_days)
    n_days = len(window)

    port_rets = [_to_float(r.get("day_return")) for r in window]
    # benchmark daily returns from cum_return deltas (handles missing rows).
    bench_cum = [_to_float(r.get("benchmark_cum_return")) for r in window]
    bench_rets: list[float] = []
    # need the bench_cum one row BEFORE the window to anchor the first delta
    pre = rows[-(n_days + 1):-n_days]
    prior_cum = _to_float(pre[0].get("benchmark_cum_return")) if pre else 0.0
    for cum in bench_cum:
        prev = 1.0 + prior_cum
        cur = 1.0 + cum
        bench_rets.append((cur / prev - 1.0) if prev > 0 else 0.0)
        prior_cum = cum

    trailing_return = _compound(port_rets)
    trailing_bench = _compound(bench_rets)
    trailing_excess = trailing_return - trailing_bench

    paired = list(zip(port_rets, bench_rets))
    hit_rate = (sum(1 for p, b in paired if p > b) / len(paired)) if paired else 0.0
    worst_day = min(port_rets) if port_rets else 0.0
    current_dd = _to_float(window[-1].get("drawdown"))

    # ---- verdict ----------------------------------------------------------
    excess_pp = trailing_excess * 100.0
    if (excess_pp <= config.iterate_excess_pp
            and hit_rate < config.iterate_hit_rate
            and n_days >= config.min_days_for_iterate):
        verdict = "iterate"
        reason = (f"trailing {n_days}d excess {excess_pp:+.1f}pp with "
                  f"{hit_rate * 100:.0f}% hit rate — strategy is being outpaced; "
                  f"consider switching")
    elif excess_pp <= config.watch_excess_pp or current_dd >= config.watch_drawdown:
        verdict = "watch"
        bits = []
        if excess_pp <= config.watch_excess_pp:
            bits.append(f"trailing {n_days}d {excess_pp:+.1f}pp vs SPY")
        if current_dd >= config.watch_drawdown:
            bits.append(f"drawdown -{current_dd * 100:.1f}%")
        reason = f"watching: {'; '.join(bits)}"
    else:
        verdict = "ok"
        reason = (f"on track — {n_days}d excess {excess_pp:+.1f}pp, "
                  f"hit rate {hit_rate * 100:.0f}%, dd -{current_dd * 100:.1f}%")

    return DecisionReport(
        n_days=n_days, trailing_return=trailing_return,
        trailing_benchmark=trailing_bench, trailing_excess=trailing_excess,
        hit_rate=hit_rate, worst_day=worst_day,
        current_drawdown=current_dd, verdict=verdict, reason=reason,
    )
