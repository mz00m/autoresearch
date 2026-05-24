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

## Run it on your Mac (real data, no dependencies)

The entire `fund/` framework is **pure Python stdlib** — no numpy, no torch,
nothing to `pip install`. (That's separate from the parent autoresearch ML repo,
which does need uv + a GPU.) From the repo root:

```bash
# 1. Python 3.11+ (3.9+ works). On macOS: brew install python@3.11
python3 --version

# 2. Get the branch
git checkout claude/ai-investment-agents-JDN5B && git pull

# 3. Tests (25) — the safety core, the scorer, the look-ahead guard
python3 fund/tests/test_risk_engine.py
python3 fund/tests/test_evaluator.py
python3 fund/tests/test_pit.py

# 4. The full research loop on REAL ETF data (needs open network)
export FUND_CONTACT_EMAIL="you@example.com"   # SEC EDGAR wants a real contact
python3 -m fund.run_research --source real    # fetches Stooq + FRED, caches locally

#    (offline / deterministic instead:)
python3 -m fund.run_research --source synthetic
```

`--source real` writes real entries to `research_ledger.tsv` and tells you
whether dual-momentum survives the OOS deflated-Sharpe bar on actual history.
Honest prior: a single naive momentum rule likely won't clear 0.95 — that's the
system being right, not broken. Fetched data is cached under `fund/data/cache/`
(gitignored) so reruns are reproducible.

## What's built vs. next

**Built:** the un-modifiable spine (risk engine, scorer, ledger, `fund.md`,
`program.md`, agent roles) **and** the point-in-time data pipeline (Stooq + FRED +
SEC EDGAR with synthetic fallback), the dual-momentum strategy, the fixed
backtest protocol, and the end-to-end research loop. 25 tests, stdlib-only.

**Next:** an IBKR paper-trading adapter + the human-approval ticket flow
(Phase 1a), more strategy families to give the deflated-Sharpe correction real
breadth, and an append-only journal/memory for the post-mortem agent.
