"""coach.synthesize — verdict + drift + tax + wash → one recommendation."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fund.coach import synthesize


def _call(**overrides):
    defaults = dict(
        decision_verdict="ok", decision_excess_pp=0.0,
        drift_verdict="in_band", drift_reason="ok",
        tax_net_total=0.0, tax_net_long_term=0.0,
        wash_warnings=0, has_pending_tickets=False,
        active_strategy="top_n_momentum", current_drawdown=0.0,
    )
    defaults.update(overrides)
    return synthesize(**defaults)


def test_urgent_when_wash_and_pending():
    r = _call(has_pending_tickets=True, wash_warnings=2)
    assert r.severity == "urgent"
    assert "Wash-sale" in r.headline


def test_urgent_when_iterate_and_drifted():
    r = _call(decision_verdict="iterate", drift_verdict="drifted",
              decision_excess_pp=-3.5)
    assert r.severity == "urgent"
    assert "failing" in r.headline.lower()


def test_action_when_drifted_alone():
    r = _call(drift_verdict="drifted", drift_reason="live mean off")
    assert r.severity == "action"
    assert "diverges" in r.headline.lower()


def test_action_when_iterate_alone():
    r = _call(decision_verdict="iterate", decision_excess_pp=-4.0)
    assert r.severity == "action"
    assert "outpaced" in r.headline.lower()


def test_watch_when_harvestable_losses():
    r = _call(tax_net_total=-500, tax_net_long_term=-300)
    assert r.severity == "watch"
    assert "harvestable" in r.headline.lower()


def test_watch_when_drawdown_above_10pct():
    r = _call(current_drawdown=0.12)
    assert r.severity == "watch"
    assert "Drawdown" in r.headline


def test_watch_when_decision_says_watch():
    r = _call(decision_verdict="watch", decision_excess_pp=-1.5)
    assert r.severity == "watch"


def test_informational_when_pending_tickets_ready():
    r = _call(has_pending_tickets=True)
    assert r.severity == "informational"
    assert "Pending" in r.headline


def test_informational_when_all_clear():
    r = _call()
    assert r.severity == "informational"
    assert "Nothing" in r.headline


def test_next_action_always_present():
    for cases in [
        {},
        {"has_pending_tickets": True, "wash_warnings": 1},
        {"decision_verdict": "iterate", "drift_verdict": "drifted"},
        {"tax_net_total": -1000, "tax_net_long_term": -500},
        {"current_drawdown": 0.15},
    ]:
        r = _call(**cases)
        assert r.next_action, f"empty next_action for {cases}"


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
