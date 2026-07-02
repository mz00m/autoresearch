"""Decision signal — verdict thresholds, math, edge cases."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fund.decision import DecisionConfig, evaluate


def _row(day_ret: float, bench_cum: float, drawdown: float = 0.0,
         dt: str = "2024-01-01") -> dict:
    return {"date": dt, "day_return": str(day_ret),
            "benchmark_cum_return": str(bench_cum),
            "drawdown": str(drawdown)}


def _flat_log(n: int, day_port: float, bench_daily: float) -> list[dict]:
    rows = []
    bench_cum = 0.0
    for i in range(n):
        bench_cum = (1 + bench_cum) * (1 + bench_daily) - 1
        rows.append(_row(day_port, bench_cum, dt=f"2024-01-{i+1:02d}"))
    return rows


def test_empty_log_returns_ok_with_zero_days():
    r = evaluate([])
    assert r.n_days == 0
    assert r.verdict == "ok"


def test_matching_returns_yield_zero_excess():
    rows = _flat_log(25, 0.001, 0.001)
    r = evaluate(rows)
    assert abs(r.trailing_excess) < 1e-4


def test_strong_outperformance_is_ok():
    rows = _flat_log(25, 0.003, 0.001)
    r = evaluate(rows)
    assert r.verdict == "ok"
    assert r.trailing_excess > 0


def test_underperformance_triggers_watch():
    # -10bps/day for the 20-day window -> ~-2pp excess, hit rate 0
    # Between watch (-1pp) and iterate (-3pp).
    rows = _flat_log(20, -0.001, 0.0)
    r = evaluate(rows)
    assert r.verdict == "watch", f"expected watch, got {r.verdict}: {r.reason}"


def test_severe_underperformance_triggers_iterate():
    # -2bps/day vs +5bps/day for 25 days -> ~-1.75pp excess, low hit rate
    rows = _flat_log(25, -0.002, 0.0005)
    r = evaluate(rows, DecisionConfig(iterate_excess_pp=-1.0,
                                      iterate_hit_rate=0.5,
                                      min_days_for_iterate=20))
    assert r.verdict == "iterate"


def test_iterate_requires_minimum_days():
    rows = _flat_log(5, -0.05, 0.001)
    r = evaluate(rows, DecisionConfig(min_days_for_iterate=20))
    assert r.verdict != "iterate"  # thin data


def test_high_drawdown_alone_triggers_watch():
    rows = _flat_log(25, 0.001, 0.001)
    rows[-1]["drawdown"] = "0.12"  # 12% current dd
    r = evaluate(rows)
    assert r.verdict == "watch"
    assert "drawdown" in r.reason


def test_hit_rate_counts_days_above_benchmark():
    rows = []
    bench_cum = 0.0
    daily_bench = 0.001
    for i in range(20):
        port_ret = 0.002 if i < 12 else -0.001
        bench_cum = (1 + bench_cum) * (1 + daily_bench) - 1
        rows.append(_row(port_ret, bench_cum, dt=f"2024-01-{i+1:02d}"))
    r = evaluate(rows)
    assert abs(r.hit_rate - 12 / 20) < 1e-6


def test_worst_day_reflects_min_return():
    rows = _flat_log(20, 0.0, 0.0)
    rows[5]["day_return"] = "-0.04"
    r = evaluate(rows)
    assert abs(r.worst_day + 0.04) < 1e-6


def test_window_caps_to_available_rows():
    rows = _flat_log(8, 0.001, 0.0005)
    r = evaluate(rows, DecisionConfig(window_days=20))
    assert r.n_days == 8


if __name__ == "__main__":
    tests = [(n, fn) for n, fn in globals().items()
             if n.startswith("test_") and callable(fn)]
    passed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL {name}: {e}")
        except Exception as e:
            print(f"  FAIL {name}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
    sys.exit(0 if passed == len(tests) else 1)
