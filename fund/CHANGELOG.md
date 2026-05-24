# fund/ changelog

Reverse-chronological log of meaningful changes. Tests + small refactors omitted.

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
