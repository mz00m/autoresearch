# fund — an autonomous, agent-run investment process

A private investment "team of agents" that manages ~$25k under one hard rule:
**you can lose up to 100% of the capital, but never more than 100%** — you will
never owe money. Built on the autoresearch pattern: program the *org* in
markdown, let agents iterate on *strategy code*, and keep the *scorer and risk
rule* in code that agents cannot modify.

> Not a money printer. No agent has a predictive edge on prices. The edge is
> **process**: tireless research, hard risk limits, total discipline, and a
> perfect audit trail. See `fund.md` for the honest framing.

## What you get

Two coupled loops:

1. **Overnight research** (`run_research.py`) — generates candidate strategies,
   scores each on a locked OOS slice with deflated Sharpe, logs every verdict
   to `research_ledger.tsv`.
2. **Daily operations** (`morning.py` + `closeout.py`) — for the strategy
   currently driving the paper account, produce today's trade tickets (every
   BUY clears the risk engine), fill them at the actual close, mark to market,
   append one row to `daily_log.tsv`, regenerate the daily HTML card.

## How it maps to autoresearch

| autoresearch | here | who edits |
| --- | --- | --- |
| `prepare.py` (read-only metric) | `risk_engine.py` + `evaluator.py` | **nobody** (sacred) |
| `train.py` (iterated) | strategy specs in `strategy/` | agents |
| `program.md` (the org) | `fund.md` (policy) + `program.md` (loop) + `agents/*.md` | **human** |
| `results.tsv` (keep/discard) | `research_ledger.tsv` via `ledger.py` | agents (append-only) |
| 5-min run, `val_bpb` | fixed backtest protocol, OOS deflated Sortino | the loop |
| — (new) | `daily_log.tsv` + `daily.html` | the daily ops loop |

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

## Strategy bench (`strategy/`)

| Strategy | Params | Notes |
| --- | --- | --- |
| `sixty_forty` | 0 | Fixed 60% SPY / 40% AGG. The baseline anyone has to beat. |
| `dual_momentum` | 1 (lookback) | Antonacci-style GEM: best of universe, only if it beats T-bills. |
| `risk_parity` | 1 (vol window) | Inverse-volatility weights — bond-heavy by construction. |
| `top_n_momentum` | 2 (n, lookback) | Equal-weight top-N trending assets above the T-bill gate. Variance-reduced cousin of `dual_momentum`. |
| `ma_crossover` | 2 (fast, slow) | Classic 50/200 SMA regime filter. Slow but rarely whipsawed. |

Add a strategy by writing one file in `strategy/` and one line in
`strategy/registry.py`. The active strategy lives in `portfolio_state.json` as
a string, so switching is an explicit human decision (logged in git), not an
LLM whim.

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

# 3. All tests (75) — safety core, scorer, look-ahead guard, ops loop, sources
python3 fund/tests/run_all.py

# 4. The full overnight research loop on REAL ETF data (Yahoo + FRED)
export FUND_CONTACT_EMAIL="you@example.com"   # SEC EDGAR wants a real contact
python3 -m fund.run_research --source real
```

### The daily ops loop

```bash
# Initialize a paper account ($25k, 60/40 to start)
python3 -m fund.portfolio init --principal 25000 --strategy sixty_forty

# MORNING (before market open): generate today's tickets
python3 -m fund.morning --source real
# -> prints the guide; every BUY cleared by risk_engine.check()
# -> pending tickets saved to portfolio_state.json

# CLOSEOUT (after market close): fill pending tickets at today's actual close
python3 -m fund.closeout --source real
# -> marks to market, appends a row to daily_log.tsv

# SIMULATE 30 days on real history to see what the loop produces
python3 -m fund.simulate --days 30 --strategy sixty_forty
# -> writes daily.html — open it: `open fund/daily.html`

# COMPARE all strategies side-by-side on the same window (isolated, doesn't
# touch your live state)
python3 -m fund.compare --days 60
# -> writes comparison.html — see if anything would beat your active strategy
```

### "Are we on the right path?"

Every `daily.html` leads with a one-line verdict, computed from the trailing 20
days of `daily_log.tsv`:

- **on track** — trailing excess > -1pp and drawdown < 8%
- **watch** — trailing excess <= -1pp or drawdown >= 8%
- **iterate** — trailing excess <= -3pp and hit-rate < 40% for >= 20 days

Thresholds are conservative on purpose — the verdict triggers a human review,
not an autonomous switch. Run `fund.compare` whenever the verdict turns yellow
or red to see whether any other bench candidate would have done better in the
same window.

### What the simulator says today

All five strategies, 90 calendar days ending 2025-04-30, real Yahoo data,
$25k paper account, 5bp slippage modeled:

| Strategy | Cum return | Max DD | Ending equity | vs SPY (−7.65%) |
| --- | --- | --- | --- | --- |
| `sixty_forty`    | −1.54%  | −10.93% | $24,614 | +6.1pp  |
| `dual_momentum`  | +18.48% |  −5.57% | $29,619 | +26.1pp |
| `risk_parity`    | +4.76%  |  −6.08% | $26,191 | +12.4pp |
| `top_n_momentum` | +11.83% |  −7.21% | $27,957 | +19.5pp |
| `ma_crossover`   | −9.64%  | −18.60% | $22,589 |  −2.0pp |

`dual_momentum` (winner) ended the window holding GLD — it caught the gold
rally while equities sold off. `ma_crossover` (worst) sat in cash through
the rebound. **This is one window. It does not constitute alpha** — it's
the demo that the daily loop actually picks up signal from real prices and
turns it into trades. The graduation gate in `fund.md` §5 demands much more.

## What's built vs. next

**Built:** the un-modifiable spine (risk engine, scorer, ledger, `fund.md`,
`program.md`, agent roles), the point-in-time data pipeline (Yahoo + FRED + SEC
EDGAR with synthetic fallback), five strategy specs, the fixed backtest
protocol, the overnight research loop, **and** the daily ops loop (portfolio
state, morning trade guide, end-of-day closeout, HTML daily card with verdict,
multi-day simulator, side-by-side strategy comparison). 99 tests + CI on every
push, stdlib-only.

**Next:** IBKR paper-trading adapter for live execution, append-only post-mortem
journal feeding the daily card, drift-from-backtest detector (live Sharpe vs.
backtest band — the §5 graduation signal), more strategy families to widen the
deflated-Sharpe correction.
