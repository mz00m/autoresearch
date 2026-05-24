# program.md — the autonomous research loop (overnight factory)

This is the operational loop the agent org runs, modeled directly on
autoresearch's experiment loop. **Read `fund.md` first** — it is binding.

The key reframing of autoresearch for finance:
- Markets are closed ~17.5h/weekday plus weekends. **The research factory runs
  precisely when you can't trade anyway** — free compounding of research.
- The metric (`evaluator.py`) and the one rule (`risk_engine.py`) live in code
  you **cannot modify**. You optimize the score; you never touch the scorer.
- Research is **quarantined**: it produces *candidates only* and touches **no
  orders**. Live execution is human-gated (see `agents/execution.md`).

## Setup (once)

1. Read `fund.md`, `risk_engine.py`, `evaluator.py`, `ledger.py`, and the
   `agents/` role files.
2. Confirm the data pipeline is point-in-time correct (no look-ahead /
   survivorship bias). If data is missing, stop and tell the human.
3. Confirm `research_ledger.tsv` exists (run `python3 ledger.py`).

## The fixed backtest protocol (the "comparable experiments" rule)

Every hypothesis is evaluated identically so results are comparable, and tuned
to **your** real account (IBKR frictions, your tax lots) — autoresearch's "best
model for your platform," ported:

- Same universe, same history window, same cost/slippage model.
- Strategy code sees **only in-sample** data (`evaluator.oos_vault_split`).
- Score on the **locked OOS** slice via `evaluator.evaluate(...)`, passing the
  **count and Sharpes of every hypothesis tried this session** so the deflated
  Sharpe can correct for multiple testing.
- Prefer the **simpler** strategy on ties (fewer parameters == less overfit).

## LOOP FOREVER (research only — never places orders)

1. Note git state (branch/commit).
2. Form one hypothesis. Implement it as a single, reviewable strategy spec.
3. `git commit` the spec.
4. Backtest in-sample; walk-forward (`evaluator.walk_forward_splits`).
5. Score on the locked OOS slice (`evaluator.evaluate`).
6. Log to `research_ledger.tsv` via `ledger.append(...)`:
   - **keep** if it clears every hard constraint AND deflated Sharpe >= bar AND
     beats the current best objective -> advance the branch.
   - **discard** if equal/worse or fails a constraint -> `git reset` back.
   - **crash** if it errors or is fundamentally broken -> record and move on.
7. Repeat. If stuck, think harder: read the references, combine near-misses,
   try more robust (not more complex) ideas. **Do not** loosen the scorer.

## What you may NOT do

- Modify `risk_engine.py` or `evaluator.py` (the sacred core).
- Show the OOS vault to strategy code, or peek at it to tune.
- Place, route, or approve any live order. Research proposes; humans dispose.
- "Improve" a result by widening constraints or re-running the OOS slice until
  it passes — that is overfitting, and it loses real money.

## Handoff to the trading day

Each morning, emit a ranked shortlist of kept candidates. For any the human
wants live, the execution agent builds a trade ticket, runs it through
`risk_engine.check(...)`, and presents it for **human approval** before firing.
Post-trade, the post-mortem agent journals it and feeds learnings back here.
