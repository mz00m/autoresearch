# Research log: how do we pick more forward-looking trades?

**Date:** 2026-05-24
**Trigger:** Matt asked: "what if the war in Iran ends this weekend and oil prices crater — isn't this a very geopolitical-based trade?"
**Status:** hypothesis 1 falsified; pivot to portfolio-level defenses

## The actual problem

The active strategy, `top_n_momentum` (n=2, lookback=126d), picks the two best
trailing-return assets in the universe. As of 2026-05-22 close it picks USO
(+98.8%) and XLE (+34.4%) — both energy, both correlated to oil. The strategy
doesn't know *why* oil is up, just that it is. If the catalyst (Iran/Mideast
risk premium) disappears overnight, both positions take it together.

Switching to `regime_aware` doesn't fix this **in a calm regime** — VIX 16.7
/ curve +0.97 / SPY > 200d, regime = CALM, routes back to top_n_momentum
which picks the same two assets.

## Hypothesis 1: volatility-scaled momentum

**Premise:** ranking by raw return over-weights catalyst-dependent rocket
assets. Scaling by inverse vol (Sharpe-like) should prefer durable trends.

**Built and tested:** `fund/strategy/vol_scaled_momentum.py` with
`score = return / annualized_vol`, top-N by score.

### Empirical result on today's universe (2026-05-22 close)

| Symbol | 126d return | 63d vol | Score (63d) | Score (252d) |
| --- | --- | --- | --- | --- |
| USO | +98.8% | 68.9% | +1.43 | +2.27 |
| XLE | +34.4% | 23.9% | +1.44 | +1.70 |
| QQQ | +19.9% | 19.1% | +1.04 | +1.24 |
| SPY | +13.2% | 14.5% | +0.91 | +1.10 |

USO's vol is genuinely high but the return is so much larger that the score
still wins. **The vol scaling doesn't change today's picks.** Top-2 is still
USO + XLE.

### Multi-year backtest (2018-2024, honest_test)

| Strategy | Avg rank | Wins | Avg cum | Avg DD |
| --- | --- | --- | --- | --- |
| dual_momentum | 2.71 | 5/7 | **+33.5%** | -27.1% |
| sixty_forty | 3.86 | 1/7 | +9.7% | -10.3% |
| adaptive | 4.29 | 1/7 | +11.2% | -16.0% |
| ma_crossover | 4.43 | 0/7 | +9.6% | -13.7% |
| stable_adaptive | 4.57 | 0/7 | +9.5% | -13.2% |
| risk_parity | 4.86 | 0/7 | +8.2% | -9.6% |
| top_n_momentum | 5.00 | 0/7 | +9.1% | -22.2% |
| **vol_scaled_momentum** | **6.29** | **0/7** | **+4.2%** | -17.3% |

**vol_scaled_momentum is the worst strategy in the bench.** Year-by-year:

- It does fine in down/sideways years (2018, 2019, 2022, 2023) — vol scaling
  correctly underweights high-vol losers.
- It **catastrophically misses big up years**: 2020 (-11.9% while top_n was
  +12%), 2021 (+2.3% while top_n was +29.4%), 2024 (+7.0% while
  dual_momentum was +104.4% — missed the gold rally entirely).

### Honest conclusion: hypothesis FALSIFIED

Penalizing volatility defeats the entire purpose of momentum. Momentum is
the *return* per unit of *trend persistence*, not per unit of *vol*. By
suppressing the vol of winning trends, vol_scaled_momentum systematically
exits or under-weights the very assets that pay off.

This is the autoresearch pattern working correctly — hypothesis, test,
honest negative result, log it, move on.

## Hypothesis 2: credit-spread regime (still worth building — defer)

HY credit spreads lead equity drawdowns by 2-8 weeks. Adding HYG/LQD ratio
to the regime classifier could shift defensive earlier than VIX alone. Not
built yet — separate research run.

## 10 curiosity cycles — what the academic + practitioner literature offered

Ran 10 documented strategies through honest_test 2018-2024:

| # | Strategy | Avg cum | Avg rank | Avg DD | Verdict |
| --- | --- | --- | --- | --- | --- |
| 1 | **skip_month_momentum** (JT 1993) | **+23.3%** | **4.86** ← best | -22% | **PROMOTE** — beats top_n_momentum on every axis |
| 2 | time_series_momentum (Moskowitz 2012) | +9.9% | 8.86 | -17% | Mediocre — own-history signal adds little |
| 3 | faber_gtaa (Faber 2007) | +4.8% | 10.14 | **-7.1%** | Smoothest in test — defensive sleeve candidate |
| 4 | all_weather (Bridgewater simplified) | +5.5% | 9.57 | -9.7% | Steady but light returns; benchmark only |
| 5 | permanent_portfolio (Browne 1981) | +6.9% | 8.57 | -7.4% | "Won't blow up" baseline — preserve for blend slot |
| 6 | mean_reversion (DeBondt-Thaler 1985) | +6.9% | 8.57 | **-26%** | -51% in 2020 (bought USO at oil-negative). Documented failure mode confirmed |
| 7 | low_vol (BAB, Frazzini-Pedersen 2014) | +8.6% | 8.43 | -8.9% | Anomaly textbook — modest, low DD |
| 8 | vix_gated_momentum (D-M 2016) | +4.5% | 11.57 | -18% | **FAILED** — turned off too often, missed all recoveries |
| 9 | rp_crisis_hedge (RP + TLT) | +6.8% | 8.86 | -8.6% | Slight improvement over plain RP; not dramatic |
| 10 | trend_carry (AMP 2013) | +13.2% | 9.14 | -19% | Middling — carry proxy too crude in ETF universe |

**Existing bench, re-scored alongside:**

| | Avg cum | Avg rank | Avg DD |
| --- | --- | --- | --- |
| dual_momentum (existing winner) | +33.5% | 5.00 | -27% |
| sixty_forty | +9.7% | 6.57 | -10% |
| top_n_momentum (current active) | +9.1% | 8.57 | -22% |
| risk_parity | +8.2% | 8.00 | -9.6% |
| ma_crossover | +9.6% | 7.71 | -14% |

## Key new finding: skip_month_momentum

The Jegadeesh-Titman "skip the most recent month" academic standard
**outperformed top_n_momentum on every meaningful axis** in our window:
  - Higher avg return: +23.3% vs +9.1%
  - Better avg rank: 4.86 vs 8.57
  - Same DD class (-22% vs -22%)
  - Top-3 in 5/7 years vs 1/7
  - Beat SPY in 4/7 vs 3/7

Mechanism: the last ~21 trading days exhibit short-term mean reversion;
including them in the momentum signal contaminates it. JT's "12-month
minus 1-month" formulation isolates clean persistent trend.

**Recommendation: switch active strategy to skip_month_momentum.** Same
momentum thesis as top_n_momentum but with the academic correction.

## What failed and why

- **vix_gated_momentum**: VIX > 25 too often coincides with recovery starts,
  not crash continuations. Going to cash at VIX 25 missed 2020 recovery
  (March-Dec), 2022 H2 recovery, and 2023 rally.
- **mean_reversion**: 2020 oil collapse + USO at -50% in March = "buy the
  loser" loaded USO at the bottom. Picked up the entire pain.
- **vol_scaled_momentum**: documented earlier — penalizes the trend
  persistence that momentum is designed to capture.

## What actually helps with the concentration concern

Three things, in order of leverage:

### A) Switch to `multi` strategy (60% top_n + 40% risk_parity)

Halves the energy concentration. Risk parity provides bond + diversification
ballast. Sacrifices ~30-50% of momentum upside in exchange for a real cushion
if the catalyst disappears. **One click in Strategy Picker.**

### B) Enable the concentration mandate

`FUND_CONCENTRATION_MANDATE=1` in `.env.local` activates the sector / cluster
caps (default 85%/90%). Would have prevented the 100%-energy allocation by
rejecting the second leg. Forces top_n_momentum to spread across sectors.

### C) Keep current strategy, accept the bet, lean on stops

The 10% trailing stop at Alpaca is the safety net. Locks in gains as price
rises; fires a market sell if price drops 10% from peak. **Doesn't protect
against overnight gaps** — Sunday Iran-deal-announced scenario could see
oil futures gap down 20%+ before stops can fire. Stops are market-on-trigger,
not guaranteed-fill-at-stop-price.

## Recommendation

Switch to `multi`. The data says momentum still works as a return engine,
the issue is exposure concentration when momentum picks two correlated
assets. Blending halves the concentration without sacrificing the trend
signal entirely.

If Matt wants to keep `regime_aware` for the VIX/curve regime detection
upside, he can also enable the concentration mandate as a separate layer
of defense — they compose.
