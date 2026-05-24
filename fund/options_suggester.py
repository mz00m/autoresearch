"""options_suggester.py — asymmetric upside via long calls on conviction holds.

The risk_engine whitelist allows LONG_CALL — bounded loss = premium paid,
unbounded upside. This is the only tool in §3 that can credibly produce
5-20× returns on a position. Used right, it's how a $25k account
plausibly grows to $250k in 1-2 great years; used wrong, the premium
expires worthless and you've burned 100% of that slug.

This module is a SUGGESTER, not an executor:
  1. Walks held positions with active theses (fund.thesis).
  2. For each, computes a heuristic 30-day, ~10% OTM call recommendation:
     strike, expiry, approximate premium (Black-Scholes-ish estimate
     from underlying + assumed implied vol).
  3. Sizes the suggestion to ~5% of book per call (default).
  4. Prints a markdown card. User takes it to Alpaca's options screen
     (requires options approval level 2+) and trades manually.

The math:
  - Buy a $1.25k call on a $50k underlying position (~5% of book)
  - If underlying moves +20%, the call delta and gamma can produce
    3-8× return on the premium → $3.75-10k profit on $1.25k risk
  - If underlying drops or stays flat, premium decays to ~0
  - Expected value: positive ONLY if your thesis is right more often
    than the option's IV implies

The user is expected to know their own conviction. The suggester just
makes the asymmetric trade mechanically obvious + sized correctly.

No Yahoo options data dependency — Yahoo gated the chain endpoint in
2023. We use heuristic premium estimates instead. For exact pricing
the user reads the broker's chain at submit time.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import NormalDist
from typing import Optional

from fund.data.loader import load_panel
from fund.portfolio import Portfolio
from fund.thesis import active_for

_PHI = NormalDist()

# Typical implied-vol ranges (annualized) by asset class — order-of-magnitude
# pricing only. Real IV at submit time will differ.
_TYPICAL_IV: dict[str, float] = {
    # 3x leveraged ETFs — IV is HIGH
    "TQQQ": 0.65, "SOXL": 0.85, "UPRO": 0.60, "TMF": 0.40, "UGL": 0.30,
    # Single-commodity ETFs
    "USO": 0.45, "URA": 0.55,
    # Sector ETFs
    "XLE": 0.30,
    # Broad / index
    "SPY": 0.18, "QQQ": 0.22, "EFA": 0.18, "IWM": 0.25,
    # Single stocks — high-momentum names
    "NVDA": 0.55, "AVGO": 0.45, "MSFT": 0.28, "META": 0.40,
    "AMZN": 0.35, "PLTR": 0.65, "AAPL": 0.30, "TSLA": 0.65,
    "TSM": 0.40, "AMD": 0.50, "GOOG": 0.30, "ASML": 0.40, "COIN": 0.85,
    "NFLX": 0.40,
    # Bonds, gold (low vol)
    "AGG": 0.06, "TLT": 0.15, "GLD": 0.16, "BIL": 0.01,
    # Crypto-adjacent
    "BITO": 0.70,
}


@dataclass
class OptionsSuggestion:
    symbol: str
    underlying_price: float
    strike: float
    expiry: str
    days_to_expiry: int
    est_premium_per_contract: float    # $ per contract (× 100 = total)
    est_total_cost: float              # for the recommended contract count
    contracts: int
    pct_of_book: float
    breakeven_price: float
    breakeven_move_pct: float
    estimated_upside_5x_move: float    # P&L if underlying +20%
    conviction: int                    # from the active thesis
    catalyst: str                      # from the active thesis
    notes: str


def _bs_call(S: float, K: float, T_years: float, r: float, sigma: float) -> float:
    """Black-Scholes call premium — heuristic estimate only."""
    if T_years <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T_years) / (sigma * math.sqrt(T_years))
    d2 = d1 - sigma * math.sqrt(T_years)
    return S * _PHI.cdf(d1) - K * math.exp(-r * T_years) * _PHI.cdf(d2)


def suggest_for(symbol: str, underlying_price: float, *,
                book_value: float,
                pct_per_call: float = 0.05,
                otm_pct: float = 0.10,
                dte: int = 30,
                risk_free: float = 0.045) -> OptionsSuggestion:
    """Recommend one OTM call for `symbol` at ~otm_pct above spot, ~dte days
    out. Sizes to roughly pct_per_call of book."""
    iv = _TYPICAL_IV.get(symbol.upper(), 0.30)
    # Round strike to a sensible increment (dollar for cheap, $5 for $100+)
    raw_strike = underlying_price * (1.0 + otm_pct)
    if underlying_price >= 200:
        strike = round(raw_strike / 5) * 5
    elif underlying_price >= 50:
        strike = round(raw_strike)
    else:
        strike = round(raw_strike * 2) / 2
    T = dte / 365.0
    premium = _bs_call(underlying_price, strike, T, risk_free, iv)
    cost_per_contract = premium * 100.0   # 100 shares per contract
    target_dollars = book_value * pct_per_call
    contracts = max(1, int(target_dollars // cost_per_contract))
    total_cost = contracts * cost_per_contract

    breakeven = strike + premium
    breakeven_move = (breakeven / underlying_price - 1.0) * 100.0
    # If underlying +20% from spot — rough estimate via intrinsic at expiry
    spot_plus20 = underlying_price * 1.20
    intrinsic_plus20 = max(0.0, spot_plus20 - strike) * 100.0 * contracts
    upside_5x = intrinsic_plus20 - total_cost

    expiry_date = (date.today() + timedelta(days=dte)).isoformat()
    pct_of_book = total_cost / book_value if book_value > 0 else 0
    thesis = active_for(symbol)
    notes = "no active thesis — write one BEFORE adding this call" if not thesis else ""

    return OptionsSuggestion(
        symbol=symbol, underlying_price=underlying_price,
        strike=strike, expiry=expiry_date, days_to_expiry=dte,
        est_premium_per_contract=cost_per_contract,
        est_total_cost=total_cost, contracts=contracts,
        pct_of_book=pct_of_book,
        breakeven_price=breakeven, breakeven_move_pct=breakeven_move,
        estimated_upside_5x_move=upside_5x,
        conviction=thesis["confidence"] if thesis else 0,
        catalyst=thesis["catalyst"] if thesis else "(none)",
        notes=notes,
    )


def suggest_for_portfolio(pf: Portfolio, prices: dict[str, float],
                          *, pct_per_call: float = 0.05,
                          min_conviction: int = 3,
                          dte: int = 30) -> list[OptionsSuggestion]:
    """One suggestion per HELD position with conviction >= min_conviction."""
    book = pf.cash + sum(
        p.qty * prices.get(s, p.avg_cost)
        for s, p in pf.positions.items() if p.qty)
    out: list[OptionsSuggestion] = []
    for sym, pos in pf.positions.items():
        if pos.qty <= 0:
            continue
        thesis = active_for(sym)
        if not thesis or thesis["confidence"] < min_conviction:
            continue
        price = prices.get(sym, pos.avg_cost)
        out.append(suggest_for(sym, price, book_value=book,
                                pct_per_call=pct_per_call, dte=dte))
    return out


def _print_card(suggs: list[OptionsSuggestion]) -> None:
    if not suggs:
        print("no suggestions — need positions with active conviction-3+ theses.")
        return
    print(f"\n{'=' * 84}")
    print(f" OPTIONS PLAYBOOK — informational. Execute at your broker.")
    print(f"{'=' * 84}")
    for s in suggs:
        print(f"\n  {s.symbol}  (underlying @ ${s.underlying_price:,.2f}, "
              f"conviction {s.conviction}/5)")
        print(f"    Catalyst: {s.catalyst}")
        print(f"    Buy: {s.contracts}× {s.symbol} {s.expiry} ${s.strike:g} CALL")
        print(f"    Est. premium per contract: ~${s.est_premium_per_contract:,.0f}")
        print(f"    Total cost (max loss):     ~${s.est_total_cost:,.0f}  "
              f"({s.pct_of_book * 100:.1f}% of book)")
        print(f"    Breakeven:  ${s.breakeven_price:,.2f}  "
              f"({s.breakeven_move_pct:+.1f}% from spot)")
        print(f"    If underlying +20% at expiry: ~${s.estimated_upside_5x_move:,.0f} "
              f"({s.estimated_upside_5x_move / s.est_total_cost:.1f}× on premium)")
        if s.notes:
            print(f"    ⚠ {s.notes}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Long-call options suggestions for held positions.")
    ap.add_argument("--pct-per-call", type=float, default=0.05,
                    help="fraction of book per options position (default 5%%)")
    ap.add_argument("--min-conviction", type=int, default=3,
                    help="only suggest for theses with conviction >= this")
    ap.add_argument("--dte", type=int, default=30,
                    help="days to expiry (default 30)")
    ap.add_argument("--source", default="auto")
    args = ap.parse_args()

    try:
        pf = Portfolio.load()
    except FileNotFoundError:
        print("no portfolio — run fund.portfolio init first")
        return 1

    held = [s for s, p in pf.positions.items() if p.qty]
    if not held:
        print("no held positions — fire morning + fill first")
        return 0

    panel, _ = load_panel(held, date(2024, 1, 1), date.today(), source=args.source)
    prices = {s: panel.series[s].last for s in held
              if panel.series.get(s) and panel.series[s].last}
    for s, p in pf.positions.items():
        if s not in prices:
            prices[s] = p.avg_cost
    suggs = suggest_for_portfolio(pf, prices,
                                   pct_per_call=args.pct_per_call,
                                   min_conviction=args.min_conviction,
                                   dte=args.dte)
    _print_card(suggs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
