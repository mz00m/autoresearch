# fund.md — Investment Policy Statement (the constitution)

This is the human-edited "org code" for an autonomous, agent-run investment
process. It is the policy layer; agents are bound by it. It is the investing
analog of `program.md` in autoresearch — **you (the human) iterate on this file;
the agents iterate on strategy code.**

The deterministic guarantees in this document are enforced in code that agents
**must not modify**: `risk_engine.py` (the one rule) and `evaluator.py` (the
overfitting-resistant scorer). Those are this project's sacred `prepare.py`.

---

## 1. Mission

Grow a personal account of **~$25,000** on a **risk-adjusted, after-cost,
after-tax** basis, measured against a benchmark — **not** "maximize returns" in
the abstract. The edge we are buying is **process, not prophecy**: tireless
research, total discipline, perfect record-keeping, and hard risk limits — the
advantage of being a systematic investor rather than a gut-trader. No agent has
a predictive edge on prices; assume none.

**Benchmark:** SPY total return (swap for 60/40 if the mandate turns
conservative). We judge ourselves on risk-adjusted excess vs. this.

## 2. The one rule (hard, non-negotiable)

> **You can lose up to 100% of the capital, but never more than 100%.**
> No position may have a worst-case loss greater than the equity backing it,
> and the account may never go below zero. You will never owe money.

This is enforced deterministically in `risk_engine.py`, deny-by-default. It is
not a guideline the agents might forget — it is a gate every order clears first.

**Honest caveat:** bounded liability guarantees you can't lose *more* than the
principal; it does **not** promise you won't lose a lot of it. A concentrated
bad month can still take a real bite. The agents' job is to make that rare.

## 3. Allowed instruments (the whitelist)

Only bounded-liability shapes. Anything not listed is forbidden by default:

| Allowed (max loss <= cash committed) | Forbidden (loss can exceed capital) |
| --- | --- |
| Long equities & ETFs | Margin borrowing / leveraged long |
| Long calls / long puts | Short selling stock |
| Debit (defined-risk) option spreads | Naked / uncovered options |
| Covered calls | Futures |
| Cash-secured puts | Anything with unbounded downside |

## 4. Phased roadmap

Two independent axes — capital-at-risk and enforcement — composed:

| Phase | Capital | Account | Guarantee | Goal |
| --- | --- | --- | --- | --- |
| 0  | none          | —       | —          | Build harness; strategies survive walk-forward + OOS vault |
| 1a | paper         | cash    | n/a        | Live behavior matches backtest; loop runs unattended overnight |
| 1b | small ($1-2k) | cash    | structural | Human approves every trade; validate real costs/execution/taxes |
| 1c | full ($25k)   | cash    | structural | Run the mandate; accumulate the graduation track record |
| 2  | full ($25k)   | margin  | software   | Graduate per §5; gain efficiency, **same rule** |

Margin (Phase 2) is for **operational efficiency only** (recycling unsettled
proceeds, capital-efficient defined-risk spreads). It is **never** uncovered
leverage. The `max_loss <= equity` rule is unchanged; only the guarantee shifts
from account-type-structural to software-enforced — which is why §5 must first
prove the software.

## 5. Graduation gate: cash -> margin (pre-registered, do not move goalposts)

Measured from the **live cash-account** track record, not the backtest:

1. **Live-vs-backtest fidelity** — realized risk-adjusted return within a sane
   band of backtested. *The single most important check.* If live badly trails
   backtest, the scorer is being gamed; do not graduate.
2. **Zero risk-rule breaches** — the risk engine never let a forbidden position
   through; no hard-constraint was overridden by hand.
3. **Operational reliability** — well-formed tickets, live slippage within the
   modeled budget, complete journaling/post-mortems, no data error reached a trade.
4. **Real edge after real costs** — positive risk-adjusted, net of IBKR
   frictions and taxes — not merely "didn't blow up."
5. **Enough sample, across conditions** — a minimum trade count *and* enough
   calendar time to span more than one market mood, ideally including a
   drawdown episode handled cleanly.

> Set concrete thresholds here before Phase 1 begins, e.g.:
> realized Sortino >= 0.7 x backtested; 0 breaches; >= 60 live trades;
> >= 6 calendar months; >= 1 drawdown of >= 8% survived within the rules.

## 6. Risk limits (tunable; enforced in `risk_engine.py` / `evaluator.py`)

- **Position worst-case loss:** sum over the book must never exceed equity (§2).
- **Single-position cap:** no one position's max loss > **15%** of equity.
- **Drawdown circuit-breaker:** optional kill-switch (`drawdown_halt_frac`).
  Default off (mandate permits down to -100%), but recommended set to e.g. 0.35
  during early phases.
- **Turnover budget:** keep annualized turnover within the evaluator's cap;
  costs and taxes dominate at this account size.

## 7. Autonomy model

- **Research is autonomous and quarantined.** The overnight factory may run
  forever; it only ever produces *candidates* and touches **no orders**.
- **Execution is human-gated.** Every live trade is a ticket with rationale +
  risk-engine verdict that **you approve** before it fires. (Phase 1-2.)
- A kill-switch (deterministic, outside the LLM) can halt all new risk.

## 8. The overfitting doctrine (the #1 risk)

The overnight loop's throughput is also its danger: 100 attempts at fitting
noise *will* find spurious winners. Defenses, all in `evaluator.py`:

1. **OOS vault** the agents never see; scored once.
2. **Walk-forward** across rolling regimes.
3. **Deflated Sharpe** that knows how many hypotheses were tried.
4. **Simplicity as a hard tiebreaker** — complex must clear a much higher bar,
   because simpler == fewer parameters == less overfit.

A candidate that fails any §6 hard constraint is logged `crash`/`discard`
regardless of how good its return looks.
