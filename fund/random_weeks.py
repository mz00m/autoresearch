"""random_weeks.py — does each strategy work in random samples, not just chosen windows?

The honest_test runs each strategy through full calendar years, which is fair
but still cherry-picks the start-of-year boundary. This module is harder:
N random Monday dates over the last 10 years, each followed by a 4-week
holding period. If a strategy only works when started on Jan 1 it'll fail
here; if its edge is genuine it'll show up across the distribution.

For each (strategy, week) pair we record the 4-week return + max DD, then
aggregate: mean, median, std, win-rate vs SPY, % positive weeks. Random
seed is configurable so runs are reproducible.

Run:
  python3 -m fund.random_weeks                       # 30 samples, last 10 years
  python3 -m fund.random_weeks --samples 60 --weeks 4
  python3 -m fund.random_weeks --seed 42 --html /tmp/r.html
"""

from __future__ import annotations

import argparse
import html as _html
import os
import random
import statistics
import sys
import tempfile
from datetime import date, datetime, timedelta

from fund.portfolio import Portfolio
from fund.simulate import simulate

STRATEGIES: list[tuple[str, dict]] = [
    ("sixty_forty", {}),
    ("dual_momentum", {"lookback_days": 252}),
    ("risk_parity", {"vol_window": 63}),
    ("top_n_momentum", {"n": 2, "lookback_days": 126}),
    ("ma_crossover", {"fast": 50, "slow": 200}),
    ("adaptive", {"lookback_days": 90}),
]


def _max_dd(history) -> float:
    if not history:
        return 0.0
    peak = history[0].equity
    mdd = 0.0
    for h in history:
        peak = max(peak, h.equity)
        if peak > 0:
            mdd = max(mdd, (peak - h.equity) / peak)
    return mdd


def _trading_days_back(end: date, n_days: int) -> date:
    """Approximate: 5 trading days per 7 calendar days."""
    return end - timedelta(days=int(n_days * 7 / 5))


def _sample_dates(n: int, lookback_years: int, weeks_held: int,
                  rng: random.Random) -> list[date]:
    """Pick N random Mondays within [today - lookback_years, today - weeks_held]."""
    today = date.today()
    earliest = today - timedelta(days=lookback_years * 365)
    latest = today - timedelta(days=weeks_held * 7 + 7)
    days_range = (latest - earliest).days
    out: list[date] = []
    seen: set[date] = set()
    while len(out) < n:
        offset = rng.randint(0, days_range)
        d = earliest + timedelta(days=offset)
        # Roll to Monday
        d += timedelta(days=(0 - d.weekday()) % 7)
        if d not in seen and earliest <= d <= latest:
            seen.add(d)
            out.append(d)
    out.sort()
    return out


def _run_one(name: str, params: dict, start: date, weeks: int,
             source: str = "auto") -> dict | None:
    """Run a `weeks * 5` trading day sim ending `start + weeks*7 - 1` calendar days
    later. Returns cum_return, max_dd, ending_equity, or None on failure."""
    end = start + timedelta(days=weeks * 7 - 1)
    # roll end back to a weekday
    while end.weekday() >= 5:
        end -= timedelta(days=1)
    days = weeks * 5
    state = tempfile.mktemp(suffix=".json")
    log = tempfile.mktemp(suffix=".tsv")
    try:
        pf, _ = simulate(days=days, end=end, principal=25_000.0,
                         strategy=name, strategy_params=params,
                         source=source, state_path=state, log_path=log,
                         quiet=True)
        if len(pf.history) < 2:
            return None
        cum = pf.history[-1].equity / pf.history[0].equity - 1.0
        return {"cum": cum, "max_dd": _max_dd(pf.history),
                "ending": pf.history[-1].equity}
    except Exception as e:
        return {"error": str(e)}
    finally:
        for p in (state, log):
            if os.path.exists(p):
                os.unlink(p)


def _spy_window_return(start: date, end: date, source: str = "auto") -> float | None:
    from fund.data.loader import load_panel
    panel, _ = load_panel(["SPY"], date(2005, 1, 1), end, source=source)
    spy = panel.series.get("SPY")
    if spy is None:
        return None
    start_slice = spy.as_of(start - timedelta(days=7))
    end_slice = spy.as_of(end)
    if not start_slice.closes or not end_slice.closes:
        return None
    return end_slice.closes[-1] / start_slice.closes[-1] - 1.0


def evaluate(samples: int, weeks: int, *,
             lookback_years: int = 10, seed: int = 11,
             strategies: list[tuple[str, dict]] = STRATEGIES,
             source: str = "auto") -> dict:
    rng = random.Random(seed)
    starts = _sample_dates(samples, lookback_years, weeks, rng)
    print(f"\nrandom-week test  ({samples} samples × {weeks} weeks each)")
    print(f"sampled from {starts[0]} -> {starts[-1]}")
    results: dict[str, list[dict]] = {n: [] for n, _ in strategies}
    spy_rets: list[float] = []
    for i, start in enumerate(starts, 1):
        end = start + timedelta(days=weeks * 7 - 1)
        spy = _spy_window_return(start, end, source=source)
        if spy is None:
            print(f"  [{i:>2}/{samples}] {start}: SPY data missing, skip")
            continue
        spy_rets.append(spy)
        row = [f"  [{i:>2}/{samples}] {start}  SPY {spy * 100:+5.2f}%  "]
        for name, params in strategies:
            r = _run_one(name, params, start, weeks, source=source)
            if r and "cum" in r:
                results[name].append({"start": start.isoformat(),
                                      "cum": r["cum"], "max_dd": r["max_dd"],
                                      "spy": spy, "excess": r["cum"] - spy})
                row.append(f"{name[:8]:<8}{r['cum'] * 100:+5.1f}%")
        print(" ".join(row))
    return {"results": results, "spy_returns": spy_rets,
            "starts": [s.isoformat() for s in starts],
            "samples": samples, "weeks": weeks}


def summarize(report: dict) -> dict:
    """Compute per-strategy aggregates."""
    out: dict = {}
    for name, rows in report["results"].items():
        if not rows:
            out[name] = {"n": 0}
            continue
        cums = [r["cum"] for r in rows]
        excs = [r["excess"] for r in rows]
        dds = [r["max_dd"] for r in rows]
        wins_vs_spy = sum(1 for e in excs if e > 0)
        positives = sum(1 for c in cums if c > 0)
        out[name] = {
            "n": len(rows),
            "mean_cum": statistics.mean(cums),
            "median_cum": statistics.median(cums),
            "stdev_cum": statistics.stdev(cums) if len(cums) > 1 else 0.0,
            "mean_excess": statistics.mean(excs),
            "win_rate_vs_spy": wins_vs_spy / len(rows),
            "positive_rate": positives / len(rows),
            "mean_max_dd": statistics.mean(dds),
            "worst_window": min(cums),
            "best_window": max(cums),
        }
    return out


def print_summary(agg: dict) -> None:
    print("\n" + "=" * 92)
    print("AGGREGATE — random-week distributions")
    print("=" * 92)
    print(f"  {'strategy':<20} {'n':>4} {'mean':>8} {'median':>8} {'stdev':>8} "
          f"{'excess':>9} {'>SPY':>7} {'positive':>10} {'avg DD':>9}")
    rows = sorted(agg.items(),
                  key=lambda kv: kv[1].get("mean_excess", -999), reverse=True)
    for name, s in rows:
        if s.get("n", 0) == 0:
            print(f"  {name:<20} (no successful runs)")
            continue
        print(f"  {name:<20} {s['n']:>4} "
              f"{s['mean_cum'] * 100:>+7.2f}% "
              f"{s['median_cum'] * 100:>+7.2f}% "
              f"{s['stdev_cum'] * 100:>+7.2f}% "
              f"{s['mean_excess'] * 100:>+8.2f}pp "
              f"{s['win_rate_vs_spy'] * 100:>6.0f}% "
              f"{s['positive_rate'] * 100:>9.0f}% "
              f"{-s['mean_max_dd'] * 100:>+8.2f}%")


def render_html(report: dict, agg: dict, principal: float = 25_000.0) -> str:
    rows = []
    for name, s in sorted(agg.items(),
                          key=lambda kv: kv[1].get("mean_excess", -999),
                          reverse=True):
        if s.get("n", 0) == 0:
            continue
        rows.append(
            f'<tr><td><strong>{_html.escape(name)}</strong></td>'
            f'<td class="num">{s["n"]}</td>'
            f'<td class="num">{s["mean_cum"] * 100:+.2f}%</td>'
            f'<td class="num">{s["median_cum"] * 100:+.2f}%</td>'
            f'<td class="num">{s["stdev_cum"] * 100:+.2f}%</td>'
            f'<td class="num">{s["mean_excess"] * 100:+.2f}pp</td>'
            f'<td class="num">{s["win_rate_vs_spy"] * 100:.0f}%</td>'
            f'<td class="num">{s["positive_rate"] * 100:.0f}%</td>'
            f'<td class="num">-{s["mean_max_dd"] * 100:.2f}%</td>'
            f'<td class="num">{s["best_window"] * 100:+.2f}%</td>'
            f'<td class="num">{s["worst_window"] * 100:+.2f}%</td>'
            f'</tr>'
        )
    body = (
        '<table><thead><tr><th>Strategy</th>'
        '<th class="num">N</th><th class="num">Mean</th><th class="num">Median</th>'
        '<th class="num">Stdev</th><th class="num">Excess vs SPY</th>'
        '<th class="num">Beats SPY</th><th class="num">Positive</th>'
        '<th class="num">Avg DD</th><th class="num">Best</th><th class="num">Worst</th>'
        '</tr></thead><tbody>' + "".join(rows) + '</tbody></table>'
    )
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Random-week test</title>
<style>body{{font-family:Iowan Old Style,Charter,Georgia,serif;background:#fbfaf6;color:#0f1115;max-width:1080px;margin:0 auto;padding:48px 32px;line-height:1.55}}
h1{{font-size:28px;font-weight:600;letter-spacing:-0.012em;margin:0 0 8px}}
.eyebrow{{font-size:10px;letter-spacing:0.14em;text-transform:uppercase;color:#6b6f76;font-family:-apple-system,sans-serif}}
table{{width:100%;border-collapse:collapse;font-size:13px;font-family:-apple-system,sans-serif;margin-top:24px}}
th{{text-align:left;padding:8px 10px;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#6b6f76;border-bottom:1px solid #1a1a1a;font-weight:500}}
td{{padding:8px 10px;border-bottom:1px solid #ececec;font-variant-numeric:tabular-nums}}
.num{{text-align:right}}
.muted{{color:#6b6f76;font-family:-apple-system,sans-serif;font-size:13px;margin-top:8px}}
</style></head><body>
<div class="eyebrow">Robustness test</div>
<h1>Random-week distribution — {report["samples"]} samples × {report["weeks"]} weeks</h1>
<div class="muted">If a strategy only works in cherry-picked windows it'll fail here.
Real edge survives random sampling.</div>
{body}
</body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Random-week robustness test.")
    ap.add_argument("--samples", type=int, default=30)
    ap.add_argument("--weeks", type=int, default=4)
    ap.add_argument("--lookback-years", type=int, default=10)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--source", default="auto")
    ap.add_argument("--html", default="")
    args = ap.parse_args()
    report = evaluate(args.samples, args.weeks,
                      lookback_years=args.lookback_years, seed=args.seed,
                      source=args.source)
    agg = summarize(report)
    print_summary(agg)
    if args.html:
        with open(args.html, "w") as f:
            f.write(render_html(report, agg))
        print(f"\nhtml: {args.html}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
