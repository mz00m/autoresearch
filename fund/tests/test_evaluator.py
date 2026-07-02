"""Smoke tests for the evaluator. Run: python3 fund/tests/test_evaluator.py"""

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluator import (  # noqa: E402
    Constraints,
    deflated_sharpe_ratio,
    evaluate,
    max_drawdown,
    oos_vault_split,
    sortino_annualized,
    walk_forward_splits,
)


def test_oos_vault_split_hides_tail():
    ins, oos = oos_vault_split(100, oos_frac=0.3)
    assert list(ins)[-1] == 69 and list(oos)[0] == 70 and list(oos)[-1] == 99


def test_walk_forward_expands():
    splits = list(walk_forward_splits(200, n_splits=5, min_train=50))
    assert len(splits) >= 1
    # train window is anchored at 0 and grows
    assert all(tr.start == 0 for tr, _ in splits)
    assert splits[0][0].stop <= splits[-1][0].stop


def test_max_drawdown_basic():
    # +10% then -50% => peak 1.1, trough 0.55 => dd ~ 0.5
    assert abs(max_drawdown([0.10, -0.50]) - 0.5) < 1e-9


def test_deflation_penalizes_many_trials():
    random.seed(0)
    # a modestly good-looking OOS series
    rets = [random.gauss(0.0008, 0.01) for _ in range(252)]
    few = deflated_sharpe_ratio(rets, trial_sharpes=[0.05, 0.06])
    many = deflated_sharpe_ratio(
        rets, trial_sharpes=[random.gauss(0.04, 0.05) for _ in range(200)]
    )
    # the SAME returns look far less convincing when cherry-picked from 200 trials
    assert many < few


def test_evaluate_rejects_overfit_winner():
    random.seed(1)
    rets = [random.gauss(0.0005, 0.01) for _ in range(252)]
    score = evaluate(
        rets,
        trial_sharpes=[random.gauss(0.05, 0.06) for _ in range(300)],
        turnover=4.0,
        n_trades=120,
        constraints=Constraints(),
    )
    # plausible noise dressed up as a winner should not pass the deflated bar
    assert not score.passed
    assert any("overfit" in r or "deflated" in r for r in score.reasons)


def test_evaluate_rejects_thin_sample():
    score = evaluate([0.01, 0.02, -0.01], trial_sharpes=[0.1],
                     turnover=1.0, n_trades=3)
    assert not score.passed


def test_sortino_downside_only():
    # all-positive returns => no downside => sortino returns 0.0 by convention
    assert sortino_annualized([0.01, 0.02, 0.03]) == 0.0


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
    print(f"\n{len(fns)}/{len(fns)} tests passed")


if __name__ == "__main__":
    _run_all()
