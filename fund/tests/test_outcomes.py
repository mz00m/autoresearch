"""outcomes — thesis outcome tracking + conviction calibration."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import fund.outcomes as oc


def _tmp_path():
    fd, path = tempfile.mkstemp(suffix=".tsv")
    os.close(fd)
    os.unlink(path)
    return path


def _fake_thesis(confidence=4, created="2023-06-01T00:00:00"):
    return {"confidence": confidence, "catalyst": "test catalyst",
            "created_at": created, "status": "active"}


def _patch(monkey_returns, invalidated):
    """Patch thesis lookups + window returns; record invalidate calls."""
    oc.thesis_mod.active_for = lambda sym: monkey_returns.get("thesis")
    oc.thesis_mod.invalidate = lambda sym, reason, on=None: invalidated.append(sym) or True
    oc._window_return = lambda sym, s, e, source="auto": monkey_returns["rets"].get(sym)


def test_close_records_hit_and_invalidates():
    p = _tmp_path()
    invalidated = []
    _patch({"thesis": _fake_thesis(4),
            "rets": {"QQQ": 0.30, "SPY": 0.10}}, invalidated)
    out = oc.close_thesis("QQQ", "played out", on=date(2023, 12, 29), path=p)
    assert out is not None and out.hit
    assert abs(out.excess_return - 0.20) < 1e-9
    assert invalidated == ["QQQ"]
    rows = oc.load_outcomes(p)
    assert len(rows) == 1 and rows[0]["symbol"] == "QQQ"


def test_close_without_thesis_is_noop():
    p = _tmp_path()
    invalidated = []
    _patch({"thesis": None, "rets": {}}, invalidated)
    assert oc.close_thesis("QQQ", "x", on=date(2023, 12, 29), path=p) is None
    assert invalidated == []
    assert oc.load_outcomes(p) == []


def test_miss_recorded():
    p = _tmp_path()
    _patch({"thesis": _fake_thesis(2),
            "rets": {"USO": -0.15, "SPY": 0.05}}, [])
    out = oc.close_thesis("USO", "thesis broke", on=date(2023, 12, 29), path=p)
    assert out is not None and not out.hit
    assert abs(out.excess_return - (-0.20)) < 1e-9


def test_calibration_groups_by_conviction():
    p = _tmp_path()
    for conv, sym, ret in ((5, "AAA", 0.30), (5, "BBB", -0.10), (3, "CCC", 0.02)):
        _patch({"thesis": _fake_thesis(conv),
                "rets": {sym: ret, "SPY": 0.0}}, [])
        oc.close_thesis(sym, "close", on=date(2023, 12, 29), path=p)
    cal = oc.calibration(p)
    assert [c["conviction"] for c in cal] == [5, 3]
    c5 = cal[0]
    assert c5["n"] == 2 and abs(c5["hit_rate"] - 0.5) < 1e-9
    assert abs(c5["avg_excess_return"] - 0.10) < 1e-9


def test_unavailable_returns_flagged_not_crashed():
    p = _tmp_path()
    _patch({"thesis": _fake_thesis(3), "rets": {}}, [])
    out = oc.close_thesis("QQQ", "x", on=date(2023, 12, 29), path=p)
    assert out is not None
    assert "WARN" in out.reason


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
    print(f"\n{len(fns)}/{len(fns)} tests passed")


if __name__ == "__main__":
    _run_all()
