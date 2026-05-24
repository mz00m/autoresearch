# fund — an autonomous, agent-run investment process

A private investment "team of agents" that manages ~$25k under one hard rule:
**you can lose up to 100% of the capital, but never more than 100%** — you will
never owe money. Built on the autoresearch pattern: program the *org* in
markdown, let agents iterate on *strategy code*, and keep the *scorer and risk
rule* in code that agents cannot modify.

> Not a money printer. No agent has a predictive edge on prices. The edge is
> **process**: tireless research, hard risk limits, total discipline, and a
> perfect audit trail. See `fund.md` for the honest framing.

## How it maps to autoresearch

| autoresearch | here | who edits |
| --- | --- | --- |
| `prepare.py` (read-only metric) | `risk_engine.py` + `evaluator.py` (the one rule + overfitting-proof scorer) | **nobody** (sacred) |
| `train.py` (iterated) | strategy specs (to be added by the quant agent) | agents |
| `program.md` (the org) | `fund.md` (policy) + `program.md` (loop) + `agents/*.md` | **human** |
| `results.tsv` (keep/discard) | `research_ledger.tsv` via `ledger.py` | agents (append-only) |
| 5-min run, `val_bpb` | fixed backtest protocol, OOS deflated Sortino | the loop |

The crucial adaptation: autoresearch's fast hypothesis search is, in markets, a
**machine for manufacturing overfit strategies**. So the scorer is hardened with
an OOS vault, walk-forward, and a deflated Sharpe that knows how many hypotheses
were tried. Simplicity is a hard tiebreaker. See `fund.md` §8.

## The sacred core (do not modify)

- **`risk_engine.py`** — deny-by-default. Enforces the one rule: no position's
  worst-case loss may exceed the equity behind it; the account can't go negative.
  Whitelists only bounded-liability instruments (long stock/ETF, long options,
  debit spreads, covered calls, cash-secured puts).
- **`evaluator.py`** — the `val_bpb` analog. OOS vault, walk-forward, deflated
  Sharpe, downside-focused (Sortino) objective, hard constraints first.

## The agent team (`agents/`)

`pm` (orchestrator) · `quant` (signals / the `train.py` editor) · `risk_manager`
(veto, owns the engine) · `red_team` (overfitting & thesis killer) · `execution`
(human-gated tickets) · `post_mortem` (attribution + memory). Minimum viable
team: pm + quant + risk_manager + execution + post_mortem.

## Phased rollout (`fund.md` §4-5)

backtest -> paper -> small real (cash) -> full $25k (cash) -> **graduate** ->
margin. Margin is for efficiency, never uncovered leverage; the one rule never
changes. The cash->margin graduation gate is pre-registered in `fund.md` §5.

## Run the tests

```bash
python3 fund/tests/test_risk_engine.py     # 12 tests — the safety core
python3 fund/tests/test_evaluator.py       # 7 tests — the scorer
python3 fund/ledger.py                      # initialize the research ledger
```

## What's built vs. next

**Built (the un-modifiable spine):** the risk engine, the scorer, the ledger,
the policy (`fund.md`), the loop (`program.md`), and the agent roles — all tested
and stdlib-only.

**Next:** point-in-time data pipeline (SEC EDGAR + FRED + a price feed), one
end-to-end strategy spec (e.g. dual-momentum ETF) run through the protocol, an
IBKR paper-trading adapter, and a vector-store journal for the post-mortem agent.
