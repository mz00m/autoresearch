# fund/ changelog

Reverse-chronological log of meaningful changes. Tests + small refactors omitted.

## 2026-07-02 — selection layer: scorecard + thesis calibration

### Added
- **Candidate scorecard** (`fund/scorecard.py` + `/scorecard` dashboard page):
  one ranked table over the whole universe joining what was scattered across
  five tools — multi-horizon momentum + 200d trend, annualized vol, gap
  fragility (worst 1d/3d), regime tilt by asset class, thesis conviction,
  held weight + unrealized P&L. Composite score is a documented sort
  heuristic (trend ≤55 + regime ±10 + thesis ≤15 − fragility), not an
  oracle. Wired into `cache_for_ui` so the dashboard picks it up.
- **Thesis outcome tracking** (`fund/outcomes.py`): closing a thesis
  (`python3 -m fund.outcomes close SYMBOL --reason ...`) records the
  symbol's return vs SPY over the thesis window, hit/miss, and days held —
  append-only. `report` prints calibration by conviction level: the table
  that eventually answers whether conviction-4s beat conviction-3s (and
  whether the options layer can have positive EV).

## 2026-07-02 — rails around the aggressive layer

### Added
- **Options premium budget** (`fund/options_budget.py`): rolling-12-month
  premium spend hard-capped at 12% of book (configurable). The bounded-loss
  rule (§2) covers each call, but *repeated* premium spend was unbounded —
  5% of book per conviction name per month is a 100%+ annualized burn if
  calls keep expiring worthless. Actual fills recorded append-only via
  `python3 -m fund.options_suggester --record SYMBOL COST`.
- **Gap-stress tool** (`fund/gap_stress.py`): the adversarial review's
  "stops are triggers, not floors" finding as a deterministic check. Per
  held symbol: worst historical 1-day / 3-day drop, sessions that moved past
  the stop distance, and the portfolio hit if stops gap-fill at historical
  worst instead of at the trail.

### Changed
- **Options suggester hardened**: batch trimmed to the premium budget
  (highest conviction first); one-contract suggestions that exceed the
  sizing target by >1.5× are skipped instead of silently oversized
  (`max(1, ...)` bug); every suggestion now carries a risk-engine
  LONG_CALL verdict on the card, same sign-off discipline as equity
  tickets; expiries land on real Fridays instead of spot+30d midweek.

## 2026-05-24 — autonomous overnight build

### Added
- **Daily ops loop**: portfolio state, morning ticket generator, end-of-day
  closeout, simulator. Whole-share + fractional support.
- **Strategy bench**: 10 strategies (60/40, dual momentum, risk parity, top-N
  momentum, MA crossover, leveraged momentum, regime-aware, adaptive,
  stable adaptive, multi-strategy blend).
- **Data sources**: Yahoo Finance (keyless), FRED (T-bill, treasury yields),
  SEC EDGAR (fundamentals — wired but unused). Cache with auto-refresh.
- **Risk concentration caps**: sector + correlation cluster + single-symbol
  limits. Defaults permissive for ETF universes (sector 85%, cluster 90%,
  single 100%).
- **Tax-lot accounting**: TaxLot dataclass, 5 lot selection policies
  (FIFO/LIFO/HIFO/LT_FIRST/TAX_OPTIMAL), wash-sale window (IRC §1091).
- **Decision verdict**: ok / watch / iterate from trailing 20-day excess +
  hit rate + drawdown.
- **Drift detector**: Welch t-test live vs backtest. Pickle cache so
  refresh-cache stays sub-second.
- **Coach card**: synthesizes verdict + drift + tax + wash + drawdown into
  one informational/watch/action/urgent recommendation.
- **Broker adapters**: Alpaca (pure-stdlib REST, paper-friendly) and IBKR
  (`ib_insync`, requires IB Gateway). Human-gated `send_orders` CLI.
- **Live reconciliation**: `/api/fire-and-watch` chains send → wait →
  reconcile in one request.
- **Next.js dashboard** at `fund/ui/`: Today cockpit (KPIs, coach, verdict,
  recommendations, holdings, drift, tax, regime, equity chart), History,
  Compare, Strategies, Recommendations, Sell guide. All actions runnable
  from buttons; no terminal trips.
- **Multi-account**: `FUND_PORTFOLIO_PATH` env var lets the same dashboard
  point at taxable / IRA / multiple state files.
- **Playwright smoke tests**: 4 tests covering the main dashboard flows.
- **Evaluation harnesses**: `honest_test` (calendar-year), `random_weeks`
  (40 random Mondays × 4 weeks), `compare` (side-by-side bench).

### Deprecated
- **`adaptive` and `stable_adaptive` are hidden from the dashboard picker.**
  Multi-year evaluation showed they consistently land at the bottom of the
  bench (avg rank 4.14-4.29 / 6 strategies, +27pp annual regret vs in-hindsight
  oracle). Still callable via the registry for diagnostic backtests, but the
  UI won't let you switch into them. Documentation updated.

### Known limitations
- **Survivorship bias**: Yahoo only lists currently-listed tickers. For paper
  this is fine; for live money, swap to CRSP / Sharadar (~$500-2000/year).
- **No live websocket reconciliation**: `fire-and-watch` polls after a sleep.
  Fine for paper; for production, IBKR's TWS streaming is the next step.
- **No post-mortem journal**: the daily card doesn't yet aggregate freeform
  notes. Roadmap item.
