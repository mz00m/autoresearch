"""scorecard.py — one ranked table over the whole universe: the selection view.

The "should I buy X?" evidence lives in five places: momentum in the
strategies, fragility in gap_stress/red_team, conviction in thesis, regime in
the allocator, cost basis in the portfolio. This module joins them into a
single ranked candidate list so the morning question changes from "what does
dual-momentum say?" to "here are all candidates, ranked, with the reason and
the risk on one line each."

Per symbol:
  trend      r21 / r63 / r252 + above-200d-MA — is it going up, on all horizons?
  vol        annualized 63d realized volatility
  fragility  worst historical 1-day and 3-day drop (stops are triggers, not floors)
  regime     does the current regime favor this asset class?
  thesis     your active conviction (and its age)
  held       current weight + unrealized P&L if already in the book

The composite score is a documented heuristic SYNTHESIS, not an oracle:
  score = trend(≤55) + regime tilt(±10) + thesis(≤15) − fragility penalty
It exists to sort the table sensibly; the columns are the point. Selection
still runs through the strategy bench, the risk engine, and your approval.

Run:
  python3 -m fund.scorecard                     # today, full universe
  python3 -m fund.scorecard --as-of 2026-05-22 --top 15
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime

from fund.data.loader import load_panel
from fund.data.pit import Panel, PriceSeries
from fund.gap_stress import stress_symbol
from fund.portfolio import Portfolio
from fund.strategy.registry import REGIME_SIGNALS, list_strategies, universe_for
from fund.thesis import active_for

# --- asset-class map + regime tilts ------------------------------------------

ASSET_CLASS: dict[str, str] = {
    "SPY": "us_equity", "QQQ": "tech", "EFA": "intl_equity", "IWM": "us_equity",
    "XLE": "energy", "USO": "commodity", "URA": "commodity", "GLD": "gold",
    "AGG": "bond", "TLT": "bond", "BIL": "cash_like",
    "TQQQ": "leveraged", "SOXL": "leveraged", "UPRO": "leveraged",
    "TMF": "leveraged", "UGL": "leveraged",
    "BITO": "crypto", "COIN": "crypto",
    "NVDA": "tech", "AVGO": "tech", "TSM": "tech", "AMD": "tech", "ASML": "tech",
    "MSFT": "tech", "META": "tech", "GOOG": "tech", "AMZN": "tech",
    "PLTR": "tech", "AAPL": "tech", "TSLA": "tech", "NFLX": "tech",
}

# Which asset classes each regime favors (+) or punishes (−), in score points.
# Mirrors the regime_aware routing philosophy: risk-on in CALM, ballast in
# STRESSED, capital preservation in PANIC.
REGIME_TILT: dict[str, dict[str, float]] = {
    "CALM":     {"tech": +10, "leveraged": +8, "us_equity": +8, "intl_equity": +5,
                 "crypto": +3, "energy": +3, "commodity": 0, "gold": -3,
                 "bond": -5, "cash_like": -8},
    "NORMAL":   {"us_equity": +8, "tech": +6, "intl_equity": +5, "energy": +3,
                 "commodity": +2, "gold": 0, "leveraged": 0, "bond": 0,
                 "crypto": -2, "cash_like": -5},
    "STRESSED": {"gold": +8, "bond": +8, "cash_like": +5, "us_equity": -3,
                 "intl_equity": -3, "energy": -3, "commodity": 0, "tech": -6,
                 "crypto": -8, "leveraged": -10},
    "PANIC":    {"cash_like": +10, "bond": +8, "gold": +8, "us_equity": -8,
                 "intl_equity": -8, "commodity": -5, "energy": -5, "tech": -10,
                 "crypto": -10, "leveraged": -10},
    "UNKNOWN":  {},
}


@dataclass
class CandidateScore:
    symbol: str
    asset_class: str
    price: float | None
    r21: float | None
    r63: float | None
    r252: float | None
    above_200d: bool | None
    vol_annualized: float | None
    worst_1d: float | None
    worst_3d: float | None
    regime_tilt: float
    thesis_conviction: int          # 0 = no active thesis
    thesis_age_days: int | None
    held_weight: float              # fraction of book, 0 if not held
    unrealized_pct: float | None    # vs avg cost, only when held
    score: float
    reason: str


def _vol_annualized(ps: PriceSeries, window: int = 63) -> float | None:
    closes = ps.closes[-(window + 1):]
    if len(closes) < window // 2:
        return None
    rets = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))
            if closes[i - 1] > 0]
    if len(rets) < 2:
        return None
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


def _above_200d(ps: PriceSeries) -> bool | None:
    if len(ps.closes) < 200 or ps.last is None:
        return None
    ma = sum(ps.closes[-200:]) / 200.0
    return ps.last > ma


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _composite(r21, r63, r252, above_200d, worst_3d, tilt,
               conviction) -> tuple[float, str]:
    """Documented heuristic: trend(≤55) + tilt(±10) + thesis(≤15) − fragility."""
    parts: list[str] = []

    horizons = [(r, w) for r, w in ((r21, 10), (r63, 20), (r252, 20))
                if r is not None]
    trend = sum(_clip(r, -0.5, 0.5) / 0.5 * w for r, w in horizons)
    if above_200d:
        trend += 5
    parts.append(f"trend {trend:+.0f}")

    frag = 0.0
    if worst_3d is not None:
        frag = _clip(-worst_3d, 0.0, 0.6) * 40   # a −35% 3-day day costs 14 pts
        parts.append(f"fragility -{frag:.0f}")

    if tilt:
        parts.append(f"regime {tilt:+.0f}")
    thesis_pts = conviction * 3
    if thesis_pts:
        parts.append(f"thesis {thesis_pts:+.0f}")

    return trend + tilt + thesis_pts - frag, ", ".join(parts)


def _classify_regime(panel: Panel, asof: date) -> str:
    try:
        from fund.strategy.regime_aware import RegimeAwareAllocator
        regime, _ = RegimeAwareAllocator().classify(panel.as_of(asof))
        return regime
    except Exception:
        return "UNKNOWN"


def _thesis_age_days(thesis: dict, asof: date) -> int | None:
    try:
        created = datetime.fromisoformat(thesis["created_at"]).date()
        return (asof - created).days
    except (KeyError, ValueError):
        return None


def scorecard_universe() -> tuple[str, ...]:
    """Every tradeable symbol any registered strategy might pick."""
    syms: set[str] = set()
    for name in list_strategies():
        try:
            syms.update(universe_for(name, {}))
        except Exception:
            continue
    return tuple(sorted(s for s in syms
                        if not s.startswith("^") and s != "CASH"))


def build_scorecard(panel: Panel, asof: date,
                    pf: Portfolio | None = None,
                    symbols: tuple[str, ...] | None = None,
                    ) -> list[CandidateScore]:
    """Score and rank every candidate. Panel should include REGIME_SIGNALS
    tickers when available so the regime column is live."""
    symbols = symbols or scorecard_universe()
    regime = _classify_regime(panel, asof)

    prices: dict[str, float] = {}
    held_w: dict[str, float] = {}
    unreal: dict[str, float] = {}
    if pf is not None:
        for sym, pos in pf.positions.items():
            ps = panel.series.get(sym)
            last = ps.as_of(asof).last if ps else None
            prices[sym] = last if last else pos.avg_cost
        book = pf.cash + sum(p.qty * prices.get(s, p.avg_cost)
                             for s, p in pf.positions.items() if p.qty)
        for sym, pos in pf.positions.items():
            if pos.qty > 0 and book > 0:
                held_w[sym] = pos.qty * prices[sym] / book
                if pos.avg_cost > 0:
                    unreal[sym] = prices[sym] / pos.avg_cost - 1.0

    out: list[CandidateScore] = []
    for sym in symbols:
        ps_full = panel.series.get(sym)
        if ps_full is None:
            continue
        ps = ps_full.as_of(asof)
        if len(ps) < 30:
            continue
        r21, r63, r252 = (ps.trailing_return(n) for n in (21, 63, 252))
        above = _above_200d(ps)
        vol = _vol_annualized(ps)
        gap = stress_symbol(sym, Panel({sym: ps}), weight=1.0)
        thesis = active_for(sym)
        conviction = thesis["confidence"] if thesis else 0
        tilt = REGIME_TILT.get(regime, {}).get(
            ASSET_CLASS.get(sym, "us_equity"), 0.0)
        score, reason = _composite(r21, r63, r252, above,
                                   gap.worst_3d if gap else None,
                                   tilt, conviction)
        out.append(CandidateScore(
            symbol=sym, asset_class=ASSET_CLASS.get(sym, "us_equity"),
            price=ps.last,
            r21=r21, r63=r63, r252=r252, above_200d=above,
            vol_annualized=vol,
            worst_1d=gap.worst_1d if gap else None,
            worst_3d=gap.worst_3d if gap else None,
            regime_tilt=tilt,
            thesis_conviction=conviction,
            thesis_age_days=_thesis_age_days(thesis, asof) if thesis else None,
            held_weight=held_w.get(sym, 0.0),
            unrealized_pct=unreal.get(sym),
            score=round(score, 1), reason=reason,
        ))
    out.sort(key=lambda c: c.score, reverse=True)
    return out


def compute(asof: date, *, source: str = "auto",
            pf: Portfolio | None = None) -> dict:
    """JSON-friendly bundle for the CLI and the UI cache."""
    symbols = scorecard_universe()
    panel, _tbill = load_panel(list(symbols) + list(REGIME_SIGNALS),
                               date(2005, 1, 1), asof, source=source)
    rows = build_scorecard(panel, asof, pf=pf, symbols=symbols)
    return {
        "as_of": asof.isoformat(),
        "regime": _classify_regime(panel, asof),
        "rows": [asdict(r) for r in rows],
    }


def _fmt_pct(x: float | None) -> str:
    return f"{x:+.1%}" if x is not None else "   —  "


def _print_table(bundle: dict, top: int | None) -> None:
    rows = bundle["rows"][:top] if top else bundle["rows"]
    print(f"\n CANDIDATE SCORECARD — {bundle['as_of']}   "
          f"regime: {bundle['regime']}")
    print(f" score = trend(≤55) + regime(±10) + thesis(≤15) − fragility. "
          f"A sort key, not an oracle.\n")
    hdr = (f" {'#':>2} {'sym':<6} {'class':<11} {'score':>6}  {'r21':>7} "
           f"{'r63':>7} {'r252':>7} {'>200d':>5} {'vol':>5} {'w3d':>7} "
           f"{'conv':>4} {'held':>5}  reason")
    print(hdr)
    print(" " + "-" * (len(hdr) + 8))
    for i, r in enumerate(rows, 1):
        held = f"{r['held_weight']:.0%}" if r["held_weight"] else "  ·"
        above = ("yes" if r["above_200d"] else " no") \
            if r["above_200d"] is not None else "  —"
        vol = f"{r['vol_annualized']:.0%}" if r["vol_annualized"] else "  —"
        conv = str(r["thesis_conviction"]) if r["thesis_conviction"] else "·"
        print(f" {i:>2} {r['symbol']:<6} {r['asset_class']:<11} "
              f"{r['score']:>6.1f}  {_fmt_pct(r['r21'])} {_fmt_pct(r['r63'])} "
              f"{_fmt_pct(r['r252'])} {above:>5} {vol:>5} "
              f"{_fmt_pct(r['worst_3d'])} "
              f"{conv:>4} {held:>5}  {r['reason']}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Ranked candidate scorecard across the universe.")
    ap.add_argument("--as-of", default=None, help="YYYY-MM-DD (default today)")
    ap.add_argument("--top", type=int, default=None, help="show top N only")
    ap.add_argument("--source", default="auto")
    args = ap.parse_args()

    asof = date.fromisoformat(args.as_of) if args.as_of else date.today()
    try:
        pf = Portfolio.load()
    except FileNotFoundError:
        pf = None
    bundle = compute(asof, source=args.source, pf=pf)
    _print_table(bundle, args.top)
    return 0


if __name__ == "__main__":
    sys.exit(main())
